from __future__ import annotations

import json
from threading import Event, Thread
from typing import Any

from hydra_graph.cards import HydraEntity, HydraRelation, HydraSourceGraph, SourceCard
from hydra_graph.config import HydraDBConfig
from hydra_graph.events import EventBus
from hydra_graph.hydradb import HydraDBAPIError, HydraDBClient, HydraDBUnavailable
from hydra_graph.sync import SyncManifest, SyncService, SyncStatus


def card(
    source_id: str,
    node_id: str,
    content_hash: str,
    *,
    revision_id: str = "rev-new",
    relation_predicate: str | None = None,
) -> SourceCard:
    graph = HydraSourceGraph(
        entities={
            node_id: HydraEntity(
                name=node_id,
                type="FILE",
                namespace="test",
                identifier=node_id,
            )
        },
        relations=(),
    )
    if relation_predicate:
        graph = HydraSourceGraph(
            entities={
                "source": HydraEntity(name="source", type="FUNCTION", namespace="test"),
                "target": HydraEntity(name="target", type="FUNCTION", namespace="test"),
            },
            relations=(
                HydraRelation(
                    source="source",
                    target="target",
                    predicate=relation_predicate,
                    context="source relation target",
                ),
            ),
        )
    return SourceCard(
        source_id=source_id,
        node_id=node_id,
        content=f"Entity: {node_id}",
        metadata={
            "repository_id": "hack-hydra",
            "revision_id": revision_id,
            "entity_kind": "FILE",
            "language": "python",
            "relation_quality": "exact",
            "is_generated": False,
            "is_test": False,
        },
        additional_metadata={
            "display_name": node_id,
            "path": f"src/{node_id}.py",
            "content_hash": content_hash,
            "node_id": node_id,
        },
        graph=graph,
    )


