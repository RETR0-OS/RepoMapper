from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hydra_graph.analyzer import analyze_repository
from hydra_graph.api import ServiceContainer, create_app
from hydra_graph.cards import build_source_cards
from hydra_graph.config import HydraDBConfig
from hydra_graph.diff import compare_graphs
from hydra_graph.events import EventBus
from hydra_graph.evolution import (
    build_change_event_cards,
    build_system_lens,
    build_system_lens_card,
)
from hydra_graph.evolution_service import EvolutionService
from hydra_graph.hydradb import HydraDBClient
from hydra_graph.models import GraphIR, RelationPredicate
from hydra_graph.query import QueryService
from hydra_graph.sync import SyncService
from hydra_graph.views import (
    ViewDepth,
    ViewMode,
    ViewService,
    ViewStore,
    build_product_view,
)

HYDRA_FIXTURE = Path(__file__).parents[1] / "fixtures" / "hydradb" / "query_authorization.json"


class Transport:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if kwargs["url"].endswith("/context/ingest"):
            sources = json.loads(kwargs["form"]["app_knowledge"])
            return {"success": True, "data": {"ids": [item["id"] for item in sources]}}
        if kwargs["url"].endswith("/context/status"):
            return {
                "success": True,
                "data": {
                    "statuses": [
                        {"id": item, "indexing_status": "completed", "success": True}
                        for item in kwargs["query"]["ids"].split(",")
                    ]
                },
            }
        if not self.responses:
            raise AssertionError(f"unexpected request: {kwargs}")
        return self.responses.pop(0)


class Checkpoints:
    def __init__(self, before: GraphIR, after: GraphIR) -> None:
        self.before = before
        self.after = after
        self.clear_calls = 0
        self.captures: list[tuple[str, GraphIR]] = []

    def load_pair(self, **_: Any) -> tuple[GraphIR, GraphIR]:
        return self.before, self.after

    def clear(self) -> None:
        self.clear_calls += 1

    def capture(self, slot: Any, graph: GraphIR) -> Any:
        self.captures.append((str(slot), graph))
        return type("Ref", (), {"graph_hash": "a" * 64})()


class CurrentQueries:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.calls: list[Any] = []

    def repository_query(self, request: Any) -> dict[str, Any]:
        self.calls.append(request)
        return json.loads(json.dumps(self.result))


def _client(transport: Transport, *, api_key: str | None = "test") -> HydraDBClient:
    return HydraDBClient(
        HydraDBConfig(
            api_key=api_key,
            database="repo_evolution",
            collection="current",
            evolution_collection="evolution",
            max_retries=0,
            poll_interval_seconds=0.001,
            poll_timeout_seconds=1,
        ),
        transport=transport,
    )


def _graphs(root: Path) -> tuple[GraphIR, GraphIR]:
    source = root / "module.py"
    source.write_text(
        "def target():\n    return 1\n\ndef caller():\n    return target()\n",
        encoding="utf-8",
    )
    before = analyze_repository(root, repository_id="evolution", revision_id="before")
    source.write_text(
        "def target():\n    return 2\n\ndef caller():\n    return target()\n",
        encoding="utf-8",
    )
    after = analyze_repository(root, repository_id="evolution", revision_id="after")
    return before, after


def _card_response(cards: Any) -> dict[str, Any]:
    chunks = [
        {
            "chunk_uuid": f"chunk-{card.source_id}",
            "id": card.source_id,
            "chunk_content": card.content,
            "source_type": card.source_type,
            "source_title": card.title,
            "relevancy_score": 1.0 - index / 1000,
            "metadata": card.metadata,
            "additional_metadata": card.additional_metadata,
        }
        for index, card in enumerate(cards)
    ]
    return {
        "success": True,
        "data": {
            "chunks": chunks,
            "sources": [
                {
                    "id": card.source_id,
                    "title": card.title,
                    "type": card.source_type,
                    "metadata": card.metadata,
                    "additional_metadata": card.additional_metadata,
                }
                for card in cards
            ],
            "graph_context": {
                "query_paths": [],
                "chunk_relations": [],
                "chunk_id_to_group_ids": {},
            },
            "additional_context": {},
        },
        "meta": {"request_id": "evolution-fixture"},
    }


