"""Reliable Graph IR card synchronization into HydraDB Knowledge."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from threading import Lock, RLock
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
    database: str | None = None
    collection: str | None = None


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
        manifest_path: str | Path | None = None,
        events: EventBus | None = None,
        batch_size: int = 25,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.client = client
        self.repository_id = repository_id
        self.manifest_path = Path(manifest_path).resolve() if manifest_path else None
        self.manifest = manifest or self._load_manifest()
        if self.manifest.repository_id != repository_id:
            raise ValueError("Sync manifest belongs to another repository")
        if self.manifest.database not in {None, self.client.config.database}:
            raise ValueError("Sync manifest belongs to another HydraDB database")
        if self.manifest.collection not in {None, self.client.config.collection}:
            raise ValueError("Sync manifest belongs to another HydraDB collection")
        self.events = events or EventBus()
        self.batch_size = batch_size
        self._sleep = sleep
        self._monotonic = monotonic
        self._status = SyncStatus.READY if self.manifest.revision_id else SyncStatus.IDLE
        self._current_state_indeterminate = False
        self._state_lock = RLock()
        self._operation_lock = Lock()

    @property
    def status(self) -> dict[str, Any]:
        with self._state_lock:
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
        with self._operation_lock:
            return self._sync_locked(cards, revision_id=revision_id)

    def _sync_locked(self, cards: Sequence[SourceCard], *, revision_id: str) -> SyncResult:
        if not revision_id.strip():
            raise ValueError("revision_id must not be blank")
        if not cards:
            raise ValueError("A repository revision must contain at least one source card")
        for card in cards:
            if card.metadata.get("repository_id") != self.repository_id:
                raise ValueError(f"Source card {card.source_id} belongs to another repository")
            if card.metadata.get("revision_id") != revision_id:
                raise ValueError(f"Source card {card.source_id} belongs to another revision")
        by_id = {card.source_id: card for card in cards}
        if len(by_id) != len(cards):
            raise ValueError("Source cards contain duplicate source IDs")
        new_hashes = {source_id: _card_hash(card) for source_id, card in by_id.items()}
        with self._state_lock:
            old_hashes = dict(self.manifest.sources)
            ready_revision = self.manifest.revision_id
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
        affected = tuple(sorted(set(changed).union(removed)))
        session_id = f"sync_{uuid.uuid4().hex}"
        self._set_state(SyncStatus.INDEXING, indeterminate=True)
        self.events.emit(
            "hydradb_sync_started",
            session_id=session_id,
            revision_id=revision_id,
            entity_ids=tuple(
                card.node_id for card in cards if card.source_id in changed
            )[:100],
            hydradb_query_metadata={
                "database": self.client.config.database,
                "collection": self.client.config.collection,
                "added": len(added),
                "replaced": len(replaced),
                "deleted": len(removed),
                "affected_entity_count": len(changed),
            },
        )
        try:
            for batch in _batches([by_id[source_id] for source_id in changed], self.batch_size):
                self.client.ingest(
                    app_knowledge=build_app_knowledge(batch),
                    graph_payload=build_graph_payload(batch),
                    upsert=True,
                )
            failed = self._wait_until_completed(changed)
            if failed:
                self._set_state(SyncStatus.FAILED, indeterminate=bool(changed))
                return SyncResult(
                    status=SyncStatus.FAILED,
                    candidate_revision=revision_id,
                    ready_revision=ready_revision,
                    added=added,
                    replaced=replaced,
                    deleted=(),
                    pending=(),
                    failed=failed,
                    current_state_indeterminate=bool(changed),
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
                confirmed = {
                    str(item.get("id"))
                    for item in results
                    if isinstance(item, Mapping) and item.get("deleted") is True
                }
                missing_confirmations = set(removed).difference(confirmed)
                failed_deletes.update(
                    {source_id: "delete not confirmed" for source_id in missing_confirmations}
                )
                deleted_count = int(deletion.get("deleted_count", -1))
                if deleted_count != len(removed) and deleted_count != len(confirmed):
                    failed_deletes["__aggregate__"] = (
                        "deleted_count disagrees with item confirmations"
                    )
                if failed_deletes:
                    self._set_state(SyncStatus.FAILED, indeterminate=True)
                    return SyncResult(
                        status=SyncStatus.FAILED,
                        candidate_revision=revision_id,
                        ready_revision=ready_revision,
                        added=added,
                        replaced=replaced,
                        deleted=tuple(
                            source_id for source_id in removed if source_id in confirmed
                        ),
                        pending=tuple(
                            source_id for source_id in removed if source_id not in confirmed
                        ),
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
            self._set_state(SyncStatus.UNAVAILABLE, indeterminate=bool(affected))
            return SyncResult(
                status=SyncStatus.UNAVAILABLE,
                candidate_revision=revision_id,
                ready_revision=ready_revision,
                added=added,
                replaced=replaced,
                deleted=(),
                pending=affected,
                failed={},
                current_state_indeterminate=bool(affected),
                warning=(
                    f"{exc}. The prior revision is only the last verified marker; "
                    "the current collection state could not be confirmed."
                ),
            )
        manifest = SyncManifest(
            repository_id=self.repository_id,
            revision_id=revision_id,
            sources=new_hashes,
            database=self.client.config.database,
            collection=self.client.config.collection,
        )
        try:
            self._persist_manifest(manifest)
        except OSError as exc:
            self._set_state(SyncStatus.FAILED, indeterminate=True)
            return SyncResult(
                status=SyncStatus.FAILED,
                candidate_revision=revision_id,
                ready_revision=ready_revision,
                added=added,
                replaced=replaced,
                deleted=deleted,
                pending=(),
                failed={"manifest": str(exc)},
                current_state_indeterminate=True,
                warning=(
                    "HydraDB completed the candidate revision, but its local verification "
                    "manifest could not be saved; current queries remain gated."
                ),
            )
        self._set_state(SyncStatus.READY, indeterminate=False, manifest=manifest)
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
            status=SyncStatus.READY,
            candidate_revision=revision_id,
            ready_revision=revision_id,
            added=added,
            replaced=replaced,
            deleted=deleted,
            pending=(),
            failed={},
        )

    def _set_state(
        self,
        status: SyncStatus,
        *,
        indeterminate: bool,
        manifest: SyncManifest | None = None,
    ) -> None:
        with self._state_lock:
            self._status = status
            self._current_state_indeterminate = indeterminate
            if manifest is not None:
                self.manifest = manifest

    def _load_manifest(self) -> SyncManifest:
        if self.manifest_path is None or not self.manifest_path.exists():
            return SyncManifest(repository_id=self.repository_id)
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            manifest = SyncManifest(
                repository_id=str(payload["repository_id"]),
                revision_id=(
                    str(payload["revision_id"])
                    if payload.get("revision_id") is not None
                    else None
                ),
                sources={str(key): str(value) for key, value in payload["sources"].items()},
                database=(str(payload["database"]) if payload.get("database") else None),
                collection=(
                    str(payload["collection"]) if payload.get("collection") else None
                ),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid sync manifest: {self.manifest_path}") from exc
        return manifest

    def _persist_manifest(self, manifest: SyncManifest) -> None:
        if self.manifest_path is None:
            return
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.manifest_path.with_name(
            f".{self.manifest_path.name}.{uuid.uuid4().hex}.tmp"
        )
        payload = {
            "repository_id": manifest.repository_id,
            "revision_id": manifest.revision_id,
            "sources": dict(manifest.sources),
            "database": manifest.database,
            "collection": manifest.collection,
        }
        try:
            temporary.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.manifest_path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _wait_until_completed(self, source_ids: Sequence[str]) -> dict[str, str]:
        if not source_ids:
            return {}
        deadline = self._monotonic() + self.client.config.poll_timeout_seconds
        while True:
            statuses: dict[str, Mapping[str, Any]] = {}
            for index in range(0, len(source_ids), self.batch_size):
                batch = source_ids[index : index + self.batch_size]
                data = response_data(self.client.status(batch))
                statuses.update(
                    {
                        str(item.get("id")): item
                        for item in data.get("statuses", [])
                        if isinstance(item, Mapping)
                    }
                )
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
    if not card.additional_metadata.get("content_hash"):
        raise ValueError(f"Source card {card.source_id} has no content_hash")
    # Source content alone is not a sync identity. Revision metadata, readable
    # card text, and the complete BYOG payload all affect what HydraDB stores.
    payload = card.model_dump(mode="json", exclude_none=True)
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _batches(items: Sequence[SourceCard], size: int) -> list[list[SourceCard]]:
    if not items:
        return []
    return [list(items[index : index + size]) for index in range(0, len(items), size)]
