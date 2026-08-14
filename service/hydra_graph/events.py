"""In-process event transport for observable, non-reasoning agent activity."""

from __future__ import annotations

import json
import uuid
from collections import OrderedDict, deque
from collections.abc import Iterator, Mapping
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from queue import Empty, Full, Queue
from threading import Lock
from typing import Any

EVENT_TYPES = {
    "session_started",
    "query_started",
    "hydradb_result_returned",
    "path_replay_started",
    "path_hop_replayed",
    "context_selected",
    "evidence_opened",
    "user_context_pinned",
    "workspace_entity_changed",
    "hydradb_sync_started",
    "hydradb_revision_ready",
    "lens_drift_detected",
    "session_completed",
}


@dataclass(frozen=True, slots=True)
class AgentEvent:
    event_id: str
    session_id: str
    timestamp: str
    type: str
    revision_id: str
    view_id: str | None = None
    entity_ids: tuple[str, ...] = ()
    relationship_ids: tuple[str, ...] = ()
    hydradb_query_metadata: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["entity_ids"] = list(self.entity_ids)
        data["relationship_ids"] = list(self.relationship_ids)
        if self.hydradb_query_metadata is not None:
            data["hydradb_query_metadata"] = dict(self.hydradb_query_metadata)
        return data


@dataclass(frozen=True, slots=True)
class ObserveSession:
    session_id: str
    revision_id: str
    active: bool


class ObserveSessionNotFound(LookupError):
    """Raised when an opaque Observe session ID is unknown or expired."""


class ObserveSessionInactive(RuntimeError):
    """Raised when an Observe session was already completed."""


class ObserveSessionLimit(RuntimeError):
    """Raised instead of silently evicting a still-active Observe session."""


class ObserveSessionAmbiguous(RuntimeError):
    """Raised when an omitted tool session cannot be correlated safely."""


class EventHistoryGap(LookupError):
    """Raised when a polling cursor is no longer retained for its session."""


class ObserveSessions:
    """Bounded registry for server-issued Observe sessions."""

    def __init__(
        self,
        events: EventBus,
        *,
        max_active: int = 32,
        history_limit: int = 128,
    ) -> None:
        if max_active < 1 or history_limit < max_active:
            raise ValueError("Observe session bounds are invalid")
        self.events = events
        self.max_active = max_active
        self.history_limit = history_limit
        self._sessions: OrderedDict[str, ObserveSession] = OrderedDict()
        self._lock = Lock()

    def start(self, revision_id: str) -> tuple[ObserveSession, AgentEvent]:
        _validate_identifier("revision_id", revision_id)
        with self._lock:
            active_count = sum(session.active for session in self._sessions.values())
            if active_count >= self.max_active:
                raise ObserveSessionLimit("Too many Observe sessions are active")
            session = ObserveSession(
                session_id=f"session_{uuid.uuid4().hex}",
                revision_id=revision_id,
                active=True,
            )
            self._sessions[session.session_id] = session
            self._prune_completed()
        event = self.events.emit(
            "session_started",
            session_id=session.session_id,
            revision_id=revision_id,
        )
        return session, event

    def require(self, session_id: str, *, active: bool = False) -> ObserveSession:
        _validate_identifier("session_id", session_id)
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise ObserveSessionNotFound(session_id)
        if active and not session.active:
            raise ObserveSessionInactive(session_id)
        return session

    def complete(self, session_id: str) -> tuple[ObserveSession, AgentEvent]:
        _validate_identifier("session_id", session_id)
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise ObserveSessionNotFound(session_id)
            if not session.active:
                raise ObserveSessionInactive(session_id)
            completed = ObserveSession(
                session_id=session.session_id,
                revision_id=session.revision_id,
                active=False,
            )
            self._sessions[session_id] = completed
            self._sessions.move_to_end(session_id)
        event = self.events.emit(
            "session_completed",
            session_id=session_id,
            revision_id=session.revision_id,
        )
        return completed, event

    def resolve(self, session_id: str | None) -> ObserveSession | None:
        """Resolve an explicit session or the sole active mounted-MCP session."""

        if session_id is not None:
            return self.require(session_id, active=True)
        with self._lock:
            active_sessions = [session for session in self._sessions.values() if session.active]
        if not active_sessions:
            return None
        if len(active_sessions) > 1:
            raise ObserveSessionAmbiguous(
                "More than one Observe session is active; pass session_id explicitly"
            )
        return active_sessions[0]

    def _prune_completed(self) -> None:
        while len(self._sessions) > self.history_limit:
            removable = next(
                (key for key, session in self._sessions.items() if not session.active),
                None,
            )
            if removable is None:
                break
            self._sessions.pop(removable)


