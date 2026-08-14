from __future__ import annotations

from threading import Event, Thread
from typing import Any

from hydra_graph.cards import HydraEntity, HydraRelation, HydraSourceGraph, SourceCard
from hydra_graph.config import HydraDBConfig
from hydra_graph.events import EventBus
from hydra_graph.hydradb import HydraDBClient, HydraDBUnavailable
from hydra_graph.sync import SyncManifest, SyncService, SyncStatus


def card(
    source_id: str,
    node_id: str,
    content_hash: str,
    *,
    revision_id: str = "rev-new",
    relation_predicate: str | None = None,
) -> SourceCard:
    graph = HydraSourceGraph(entities={}, relations=())
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
            return {"success": True, "data": {"ids": ["source-a"]}}
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
    transport: LifecycleTransport, *, manifest: SyncManifest | None = None
) -> tuple[SyncService, EventBus]:
    events = EventBus()
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
    return (
        SyncService(
            client,
            repository_id="hack-hydra",
            manifest=manifest,
            events=events,
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
    assert service.manifest.sources["source-a"] != "a" * 64
    assert transport.status_calls == 2
    assert [event["type"] for event in events.recent()] == [
        "hydradb_sync_started",
        "hydradb_revision_ready",
    ]


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
    assert all(len(call["query"]["ids"].split(",")) <= 25 for call in status_calls)


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


def test_verified_snapshot_requires_exact_ready_card_hashes() -> None:
    service, _ = sync_service(LifecycleTransport())
    original = card("source-a", "node-a", "a" * 64)
    assert service.sync([original], revision_id="rev-new").status is SyncStatus.READY

    changed = card("source-a", "node-a", "b" * 64)

    assert service.verifies_snapshot([original], revision_id="rev-new") is True
    assert service.verifies_snapshot([changed], revision_id="rev-new") is False
    assert service.verifies_snapshot([original], revision_id="fabricated") is False
