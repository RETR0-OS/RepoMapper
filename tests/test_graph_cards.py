from __future__ import annotations

import json
from pathlib import Path

import pytest
from hydra_graph.analyzer import analyze_repository
from hydra_graph.cards import (
    MAX_RELATIONS_PER_ENTITY,
    RELATION_EVIDENCE_SCHEMA,
    HydraEntity,
    HydraRelation,
    HydraSourceGraph,
    build_app_knowledge,
    build_graph_payload,
    build_source_cards,
    graph_payload_json,
)
from hydra_graph.ids import edge_id
from hydra_graph.models import GraphEdge, GraphIR, RelationPredicate, RelationQuality
from pydantic import ValidationError

FIXTURE = Path(__file__).parents[1] / "fixtures" / "sample_repo"


def test_cards_contain_grounded_source_and_filterable_metadata() -> None:
    graph = analyze_repository(FIXTURE, repository_id="sample", revision_id="r1")
    cards = build_source_cards(graph, FIXTURE)
    greeter = next(
        card
        for card in cards
        if card.additional_metadata["qualified_name"] == "app.service.Greeter.greet"
    )

    assert "Signature: greet(self, name: str) -> str" in greeter.content
    assert "return format_greeting(normalize_name(name))" in greeter.content
    assert greeter.metadata == {
        "repository_id": "sample",
        "revision_id": "r1",
        "entity_kind": "METHOD",
        "language": "python",
        "relation_quality": "exact",
        "is_generated": False,
        "is_test": False,
    }
    assert greeter.additional_metadata["path"] == "app/service.py"
    assert greeter.additional_metadata["start_line"] == 5
    assert greeter.additional_metadata["start_column"] == 4
    assert greeter.additional_metadata["end_column"] > 0
    assert greeter.additional_metadata["logical_id"]
    assert greeter.additional_metadata["signature"] == "greet(self, name: str) -> str"
    assert greeter.additional_metadata["evidence_id"].startswith("evidence_")
    assert (
        greeter.additional_metadata["excerpt_hash"] == greeter.additional_metadata["content_hash"]
    )


def test_every_exact_relation_has_one_canonical_byog_owner() -> None:
    graph = analyze_repository(FIXTURE, repository_id="sample", revision_id="r1")
    cards = build_source_cards(graph, FIXTURE)
    emitted = [
        (relation.source, relation.predicate, relation.target)
        for card in cards
        for relation in card.graph.relations
    ]
    expected = [(edge.source_id, edge.predicate.value, edge.target_id) for edge in graph.edges]

    assert sorted(emitted) == sorted(expected)
    assert len(emitted) == len(set(emitted))


def test_byog_relation_context_round_trips_original_edge_evidence() -> None:
    graph = analyze_repository(FIXTURE, repository_id="sample", revision_id="r1")
    cards = build_source_cards(graph, FIXTURE)
    envelopes = {
        payload["edge_id"]: payload
        for card in cards
        for relation in card.graph.relations
        for payload in (json.loads(relation.context or "{}"),)
    }

    assert set(envelopes) == {edge.id for edge in graph.edges}
    for edge in graph.edges:
        envelope = envelopes[edge.id]
        assert envelope["schema"] == RELATION_EVIDENCE_SCHEMA
        assert envelope["summary"]
        assert envelope["quality"] == "exact"
        assert envelope["extractor"] == edge.extractor
        assert envelope["extractor_version"] == edge.extractor_version
        assert envelope["evidence"] == edge.evidence[0].model_dump(mode="json", exclude_none=True)
        serialized = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        assert len(serialized) <= 2_000


def test_byog_relation_context_refuses_to_truncate_exact_evidence() -> None:
    graph = analyze_repository(FIXTURE, repository_id="sample", revision_id="r1")
    original = graph.edges[0]
    oversized_evidence = original.evidence[0].model_copy(update={"explanation": "x" * 2_000})
    oversized_edge = original.model_copy(update={"evidence": (oversized_evidence,)})
    oversized_graph = graph.model_copy(update={"edges": (oversized_edge, *graph.edges[1:])})

    with pytest.raises(ValueError, match="cannot fit HydraDB"):
        build_source_cards(oversized_graph, FIXTURE)


def test_byog_shape_uses_source_ids_and_globally_unambiguous_names() -> None:
    graph = analyze_repository(FIXTURE, repository_id="sample", revision_id="r1")
    cards = build_source_cards(graph, FIXTURE)
    payload = build_graph_payload(cards)

    assert set(payload) == {card.source_id for card in cards}
    for source_graph in payload.values():
        assert set(source_graph) == {"entities", "relations"}
        for entity in source_graph["entities"].values():
            assert " [" in entity["name"] and " @ " in entity["name"]
            assert entity["namespace"] == "sample"
        for relation in source_graph["relations"]:
            assert relation["source"] in source_graph["entities"]
            assert relation["target"] in source_graph["entities"]
            assert len(relation["context"]) <= 2_000
    assert graph_payload_json(cards) == graph_payload_json(list(reversed(cards)))
    app_sources = build_app_knowledge(cards)
    assert {source["id"] for source in app_sources} == set(payload)
    assert all(source["type"] == "code_entity" for source in app_sources)
    assert all(source["content"]["text"] for source in app_sources)


def test_inferred_relations_never_enter_exact_cards_or_byog() -> None:
    graph = analyze_repository(FIXTURE, repository_id="sample", revision_id="r1")
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
        confidence=0.6,
        evidence=next(edge.evidence for edge in graph.edges if edge.source_id == source.id),
        revision_id="r1",
        extractor="unresolved-receiver-heuristic",
        extractor_version="1",
        owner_source_id=source.id,
    )
    with_inferred = GraphIR(
        repository_id=graph.repository_id,
        revision_id=graph.revision_id,
        nodes=graph.nodes,
        edges=(*graph.edges, inferred),
    )
    cards = build_source_cards(with_inferred, FIXTURE)

    assert all(
        relation.predicate != "MAY_CALL" for card in cards for relation in card.graph.relations
    )
    source_card = next(card for card in cards if card.node_id == source.id)
    assert "MAY_CALL" not in source_card.content


def test_byog_model_enforces_documented_degree_and_name_limits() -> None:
    entities = {
        "a": HydraEntity(name="a", type="FUNCTION", namespace="repo"),
        "b": HydraEntity(name="b", type="FUNCTION", namespace="repo"),
    }
    repeated = tuple(
        HydraRelation(source="a", target="b", predicate="CALLS")
        for _ in range(MAX_RELATIONS_PER_ENTITY + 1)
    )
    with pytest.raises(ValidationError, match="exceeds degree"):
        HydraSourceGraph(entities=entities, relations=repeated)
    with pytest.raises(ValidationError):
        HydraEntity(name="x" * 257, type="FUNCTION", namespace="repo")


def test_card_builder_refuses_stale_or_fabricated_source_spans(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("def real():\n    return 1\n", encoding="utf-8")
    graph = analyze_repository(tmp_path, repository_id="sample", revision_id="r1")
    source.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="span exceeds"):
        build_source_cards(graph, tmp_path)


def test_card_builder_refuses_same_length_source_replacement(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("def real():\n    return 1\n", encoding="utf-8")
    graph = analyze_repository(tmp_path, repository_id="sample", revision_id="r1")
    source.write_text("def fake():\n    return 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after analysis"):
        build_source_cards(graph, tmp_path)
