from __future__ import annotations

from pathlib import Path

from hydra_graph.analyzer import analyze_repository
from hydra_graph.ids import edge_id
from hydra_graph.models import GraphEdge, GraphIR, NodeKind, RelationPredicate, RelationQuality
from hydra_graph.projections import ProjectionDepth, build_repository_projection

FIXTURE = Path(__file__).parents[1] / "fixtures" / "sample_repo"


def _graph():
    return analyze_repository(FIXTURE, repository_id="sample", revision_id="r1")


def test_package_projection_contains_only_real_packages_and_exact_aggregates() -> None:
    graph = _graph()
    projection = build_repository_projection(graph, ProjectionDepth.PACKAGES)
    names = {node.qualified_name for node in projection.nodes}

    assert names == {"app", "tests"}
    assert all(node.kind is NodeKind.PACKAGE for node in projection.nodes)
    assert projection.edges == ()
    assert projection.aggregates
    for aggregate in projection.aggregates:
        assert aggregate.exact_relation_count == len(aggregate.contributing_edge_ids)
        assert aggregate.contributing_evidence_ids
        assert "evidence" not in aggregate.model_dump()


def test_file_aggregates_retain_every_contributing_fact() -> None:
    graph = _graph()
    projection = build_repository_projection(graph, ProjectionDepth.FILES)
    nodes = {node.id: node for node in projection.nodes}
    aggregate = next(
        edge
        for edge in projection.aggregates
        if nodes[edge.source_group_id].qualified_name == "app.service"
        and nodes[edge.target_group_id].qualified_name == "app.helpers"
        and edge.predicate is RelationPredicate.CALLS
    )
    source_edges = {edge.id: edge for edge in graph.edges}
    assert aggregate.exact_relation_count == 1
    assert all(
        source_edges[edge_id].quality is RelationQuality.EXACT
        for edge_id in aggregate.contributing_edge_ids
    )
    assert set(aggregate.contributing_evidence_ids) == {
        evidence.id
        for edge_id in aggregate.contributing_edge_ids
        for evidence in source_edges[edge_id].evidence
    }


def test_symbol_projection_hides_inferred_edges_by_default() -> None:
    graph = _graph()
    source = next(node for node in graph.nodes if node.qualified_name == "app.api.handle_request")
    target = next(
        node for node in graph.nodes if node.qualified_name == "app.service.Greeter.greet"
    )
    compact, logical = edge_id(
        repository_id="sample",
        source_id=source.id,
        predicate="MAY_CALL",
        target_id=target.id,
        quality="inferred",
    )
    inferred = GraphEdge(
        id=compact,
        logical_id=logical,
        source_id=source.id,
        predicate=RelationPredicate.MAY_CALL,
        target_id=target.id,
        quality=RelationQuality.INFERRED,
        confidence=0.55,
        evidence=next(edge.evidence for edge in graph.edges if edge.source_id == source.id),
        revision_id="r1",
        extractor="receiver-name-heuristic",
        extractor_version="1",
        owner_source_id=source.id,
    )
    graph = GraphIR(
        repository_id=graph.repository_id,
        revision_id=graph.revision_id,
        nodes=graph.nodes,
        edges=(*graph.edges, inferred),
    )
    default = build_repository_projection(graph, ProjectionDepth.SYMBOLS)
    opted_in = build_repository_projection(graph, ProjectionDepth.SYMBOLS, include_inferred=True)

    assert inferred.id not in {edge.id for edge in default.edges}
    assert inferred.id in {edge.id for edge in opted_in.edges}
    assert all(
        node.kind not in {NodeKind.SYSTEM_LENS, NodeKind.CHANGE_EVENT} for node in default.nodes
    )


def test_projection_budgets_are_honest_and_deterministic() -> None:
    graph = _graph()
    first = build_repository_projection(graph, "symbols", node_budget=3, edge_budget=1)
    second = build_repository_projection(graph, "symbols", node_budget=3, edge_budget=1)
    assert first == second
    assert len(first.nodes) == 3
    assert len(first.edges) <= 1
    assert first.total_node_count > len(first.nodes)
    assert first.truncated is True