def _query_from_graph(graph: GraphIR, root: Path) -> dict[str, Any]:
    edge = next(item for item in graph.edges if item.predicate is RelationPredicate.CALLS)
    nodes = graph.node_map()
    cards = build_source_cards(graph, root)
    context = next(
        relation.context
        for card in cards
        for relation in card.graph.relations
        if relation.predicate == "CALLS"
    )

    def chunk(node_id: str, rank: int) -> dict[str, Any]:
        node = nodes[node_id]
        return {
            "rank": rank,
            "chunk_id": f"chunk-{node.id}",
            "source_id": f"source-{node.id}",
            "content": node.display_name,
            "content_truncated": False,
            "title": node.display_name,
            "source_type": "code_entity",
            "score": 1.0,
            "path": node.path,
            "span": node.span.model_dump(mode="json") if node.span else None,
            "revision": graph.revision_id,
            "repository_id": graph.repository_id,
            "entity_kind": node.kind.value,
            "language": node.language,
            "relation_quality": "exact",
            "node_id": node.id,
            "logical_id": node.logical_id,
            "qualified_name": node.qualified_name,
            "signature": node.signature,
            "content_hash": node.content_hash,
            "parser": node.parser,
            "parser_version": node.parser_version,
            "is_generated": False,
            "group_ids": ["path-current"],
        }

    path = {
        "path_id": "path-current",
        "rank": 1,
        "score": 1.0,
        "summary": "Current exact call path.",
        "chunk_ids": [f"chunk-{edge.source_id}", f"chunk-{edge.target_id}"],
        "hops": [
            {
                "hop": 1,
                "source": {
                    "id": edge.source_id,
                    "logical_id": nodes[edge.source_id].logical_id,
                    "hydradb_entity_id": "hydra-source",
                    "name": nodes[edge.source_id].qualified_name,
                    "kind": nodes[edge.source_id].kind.value,
                    "namespace": graph.repository_id,
                },
                "relation": {
                    "id": "hydra-call",
                    "predicate": "CALLS",
                    "raw_predicate": "CALLS",
                    "context": context,
                    "confidence": 1.0,
                    "origin": "byog",
                    "chunk_id": f"chunk-{edge.source_id}",
                },
                "target": {
                    "id": edge.target_id,
                    "logical_id": nodes[edge.target_id].logical_id,
                    "hydradb_entity_id": "hydra-target",
                    "name": nodes[edge.target_id].qualified_name,
                    "kind": nodes[edge.target_id].kind.value,
                    "namespace": graph.repository_id,
                },
            }
        ],
    }
    return {
        "session_id": "session-current",
        "view_id": f"view-{graph.revision_id}",
        "status": "ready",
        "hydradb": {
            "available": True,
            "collections": ["current"],
            "query_by": "hybrid",
            "mode": "thinking",
            "graph_context": True,
            "path_ids": ["path-current"],
            "origin": "byog",
        },
        "revision": graph.revision_id,
        "paths": [path],
        "relations": [],
        "chunk_id_to_group_ids": {},
        "chunks": [chunk(edge.source_id, 1), chunk(edge.target_id, 2)],
        "sources": [],
        "additional_context": [],
        "warnings": [],
        "budget": {
            "max_context_chars": 15_000,
            "returned_context_chars": 10,
            "max_paths": 3,
            "returned_paths": 1,
            "max_relations": 24,
            "returned_relations": 1,
            "truncated": False,
        },
    }


def _service(
    root: Path,
    transport: Transport,
    before: GraphIR,
    after: GraphIR,
    *,
    current: dict[str, Any] | None = None,
    api_key: str | None = "test",
) -> tuple[EvolutionService, Checkpoints, ViewStore, CurrentQueries]:
    checkpoints = Checkpoints(before, after)
    views = ViewStore()
    current_queries = CurrentQueries(current or _query_from_graph(after, root))
    service = EvolutionService(
        _client(transport, api_key=api_key),
        repository_id="evolution",
        repository_root=root,
        checkpoints=checkpoints,  # type: ignore[arg-type]
        views=views,
        current_queries=current_queries,  # type: ignore[arg-type]
        verified_revision=lambda: after.revision_id,
        snapshot_verifier=lambda _cards, **_kwargs: True,
        sleep=lambda _: None,
    )
    return service, checkpoints, views, current_queries


