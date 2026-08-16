from __future__ import annotations

import json
from pathlib import Path

import pytest
from hydra_graph.analyzer import analyze_repository
from hydra_graph.cards import build_app_knowledge, build_graph_payload
from hydra_graph.diff import compare_graphs
from hydra_graph.evolution import (
    CHANGE_EVENT_PAGE_SCHEMA,
    CHANGE_EVENT_SCHEMA,
    SYSTEM_LENS_SCHEMA,
    ChangeEventPage,
    ChangeEventSummary,
    ChangeKind,
    LensDriftKind,
    RelationQuality,
    SystemLensRecord,
    build_change_event,
    build_change_event_cards,
    build_system_lens,
    build_system_lens_card,
    classify_lens_drift,
)
from hydra_graph.models import GraphIR, RelationPredicate


def _rename_graphs(root: Path):
    source = root / "module.py"
    source.write_text(
        "def keep():\n    return 1\n\n"
        "def old_name(value):\n    return value + 1\n\n"
        "def removed():\n    return 0\n",
        encoding="utf-8",
    )
    before = analyze_repository(root, repository_id="evolution", revision_id="before")
    source.write_text(
        "def keep():\n    return 2\n\n"
        "def new_name(value):\n    return value + 1\n\n"
        "def added():\n    return 3\n",
        encoding="utf-8",
    )
    after = analyze_repository(root, repository_id="evolution", revision_id="after")
    return before, after


def _call_graph(root: Path):
    (root / "module.py").write_text(
        "def target():\n    return 1\n\ndef caller():\n    return target()\n",
        encoding="utf-8",
    )
    return analyze_repository(root, repository_id="lens", revision_id="verified")


def test_change_event_keeps_exact_set_facts_and_inferred_rename(tmp_path: Path) -> None:
    before, after = _rename_graphs(tmp_path)
    delta = compare_graphs(before, after)
    event = build_change_event(delta, before, after)
    rename = next(fact for fact in event.facts if fact.kind is ChangeKind.RENAME_HYPOTHESIS)

    assert rename.quality is RelationQuality.INFERRED
    assert rename.confidence == delta.renamed_nodes[0].score
    assert rename.matched_signals == tuple(sorted(delta.renamed_nodes[0].matched_signals))
    renamed_before = delta.renamed_nodes[0].before_node_id
    renamed_after = delta.renamed_nodes[0].after_node_id
    assert any(
        fact.kind is ChangeKind.NODE_REMOVED
        and fact.before_nodes[0].node_id == renamed_before
        and fact.quality is RelationQuality.EXACT
        for fact in event.facts
    )
    assert any(
        fact.kind is ChangeKind.NODE_ADDED
        and fact.after_nodes[0].node_id == renamed_after
        and fact.quality is RelationQuality.EXACT
        for fact in event.facts
    )
    assert event.lens_impact_status.value == "not_evaluated"
    assert event.affected_lens_ids == ()


def test_change_cards_round_trip_every_fact_and_original_evidence(tmp_path: Path) -> None:
    before, after = _rename_graphs(tmp_path)
    delta = compare_graphs(before, after)
    event = build_change_event(delta, before, after)
    cards = build_change_event_cards(delta, before, after)
    summary_card = next(
        card for card in cards if card.additional_metadata["record_kind"] == "change_event_summary"
    )
    page_cards = [
        card for card in cards if card.additional_metadata["record_kind"] == "change_event_page"
    ]
    summary = ChangeEventSummary.model_validate_json(
        str(summary_card.additional_metadata["record_json"])
    )
    pages = [
        ChangeEventPage.model_validate_json(str(card.additional_metadata["record_json"]))
        for card in page_cards
    ]

    assert summary.record_schema == CHANGE_EVENT_SCHEMA
    assert summary.fact_count == len(event.facts) == len(pages)
    assert {page.fact for page in pages} == set(event.facts)
    assert {page.page_index for page in pages} == set(range(1, len(pages) + 1))
    assert all(page.record_schema == CHANGE_EVENT_PAGE_SCHEMA for page in pages)
    assert all(len(card.content) <= 12_000 for card in cards)
    app_knowledge = build_app_knowledge(list(cards))
    assert {item["type"] for item in app_knowledge} == {"change_event"}
    assert all("record_json" not in item["additional_metadata"] for item in app_knowledge)
    assert all(
        len(
            json.dumps(item["additional_metadata"], separators=(",", ":"), sort_keys=True).encode(
                "utf-8"
            )
        )
        <= 1_024
        for item in app_knowledge
    )
    assert set(build_graph_payload(list(cards))) == {
        card.source_id for card in cards if card.graph.relations
    }
    # Machine records contain complete evidence objects; they are not reconstructed spans.
    rename_page = next(page for page in pages if page.fact.kind is ChangeKind.RENAME_HYPOTHESIS)
    assert rename_page.fact.before_nodes[0].evidence.evidence.id
    assert rename_page.fact.after_nodes[0].evidence.evidence.id


