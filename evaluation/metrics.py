"""Transparent ID- and evidence-based evaluation metrics."""

from __future__ import annotations

from hydra_graph.models import Evidence, GraphEdge

from .gold import ResolvedQuestion
from .models import (
    EvidenceObservation,
    QuestionMetrics,
    RelationObservation,
    RetrievalObservation,
)


def score_observation(
    question: ResolvedQuestion, observation: RetrievalObservation
) -> QuestionMetrics:
    if observation.question_id != question.question.id:
        raise ValueError("observation and gold question IDs differ")
    required_nodes = set(question.required_node_ids)
    returned_nodes = set(observation.returned_node_ids)
    exact_gold = {
        edge.id: edge for edge in question.required_relations if edge.quality.value == "exact"
    }
    inferred_gold = {
        edge.id: edge for edge in question.required_relations if edge.quality.value == "inferred"
    }
    returned_relations = _unique_relations(observation.returned_relations)
    returned_exact = [edge for edge in returned_relations if edge.quality == "exact"]
    returned_inferred = [edge for edge in returned_relations if edge.quality == "inferred"]
    returned_other = [
        edge for edge in returned_relations if edge.quality not in {"exact", "inferred"}
    ]
    supported_exact = sum(
        _same_relation(edge, exact_gold.get(edge.edge_id)) for edge in returned_exact
    )
    supported_inferred = sum(
        _same_relation(edge, inferred_gold.get(edge.edge_id)) for edge in returned_inferred
    )
    all_gold = {edge.id: edge for edge in question.required_relations}
    supported_all = sum(
        _same_relation(edge, all_gold.get(edge.edge_id)) for edge in returned_relations
    )
    required_evidence = {item.id: item for item in question.required_evidence}
    evidence_hits = sum(
        any(_same_evidence(item, expected) for item in observation.returned_evidence)
        for expected in required_evidence.values()
    )
    exact_hits = sum(
        any(_same_relation(item, edge) for item in returned_exact) for edge in exact_gold.values()
    )
    inferred_hits = sum(
        any(_same_relation(item, edge) for item in returned_inferred)
        for edge in inferred_gold.values()
    )
    return QuestionMetrics(
        question_id=question.question.id,
        condition=observation.condition,
        required_nodes=len(required_nodes),
        returned_nodes=len(returned_nodes),
        useful_returned_nodes=len(required_nodes & returned_nodes),
        required_node_hits=len(required_nodes & returned_nodes),
        required_exact_relations=len(exact_gold),
        exact_relation_hits=exact_hits,
        required_inferred_relations=len(inferred_gold),
        inferred_relation_hits=inferred_hits,
        required_evidence=len(required_evidence),
        evidence_hits=evidence_hits,
        supported_returned_exact=supported_exact,
        returned_exact_relations=len(returned_exact),
        supported_returned_inferred=supported_inferred,
        returned_inferred_relations=len(returned_inferred),
        returned_other_relations=len(returned_other),
        unsupported_relations=len(returned_relations) - supported_all,
        context_chars=observation.context_chars,
        context_tokens=observation.context_tokens,
        latency_ms=observation.latency_ms,
    )


def _same_relation(observed: RelationObservation, expected: GraphEdge | None) -> bool:
    if expected is None:
        return False
    return (
        observed.edge_id,
        observed.source_id,
        observed.predicate,
        observed.target_id,
        observed.quality,
    ) == (
        expected.id,
        expected.source_id,
        expected.predicate.value,
        expected.target_id,
        expected.quality.value,
    )


def _same_evidence(observed: EvidenceObservation, expected: Evidence | None) -> bool:
    if expected is None:
        return False
    return (
        observed.evidence_id,
        observed.path,
        observed.start_line,
        observed.start_column,
        observed.end_line,
        observed.end_column,
        observed.excerpt_hash,
    ) == (
        expected.id,
        expected.path,
        expected.start_line,
        expected.start_column,
        expected.end_line,
        expected.end_column,
        expected.excerpt_hash,
    )


def _unique_relations(
    relations: tuple[RelationObservation, ...],
) -> tuple[RelationObservation, ...]:
    unique: dict[tuple[object, ...], RelationObservation] = {}
    for relation in relations:
        key = (
            relation.edge_id,
            relation.source_id,
            relation.predicate,
            relation.target_id,
            relation.quality,
            tuple(
                (
                    evidence.evidence_id,
                    evidence.path,
                    evidence.start_line,
                    evidence.start_column,
                    evidence.end_line,
                    evidence.end_column,
                    evidence.excerpt_hash,
                )
                for evidence in relation.evidence
            ),
        )
        unique[key] = relation
    return tuple(unique.values())
