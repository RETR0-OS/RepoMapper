"""In-process event transport for observable, non-reasoning agent activity."""

from __future__ import annotations

import uuid
from collections import deque
from collections.abc import Iterator, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from queue import Empty, Queue
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


class EventBus:
    """Bounded history plus live subscribers for extension SSE clients."""

    def __init__(self, *, history_limit: int = 500) -> None:
        if history_limit < 1:
            raise ValueError("history_limit must be positive")
        self._history: deque[AgentEvent] = deque(maxlen=history_limit)
        self._subscribers: set[Queue[AgentEvent]] = set()
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
            subscriber.put_nowait(event)
        return event

    def recent(self, *, session_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            events = tuple(self._history)
        return [
            event.as_dict()
            for event in events
            if session_id is None or event.session_id == session_id
        ]

    def stream(self, *, timeout: float = 15.0) -> Iterator[AgentEvent | None]:
        """Yield live events; ``None`` is a heartbeat after an idle timeout."""

        subscriber: Queue[AgentEvent] = Queue()
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