def test_change_event_rejects_delta_mismatch_and_tampered_evidence_id(tmp_path: Path) -> None:
    graph = _call_graph(tmp_path)
    after = graph.model_copy(update={"revision_id": "after"})
    after = GraphIR.model_validate(
        {
            **after.model_dump(mode="json"),
            "nodes": [
                {**node.model_dump(mode="json"), "revision_id": "after"} for node in graph.nodes
            ],
            "edges": [
                {**edge.model_dump(mode="json"), "revision_id": "after"} for edge in graph.edges
            ],
        }
    )
    delta = compare_graphs(graph, after)
    wrong_delta = delta.model_copy(update={"after_revision_id": "wrong"})
    with pytest.raises(ValueError, match="after revision"):
        build_change_event(wrong_delta, graph, after)

    edge = after.edges[0]
    forged_evidence = edge.evidence[0].model_copy(
        update={"id": "evidence_000000000000000000000000"}
    )
    forged_edge = edge.model_copy(update={"evidence": (forged_evidence,)})
    forged_after = after.model_copy(update={"edges": (forged_edge, *after.edges[1:])})
    forged_delta = compare_graphs(graph, forged_after)
    with pytest.raises(ValueError, match="does not match its source identity"):
        build_change_event(forged_delta, graph, forged_after)


def test_empty_delta_emits_only_explicit_summary_without_fabricated_edges(tmp_path: Path) -> None:
    before = _call_graph(tmp_path)
    after_payload = before.model_dump(mode="json")
    after_payload["revision_id"] = "after"
    for node in after_payload["nodes"]:
        node["revision_id"] = "after"
    for edge in after_payload["edges"]:
        edge["revision_id"] = "after"
    after = GraphIR.model_validate(after_payload)
    delta = compare_graphs(before, after)

    cards = build_change_event_cards(delta, before, after)

    assert len(cards) == 1
    assert set(cards[0].graph.entities) == {cards[0].node_id}
    assert cards[0].graph.relations == ()
    record = json.loads(str(cards[0].additional_metadata["record_json"]))
    assert record["fact_count"] == 0


def test_system_lens_is_shared_exact_grounded_and_has_no_duplicate_byog(tmp_path: Path) -> None:
    graph = _call_graph(tmp_path)
    call = next(edge for edge in graph.edges if edge.predicate is RelationPredicate.CALLS)
    node_ids = {call.source_id, call.target_id}
    nodes = [
        node.model_copy(
            update={"attributes": {**node.attributes, "hydradb_origin": "repository-source-card"}}
        )
        for node in graph.nodes
        if node.id in node_ids
    ]
    returned_call = call.model_copy(
        update={"attributes": {**call.attributes, "hydradb_origin": "byog"}}
    )
    view = {
        "view_id": "view_exact",
        "revision_id": graph.revision_id,
        "hydradb": {"available": True, "origin": "byog"},
        "nodes": [node.model_dump(mode="json") for node in reversed(nodes)],
        "edges": [returned_call.model_dump(mode="json")],
    }

    lens = build_system_lens(
        repository_id="lens",
        name="Call path",
        purpose="Keep the caller-to-target flow visible.",
        view=view,
        anchor_node_ids=sorted(node_ids),
        edge_ids=[call.id],
    )
    card = build_system_lens_card(lens)
    restored = SystemLensRecord.model_validate_json(str(card.additional_metadata["record_json"]))

    assert restored == lens
    assert lens.ownership == "shared"
    assert lens.baseline_hops[0].evidence == call.evidence
    assert card.metadata["record_schema"] == SYSTEM_LENS_SCHEMA
    assert card.source_type == "system_lens"
    assert set(card.graph.entities) == {card.node_id}
    assert card.graph.relations == ()
    assert (
        build_system_lens_card(lens.model_copy(update={"name": "Renamed lens"})).source_id
        == card.source_id
    )

    unavailable = {**view, "hydradb": {"available": False}}
    with pytest.raises(ValueError, match="available HydraDB"):
        build_system_lens(
            repository_id="lens",
            name="Forged",
            purpose="Must fail.",
            view=unavailable,
            anchor_node_ids=sorted(node_ids),
            edge_ids=[call.id],
        )
    with pytest.raises(ValueError, match="at least one grounded hop"):
        build_system_lens(
            repository_id="lens",
            name="Node only",
            purpose="Must fail.",
            view={**view, "edges": []},
            anchor_node_ids=sorted(node_ids),
            edge_ids=[],
        )


