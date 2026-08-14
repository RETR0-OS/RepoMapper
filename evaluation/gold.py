"""Load and verify hand-checked gold facts against a concrete Graph IR."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from hydra_graph.analyzer import analyze_repository
from hydra_graph.models import Evidence, GraphEdge, GraphIR, GraphNode

from .models import GoldEvidence, GoldManifest, GoldQuestion, GoldRelation


@dataclass(frozen=True, slots=True)
class ResolvedQuestion:
    question: GoldQuestion
    required_node_ids: tuple[str, ...]
    required_relations: tuple[GraphEdge, ...]
    required_evidence: tuple[Evidence, ...]


@dataclass(frozen=True, slots=True)
class ResolvedGold:
    manifest: GoldManifest
    graph: GraphIR
    questions: tuple[ResolvedQuestion, ...]
    digest: str
    fixture_root: Path


def load_gold(path: str | Path) -> GoldManifest:
    manifest_path = Path(path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read gold manifest: {manifest_path}") from error
    return GoldManifest.model_validate(payload)


def resolve_gold(manifest: GoldManifest, graph: GraphIR) -> tuple[ResolvedQuestion, ...]:
    if graph.repository_id != manifest.repository_id:
        raise ValueError("gold manifest and Graph IR repository IDs differ")
    if graph.revision_id != manifest.revision_id:
        raise ValueError("gold manifest and Graph IR revision IDs differ")

    nodes_by_logical = {node.logical_id: node for node in graph.nodes}
    edges_by_id = {edge.id: edge for edge in graph.edges}
    resolved: list[ResolvedQuestion] = []
    for question in manifest.questions:
        node_ids: list[str] = []
        for logical_id in question.required_node_logical_ids:
            node = nodes_by_logical.get(logical_id)
            if node is None:
                raise ValueError(f"question {question.id} references unknown node {logical_id}")
            node_ids.append(node.id)

        relations: list[GraphEdge] = []
        evidence: dict[str, Evidence] = {}
        for relation in question.required_relations:
            edge = _resolve_relation(question.id, relation, nodes_by_logical, edges_by_id)
            relations.append(edge)
            edge_evidence = {item.id: item for item in edge.evidence}
            for expected in relation.evidence:
                actual = edge_evidence.get(expected.evidence_id)
                if actual is None or not _same_evidence(expected, actual):
                    raise ValueError(
                        f"question {question.id} evidence {expected.evidence_id} "
                        "does not match the Graph IR"
                    )
                evidence[actual.id] = actual
        resolved.append(
            ResolvedQuestion(
                question=question,
                required_node_ids=tuple(sorted(set(node_ids))),
                required_relations=tuple(sorted(relations, key=lambda item: item.id)),
                required_evidence=tuple(sorted(evidence.values(), key=lambda item: item.id)),
            )
        )
    return tuple(resolved)


def load_and_resolve_gold(path: str | Path, *, verify_fixture: bool = True) -> ResolvedGold:
    manifest_path = Path(path).resolve()
    manifest = load_gold(manifest_path)
    base = manifest_path.parent
    fixture_root = _safe_relative(base, manifest.fixture_root)
    graph_path = _safe_relative(base, manifest.graph_ir_path)
    try:
        graph_bytes = graph_path.read_bytes()
        graph = GraphIR.model_validate_json(graph_bytes)
    except (OSError, ValueError) as error:
        raise ValueError(f"cannot read validated gold Graph IR: {graph_path}") from error
    if verify_fixture:
        analyzed = analyze_repository(
            fixture_root,
            repository_id=manifest.repository_id,
            revision_id=manifest.revision_id,
        )
        analyzed_nodes = analyzed.node_map()
        analyzed_edges = {edge.id: edge for edge in analyzed.edges}
        if any(analyzed_nodes.get(node.id) != node for node in graph.nodes) or any(
            analyzed_edges.get(edge.id) != edge for edge in graph.edges
        ):
            raise ValueError("gold Graph IR is stale relative to its fixture repository")
    questions = resolve_gold(manifest, graph)
    digest_payload = {
        "manifest": manifest.model_dump(mode="json"),
        "graph_hash": hashlib.sha256(graph_bytes).hexdigest(),
    }
    digest = hashlib.sha256(
        json.dumps(digest_payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return ResolvedGold(
        manifest=manifest,
        graph=graph,
        questions=questions,
        digest=digest,
        fixture_root=fixture_root,
    )


def _resolve_relation(
    question_id: str,
    relation: GoldRelation,
    nodes_by_logical: dict[str, GraphNode],
    edges_by_id: dict[str, GraphEdge],
) -> GraphEdge:
    source = nodes_by_logical.get(relation.source_logical_id)
    target = nodes_by_logical.get(relation.target_logical_id)
    if source is None or target is None:
        raise ValueError(f"question {question_id} relation references an unknown endpoint")
    edge = edges_by_id.get(relation.edge_id)
    if edge is None:
        raise ValueError(f"question {question_id} references unknown edge {relation.edge_id}")
    expected = (
        source.id,
        relation.predicate,
        target.id,
        relation.quality,
    )
    actual = (edge.source_id, edge.predicate.value, edge.target_id, edge.quality.value)
    if actual != expected:
        raise ValueError(f"question {question_id} edge {edge.id} does not match its gold fact")
    return edge


def _same_evidence(expected: GoldEvidence, actual: Evidence) -> bool:
    return (
        actual.path,
        actual.start_line,
        actual.start_column,
        actual.end_line,
        actual.end_column,
        actual.excerpt_hash,
    ) == (
        expected.path,
        expected.start_line,
        expected.start_column,
        expected.end_line,
        expected.end_column,
        expected.excerpt_hash,
    )


def _safe_relative(base: Path, relative: str) -> Path:
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as error:
        raise ValueError(
            f"evaluation fixture path escapes its manifest directory: {relative}"
        ) from error
    return candidate
