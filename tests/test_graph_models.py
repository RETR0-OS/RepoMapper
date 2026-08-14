from __future__ import annotations

import pytest
from hydra_graph.ids import content_hash, edge_id, evidence_id, node_id
from hydra_graph.models import (
    Evidence,
    GraphEdge,
    GraphIR,
    GraphNode,
    NodeKind,
    RelationPredicate,
    RelationQuality,
    SourceSpan,
)
from pydantic import ValidationError


def make_node(name: str, *, kind: NodeKind = NodeKind.FUNCTION) -> GraphNode:
    compact, logical = node_id(
        repository_id="example",
        path="src/example.py",
        language="python",
        kind=kind.value,
        qualified_name=f"example.{name}",
        signature_discriminator=None,
    )
    return GraphNode(
        id=compact,
        logical_id=logical,
        kind=kind,
        display_name=name,
        qualified_name=f"example.{name}",
        language="python",
        path="src/example.py",
        span=SourceSpan(start_line=1, start_column=0, end_line=2, end_column=4),
        signature=f"{name}()",
        revision_id="r1",
        content_hash=content_hash(f"def {name}(): pass"),
        parser="test-parser",
        parser_version="1",
    )


def make_evidence() -> Evidence:
    excerpt = content_hash("target()")
    return Evidence(
        id=evidence_id(
            path="src/example.py",
            start_line=2,
            start_column=4,
            end_line=2,
            end_column=12,
            excerpt_hash=excerpt,
        ),
        path="src/example.py",
        start_line=2,
        start_column=4,
        end_line=2,
        end_column=12,
        excerpt_hash=excerpt,
        explanation="example.source calls example.target at src/example.py:2.",
    )


def test_exact_edge_requires_evidence_and_rejects_decorative_confidence() -> None:
    source = make_node("source")
    target = make_node("target")
    compact, logical = edge_id(
        repository_id="example",
        source_id=source.id,
        predicate="CALLS",
        target_id=target.id,
        quality="exact",
    )
    fields = dict(
        id=compact,
        logical_id=logical,
        source_id=source.id,
        predicate=RelationPredicate.CALLS,
        target_id=target.id,
        quality=RelationQuality.EXACT,
        revision_id="r1",
        extractor="test-parser",
        extractor_version="1",
        owner_source_id=source.id,
    )
    with pytest.raises(ValidationError, match="require grounded evidence"):
        GraphEdge(**fields, evidence=())
    with pytest.raises(ValidationError, match="decorative confidence"):
        GraphEdge(**fields, evidence=(make_evidence(),), confidence=1.0)


def test_inferred_edge_cannot_hide_missing_confidence() -> None:
    source = make_node("source")
    target = make_node("target")
    compact, logical = edge_id(
        repository_id="example",
        source_id=source.id,
        predicate="MAY_CALL",
        target_id=target.id,
        quality="inferred",
    )
    with pytest.raises(ValidationError, match="inferred relations require"):
        GraphEdge(
            id=compact,
            logical_id=logical,
            source_id=source.id,
            predicate=RelationPredicate.MAY_CALL,
            target_id=target.id,
            quality=RelationQuality.INFERRED,
            evidence=(make_evidence(),),
            revision_id="r1",
            extractor="heuristic",
            extractor_version="1",
            owner_source_id=source.id,
        )


def test_line_addressable_nodes_cannot_use_fabricated_missing_spans() -> None:
    valid = make_node("grounded")
    with pytest.raises(ValidationError, match="require an exact source span"):
        GraphNode(**{**valid.model_dump(), "span": None})


def test_model_has_no_concept_node_kind() -> None:
    assert "CONCEPT" not in NodeKind.__members__
    with pytest.raises(ValueError):
        NodeKind("CONCEPT")


def test_graph_rejects_dangling_edges_and_duplicate_ids() -> None:
    source = make_node("source")
    target = make_node("target")
    compact, logical = edge_id(
        repository_id="example",
        source_id=source.id,
        predicate="CALLS",
        target_id=target.id,
        quality="exact",
    )
    edge = GraphEdge(
        id=compact,
        logical_id=logical,
        source_id=source.id,
        predicate=RelationPredicate.CALLS,
        target_id=target.id,
        quality=RelationQuality.EXACT,
        evidence=(make_evidence(),),
        revision_id="r1",
        extractor="test-parser",
        extractor_version="1",
        owner_source_id=source.id,
    )
    with pytest.raises(ValidationError, match="missing node"):
        GraphIR(repository_id="example", revision_id="r1", nodes=(source,), edges=(edge,))
    with pytest.raises(ValidationError, match="duplicate node IDs"):
        GraphIR(repository_id="example", revision_id="r1", nodes=(source, source), edges=())


def test_evidence_range_is_all_or_nothing() -> None:
    with pytest.raises(ValidationError, match="complete source range"):
        Evidence(
            id="evidence_incomplete",
            path="src/example.py",
            start_line=1,
            excerpt_hash=content_hash("x"),
            explanation="An incomplete range is invalid.",
        )
