"""Reliable Graph IR card synchronization into HydraDB Knowledge."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .cards import SourceCard, build_app_knowledge, build_graph_payload
from .events import EventBus
from .hydradb import HydraDBClient, HydraDBError, response_data


class SyncStatus(StrEnum):
    IDLE = "idle"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class SyncManifest:
    """Bookkeeping only: no graph content and no retrieval behavior."""

    repository_id: str
    revision_id: str | None = None
    sources: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SyncResult:
    status: SyncStatus
    candidate_revision: str
    ready_revision: str | None
    added: tuple[str, ...]
    replaced: tuple[str, ...]
    deleted: tuple[str, ...]
    pending: tuple[str, ...]
    failed: Mapping[str, str]
    current_state_indeterminate: bool = False
    warning: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "candidate_revision": self.candidate_revision,
            "ready_revision": self.ready_revision,
            "added": list(self.added),
            "replaced": list(self.replaced),
            "deleted": list(self.deleted),
            "pending": list(self.pending),
            "failed": dict(self.failed),
            "current_state_indeterminate": self.current_state_indeterminate,
            "warning": self.warning,
        }


class SyncService:
    def __init__(
        self,
        client: HydraDBClient,
        *,
        repository_id: str,
        manifest: SyncManifest | None = None,
        events: EventBus | None = None,
        batch_size: int = 25,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.client = client
        self.repository_id = repository_id
        self.manifest = manifest or SyncManifest(repository_id=repository_id)
        if self.manifest.repository_id != repository_id:
            raise ValueError("Sync manifest belongs to another repository")
        self.events = events or EventBus()
        self.batch_size = batch_size
        self._sleep = sleep
        self._monotonic = monotonic
        self._status = SyncStatus.READY if self.manifest.revision_id else SyncStatus.IDLE
        self._current_state_indeterminate = False

    @property
    def status(self) -> dict[str, Any]:
        return {
            "status": self._status.value,
            "ready_revision": self.manifest.revision_id,
            "source_count": len(self.manifest.sources),
            "hydradb_available": self.client.config.configured,
            "database": self.client.config.database or None,
            "collection": self.client.config.collection,
            "current_state_indeterminate": self._current_state_indeterminate,
        }

    def sync(self, cards: Sequence[SourceCard], *, revision_id: str) -> SyncResult:
        if not revision_id.strip():
            raise ValueError("revision_id must not be blank")
        by_id = {card.source_id: card for card in cards}
        if len(by_id) != len(cards):
            raise ValueError("Source cards contain duplicate source IDs")
        new_hashes = {source_id: _card_hash(card) for source_id, card in by_id.items()}
        old_hashes = dict(self.manifest.sources)
        added = tuple(sorted(set(new_hashes).difference(old_hashes)))
        replaced = tuple(
            sorted(
                source_id
                for source_id in set(new_hashes).intersection(old_hashes)
                if new_hashes[source_id] != old_hashes[source_id]
            )
        )
        removed = tuple(sorted(set(old_hashes).difference(new_hashes)))
        changed = (*added, *replaced)
        session_id = f"sync_{uuid.uuid4().hex}"
        self.events.emit(
            "hydradb_sync_started",
            session_id=session_id,
            revision_id=revision_id,
            entity_ids=tuple(card.node_id for card in cards if card.source_id in changed),
            hydradb_query_metadata={
                "database": self.client.config.database,
                "collection": self.client.config.collection,
                "added": len(added),
                "replaced": len(replaced),
                "deleted": len(removed),
            },
        )
        self._status = SyncStatus.INDEXING
        try:
            for batch in _batches([by_id[source_id] for source_id in changed], self.batch_size):
                self.client.ingest(
                    app_knowledge=build_app_knowledge(batch),
                    graph_payload=build_graph_payload(batch),
                    upsert=True,
                )
            failed = self._wait_until_completed(changed)
            if failed:
                self._status = SyncStatus.FAILED
                self._current_state_indeterminate = bool(changed)
                return SyncResult(
                    status=self._status,
                    candidate_revision=revision_id,
                    ready_revision=self.manifest.revision_id,
                    added=added,
                    replaced=replaced,
                    deleted=(),
                    pending=(),
                    failed=failed,
                    current_state_indeterminate=self._current_state_indeterminate,
                    warning=(
                        "HydraDB indexing failed after upsert. The prior revision remains the last "
                        "verified marker, but candidate content may already be visible in current."
                    ),
                )
            deleted: tuple[str, ...] = ()
            if removed:
                deletion = response_data(self.client.delete(removed))
                results = deletion.get("results", [])
                failed_deletes = {
                    str(item.get("id")): str(item.get("error") or "delete failed")
                    for item in results
                    if isinstance(item, Mapping) and not item.get("deleted")
                }
                # An empty/missing results array is accepted only when HydraDB's
                # aggregate count proves every requested source was removed.
                if not results and int(deletion.get("deleted_count", 0)) != len(removed):
                    failed_deletes = {source_id: "delete not confirmed" for source_id in removed}
                if failed_deletes:
                    self._status = SyncStatus.FAILED
                    self._current_state_indeterminate = True
                    return SyncResult(
                        status=self._status,
                        candidate_revision=revision_id,
                        ready_revision=self.manifest.revision_id,
                        added=added,
                        replaced=replaced,
                        deleted=tuple(
                            source_id for source_id in removed if source_id not in failed_deletes
                        ),
                        pending=(),
                        failed=failed_deletes,
                        current_state_indeterminate=True,
                        warning=(
                            "HydraDB deletion was incomplete. The candidate revision was not "
                            "verified, "
                            "and the current collection may contain a mixed state."
                        ),
                    )
                deleted = removed
        except HydraDBError as exc:
            self._status = SyncStatus.UNAVAILABLE
            self._current_state_indeterminate = bool(changed)
            return SyncResult(
                status=self._status,
                candidate_revision=revision_id,
                ready_revision=self.manifest.revision_id,
                added=added,
                replaced=replaced,
                deleted=(),
                pending=tuple(changed),
                failed={},
                current_state_indeterminate=self._current_state_indeterminate,
                warning=(
                    f"{exc}. The prior revision is only the last verified marker; "
                    "the current collection state could not be confirmed."
                ),
            )
        self.manifest = SyncManifest(
            repository_id=self.repository_id,
            revision_id=revision_id,
            sources=new_hashes,
        )
        self._status = SyncStatus.READY
        self._current_state_indeterminate = False
        self.events.emit(
            "hydradb_revision_ready",
            session_id=session_id,
            revision_id=revision_id,
            hydradb_query_metadata={
                "database": self.client.config.database,
                "collection": self.client.config.collection,
                "source_count": len(cards),
            },
        )
        return SyncResult(
            status=self._status,
            candidate_revision=revision_id,
            ready_revision=revision_id,
            added=added,
            replaced=replaced,
            deleted=deleted,
            pending=(),
            failed={},
        )

    def _wait_until_completed(self, source_ids: Sequence[str]) -> dict[str, str]:
        if not source_ids:
            return {}
        deadline = self._monotonic() + self.client.config.poll_timeout_seconds
        while True:
            data = response_data(self.client.status(source_ids))
            statuses = {
                str(item.get("id")): item
                for item in data.get("statuses", [])
                if isinstance(item, Mapping)
            }
            missing = set(source_ids).difference(statuses)
            if missing:
                return {
                    source_id: "status missing from HydraDB response"
                    for source_id in sorted(missing)
                }
            failures = {
                source_id: str(
                    item.get("error_code") or item.get("error_message") or "indexing failed"
                )
                for source_id, item in statuses.items()
                if item.get("indexing_status") == "errored" or item.get("success") is False
            }
            if failures:
                return failures
            if all(item.get("indexing_status") == "completed" for item in statuses.values()):
                return {}
            if self._monotonic() >= deadline:
                return {
                    source_id: (
                        "indexing timed out in state "
                        f"{item.get('indexing_status', 'unknown')}"
                    )
                    for source_id, item in statuses.items()
                    if item.get("indexing_status") != "completed"
                }
            self._sleep(self.client.config.poll_interval_seconds)


def _card_hash(card: SourceCard) -> str:
    value = card.additional_metadata.get("content_hash")
    if not value:
        raise ValueError(f"Source card {card.source_id} has no content_hash")
    return str(value)


def _batches(items: Sequence[SourceCard], size: int) -> list[list[SourceCard]]:
    if not items:
        return []
    return [list(items[index : index + size]) for index in range(0, len(items), size)]