class EventBus:
    """Bounded history plus live subscribers for extension SSE clients."""

    def __init__(self, *, history_limit: int = 500, subscriber_queue_limit: int = 100) -> None:
        if history_limit < 1 or subscriber_queue_limit < 1:
            raise ValueError("event history and subscriber queue limits must be positive")
        self._history: deque[AgentEvent] = deque(maxlen=history_limit)
        self._subscribers: set[Queue[AgentEvent]] = set()
        self._subscriber_queue_limit = subscriber_queue_limit
        self._lock = Lock()

    def emit(
        self,
        event_type: str,
        *,
        session_id: str,
        revision_id: str,
        view_id: str | None = None,
        entity_ids: tuple[str, ...] = (),
        relationship_ids: tuple[str, ...] = (),
        hydradb_query_metadata: Mapping[str, Any] | None = None,
    ) -> AgentEvent:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"Unknown event type: {event_type}")
        _validate_identifier("session_id", session_id)
        _validate_identifier("revision_id", revision_id)
        if view_id is not None:
            _validate_identifier("view_id", view_id)
        if len(entity_ids) > 100 or len(relationship_ids) > 100:
            raise ValueError("An event can reference at most 100 entities and relationships")
        for value in (*entity_ids, *relationship_ids):
            _validate_identifier("event reference", value, max_length=1_024)
        if hydradb_query_metadata is not None:
            try:
                encoded_metadata = json.dumps(hydradb_query_metadata)
            except (TypeError, ValueError) as exc:
                raise ValueError("hydradb_query_metadata must be JSON serializable") from exc
            if len(encoded_metadata) > 16_000:
                raise ValueError("hydradb_query_metadata exceeds 16000 characters")
        event = AgentEvent(
            event_id=f"event_{uuid.uuid4().hex}",
            session_id=session_id,
            timestamp=datetime.now(UTC).isoformat(),
            type=event_type,
            revision_id=revision_id,
            view_id=view_id,
            entity_ids=entity_ids,
            relationship_ids=relationship_ids,
            hydradb_query_metadata=hydradb_query_metadata,
        )
        with self._lock:
            self._history.append(event)
            subscribers = tuple(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(event)
            except Full:
                # Slow SSE consumers keep only the newest bounded activity.
                with suppress(Empty):
                    subscriber.get_nowait()
                with suppress(Full):
                    subscriber.put_nowait(event)
        return event

    def recent(
        self,
        *,
        session_id: str | None = None,
        after_event_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if after_event_id is not None:
            if session_id is None:
                raise ValueError("after_event_id requires session_id")
            _validate_identifier("after_event_id", after_event_id)
        with self._lock:
            events = tuple(self._history)
        selected = [
            event for event in events if session_id is None or event.session_id == session_id
        ]
        if after_event_id is not None:
            cursor = next(
                (index for index, event in enumerate(selected) if event.event_id == after_event_id),
                None,
            )
            if cursor is None:
                raise EventHistoryGap(after_event_id)
            selected = selected[cursor + 1 :]
        return [event.as_dict() for event in selected]

    def stream(self, *, timeout: float = 15.0) -> Iterator[AgentEvent | None]:
        """Yield live events; ``None`` is a heartbeat after an idle timeout."""

        subscriber: Queue[AgentEvent] = Queue(maxsize=self._subscriber_queue_limit)
        with self._lock:
            self._subscribers.add(subscriber)
        try:
            while True:
                try:
                    yield subscriber.get(timeout=timeout)
                except Empty:
                    yield None
        finally:
            with self._lock:
                self._subscribers.discard(subscriber)


def _validate_identifier(name: str, value: str, *, max_length: int = 256) -> None:
    if not value.strip():
        raise ValueError(f"{name} must not be blank")
    if len(value) > max_length:
        raise ValueError(f"{name} exceeds {max_length} characters")
