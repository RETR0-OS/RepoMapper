from __future__ import annotations

from typing import Any

from hydra_graph.cards import HydraSourceGraph, SourceCard
from hydra_graph.config import HydraDBConfig
from hydra_graph.events import EventBus
from hydra_graph.hydradb import HydraDBClient, HydraDBUnavailable
from hydra_graph.sync import SyncManifest, SyncService, SyncStatus


def card(source_id: str, node_id: str, content_hash: str) -> SourceCard:
    return SourceCard(
        source_id=source_id,
        node_id=node_id,
        content=f"Entity: {node_id}",
        metadata={
            "repository_id": "hack-hydra",
            "revision_id": "rev-new",
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
        graph=HydraSourceGraph(entities={}, relations=()),
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
    assert service.manifest.sources == {"source-a": "a" * 64}
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
