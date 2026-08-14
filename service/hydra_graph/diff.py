"""Deterministic comparison of two verified Graph IR revisions."""

from __future__ import annotations

import re
from collections import defaultdict

from pydantic import Field

from .models import FrozenModel, GraphEdge, GraphIR, GraphNode, NodeKind, RelationPredicate

DEFAULT_RENAME_THRESHOLD = 0.80


class NodeModification(FrozenModel):
    node_id: str
    changed_fields: tuple[str, ...]
    explanation: str


class RenameMatch(FrozenModel):
    before_node_id: str
    after_node_id: str
    score: float = Field(ge=0, le=1)
    matched_signals: tuple[str, ...]
    explanation: str


class EvidenceMove(FrozenModel):
    edge_id: str
    before_evidence_ids: tuple[str, ...]
    after_evidence_ids: tuple[str, ...]
    explanation: str


class RelationQualityChange(FrozenModel):
    before_edge_id: str
    after_edge_id: str
    explanation: str


class GraphDelta(FrozenModel):
    repository_id: str
    before_revision_id: str
    after_revision_id: str
    added_node_ids: tuple[str, ...]
    removed_node_ids: tuple[str, ...]
    modified_nodes: tuple[NodeModification, ...]
    renamed_nodes: tuple[RenameMatch, ...]
    added_edge_ids: tuple[str, ...]
    removed_edge_ids: tuple[str, ...]
    evidence_moves: tuple[EvidenceMove, ...]
    relation_quality_changes: tuple[RelationQualityChange, ...]
    structural_warnings: tuple[str, ...]


def _signature_shape(node: GraphNode) -> str | None:
    if not node.signature:
        return None
    if node.kind in {NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.TEST}:
        return re.sub(r"^(?:async\s+)?[^\(]+", "function", node.signature)
    if node.kind is NodeKind.CLASS:
        return "class"
    return node.signature


def _rename_score(before: GraphNode, after: GraphNode) -> tuple[float, tuple[str, ...]]:
    if before.kind is not after.kind or before.language != after.language:
        return 0.0, ()
    score = 0.0
    signals: list[str] = []
    before_fingerprint = before.attributes.get("body_fingerprint")
    after_fingerprint = after.attributes.get("body_fingerprint")
    if before_fingerprint and before_fingerprint == after_fingerprint:
        score += 0.65
        signals.append("body_fingerprint")
    if before.path == after.path:
        score += 0.15
        signals.append("same_path")
    if _signature_shape(before) and _signature_shape(before) == _signature_shape(after):
        score += 0.15
        signals.append("signature_shape")
    before_owner = before.qualified_name.rpartition(".")[0]
    after_owner = after.qualified_name.rpartition(".")[0]
    if before_owner and before_owner == after_owner:
        score += 0.05
        signals.append("same_owner")
    return min(score, 1.0), tuple(signals)


def _match_renames(
    removed: list[GraphNode],
    added: list[GraphNode],
    threshold: float,
) -> tuple[list[RenameMatch], set[str], set[str]]:
    candidates: list[tuple[float, str, str, tuple[str, ...], GraphNode, GraphNode]] = []
    for before in removed:
        for after in added:
            score, signals = _rename_score(before, after)
            if score >= threshold:
                candidates.append((score, before.id, after.id, signals, before, after))
    # A tie is ambiguous evidence, not permission to pick an arbitrary rename.
    # Only mutually unique best matches are eligible.
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    scores_by_before: dict[str, list[float]] = defaultdict(list)
    scores_by_after: dict[str, list[float]] = defaultdict(list)
    for score, before_id, after_id, *_ in candidates:
        scores_by_before[before_id].append(score)
        scores_by_after[after_id].append(score)

    def unique_best(scores: list[float], score: float) -> bool:
        return scores.count(score) == 1 and score == max(scores)

    used_before: set[str] = set()
    used_after: set[str] = set()
    matches: list[RenameMatch] = []
    for score, before_id, after_id, signals, before, after in candidates:
        if not unique_best(scores_by_before[before_id], score) or not unique_best(
            scores_by_after[after_id], score
        ):
            continue
        if before_id in used_before or after_id in used_after:
            continue
        used_before.add(before_id)
        used_after.add(after_id)
        matches.append(
            RenameMatch(
                before_node_id=before_id,
                after_node_id=after_id,
                score=score,
                matched_signals=signals,
                explanation=(
                    f"Matched {before.qualified_name} to {after.qualified_name} using "
                    f"{', '.join(signals)}."
                ),
            )
        )
    return matches, used_before, used_after


def _modified(before: GraphNode, after: GraphNode) -> NodeModification | None:
    comparable = {
        "content_hash": (before.content_hash, after.content_hash),
        "signature": (before.signature, after.signature),
        "path": (before.path, after.path),
        "span": (before.span, after.span),
        "parser": ((before.parser, before.parser_version), (after.parser, after.parser_version)),
        "attributes": (before.attributes, after.attributes),
    }
    changed = tuple(sorted(field for field, values in comparable.items() if values[0] != values[1]))
    if not changed:
        return None
    return NodeModification(
        node_id=before.id,
        changed_fields=changed,
        explanation=f"{before.qualified_name} changed: {', '.join(changed)}.",
    )


def _edge_fact(edge: GraphEdge) -> tuple[str, RelationPredicate, str]:
    return edge.source_id, edge.predicate, edge.target_id


