"""Bounded, deterministic repository projections for semantic zoom."""

from __future__ import annotations

from collections import defaultdict
from enum import StrEnum
from pathlib import PurePosixPath

from pydantic import Field

from .ids import aggregate_id
from .models import (
    FrozenModel,
    GraphEdge,
    GraphIR,
    GraphNode,
    NodeKind,
    RelationPredicate,
    RelationQuality,
)


class ProjectionDepth(StrEnum):
    PACKAGES = "packages"
    FILES = "files"
    SYMBOLS = "symbols"


class AggregatedEdge(FrozenModel):
    id: str
    source_group_id: str
    predicate: RelationPredicate
    target_group_id: str
    exact_relation_count: int = Field(ge=1)
    contributing_edge_ids: tuple[str, ...]
    contributing_evidence_ids: tuple[str, ...]
    revision_id: str


class RepositoryProjection(FrozenModel):
    depth: ProjectionDepth
    revision_id: str
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...] = ()
    aggregates: tuple[AggregatedEdge, ...] = ()
    total_node_count: int = Field(ge=0)
    total_edge_count: int = Field(ge=0)
    truncated: bool = False


_NON_REPOSITORY_KINDS = {NodeKind.SYSTEM_LENS, NodeKind.CHANGE_EVENT}


def _containing_group(
    node: GraphNode,
    depth: ProjectionDepth,
    files_by_path: dict[str, GraphNode],
    packages_by_path: dict[str, GraphNode],
) -> GraphNode | None:
    if depth is ProjectionDepth.FILES:
        if node.kind is NodeKind.FILE:
            return node
        return files_by_path.get(node.path)
    if node.kind is NodeKind.PACKAGE:
        return node
    path = PurePosixPath(node.path)
    parent = path if node.kind is NodeKind.PACKAGE else path.parent
    while str(parent) != ".":
        candidate = packages_by_path.get(str(parent))
        if candidate:
            return candidate
        parent = parent.parent
    return None


def _aggregate_edges(
    graph: GraphIR,
    depth: ProjectionDepth,
    selected_ids: set[str],
) -> tuple[AggregatedEdge, ...]:
    files = {node.path: node for node in graph.nodes if node.kind is NodeKind.FILE}
    packages = {node.path: node for node in graph.nodes if node.kind is NodeKind.PACKAGE}
    nodes = graph.node_map()
    grouped: dict[tuple[str, RelationPredicate, str], list[GraphEdge]] = defaultdict(list)
    for edge in graph.edges:
        if edge.quality is not RelationQuality.EXACT:
            continue
        source = _containing_group(nodes[edge.source_id], depth, files, packages)
        target = _containing_group(nodes[edge.target_id], depth, files, packages)
        if source is None or target is None or source.id == target.id:
            continue
        if source.id not in selected_ids or target.id not in selected_ids:
            continue
        grouped[(source.id, edge.predicate, target.id)].append(edge)

    aggregates: list[AggregatedEdge] = []
    for (source, predicate, target), contributors in grouped.items():
        edge_ids = tuple(sorted(edge.id for edge in contributors))
        evidence_ids = tuple(
            sorted({evidence.id for edge in contributors for evidence in edge.evidence})
        )
        aggregates.append(
            AggregatedEdge(
                id=aggregate_id(
                    repository_id=graph.repository_id,
                    depth=depth.value,
                    source_group_id=source,
                    predicate=predicate.value,
                    target_group_id=target,
                ),
                source_group_id=source,
                predicate=predicate,
                target_group_id=target,
                exact_relation_count=len(contributors),
                contributing_edge_ids=edge_ids,
                contributing_evidence_ids=evidence_ids,
                revision_id=graph.revision_id,
            )
        )
    return tuple(
        sorted(
            aggregates,
            key=lambda item: (-item.exact_relation_count, item.predicate.value, item.id),
        )
    )


def build_repository_projection(
    graph: GraphIR,
    depth: ProjectionDepth | str,
    *,
    node_budget: int = 500,
    edge_budget: int = 1_000,
    include_inferred: bool = False,
) -> RepositoryProjection:
    """Build a bounded view without changing or reinterpreting graph facts."""

    selected_depth = ProjectionDepth(depth)
    if node_budget < 1 or edge_budget < 0:
        raise ValueError("projection budgets must be non-negative and node_budget must be positive")
    if selected_depth is ProjectionDepth.PACKAGES:
        candidates = [node for node in graph.nodes if node.kind is NodeKind.PACKAGE]
    elif selected_depth is ProjectionDepth.FILES:
        candidates = [node for node in graph.nodes if node.kind is NodeKind.FILE]
    else:
        candidates = [
            node
            for node in graph.nodes
            if node.kind
            not in {NodeKind.REPOSITORY, NodeKind.PACKAGE, NodeKind.MODULE, NodeKind.FILE}
            and node.kind not in _NON_REPOSITORY_KINDS
        ]
    ordered_nodes = sorted(
        candidates, key=lambda item: (item.path, item.span.start_line if item.span else 0, item.id)
    )
    visible_nodes = tuple(ordered_nodes[:node_budget])
    visible_ids = {node.id for node in visible_nodes}

    if selected_depth is ProjectionDepth.SYMBOLS:
        allowed_qualities = {RelationQuality.EXACT}
        if include_inferred:
            allowed_qualities.add(RelationQuality.INFERRED)
        all_edges = tuple(
            sorted(
                (
                    edge
                    for edge in graph.edges
                    if edge.source_id in visible_ids
                    and edge.target_id in visible_ids
                    and edge.quality in allowed_qualities
                ),
                key=lambda item: item.id,
            )
        )
        visible_edges = all_edges[:edge_budget]
        aggregates: tuple[AggregatedEdge, ...] = ()
        total_edges = len(all_edges)
    else:
        all_aggregates = _aggregate_edges(graph, selected_depth, visible_ids)
        aggregates = all_aggregates[:edge_budget]
        visible_edges = ()
        total_edges = len(all_aggregates)

    return RepositoryProjection(
        depth=selected_depth,
        revision_id=graph.revision_id,
        nodes=visible_nodes,
        edges=visible_edges,
        aggregates=aggregates,
        total_node_count=len(ordered_nodes),
        total_edge_count=total_edges,
        truncated=len(visible_nodes) < len(ordered_nodes)
        or len(visible_edges) + len(aggregates) < total_edges,
    )