def test_compare_reconstructs_complete_records_from_evolution_collection(tmp_path: Path) -> None:
    before, after = _graphs(tmp_path)
    cards = build_change_event_cards(compare_graphs(before, after), before, after)
    transport = Transport([_card_response(cards)])
    service, _, _, _ = _service(tmp_path, transport, before, after)

    result = service.compare(before_revision_id="before", after_revision_id="after")

    assert result["status"] == "ready"
    assert len(result["records"]) == 1
    assert result["records"][0]["facts"]
    sent = transport.calls[0]["json_body"]
    assert sent["collection"] == "evolution"
    assert "collections" not in sent
    assert sent["metadata_filters"] == {
        "repository_id": "evolution",
        "entity_kind": "CHANGE_EVENT",
        "before_revision_id": "before",
        "after_revision_id": "after",
    }


def test_incomplete_or_generic_change_chunks_cannot_masquerade(tmp_path: Path) -> None:
    before, after = _graphs(tmp_path)
    cards = list(build_change_event_cards(compare_graphs(before, after), before, after))
    cards.pop()
    incomplete = EvolutionService(
        _client(Transport([_card_response(cards)])),
        repository_id="evolution",
        repository_root=tmp_path,
        checkpoints=Checkpoints(before, after),  # type: ignore[arg-type]
        views=ViewStore(),
        current_queries=CurrentQueries(_query_from_graph(after, tmp_path)),  # type: ignore[arg-type]
    ).compare(before_revision_id="before", after_revision_id="after")

    raw = json.loads(HYDRA_FIXTURE.read_text(encoding="utf-8"))
    generic, _, _, _ = _service(tmp_path, Transport([raw]), before, after)
    ignored_filter = generic.compare(before_revision_id="before", after_revision_id="after")

    assert incomplete["status"] == "degraded"
    assert incomplete["records"] == []
    assert incomplete["chunks"] == []
    assert ignored_filter["status"] == "degraded"
    assert ignored_filter["records"] == []


def test_publish_is_deterministic_and_clears_only_after_ready(tmp_path: Path) -> None:
    before, after = _graphs(tmp_path)
    transport = Transport([])
    service, checkpoints, _, _ = _service(tmp_path, transport, before, after)

    first = service.publish_delta(
        before_revision_id="before", after_revision_id="after", confirm=False
    )
    second = service.publish_delta(
        before_revision_id="before", after_revision_id="after", confirm=False
    )
    confirmed = service.publish_delta(
        before_revision_id="before", after_revision_id="after", confirm=True
    )

    assert first["source_ids"] == second["source_ids"]
    assert first["writes_performed"] is False
    assert checkpoints.clear_calls == 1
    assert confirmed["status"] == "ready"
    assert confirmed["checkpoints_cleared"] is True