def test_lens_drift_classification_has_honest_precedence(tmp_path: Path) -> None:
    (tmp_path / "flow.py").write_text(
        "def third():\n    return 1\n\n"
        "def second():\n    return third()\n\n"
        "def first():\n    return second()\n",
        encoding="utf-8",
    )
    graph = analyze_repository(tmp_path, repository_id="drift", revision_id="before")
    calls = sorted(
        (edge for edge in graph.edges if edge.predicate is RelationPredicate.CALLS),
        key=lambda edge: edge.id,
    )
    returned_nodes = [
        node.model_copy(
            update={"attributes": {**node.attributes, "hydradb_origin": "repository-source-card"}}
        )
        for node in graph.nodes
    ]
    returned_edges = [
        edge.model_copy(update={"attributes": {**edge.attributes, "hydradb_origin": "byog"}})
        for edge in calls
    ]
    view = {
        "view_id": "view_before",
        "revision_id": "before",
        "hydradb": {"available": True, "origin": "byog"},
        "nodes": [node.model_dump(mode="json") for node in returned_nodes],
        "edges": [edge.model_dump(mode="json") for edge in returned_edges],
    }
    first_edge = returned_edges[0]
    saved = build_system_lens(
        repository_id="drift",
        name="Flow",
        purpose="Track a grounded path.",
        view=view,
        anchor_node_ids=[first_edge.source_id, first_edge.target_id],
        edge_ids=[first_edge.id],
    )
    current_view = {
        **view,
        "view_id": "view_after",
        "revision_id": "after",
        "nodes": [
            {**node.model_dump(mode="json"), "revision_id": "after"} for node in returned_nodes
        ],
        "edges": [
            {**edge.model_dump(mode="json"), "revision_id": "after"} for edge in returned_edges
        ],
    }
    current = build_system_lens(
        repository_id="drift",
        name="Flow",
        purpose="Track a grounded path.",
        view=current_view,
        anchor_node_ids=[first_edge.source_id, first_edge.target_id],
        edge_ids=[edge.id for edge in returned_edges],
    )

    assert classify_lens_drift(saved, current).classification is LensDriftKind.PATH_EXTENDED
    assert classify_lens_drift(current, saved).classification is LensDriftKind.PATH_SHORTENED
    assert classify_lens_drift(saved, None).classification is LensDriftKind.UNRESOLVED
    unchanged = saved.model_copy(update={"saved_revision_id": "after"})
    assert classify_lens_drift(saved, unchanged).classification is LensDriftKind.UNCHANGED

    replacement = current.baseline_hops[0].model_copy(
        update={"edge_id": "edge_replacement", "predicate": RelationPredicate.REFERENCES}
    )
    changed = saved.model_copy(update={"baseline_hops": (replacement,)})
    assert classify_lens_drift(saved, changed).classification is LensDriftKind.RELATION_CHANGED

    test_hop = saved.baseline_hops[0].model_copy(
        update={"edge_id": "edge_tests", "predicate": RelationPredicate.TESTS}
    )
    test_baseline = saved.model_copy(update={"baseline_hops": (test_hop,)})
    assert (
        classify_lens_drift(test_baseline, changed).classification
        is LensDriftKind.TEST_COVERAGE_RELATION_CHANGED
    )

    other_edge = returned_edges[1]
    other = build_system_lens(
        repository_id="drift",
        name="Flow",
        purpose="Track a grounded path.",
        view=current_view,
        anchor_node_ids=[other_edge.source_id, other_edge.target_id],
        edge_ids=[other_edge.id],
    )
    assert classify_lens_drift(saved, other).classification is LensDriftKind.ANCHOR_REMOVED
