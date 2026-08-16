"""Reliable Graph IR card synchronization into HydraDB Knowledge."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from threading import Lock, RLock
from typing import Any

from .cards import SourceCard, build_app_knowledge, build_graph_payload
from .events import EventBus
from .hydradb import (
    HydraDBAPIError,
    HydraDBClient,
    HydraDBError,
    HydraDBUnavailable,
    accepted_ingest_ids,
    hydradb_reason,
    response_data,
)

_UNAVAILABLE_WARNING = (
    "HydraDB could not complete the indexing operation. The prior revision is "
    "only the last verified marker; the current collection state could not be "
    "confirmed."
)
_CANCELLED_REASON = "Indexing was cancelled after a partial upload"
_RUNTIME_IGNORE = "*\n"
_IN_PROGRESS_MARKER = "sync-in-progress.json"


class _Cancelled(Exception):
    """Internal signal that the caller withdrew an in-flight sync."""


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
    byog_sources: tuple[str, ...] = ()
    database_fingerprint: str | None = None
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
        status_batch_size: int | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        # Ingest carries whole cards, so its batch stays small. A status poll
        # carries only ids, so it can cover far more sources per request.
        resolved_status_batch = (
            client.config.status_batch_size if status_batch_size is None else status_batch_size
        )
        if resolved_status_batch < 1:
            raise ValueError("status_batch_size must be positive")
        self.client = client
        self.repository_id = repository_id
        self.manifest_path = Path(manifest_path).resolve() if manifest_path else None
        self.in_progress_path = (
            self.manifest_path.with_name(_IN_PROGRESS_MARKER) if self.manifest_path else None
        )
        self._interrupted_sync = bool(
            self.in_progress_path is not None and self.in_progress_path.exists()
        )
        self._legacy_database_field = False
        self.manifest = manifest or self._load_manifest()
        if self.manifest.repository_id != repository_id:
            # The uploaded cards carry the manifest's repository id in their namespace, so
            # the id cannot be rewritten. Name both ids and the file: deleting the file and
            # indexing again is the only repair, and the user cannot find it otherwise.
            raise ValueError(
                "Sync manifest belongs to another repository: it holds "
                f"{self.manifest.repository_id!r} but this project is {repository_id!r}. "
                f"Delete {self.manifest_path} and index the project again."
            )
        database_fingerprint = self.client.database_fingerprint()
        if database_fingerprint is not None and self.manifest.database_fingerprint not in {
            None,
            database_fingerprint,
        }:
            raise ValueError("Sync manifest belongs to another HydraDB database")
        if self.manifest.collection not in {None, self.client.config.collection}:
            raise ValueError("Sync manifest belongs to another HydraDB collection")
        if self._legacy_database_field:
            self._persist_manifest(self.manifest)
        self.events = events or EventBus()
        self.batch_size = batch_size
        self._status_batch_size = resolved_status_batch
        self._sleep = sleep
        self._monotonic = monotonic
        self._status = (
            SyncStatus.FAILED
            if self._interrupted_sync
            else (SyncStatus.READY if self.manifest.revision_id else SyncStatus.IDLE)
        )
        self._current_state_indeterminate = self._interrupted_sync
        self._state_lock = RLock()
        self._operation_lock = Lock()

    @property
    def status(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "status": self._status.value,
                "ready_revision": self.manifest.revision_id,
                "source_count": len(self.manifest.sources),
                "hydradb_available": self.client.configured,
                "collection": self.client.config.collection,
                "current_state_indeterminate": self._current_state_indeterminate,
            }

    def verified_byog_source_ids(self) -> tuple[str, ...]:
        """Return BYOG source ownership only for the verified current snapshot."""

        with self._state_lock:
            if self._status is not SyncStatus.READY or self._current_state_indeterminate:
                return ()
            return self.manifest.byog_sources

    def verifies_snapshot(self, cards: Sequence[SourceCard], *, revision_id: str) -> bool:
        """Return whether cards exactly match the last verified current snapshot."""

        try:
            hashes = {card.source_id: _card_hash(card) for card in cards}
        except ValueError:
            return False
        if len(hashes) != len(cards):
            return False
        with self._state_lock:
            return bool(
                self._status is SyncStatus.READY
                and not self._current_state_indeterminate
                and self.manifest.revision_id == revision_id
                and dict(self.manifest.sources) == hashes
            )

    def sync(
        self,
        cards: Sequence[SourceCard],
        *,
        revision_id: str,
        progress: Callable[[str, int, int], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> SyncResult:
        with self._operation_lock:
            return self._sync_locked(
                cards,
                revision_id=revision_id,
                progress=progress,
                should_cancel=should_cancel,
            )

    def _sync_locked(
        self,
        cards: Sequence[SourceCard],
        *,
        revision_id: str,
        progress: Callable[[str, int, int], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> SyncResult:
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
            old_byog_sources = set(self.manifest.byog_sources)
            ready_revision = self.manifest.revision_id
            force_full_recovery = self._interrupted_sync
        added = tuple(sorted(set(new_hashes).difference(old_hashes)))
        replaced = tuple(
            sorted(
                source_id
                for source_id in set(new_hashes).intersection(old_hashes)
                if force_full_recovery or new_hashes[source_id] != old_hashes[source_id]
            )
        )
        removed = tuple(sorted(set(old_hashes).difference(new_hashes)))
        changed = (*added, *replaced)
        stale_byog = tuple(
            source_id
            for source_id in replaced
            if source_id in old_byog_sources and not by_id[source_id].graph.relations
        )
        affected = tuple(sorted(set(changed).union(removed)))
        remote_write_started = False

        def begin_remote_write() -> None:
            nonlocal remote_write_started
            if remote_write_started:
                return
            self._persist_in_progress(revision_id)
            remote_write_started = True

        session_id = f"sync_{uuid.uuid4().hex}"
        self._set_state(SyncStatus.INDEXING, indeterminate=True)
        self.events.emit(
            "hydradb_sync_started",
            session_id=session_id,
            revision_id=revision_id,
            entity_ids=tuple(card.node_id for card in cards if card.source_id in changed)[:100],
            hydradb_query_metadata={
                "collection": self.client.config.collection,
                "added": len(added),
                "replaced": len(replaced),
                "deleted": len(removed),
                "affected_entity_count": len(changed),
            },
        )
        try:
            if should_cancel is not None and should_cancel():
                raise _Cancelled
            # HydraDB persists an earlier BYOG graph when a later upsert omits
            # graph_payload for the same source. Delete only this transition so
            # stale exact edges cannot survive a relation-free revision.
            for batch in _id_batches(stale_byog, self._status_batch_size):
                if should_cancel is not None and should_cancel():
                    raise _Cancelled
                begin_remote_write()
                confirmed, failed_deletes = _confirmed_deletions(
                    batch, response_data(self.client.delete(batch))
                )
                _report(progress, "clearing_stale_graphs", len(confirmed), len(batch))
                if failed_deletes:
                    self._set_state(SyncStatus.FAILED, indeterminate=True)
                    return SyncResult(
                        status=SyncStatus.FAILED,
                        candidate_revision=revision_id,
                        ready_revision=ready_revision,
                        added=added,
                        replaced=replaced,
                        deleted=(),
                        pending=tuple(
                            source_id for source_id in batch if source_id not in confirmed
                        ),
                        failed=failed_deletes,
                        current_state_indeterminate=True,
                        warning=(
                            "HydraDB could not clear every stale BYOG graph before re-indexing. "
                            "The candidate revision was not verified."
                        ),
                    )
            upload_batches = _batches([by_id[source_id] for source_id in changed], self.batch_size)
            for index, batch in enumerate(upload_batches):
                if should_cancel is not None and should_cancel():
                    raise _Cancelled
                begin_remote_write()
                response = self.client.ingest(
                    app_knowledge=build_app_knowledge(batch),
                    graph_payload=build_graph_payload(batch),
                    upsert=True,
                )
                expected = {card.source_id for card in batch}
                accepted = accepted_ingest_ids(response)
                if accepted != expected:
                    failed_ids = expected.difference(accepted)
                    unexpected_ids = accepted.difference(expected)
                    failures = {
                        source_id: "HydraDB did not acknowledge this source"
                        for source_id in sorted(failed_ids)
                    }
                    if unexpected_ids:
                        failures["__unexpected__"] = (
                            "HydraDB acknowledged unexpected source IDs: "
                            + ", ".join(sorted(unexpected_ids))
                        )
                    self._set_state(SyncStatus.FAILED, indeterminate=True)
                    return SyncResult(
                        status=SyncStatus.FAILED,
                        candidate_revision=revision_id,
                        ready_revision=ready_revision,
                        added=added,
                        replaced=replaced,
                        deleted=(),
                        pending=tuple(sorted(failed_ids)),
                        failed=failures,
                        current_state_indeterminate=True,
                        warning=(
                            "HydraDB did not acknowledge the complete ingest batch. The prior "
                            "revision remains the last verified marker."
                        ),
                    )
                _report(progress, "uploading", index + 1, len(upload_batches))
            failed = self._wait_until_completed(
                changed, progress=progress, should_cancel=should_cancel
            )
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
                if should_cancel is not None and should_cancel():
                    raise _Cancelled
                begin_remote_write()
                confirmed, failed_deletes = _confirmed_deletions(
                    removed, response_data(self.client.delete(removed))
                )
                _report(progress, "deleting", len(removed), len(removed))
                if failed_deletes:
                    self._set_state(SyncStatus.FAILED, indeterminate=True)
                    return SyncResult(
                        status=SyncStatus.FAILED,
                        candidate_revision=revision_id,
                        ready_revision=ready_revision,
                        added=added,
                        replaced=replaced,
                        deleted=tuple(source_id for source_id in removed if source_id in confirmed),
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
        except _Cancelled:
            indeterminate = remote_write_started or self._interrupted_sync
            if indeterminate:
                status = SyncStatus.FAILED
            else:
                status = SyncStatus.READY if ready_revision else SyncStatus.IDLE
            self._set_state(status, indeterminate=indeterminate)
            return SyncResult(
                status=SyncStatus.FAILED,
                candidate_revision=revision_id,
                ready_revision=ready_revision,
                added=added,
                replaced=replaced,
                deleted=(),
                pending=(),
                failed={"__cancelled__": _CANCELLED_REASON},
                current_state_indeterminate=indeterminate,
                warning=(
                    (
                        "The candidate revision was cancelled. Part of it may already be visible "
                        "in the current collection, and the prior revision remains the last "
                        "verified marker."
                    )
                    if indeterminate
                    else "The candidate revision was cancelled before any HydraDB write."
                ),
            )
        # HydraDB's own status, code, and message say far more than a generic
        # outage sentence. A contract error is local, so it never becomes one.
        except (HydraDBAPIError, HydraDBUnavailable) as exc:
            return self._unavailable_result(
                revision_id=revision_id,
                ready_revision=ready_revision,
                added=added,
                replaced=replaced,
                affected=affected,
                reason=hydradb_reason(exc),
            )
        except HydraDBError:
            return self._unavailable_result(
                revision_id=revision_id,
                ready_revision=ready_revision,
                added=added,
                replaced=replaced,
                affected=affected,
                reason=None,
            )
        except OSError as exc:
            indeterminate = remote_write_started or self._interrupted_sync
            self._set_state(SyncStatus.FAILED, indeterminate=indeterminate)
            return SyncResult(
                status=SyncStatus.FAILED,
                candidate_revision=revision_id,
                ready_revision=ready_revision,
                added=added,
                replaced=replaced,
                deleted=(),
                pending=affected,
                failed={"sync-safety-marker": str(exc)},
                current_state_indeterminate=indeterminate,
                warning=(
                    "The local interrupted-sync marker could not be updated. No unmarked "
                    "HydraDB write was attempted."
                ),
            )
        manifest = SyncManifest(
            repository_id=self.repository_id,
            revision_id=revision_id,
            sources=new_hashes,
            byog_sources=tuple(sorted(card.source_id for card in cards if card.graph.relations)),
            database_fingerprint=self.client.database_fingerprint(),
            collection=self.client.config.collection,
        )
        try:
            self._persist_manifest(manifest)
            self._clear_in_progress()
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

    def _unavailable_result(
        self,
        *,
        revision_id: str,
        ready_revision: str | None,
        added: tuple[str, ...],
        replaced: tuple[str, ...],
        affected: tuple[str, ...],
        reason: str | None,
    ) -> SyncResult:
        indeterminate = bool(affected) or self._interrupted_sync
        self._set_state(SyncStatus.UNAVAILABLE, indeterminate=indeterminate)
        return SyncResult(
            status=SyncStatus.UNAVAILABLE,
            candidate_revision=revision_id,
            ready_revision=ready_revision,
            added=added,
            replaced=replaced,
            deleted=(),
            pending=affected,
            failed={},
            current_state_indeterminate=indeterminate,
            warning=(
                _UNAVAILABLE_WARNING if reason is None else f"{_UNAVAILABLE_WARNING} {reason}"
            ),
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
                    str(payload["revision_id"]) if payload.get("revision_id") is not None else None
                ),
                sources={str(key): str(value) for key, value in payload["sources"].items()},
                # Manifests written before this field existed are conservative:
                # any prior source might have had a persistent BYOG graph.
                byog_sources=tuple(
                    str(item) for item in payload.get("byog_sources", payload["sources"].keys())
                ),
                database_fingerprint=(
                    str(payload["database_fingerprint"])
                    if payload.get("database_fingerprint")
                    else None
                ),
                collection=(str(payload["collection"]) if payload.get("collection") else None),
            )
            self._legacy_database_field = "database" in payload
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid sync manifest: {self.manifest_path}") from exc
        return manifest

    def _persist_manifest(self, manifest: SyncManifest) -> None:
        if self.manifest_path is None:
            return
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        ignore_path = self.manifest_path.parent / ".gitignore"
        try:
            with ignore_path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(_RUNTIME_IGNORE)
        except FileExistsError:
            pass
        temporary = self.manifest_path.with_name(
            f".{self.manifest_path.name}.{uuid.uuid4().hex}.tmp"
        )
        payload = {
            "repository_id": manifest.repository_id,
            "revision_id": manifest.revision_id,
            "sources": dict(manifest.sources),
            "byog_sources": list(manifest.byog_sources),
            "database_fingerprint": manifest.database_fingerprint,
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

    def _persist_in_progress(self, revision_id: str) -> None:
        if self.in_progress_path is None:
            return
        self.in_progress_path.parent.mkdir(parents=True, exist_ok=True)
        ignore_path = self.in_progress_path.parent / ".gitignore"
        try:
            with ignore_path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(_RUNTIME_IGNORE)
        except FileExistsError:
            pass
        temporary = self.in_progress_path.with_name(
            f".{self.in_progress_path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            temporary.write_text(
                json.dumps(
                    {
                        "repository_id": self.repository_id,
                        "candidate_revision": revision_id,
                        "started_at": time.time(),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.in_progress_path)
            self._interrupted_sync = True
        finally:
            if temporary.exists():
                temporary.unlink()

    def _clear_in_progress(self) -> None:
        if self.in_progress_path is not None:
            self.in_progress_path.unlink(missing_ok=True)
        self._interrupted_sync = False

    def _wait_until_completed(
        self,
        source_ids: Sequence[str],
        *,
        progress: Callable[[str, int, int], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> dict[str, str]:
        if not source_ids:
            return {}
        total = len(source_ids)
        # Only sources that have not reported "completed" are asked about again.
        # Re-polling every source each cycle costs one request per batch per
        # cycle, which a repository of thousands of sources can never finish.
        pending = list(source_ids)
        deadline = self._monotonic() + self.client.config.poll_timeout_seconds
        while True:
            if should_cancel is not None and should_cancel():
                raise _Cancelled
            statuses: dict[str, Mapping[str, Any]] = {}
            for index in range(0, len(pending), self._status_batch_size):
                batch = pending[index : index + self._status_batch_size]
                data = response_data(self.client.status(batch))
                statuses.update(
                    {
                        str(item.get("id")): item
                        for item in data.get("statuses", [])
                        if isinstance(item, Mapping)
                    }
                )
            missing = set(pending).difference(statuses)
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
            pending = [
                source_id
                for source_id in pending
                if statuses[source_id].get("indexing_status") != "completed"
            ]
            _report(progress, "verifying", total - len(pending), total)
            if not pending:
                return {}
            if self._monotonic() >= deadline:
                return {
                    source_id: (
                        "indexing timed out in state "
                        f"{statuses[source_id].get('indexing_status', 'unknown')}"
                    )
                    for source_id in pending
                }
            self._sleep(self.client.config.poll_interval_seconds)


def _report(
    progress: Callable[[str, int, int], None] | None, phase: str, done: int, total: int
) -> None:
    """Report one step of a phase, never letting a caller bug break the sync.

    A progress callback belongs to the caller. An exception raised there must
    not abandon an upload that is already partly visible in HydraDB.
    """

    if progress is None:
        return
    with suppress(Exception):
        progress(phase, done, total)


def _card_hash(card: SourceCard) -> str:
    if not card.additional_metadata.get("content_hash"):
        raise ValueError(f"Source card {card.source_id} has no content_hash")
    # Hash the actual HydraDB projection. This makes a wire-contract change
    # trigger replacement even when the richer local SourceCard is unchanged.
    graph_payload = build_graph_payload([card])
    payload = {
        "app_knowledge": build_app_knowledge([card])[0],
        "graph_payload": graph_payload.get(card.source_id),
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _batches(items: Sequence[SourceCard], size: int) -> list[list[SourceCard]]:
    if not items:
        return []
    return [list(items[index : index + size]) for index in range(0, len(items), size)]


def _id_batches(items: Sequence[str], size: int) -> list[list[str]]:
    if not items:
        return []
    return [list(items[index : index + size]) for index in range(0, len(items), size)]


def _confirmed_deletions(
    expected_ids: Sequence[str], deletion: Mapping[str, Any]
) -> tuple[set[str], dict[str, str]]:
    results = deletion.get("results", [])
    failed = {
        str(item.get("id")): str(item.get("error") or "delete failed")
        for item in results
        if isinstance(item, Mapping) and not item.get("deleted")
    }
    confirmed = {
        str(item.get("id"))
        for item in results
        if isinstance(item, Mapping) and item.get("deleted") is True
    }
    missing = set(expected_ids).difference(confirmed)
    failed.update({source_id: "delete not confirmed" for source_id in missing})
    deleted_count = int(deletion.get("deleted_count", -1))
    if deleted_count != len(expected_ids) and deleted_count != len(confirmed):
        failed["__aggregate__"] = "deleted_count disagrees with item confirmations"
    return confirmed, failed
