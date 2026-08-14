from __future__ import annotations

from pathlib import Path

from hydra_graph.analyzer import analyze_repository
from hydra_graph.diff import compare_graphs
from hydra_graph.models import NodeKind


def test_diff_detects_add_remove_modify_and_deterministic_rename(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text(
        "def keep():\n    return 1\n\n"
        "def old_name(value):\n    return value + 1\n\n"
        "def removed():\n    return 0\n",
        encoding="utf-8",
    )
    before = analyze_repository(tmp_path, repository_id="diff", revision_id="before")
    source.write_text(
        "def keep():\n    return 2\n\n"
        "def new_name(value):\n    return value + 1\n\n"
        "def added():\n    return 3\n",
        encoding="utf-8",
    )
    after = analyze_repository(tmp_path, repository_id="diff", revision_id="after")
    delta = compare_graphs(before, after)
    before_nodes = before.node_map()
    after_nodes = after.node_map()

    rename = delta.renamed_nodes[0]
    assert before_nodes[rename.before_node_id].display_name == "old_name"
    assert after_nodes[rename.after_node_id].display_name == "new_name"
    assert rename.score >= 0.8
    assert "body_fingerprint" in rename.matched_signals
    assert {before_nodes[node_id].display_name for node_id in delta.removed_node_ids} == {"removed"}
    assert {after_nodes[node_id].display_name for node_id in delta.added_node_ids} == {"added"}
    keep = next(node for node in before.nodes if node.display_name == "keep")
    modification = next(change for change in delta.modified_nodes if change.node_id == keep.id)
    assert "content_hash" in modification.changed_fields


def test_diff_records_evidence_movement_without_replacing_stable_edges(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text(
        "def target():\n    return 1\n\ndef caller():\n    return target()\n",
        encoding="utf-8",
    )
    before = analyze_repository(tmp_path, repository_id="moves", revision_id="before")
    source.write_text(
        "# unrelated header\n\ndef target():\n    return 1\n\ndef caller():\n    return target()\n",
        encoding="utf-8",
    )
    after = analyze_repository(tmp_path, repository_id="moves", revision_id="after")
    delta = compare_graphs(before, after)

    assert delta.evidence_moves
    assert not delta.added_edge_ids
    assert not delta.removed_edge_ids
    before_symbols = {
        node.display_name: node.id for node in before.nodes if node.kind is NodeKind.FUNCTION
    }
    after_symbols = {
        node.display_name: node.id for node in after.nodes if node.kind is NodeKind.FUNCTION
    }
    assert before_symbols == after_symbols


def test_diff_warns_when_exact_test_coverage_relation_disappears(tmp_path: Path) -> None:
    (tmp_path / "prod.py").write_text("def work():\n    return 1\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    test_file = tests / "test_prod.py"
    test_file.write_text(
        "from prod import work\n\ndef test_work():\n    assert work() == 1\n",
        encoding="utf-8",
    )
    before = analyze_repository(tmp_path, repository_id="coverage", revision_id="before")
    test_file.write_text("def test_work():\n    assert 1 == 1\n", encoding="utf-8")
    after = analyze_repository(tmp_path, repository_id="coverage", revision_id="after")
    delta = compare_graphs(before, after)

    assert any("TESTS" in warning for warning in delta.structural_warnings)
    removed_predicates = {
        edge.predicate.value for edge in before.edges if edge.id in delta.removed_edge_ids
    }
    assert "TESTS" in removed_predicates


def test_diff_rejects_cross_repository_comparisons(tmp_path: Path) -> None:
    (tmp_path / "one.py").write_text("def one():\n    pass\n", encoding="utf-8")
    before = analyze_repository(tmp_path, repository_id="one", revision_id="before")
    after = analyze_repository(tmp_path, repository_id="two", revision_id="after")
    try:
        compare_graphs(before, after)
    except ValueError as error:
        assert "different repositories" in str(error)
    else:
        raise AssertionError("cross-repository diff must fail")


def test_diff_does_not_guess_between_ambiguous_rename_candidates(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text("def old():\n    pass\n", encoding="utf-8")
    before = analyze_repository(tmp_path, repository_id="ambiguous", revision_id="before")
    source.write_text(
        "def possible_one():\n    pass\n\ndef possible_two():\n    pass\n", encoding="utf-8"
    )
    after = analyze_repository(tmp_path, repository_id="ambiguous", revision_id="after")
    delta = compare_graphs(before, after)
    assert delta.renamed_nodes == ()
    assert (
        len(
            [
                node_id
                for node_id in delta.added_node_ids
                if after.node_map()[node_id].kind is NodeKind.FUNCTION
            ]
        )
        == 2
    )