def _quality_changes(
    removed_edges: list[GraphEdge], added_edges: list[GraphEdge]
) -> tuple[list[RelationQualityChange], set[str], set[str]]:
    removed_by_fact = {_edge_fact(edge): edge for edge in removed_edges}
    added_by_fact = {_edge_fact(edge): edge for edge in added_edges}
    changes: list[RelationQualityChange] = []
    consumed_before: set[str] = set()
    consumed_after: set[str] = set()
    for fact in sorted(set(removed_by_fact) & set(added_by_fact), key=str):
        before = removed_by_fact[fact]
        after = added_by_fact[fact]
        if before.quality == after.quality:
            continue
        consumed_before.add(before.id)
        consumed_after.add(after.id)
        changes.append(
            RelationQualityChange(
                before_edge_id=before.id,
                after_edge_id=after.id,
                explanation=(
                    f"{before.predicate.value} quality changed from {before.quality.value} "
                    f"to {after.quality.value}."
                ),
            )
        )
    return changes, consumed_before, consumed_after


def _cycle_signatures(graph: GraphIR) -> set[tuple[str, ...]]:
    """Return canonical directed cycle signatures for behavioral dependencies."""

    allowed = {
        RelationPredicate.CALLS,
        RelationPredicate.IMPORTS,
        RelationPredicate.INSTANTIATES,
        RelationPredicate.DISPATCHES_TO,
        RelationPredicate.INVOKES,
    }
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        if edge.predicate in allowed and edge.quality.value == "exact":
            adjacency[edge.source_id].add(edge.target_id)

    index = 0
    stack: list[str] = []
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    on_stack: set[str] = set()
    components: set[tuple[str, ...]] = set()

    def strong_connect(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlink[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for neighbor in sorted(adjacency[node]):
            if neighbor not in indices:
                strong_connect(neighbor)
                lowlink[node] = min(lowlink[node], lowlink[neighbor])
            elif neighbor in on_stack:
                lowlink[node] = min(lowlink[node], indices[neighbor])
        if lowlink[node] == indices[node]:
            component: list[str] = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.append(member)
                if member == node:
                    break
            if len(component) > 1:
                components.add(tuple(sorted(component)))

    for node in sorted(adjacency):
        if node not in indices:
            strong_connect(node)
    return components


def compare_graphs(
    before: GraphIR,
    after: GraphIR,
    *,
    rename_threshold: float = DEFAULT_RENAME_THRESHOLD,
) -> GraphDelta:
    """Compute an explainable set diff without relying on layout or retrieval rank."""

    if before.repository_id != after.repository_id:
        raise ValueError("cannot compare graphs from different repositories")
    if not 0 <= rename_threshold <= 1:
        raise ValueError("rename_threshold must be between zero and one")
    before_nodes = before.node_map()
    after_nodes = after.node_map()
    common_nodes = sorted(set(before_nodes) & set(after_nodes))
    modified = [
        change
        for node_id in common_nodes
        if (change := _modified(before_nodes[node_id], after_nodes[node_id])) is not None
    ]
    removed_nodes = [
        before_nodes[node_id] for node_id in sorted(set(before_nodes) - set(after_nodes))
    ]
    added_nodes = [after_nodes[node_id] for node_id in sorted(set(after_nodes) - set(before_nodes))]
    renames, renamed_before, renamed_after = _match_renames(
        removed_nodes, added_nodes, rename_threshold
    )

    before_edges = {edge.id: edge for edge in before.edges}
    after_edges = {edge.id: edge for edge in after.edges}
    common_edges = sorted(set(before_edges) & set(after_edges))
    evidence_moves = []
    for edge_id in common_edges:
        before_evidence = tuple(item.id for item in before_edges[edge_id].evidence)
        after_evidence = tuple(item.id for item in after_edges[edge_id].evidence)
        if before_evidence != after_evidence:
            evidence_moves.append(
                EvidenceMove(
                    edge_id=edge_id,
                    before_evidence_ids=before_evidence,
                    after_evidence_ids=after_evidence,
                    explanation=f"Evidence for {edge_id} moved or changed.",
                )
            )

    removed_edges = [before_edges[item] for item in sorted(set(before_edges) - set(after_edges))]
    added_edges = [after_edges[item] for item in sorted(set(after_edges) - set(before_edges))]
    quality_changes, quality_before, quality_after = _quality_changes(removed_edges, added_edges)

    warnings: list[str] = []
    removed_test_edges = [
        edge
        for edge in removed_edges
        if edge.predicate is RelationPredicate.TESTS and edge.id not in quality_before
    ]
    if removed_test_edges:
        warnings.append(f"{len(removed_test_edges)} exact TESTS relation(s) were removed.")
    new_cycles = _cycle_signatures(after) - _cycle_signatures(before)
    if new_cycles:
        warnings.append(f"{len(new_cycles)} new exact dependency cycle(s) were introduced.")

    return GraphDelta(
        repository_id=before.repository_id,
        before_revision_id=before.revision_id,
        after_revision_id=after.revision_id,
        added_node_ids=tuple(node.id for node in added_nodes if node.id not in renamed_after),
        removed_node_ids=tuple(node.id for node in removed_nodes if node.id not in renamed_before),
        modified_nodes=tuple(modified),
        renamed_nodes=tuple(sorted(renames, key=lambda item: item.before_node_id)),
        added_edge_ids=tuple(edge.id for edge in added_edges if edge.id not in quality_after),
        removed_edge_ids=tuple(edge.id for edge in removed_edges if edge.id not in quality_before),
        evidence_moves=tuple(evidence_moves),
        relation_quality_changes=tuple(quality_changes),
        structural_warnings=tuple(warnings),
    )