def test_partial_ingest_acknowledgement_is_indeterminate_and_retains_checkpoints(
    tmp_path: Path,
) -> None:
    before, after = _graphs(tmp_path)

    class PartialAcknowledgementTransport(Transport):
        def request(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(kwargs)
            if kwargs["url"].endswith("/context/ingest"):
                sources = json.loads(kwargs["form"]["app_knowledge"])
                return {"success": True, "data": {"ids": [sources[0]["id"]]}}
            raise AssertionError(f"unexpected request: {kwargs}")

    transport = PartialAcknowledgementTransport([])
    service, checkpoints, _, _ = _service(tmp_path, transport, before, after)

    result = service.publish_delta(
        before_revision_id="before", after_revision_id="after", confirm=True
    )

    assert result["status"] == "indeterminate"
    assert result["writes_performed"] is True
    assert result["checkpoints_cleared"] is False
    assert checkpoints.clear_calls == 0
    assert len(transport.calls) == 1


def test_missing_credentials_refuse_confirmed_delta_without_transport(tmp_path: Path) -> None:
    before, after = _graphs(tmp_path)
    transport = Transport([])
    service, checkpoints, _, _ = _service(tmp_path, transport, before, after, api_key=None)

    result = service.publish_delta(
        before_revision_id="before", after_revision_id="after", confirm=True
    )

    assert result["status"] == "unavailable"
    assert result["writes_performed"] is False
    assert result["checkpoints_cleared"] is False
    assert checkpoints.clear_calls == 0
    assert transport.calls == []


def test_missing_credentials_refuse_confirmed_lens_without_transport(tmp_path: Path) -> None:
    before, after = _graphs(tmp_path)
    current_query = _query_from_graph(after, tmp_path)
    current_view = build_product_view(
        current_query,
        mode=ViewMode.TRACE,
        depth=ViewDepth.SYMBOL,
        max_nodes=25,
        max_edges=24,
    )
    transport = Transport([])
    service, _, views, _ = _service(
        tmp_path,
        transport,
        before,
        after,
        current=current_query,
        api_key=None,
    )
    views.put(current_view, current_query)

    result = service.save_lens(
        name="Call path",
        purpose="Keep the exact call path visible.",
        view_id=current_view["view_id"],
        confirm=True,
    )

    assert result["status"] == "unavailable"
    assert result["writes_performed"] is False
    assert transport.calls == []


def test_unavailable_compare_never_reads_checkpoint_or_uses_local_graph(tmp_path: Path) -> None:
    before, after = _graphs(tmp_path)

    class ForbiddenCheckpoints(Checkpoints):
        def load_pair(self, **_: Any) -> tuple[GraphIR, GraphIR]:
            raise AssertionError("query attempted checkpoint retrieval")

    transport = Transport([])
    service = EvolutionService(
        _client(transport, api_key=None),
        repository_id="evolution",
        repository_root=tmp_path,
        checkpoints=ForbiddenCheckpoints(before, after),  # type: ignore[arg-type]
        views=ViewStore(),
        current_queries=CurrentQueries(_query_from_graph(after, tmp_path)),  # type: ignore[arg-type]
    )

    result = service.compare(before_revision_id="before", after_revision_id="after")

    assert result["status"] == "unavailable"
    assert result["chunks"] == []
    assert transport.calls == []


def test_checkpoint_rejects_changed_workspace_with_same_ready_label(tmp_path: Path) -> None:
    before, after = _graphs(tmp_path)
    expected = build_source_cards(after, tmp_path)
    service, checkpoints, _, _ = _service(tmp_path, Transport([]), before, after)
    service._snapshot_verifier = lambda cards, **_: tuple(cards) == expected
    (tmp_path / "module.py").write_text("def changed():\n    return 3\n", encoding="utf-8")

    with pytest.raises(ValueError, match="does not match"):
        service.capture_checkpoint("after", revision_id="after")

    assert checkpoints.captures == []


def test_open_lens_runs_separate_evolution_and_current_queries(tmp_path: Path) -> None:
    before, after = _graphs(tmp_path)
    current_query = _query_from_graph(after, tmp_path)
    current_view = build_product_view(
        current_query,
        mode=ViewMode.TRACE,
        depth=ViewDepth.SYMBOL,
        max_nodes=25,
        max_edges=24,
    )
    edge = current_view["edges"][0]
    lens = build_system_lens(
        repository_id="evolution",
        name="Call path",
        purpose="Keep the exact call path visible.",
        view=current_view,
        anchor_node_ids=[edge["source_id"], edge["target_id"]],
        edge_ids=[edge["id"]],
    )
    transport = Transport([_card_response((build_system_lens_card(lens),))])
    service, _, views, current_queries = _service(
        tmp_path, transport, before, after, current=current_query
    )

    result = service.open_lens(lens=lens.lens_id)

    assert result["status"] == "ready"
    assert result["hydradb"]["collections"] == ["current"]
    assert result["evolution_hydradb"]["collections"] == ["evolution"]
    assert result["lens"]["lens_id"] == lens.lens_id
    assert result["drift"]["classification"] == "unchanged"
    assert len(current_queries.calls) == 1
    assert views.get(result["view_id"]) is not None


def test_open_lens_without_current_exact_path_is_unresolved(tmp_path: Path) -> None:
    before, after = _graphs(tmp_path)
    current_query = _query_from_graph(after, tmp_path)
    view = build_product_view(
        current_query,
        mode=ViewMode.TRACE,
        depth=ViewDepth.SYMBOL,
        max_nodes=25,
        max_edges=24,
    )
    edge = view["edges"][0]
    lens = build_system_lens(
        repository_id="evolution",
        name="Call path",
        purpose="Keep the exact call path visible.",
        view=view,
        anchor_node_ids=[edge["source_id"], edge["target_id"]],
        edge_ids=[edge["id"]],
    )
    no_path = {**current_query, "paths": [], "chunks": []}
    transport = Transport([_card_response((build_system_lens_card(lens),))])
    service, _, _, _ = _service(tmp_path, transport, before, after, current=no_path)

    result = service.open_lens(lens=lens.lens_id)

    assert result["drift"]["kind"] == "unresolved"
    assert "refresh" not in result


def test_compare_api_returns_visible_change_state_nodes(tmp_path: Path) -> None:
    before, after = _graphs(tmp_path)
    cards = build_change_event_cards(compare_graphs(before, after), before, after)
    transport = Transport([_card_response(cards)])
    evolution, _, view_store, _ = _service(tmp_path, transport, before, after)
    client = evolution.client
    events = EventBus()
    queries = QueryService(client, repository_id="evolution", events=events)
    views = ViewService(queries, store=view_store)
    container = ServiceContainer(
        config=client.config,
        client=client,
        events=events,
        queries=queries,
        views=views,
        sync=SyncService(client, repository_id="evolution", events=events),
        repository_root=tmp_path,
        evolution=evolution,
    )

    response = TestClient(create_app(container)).get(
        "/api/views/compare?depth=symbol&before_revision=before&after_revision=after"
    )

    assert response.status_code == 200
    view = response.json()
    change_nodes = [node for node in view["nodes"] if node["kind"] == "CHANGE_EVENT"]
    assert change_nodes
    assert {node["attributes"]["state"] for node in change_nodes}.intersection(
        {"added", "removed", "modified"}
    )
    assert any(node["attributes"].get("explanation") for node in change_nodes)


def test_preserve_api_returns_lens_node_and_current_exact_path(tmp_path: Path) -> None:
    before, after = _graphs(tmp_path)
    current_query = _query_from_graph(after, tmp_path)
    current_view = build_product_view(
        current_query,
        mode=ViewMode.TRACE,
        depth=ViewDepth.SYMBOL,
        max_nodes=25,
        max_edges=24,
    )
    edge = current_view["edges"][0]
    lens = build_system_lens(
        repository_id="evolution",
        name="Call path",
        purpose="Keep the exact call path visible.",
        view=current_view,
        anchor_node_ids=[edge["source_id"], edge["target_id"]],
        edge_ids=[edge["id"]],
    )
    transport = Transport([_card_response((build_system_lens_card(lens),))])
    evolution, _, view_store, _ = _service(
        tmp_path, transport, before, after, current=current_query
    )
    client = evolution.client
    events = EventBus()
    queries = QueryService(client, repository_id="evolution", events=events)
    views = ViewService(queries, store=view_store)
    container = ServiceContainer(
        config=client.config,
        client=client,
        events=events,
        queries=queries,
        views=views,
        sync=SyncService(client, repository_id="evolution", events=events),
        repository_root=tmp_path,
        evolution=evolution,
    )

    response = TestClient(create_app(container)).get(
        f"/api/views/preserve?depth=symbol&lens={lens.lens_id}"
    )

    assert response.status_code == 200
    view = response.json()
    assert view["revision_id"] == "after"
    assert any(node["kind"] == "SYSTEM_LENS" for node in view["nodes"])
    lens_node = next(node for node in view["nodes"] if node["kind"] == "SYSTEM_LENS")
    assert lens_node["display_name"] == "Call path"
    assert lens_node["attributes"]["purpose"] == "Keep the exact call path visible."
    assert lens_node["attributes"]["drift_classification"] == "unchanged"
    assert any(node["kind"] == "FUNCTION" for node in view["nodes"])
    assert view["edges"][0]["quality"] == "exact"
    assert transport.calls[0]["json_body"]["collection"] == "evolution"


def test_accept_lens_requires_opaque_refresh_view_binding(tmp_path: Path) -> None:
    before, after = _graphs(tmp_path)
    current_query = _query_from_graph(after, tmp_path)
    view = build_product_view(
        current_query,
        mode=ViewMode.TRACE,
        depth=ViewDepth.SYMBOL,
        max_nodes=25,
        max_edges=24,
    )
    edge = view["edges"][0]
    lens = build_system_lens(
        repository_id="evolution",
        name="Call path",
        purpose="Keep the exact call path visible.",
        view=view,
        anchor_node_ids=[edge["source_id"], edge["target_id"]],
        edge_ids=[edge["id"]],
    )
    lens_response = _card_response((build_system_lens_card(lens),))
    service, _, _, _ = _service(
        tmp_path,
        Transport([lens_response, lens_response]),
        before,
        after,
        current=current_query,
    )
    opened = service.open_lens(lens=lens.lens_id)

    rejected = service.accept_lens(lens_id=lens.lens_id, view_id="arbitrary", confirm=False)
    preview = service.accept_lens(
        lens_id=lens.lens_id,
        view_id=opened["view_id"],
        confirm=False,
    )

    assert rejected["status"] == "degraded"
    assert rejected["writes_performed"] is False
    assert preview["status"] == "preview"
    assert preview["previous_revision_id"] == "after"
    assert preview["saved_revision_id"] == "after"