class LifecycleTransport:
    def __init__(self, *, fail_status: bool = False, unavailable: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.status_calls = 0
        self.fail_status = fail_status
        self.unavailable = unavailable

    def request(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.unavailable:
            raise HydraDBUnavailable("sync network sentinel")
        if kwargs["url"].endswith("/context/ingest"):
            sources = json.loads(kwargs["form"]["app_knowledge"])
            return {
                "success": True,
                "data": {"ids": [str(source["id"]) for source in sources]},
            }
        if kwargs["url"].endswith("/context/status"):
            self.status_calls += 1
            ids = kwargs["query"]["ids"].split(",")
            state = (
                "errored"
                if self.fail_status
                else ("processing" if self.status_calls == 1 else "completed")
            )
            return {
                "success": True,
                "data": {
                    "statuses": [
                        {
                            "id": source_id,
                            "indexing_status": state,
                            "success": state != "errored",
                            "error_code": "PROCESSING_FAILED" if state == "errored" else "",
                        }
                        for source_id in ids
                    ]
                },
            }
        if kwargs["method"] == "DELETE":
            ids = kwargs["json_body"]["ids"]
            return {
                "success": True,
                "data": {
                    "deleted_count": len(ids),
                    "results": [{"id": source_id, "deleted": True} for source_id in ids],
                },
            }
        raise AssertionError(kwargs)


def sync_service(
    transport: LifecycleTransport,
    *,
    manifest: SyncManifest | None = None,
    batch_size: int = 25,
    status_batch_size: int | None = None,
    config_status_batch_size: int = 100,
) -> tuple[SyncService, EventBus]:
    events = EventBus()
    client = HydraDBClient(
        HydraDBConfig(
            api_key="test",
            database="repo_hack_hydra",
            max_retries=0,
            poll_interval_seconds=0.001,
            poll_timeout_seconds=1,
            status_batch_size=config_status_batch_size,
        ),
        transport=transport,
    )
    return (
        SyncService(
            client,
            repository_id="hack-hydra",
            manifest=manifest,
            events=events,
            batch_size=batch_size,
            status_batch_size=status_batch_size,
            sleep=lambda _: None,
        ),
        events,
    )


def test_sync_ingests_waits_for_graph_completion_then_publishes_revision() -> None:
    transport = LifecycleTransport()
    service, events = sync_service(transport)

    result = service.sync([card("source-a", "node-a", "a" * 64)], revision_id="rev-new")

    assert result.status is SyncStatus.READY
    assert result.added == ("source-a",)
    assert result.ready_revision == "rev-new"
    assert set(service.manifest.sources) == {"source-a"}
    assert service.manifest.byog_sources == ()
    assert service.manifest.sources["source-a"] != "a" * 64
    assert transport.status_calls == 2
    assert [event["type"] for event in events.recent()] == [
        "hydradb_sync_started",
        "hydradb_revision_ready",
    ]


def test_partial_ingest_acknowledgement_fails_before_status_polling() -> None:
    class PartialAckTransport(LifecycleTransport):
        def request(self, **kwargs: Any) -> dict[str, Any]:
            if kwargs["url"].endswith("/context/ingest"):
                self.calls.append(kwargs)
                return {
                    "success": True,
                    "data": {
                        "results": [
                            {"id": "source-a", "status": "queued", "error": ""},
                            {
                                "id": "source-b",
                                "status": "failed",
                                "error": "invalid source",
                            },
                        ]
                    },
                }
            return super().request(**kwargs)

    transport = PartialAckTransport()
    service, _ = sync_service(transport)

    result = service.sync(
        [
            card("source-a", "node-a", "a" * 64),
            card("source-b", "node-b", "b" * 64),
        ],
        revision_id="rev-new",
    )

    assert result.status is SyncStatus.FAILED
    assert result.pending == ("source-b",)
    assert result.failed == {"source-b": "HydraDB did not acknowledge this source"}
    assert transport.status_calls == 0
    assert service.manifest.revision_id is None


def test_sync_replaces_changed_sources_and_deletes_removed_only_after_ready() -> None:
    manifest = SyncManifest(
        repository_id="hack-hydra",
        revision_id="rev-old",
        sources={"source-a": "old", "source-removed": "r" * 64},
    )
    transport = LifecycleTransport()
    service, _ = sync_service(transport, manifest=manifest)

    result = service.sync([card("source-a", "node-a", "a" * 64)], revision_id="rev-new")

    assert result.replaced == ("source-a",)
    assert result.deleted == ("source-removed",)
    methods_and_paths = [
        (call["method"], call["url"].rsplit("/", 1)[-1]) for call in transport.calls
    ]
    assert methods_and_paths[-1] == ("DELETE", "context")


def test_relation_bearing_source_is_deleted_before_relation_free_replacement() -> None:
    manifest = SyncManifest(
        repository_id="hack-hydra",
        revision_id="rev-old",
        sources={"source-a": "old"},
        byog_sources=("source-a",),
    )
    transport = LifecycleTransport()
    service, _ = sync_service(transport, manifest=manifest)

    result = service.sync([card("source-a", "node-a", "a" * 64)], revision_id="rev-new")

    assert result.status is SyncStatus.READY
    calls = [
        call
        for call in transport.calls
        if call["method"] == "DELETE" or call["url"].endswith("/context/ingest")
    ]
    assert calls[0]["method"] == "DELETE"
    assert calls[0]["json_body"]["ids"] == ["source-a"]
    assert calls[1]["url"].endswith("/context/ingest")
    assert "graph_payload" not in calls[1]["form"]
    assert service.manifest.byog_sources == ()


def test_failed_candidate_does_not_advance_verified_manifest_or_delete_old_source() -> None:
    manifest = SyncManifest(
        repository_id="hack-hydra",
        revision_id="rev-old",
        sources={"source-a": "old", "source-removed": "r" * 64},
    )
    transport = LifecycleTransport(fail_status=True)
    service, _ = sync_service(transport, manifest=manifest)

    result = service.sync([card("source-a", "node-a", "a" * 64)], revision_id="rev-new")

    assert result.status is SyncStatus.FAILED
    assert result.ready_revision == "rev-old"
    assert result.current_state_indeterminate is True
    assert "candidate content may already be visible" in (result.warning or "")
    assert service.manifest == manifest
    assert not any(call["method"] == "DELETE" for call in transport.calls)


def test_unavailable_sync_is_explicit_and_keeps_prior_verified_revision() -> None:
    manifest = SyncManifest(
        repository_id="hack-hydra", revision_id="rev-old", sources={"source-a": "old"}
    )
    transport = LifecycleTransport(unavailable=True)
    service, _ = sync_service(transport, manifest=manifest)

    result = service.sync([card("source-a", "node-a", "a" * 64)], revision_id="rev-new")

    assert result.status is SyncStatus.UNAVAILABLE
    assert result.ready_revision == "rev-old"
    assert result.pending == ("source-a",)
    assert result.current_state_indeterminate is True
    assert "only the last verified marker" in (result.warning or "")
    assert service.manifest == manifest
    assert service.status["current_state_indeterminate"] is True
    # Only bookkeeping remains. No fixture or prior Graph IR is used as a
    # replacement retrieval result when HydraDB cannot confirm the write.
    assert len(transport.calls) == 1


def test_relation_only_change_triggers_hydradb_upsert() -> None:
    old = card(
        "source-a",
        "node-a",
        "a" * 64,
        revision_id="rev-same",
        relation_predicate="CALLS",
    )
    old_service, _ = sync_service(LifecycleTransport())
    first = old_service.sync([old], revision_id="rev-same")
    assert first.status is SyncStatus.READY
    new = card(
        "source-a",
        "node-a",
        "a" * 64,
        revision_id="rev-same",
        relation_predicate="READS_FROM",
    )
    transport = LifecycleTransport()
    service, _ = sync_service(transport, manifest=old_service.manifest)

    result = service.sync([new], revision_id="rev-same")

    assert result.replaced == ("source-a",)
    assert any(call["url"].endswith("/context/ingest") for call in transport.calls)


def test_partial_delete_confirmation_cannot_publish_revision() -> None:
    class PartialDeleteTransport(LifecycleTransport):
        def request(self, **kwargs: Any) -> dict[str, Any]:
            if kwargs["method"] == "DELETE":
                self.calls.append(kwargs)
                first = kwargs["json_body"]["ids"][0]
                return {
                    "success": True,
                    "data": {
                        "deleted_count": 1,
                        "results": [{"id": first, "deleted": True}],
                    },
                }
            return super().request(**kwargs)

    manifest = SyncManifest(
        repository_id="hack-hydra",
        revision_id="rev-old",
        sources={"removed-a": "hash-a", "removed-b": "hash-b"},
    )
    service, _ = sync_service(PartialDeleteTransport(), manifest=manifest)

    result = service.sync([card("source-c", "node-c", "c" * 64)], revision_id="rev-new")

    assert result.status is SyncStatus.FAILED
    assert result.ready_revision == "rev-old"
    assert result.current_state_indeterminate is True
    assert result.deleted == ("removed-a",)
    assert result.pending == ("removed-b",)
    assert result.failed["removed-b"] == "delete not confirmed"


def test_deletion_only_outage_is_indeterminate_and_keeps_pending_source() -> None:
    manifest = SyncManifest(
        repository_id="hack-hydra",
        revision_id="rev-old",
        sources={"removed-a": "hash-a"},
    )
    service, _ = sync_service(LifecycleTransport(unavailable=True), manifest=manifest)

    result = service.sync([card("source-b", "node-b", "b" * 64)], revision_id="rev-new")

    assert result.status is SyncStatus.UNAVAILABLE
    assert result.current_state_indeterminate is True
    assert result.pending == ("removed-a", "source-b")


def test_empty_candidate_fails_before_hydradb_io() -> None:
    transport = LifecycleTransport()
    service, _ = sync_service(transport)

    try:
        service.sync([], revision_id="rev-empty")
    except ValueError as exc:
        assert "at least one source card" in str(exc)
    else:
        raise AssertionError("empty candidate was accepted")

    assert transport.calls == []


def test_foreign_repository_or_revision_card_fails_before_hydradb_io() -> None:
    transport = LifecycleTransport()
    service, _ = sync_service(transport)
    foreign = card("source-a", "node-a", "a" * 64)
    foreign = foreign.model_copy(
        update={"metadata": {**foreign.metadata, "repository_id": "other-repository"}}
    )

    try:
        service.sync([foreign], revision_id="rev-new")
    except ValueError as exc:
        assert "another repository" in str(exc)
    else:
        raise AssertionError("foreign card was accepted")

    wrong_revision = card("source-a", "node-a", "a" * 64, revision_id="different-revision")
    try:
        service.sync([wrong_revision], revision_id="rev-new")
    except ValueError as exc:
        assert "another revision" in str(exc)
    else:
        raise AssertionError("wrong-revision card was accepted")
    assert transport.calls == []


def test_concurrent_syncs_are_serialized_and_publish_in_call_order() -> None:
    entered = Event()
    release = Event()

    class BlockingTransport(LifecycleTransport):
        def request(self, **kwargs: Any) -> dict[str, Any]:
            if kwargs["url"].endswith("/context/ingest") and not entered.is_set():
                self.calls.append(kwargs)
                entered.set()
                assert release.wait(timeout=2)
                return {"success": True, "data": {"ids": ["source-a"]}}
            return super().request(**kwargs)

    transport = BlockingTransport()
    service, _ = sync_service(transport)
    results: list[Any] = []
    first = Thread(
        target=lambda: results.append(
            service.sync(
                [card("source-a", "node-a", "a" * 64, revision_id="rev-one")],
                revision_id="rev-one",
            )
        )
    )
    second = Thread(
        target=lambda: results.append(
            service.sync(
                [card("source-a", "node-a", "a" * 64, revision_id="rev-two")],
                revision_id="rev-two",
            )
        )
    )
    first.start()
    assert entered.wait(timeout=2)
    second.start()
    assert len(transport.calls) == 1
    release.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert [result.ready_revision for result in results] == ["rev-one", "rev-two"]
    assert service.manifest.revision_id == "rev-two"


def test_indexing_status_is_visible_during_network_wait() -> None:
    entered = Event()
    release = Event()

    class BlockingTransport(LifecycleTransport):
        def request(self, **kwargs: Any) -> dict[str, Any]:
            if kwargs["url"].endswith("/context/ingest"):
                self.calls.append(kwargs)
                entered.set()
                assert release.wait(timeout=2)
                return {"success": True, "data": {"ids": ["source-a"]}}
            return super().request(**kwargs)

    service, _ = sync_service(BlockingTransport())
    worker = Thread(
        target=lambda: service.sync([card("source-a", "node-a", "a" * 64)], revision_id="rev-new")
    )
    worker.start()
    assert entered.wait(timeout=2)

    assert service.status["status"] == "indexing"
    assert service.status["current_state_indeterminate"] is True

    release.set()
    worker.join(timeout=2)


def test_large_sync_caps_events_and_batches_status_queries() -> None:
    transport = LifecycleTransport()
    service, events = sync_service(transport)
    cards = [card(f"source-{index}", f"node-{index}", f"{index:064x}") for index in range(101)]

    result = service.sync(cards, revision_id="rev-new")

    assert result.status is SyncStatus.READY
    started = events.recent()[0]
    assert len(started["entity_ids"]) == 100
    assert started["hydradb_query_metadata"]["affected_entity_count"] == 101
    status_calls = [call for call in transport.calls if call["url"].endswith("/context/status")]
    assert status_calls
    assert all(len(call["query"]["ids"].split(",")) <= 100 for call in status_calls)
    ingest_calls = [call for call in transport.calls if call["url"].endswith("/context/ingest")]
    assert all(len(json.loads(call["form"]["app_knowledge"])) <= 25 for call in ingest_calls)


def test_progress_reports_upload_verify_and_delete_phases() -> None:
    manifest = SyncManifest(
        repository_id="hack-hydra",
        revision_id="rev-old",
        sources={"source-removed": "r" * 64},
    )
    transport = LifecycleTransport()
    service, _ = sync_service(transport, manifest=manifest, batch_size=2)
    cards = [card(f"source-{index}", f"node-{index}", f"{index:064x}") for index in range(5)]
    seen: list[tuple[str, int, int]] = []

    result = service.sync(
        cards,
        revision_id="rev-new",
        progress=lambda phase, done, total: seen.append((phase, done, total)),
    )

    assert result.status is SyncStatus.READY
    assert [item for item in seen if item[0] == "uploading"] == [
        ("uploading", 1, 3),
        ("uploading", 2, 3),
        ("uploading", 3, 3),
    ]
    # The first poll cycle finds nothing finished, the second finds everything.
    assert [item for item in seen if item[0] == "verifying"] == [
        ("verifying", 0, 5),
        ("verifying", 5, 5),
    ]
    assert seen[-1] == ("deleting", 1, 1)


def test_progress_callback_failure_cannot_break_the_sync() -> None:
    transport = LifecycleTransport()
    service, _ = sync_service(transport)

    def explode(phase: str, done: int, total: int) -> None:
        raise RuntimeError("caller bug")

    result = service.sync(
        [card("source-a", "node-a", "a" * 64)], revision_id="rev-new", progress=explode
    )

    assert result.status is SyncStatus.READY
    assert service.manifest.revision_id == "rev-new"


def test_cancellation_between_batches_returns_the_indeterminate_failed_shape() -> None:
    transport = LifecycleTransport()
    service, _ = sync_service(transport, batch_size=1)
    cards = [card(f"source-{index}", f"node-{index}", f"{index:064x}") for index in range(3)]
    checks: list[int] = []

    def should_cancel() -> bool:
        checks.append(len(checks))
        return len(checks) > 3

    result = service.sync(cards, revision_id="rev-new", should_cancel=should_cancel)

    assert result.status is SyncStatus.FAILED
    assert result.current_state_indeterminate is True
    assert result.failed == {"__cancelled__": "Indexing was cancelled after a partial upload"}
    assert "cancelled" in (result.warning or "")
    assert "last verified marker" in (result.warning or "")
    assert result.ready_revision is None
    assert len([call for call in transport.calls if call["url"].endswith("/context/ingest")]) == 2
    assert not any(call["url"].endswith("/context/status") for call in transport.calls)
    assert service.status["status"] == "failed"
    assert service.status["current_state_indeterminate"] is True


def test_cancellation_during_verification_stops_polling() -> None:
    transport = LifecycleTransport()
    service, _ = sync_service(transport)
    checks: list[int] = []

    def should_cancel() -> bool:
        checks.append(len(checks))
        # Allow the one ingest batch, then withdraw at the first poll cycle.
        return len(checks) > 1

    result = service.sync(
        [card("source-a", "node-a", "a" * 64)], revision_id="rev-new", should_cancel=should_cancel
    )

    assert result.status is SyncStatus.FAILED
    assert result.failed == {"__cancelled__": "Indexing was cancelled after a partial upload"}
    assert transport.status_calls == 0


def test_poll_set_shrinks_as_sources_report_completed() -> None:
    class WaveTransport(LifecycleTransport):
        """Finishes two sources per poll cycle."""

        def __init__(self) -> None:
            super().__init__()
            self.polled: list[list[str]] = []
            self.finished: set[str] = set()

        def request(self, **kwargs: Any) -> dict[str, Any]:
            if not kwargs["url"].endswith("/context/status"):
                return super().request(**kwargs)
            self.calls.append(kwargs)
            self.status_calls += 1
            ids = kwargs["query"]["ids"].split(",")
            self.polled.append(ids)
            self.finished.update([item for item in ids if item not in self.finished][:2])
            return {
                "success": True,
                "data": {
                    "statuses": [
                        {
                            "id": item,
                            "indexing_status": (
                                "completed" if item in self.finished else "processing"
                            ),
                            "success": True,
                        }
                        for item in ids
                    ]
                },
            }

    transport = WaveTransport()
    service, _ = sync_service(transport)
    cards = [card(f"source-{index}", f"node-{index}", f"{index:064x}") for index in range(6)]

    result = service.sync(cards, revision_id="rev-new")

    assert result.status is SyncStatus.READY
    # A completed source is never asked about again, so each cycle costs less.
    assert [len(batch) for batch in transport.polled] == [6, 4, 2]


def test_status_uses_status_batch_size_while_ingest_uses_batch_size() -> None:
    transport = LifecycleTransport()
    service, _ = sync_service(transport, batch_size=2, status_batch_size=3)
    cards = [card(f"source-{index}", f"node-{index}", f"{index:064x}") for index in range(7)]

    result = service.sync(cards, revision_id="rev-new")

    assert result.status is SyncStatus.READY
    ingest_sizes = [
        len(json.loads(call["form"]["app_knowledge"]))
        for call in transport.calls
        if call["url"].endswith("/context/ingest")
    ]
    assert ingest_sizes == [2, 2, 2, 1]
    first_cycle = [
        len(call["query"]["ids"].split(","))
        for call in transport.calls
        if call["url"].endswith("/context/status")
    ][:3]
    assert first_cycle == [3, 3, 1]


def test_status_batch_size_falls_back_to_the_client_configuration() -> None:
    transport = LifecycleTransport()
    service, _ = sync_service(transport, config_status_batch_size=4)
    cards = [card(f"source-{index}", f"node-{index}", f"{index:064x}") for index in range(9)]

    assert service.sync(cards, revision_id="rev-new").status is SyncStatus.READY
    first_cycle = [
        len(call["query"]["ids"].split(","))
        for call in transport.calls
        if call["url"].endswith("/context/status")
    ][:3]
    assert first_cycle == [4, 4, 1]


def test_unavailable_warning_carries_the_hydradb_reason() -> None:
    class RefusingTransport(LifecycleTransport):
        def request(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(kwargs)
            raise HydraDBAPIError("database not found", code="NOT_FOUND", status=404)

    service, _ = sync_service(RefusingTransport())

    result = service.sync([card("source-a", "node-a", "a" * 64)], revision_id="rev-new")

    assert result.status is SyncStatus.UNAVAILABLE
    assert "only the last verified marker" in (result.warning or "")
    assert "HTTP 404 | NOT_FOUND | database not found" in (result.warning or "")


def test_local_contract_failure_reports_no_remote_reason() -> None:
    service, _ = sync_service(LifecycleTransport())
    unnamed = card("source-a", "node-a", "a" * 64).model_copy(update={"source_id": "   "})

    result = service.sync([unnamed], revision_id="rev-new")

    assert result.status is SyncStatus.UNAVAILABLE
    assert result.warning == (
        "HydraDB could not complete the indexing operation. The prior revision is "
        "only the last verified marker; the current collection state could not be "
        "confirmed."
    )


def test_timeout_still_names_the_state_of_every_unfinished_source() -> None:
    class StuckTransport(LifecycleTransport):
        def request(self, **kwargs: Any) -> dict[str, Any]:
            if not kwargs["url"].endswith("/context/status"):
                return super().request(**kwargs)
            self.calls.append(kwargs)
            self.status_calls += 1
            ids = kwargs["query"]["ids"].split(",")
            return {
                "success": True,
                "data": {
                    "statuses": [
                        {"id": item, "indexing_status": "processing", "success": True}
                        for item in ids
                    ]
                },
            }

    clock = iter([0.0, 0.0, 9_999.0])
    transport = StuckTransport()
    client = HydraDBClient(
        HydraDBConfig(
            api_key="test",
            database="repo_hack_hydra",
            max_retries=0,
            poll_interval_seconds=0.001,
            poll_timeout_seconds=1,
        ),
        transport=transport,
    )
    service = SyncService(
        client,
        repository_id="hack-hydra",
        sleep=lambda _: None,
        monotonic=lambda: next(clock),
    )

    result = service.sync([card("source-a", "node-a", "a" * 64)], revision_id="rev-new")

    assert result.status is SyncStatus.FAILED
    assert result.failed == {"source-a": "indexing timed out in state processing"}


def test_missing_status_still_fails_the_candidate_revision() -> None:
    class SilentTransport(LifecycleTransport):
        def request(self, **kwargs: Any) -> dict[str, Any]:
            if not kwargs["url"].endswith("/context/status"):
                return super().request(**kwargs)
            self.calls.append(kwargs)
            self.status_calls += 1
            return {"success": True, "data": {"statuses": []}}

    service, _ = sync_service(SilentTransport())

    result = service.sync([card("source-a", "node-a", "a" * 64)], revision_id="rev-new")

    assert result.status is SyncStatus.FAILED
    assert result.failed == {"source-a": "status missing from HydraDB response"}


def test_persisted_manifest_allows_restart_to_delete_renamed_sources(tmp_path: Any) -> None:
    manifest_path = tmp_path / ".hydra-graph" / "manifest.json"
    first_transport = LifecycleTransport()
    first_client = HydraDBClient(
        HydraDBConfig(
            api_key="test",
            database="repo_hack_hydra",
            max_retries=0,
            poll_interval_seconds=0.001,
            poll_timeout_seconds=1,
        ),
        transport=first_transport,
    )
    first = SyncService(
        first_client,
        repository_id="hack-hydra",
        manifest_path=manifest_path,
        sleep=lambda _: None,
    )
    assert (
        first.sync(
            [card("source-old", "node-old", "a" * 64, revision_id="rev-old")],
            revision_id="rev-old",
        ).status
        is SyncStatus.READY
    )
    assert (manifest_path.parent / ".gitignore").read_text(encoding="utf-8") == "*\n"

    second_transport = LifecycleTransport()
    second_client = HydraDBClient(first_client.config, transport=second_transport)
    restarted = SyncService(
        second_client,
        repository_id="hack-hydra",
        manifest_path=manifest_path,
        sleep=lambda _: None,
    )
    result = restarted.sync(
        [card("source-new", "node-new", "b" * 64, revision_id="rev-new")],
        revision_id="rev-new",
    )

    assert result.added == ("source-new",)
    assert result.deleted == ("source-old",)
    assert restarted.manifest.revision_id == "rev-new"


def test_interrupted_sync_marker_gates_restart_until_full_recovery(tmp_path: Any) -> None:
    manifest_path = tmp_path / ".hydra-graph" / "manifest.json"
    first_transport = LifecycleTransport()
    config = HydraDBConfig(
        api_key="test",
        database="repo_hack_hydra",
        max_retries=0,
        poll_interval_seconds=0.001,
        poll_timeout_seconds=1,
    )
    first = SyncService(
        HydraDBClient(config, transport=first_transport),
        repository_id="hack-hydra",
        manifest_path=manifest_path,
        sleep=lambda _: None,
    )
    assert (
        first.sync(
            [card("source-a", "node-a", "a" * 64, revision_id="rev-old")],
            revision_id="rev-old",
        ).status
        is SyncStatus.READY
    )
    marker = manifest_path.with_name("sync-in-progress.json")
    marker.write_text(
        json.dumps(
            {
                "repository_id": "hack-hydra",
                "candidate_revision": "rev-interrupted",
            }
        ),
        encoding="utf-8",
    )

    recovery_transport = LifecycleTransport()
    restarted = SyncService(
        HydraDBClient(config, transport=recovery_transport),
        repository_id="hack-hydra",
        manifest_path=manifest_path,
        sleep=lambda _: None,
    )

    assert restarted.status["status"] == "failed"
    assert restarted.status["current_state_indeterminate"] is True
    assert restarted.verified_byog_source_ids() == ()

    result = restarted.sync(
        [card("source-a", "node-a", "a" * 64, revision_id="rev-old")],
        revision_id="rev-old",
    )

    assert result.status is SyncStatus.READY
    assert result.replaced == ("source-a",)
    assert any(call["url"].endswith("/context/ingest") for call in recovery_transport.calls)
    assert restarted.status["current_state_indeterminate"] is False
    assert marker.exists() is False


def test_failed_remote_write_keeps_durable_interrupted_marker(tmp_path: Any) -> None:
    manifest_path = tmp_path / ".hydra-graph" / "manifest.json"
    config = HydraDBConfig(
        api_key="test",
        database="repo_hack_hydra",
        max_retries=0,
        poll_interval_seconds=0.001,
        poll_timeout_seconds=1,
    )
    failed = SyncService(
        HydraDBClient(config, transport=LifecycleTransport(unavailable=True)),
        repository_id="hack-hydra",
        manifest_path=manifest_path,
        sleep=lambda _: None,
    )

    result = failed.sync([card("source-a", "node-a", "a" * 64)], revision_id="rev-new")

    marker = manifest_path.with_name("sync-in-progress.json")
    assert result.current_state_indeterminate is True
    assert marker.exists() is True
    restarted = SyncService(
        HydraDBClient(config, transport=LifecycleTransport()),
        repository_id="hack-hydra",
        manifest_path=manifest_path,
        sleep=lambda _: None,
    )
    assert restarted.status["status"] == "failed"
    assert restarted.status["current_state_indeterminate"] is True


def test_verified_snapshot_requires_exact_ready_card_hashes() -> None:
    service, _ = sync_service(LifecycleTransport())
    original = card("source-a", "node-a", "a" * 64)
    assert service.sync([original], revision_id="rev-new").status is SyncStatus.READY

    changed = card("source-a", "node-a", "b" * 64)

    assert service.verifies_snapshot([original], revision_id="rev-new") is True
    assert service.verifies_snapshot([changed], revision_id="rev-new") is False
    assert service.verifies_snapshot([original], revision_id="fabricated") is False


def test_legacy_manifest_database_is_removed_without_plaintext_backup(tmp_path: Any) -> None:
    manifest_path = tmp_path / ".hydra-graph" / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "repository_id": "hack-hydra",
                "revision_id": "rev-old",
                "sources": {},
                "database": "plaintext-database-must-go",
                "collection": "current",
            }
        ),
        encoding="utf-8",
    )
    service, _ = sync_service(LifecycleTransport())
    SyncService(
        service.client,
        repository_id="hack-hydra",
        manifest_path=manifest_path,
    )

    persisted = manifest_path.read_text(encoding="utf-8")
    assert "plaintext-database-must-go" not in persisted
    assert '"database"' not in persisted
    assert '"database_fingerprint"' in persisted


def test_manifest_without_byog_marker_conservatively_clears_relation_free_replacement(
    tmp_path: Any,
) -> None:
    manifest_path = tmp_path / ".hydra-graph" / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "repository_id": "hack-hydra",
                "revision_id": "rev-old",
                "sources": {"source-a": "old-card-hash"},
                "collection": "current",
            }
        ),
        encoding="utf-8",
    )
    transport = LifecycleTransport()
    client = HydraDBClient(
        HydraDBConfig(
            api_key="test",
            database="repo_hack_hydra",
            max_retries=0,
            poll_interval_seconds=0.001,
            poll_timeout_seconds=1,
        ),
        transport=transport,
    )
    service = SyncService(
        client,
        repository_id="hack-hydra",
        manifest_path=manifest_path,
        sleep=lambda _: None,
    )

    result = service.sync(
        [card("source-a", "node-a", "a" * 64)],
        revision_id="rev-new",
    )

    assert result.status is SyncStatus.READY
    mutation_calls = [
        call
        for call in transport.calls
        if call["method"] == "DELETE" or call["url"].endswith("/context/ingest")
    ]
    assert mutation_calls[0]["method"] == "DELETE"
    assert mutation_calls[1]["url"].endswith("/context/ingest")
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["byog_sources"] == []
