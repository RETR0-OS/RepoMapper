from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from hydra_graph.analyzer import PythonAnalyzer, analyze_repository
from hydra_graph.ids import content_hash, evidence_id
from hydra_graph.models import Evidence, NodeKind, RelationPredicate, RelationQuality

FIXTURE = Path(__file__).parents[1] / "fixtures" / "sample_repo"


def _relation_names(graph):
    nodes = graph.node_map()
    return {
        (nodes[edge.source_id].qualified_name, edge.predicate, nodes[edge.target_id].qualified_name)
        for edge in graph.edges
    }


def test_analyzer_emits_concrete_nodes_and_resolved_exact_relations() -> None:
    graph = analyze_repository(FIXTURE, repository_id="sample", revision_id="r1")
    names = {node.qualified_name for node in graph.nodes}
    relations = _relation_names(graph)

    assert "app.service.Greeter.greet" in names
    assert "tests.test_service.test_format_greeting" in names
    assert "ignored.ignored_function" not in names
    assert "generated.generated_function" not in names
    assert not graph.diagnostics
    assert (
        "app.service.Greeter.greet",
        RelationPredicate.CALLS,
        "app.helpers.normalize_name",
    ) in relations
    assert (
        "tests.test_service.test_format_greeting",
        RelationPredicate.TESTS,
        "app.service.format_greeting",
    ) in relations
    assert all(edge.quality is RelationQuality.EXACT for edge in graph.edges)
    assert all(edge.confidence is None for edge in graph.edges)
    assert all(edge.evidence for edge in graph.edges)


def test_analyzer_does_not_promote_unresolved_dynamic_calls() -> None:
    graph = analyze_repository(FIXTURE, repository_id="sample", revision_id="r1")
    relations = _relation_names(graph)
    # `greeter.greet()` needs data-flow resolution which this AST adapter does not
    # claim. Omitting it is more truthful than manufacturing an exact edge.
    assert (
        "app.api.handle_request",
        RelationPredicate.CALLS,
        "app.service.Greeter.greet",
    ) not in relations
    assert not any(edge.predicate is RelationPredicate.MAY_CALL for edge in graph.edges)


def test_declaration_and_call_evidence_points_to_real_source() -> None:
    graph = analyze_repository(FIXTURE, repository_id="sample", revision_id="r1")
    for edge in graph.edges:
        for evidence in edge.evidence:
            source_path = FIXTURE / evidence.path
            assert source_path.exists()
            if evidence.span is None:
                assert edge.predicate is RelationPredicate.CONTAINS
                continue
            lines = source_path.read_text(encoding="utf-8").splitlines()
            assert 1 <= evidence.start_line <= evidence.end_line <= len(lines)
            assert evidence.excerpt_hash != "0" * 64


def test_node_ids_survive_unrelated_line_movement(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text("def stable(value):\n    return value\n", encoding="utf-8")
    before = analyze_repository(tmp_path, repository_id="stable", revision_id="before")
    source.write_text(
        "# a new unrelated line\n\ndef stable(value):\n    return value\n", encoding="utf-8"
    )
    after = analyze_repository(tmp_path, repository_id="stable", revision_id="after")

    before_symbol = next(node for node in before.nodes if node.display_name == "stable")
    after_symbol = next(node for node in after.nodes if node.display_name == "stable")
    assert before_symbol.id == after_symbol.id
    assert before_symbol.logical_id == after_symbol.logical_id
    assert before_symbol.span != after_symbol.span


def test_node_ids_change_when_semantic_identity_changes(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text("def old_name():\n    return 1\n", encoding="utf-8")
    before = analyze_repository(tmp_path, repository_id="stable", revision_id="before")
    source.write_text("def new_name():\n    return 1\n", encoding="utf-8")
    after = analyze_repository(tmp_path, repository_id="stable", revision_id="after")
    old = next(node for node in before.nodes if node.kind is NodeKind.FUNCTION)
    new = next(node for node in after.nodes if node.kind is NodeKind.FUNCTION)
    assert old.id != new.id


def test_parser_errors_are_diagnostic_not_invented_symbols(tmp_path: Path) -> None:
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    graph = analyze_repository(tmp_path, repository_id="broken", revision_id="r1")
    assert any("syntax error" in diagnostic for diagnostic in graph.diagnostics)
    assert not any(node.kind is NodeKind.FUNCTION for node in graph.nodes)
    assert any(node.kind is NodeKind.FILE and node.path == "broken.py" for node in graph.nodes)


def test_nested_functions_are_not_mislabeled_as_methods(tmp_path: Path) -> None:
    (tmp_path / "nested.py").write_text(
        "class Example:\n"
        "    def method(self):\n"
        "        def inner():\n"
        "            return 1\n"
        "        return inner()\n",
        encoding="utf-8",
    )
    graph = analyze_repository(tmp_path, repository_id="kinds", revision_id="r1")
    kinds = {node.display_name: node.kind for node in graph.nodes}
    assert kinds["method"] is NodeKind.METHOD
    assert kinds["inner"] is NodeKind.FUNCTION


def test_test_methods_are_normalized_as_tests(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_example.py").write_text(
        "class TestExample:\n    def test_behavior(self):\n        assert True\n",
        encoding="utf-8",
    )
    graph = analyze_repository(tmp_path, repository_id="tests", revision_id="r1")
    test_method = next(node for node in graph.nodes if node.display_name == "test_behavior")
    assert test_method.kind is NodeKind.TEST


def test_function_local_import_is_not_misapplied_to_other_scopes(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text("def work():\n    return 1\n", encoding="utf-8")
    (tmp_path / "caller.py").write_text(
        "def importing_scope():\n"
        "    from target import work\n"
        "    return work()\n\n"
        "def unrelated_scope():\n"
        "    return work()\n",
        encoding="utf-8",
    )
    graph = analyze_repository(tmp_path, repository_id="scope", revision_id="r1")
    relations = _relation_names(graph)
    assert (
        "caller.unrelated_scope",
        RelationPredicate.CALLS,
        "target.work",
    ) not in relations
    assert (
        "caller.importing_scope",
        RelationPredicate.CALLS,
        "target.work",
    ) not in relations


def test_relative_submodule_import_targets_the_declared_module(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "service.py").write_text("def work():\n    return 1\n", encoding="utf-8")
    (package / "api.py").write_text(
        "from . import service\n\ndef call():\n    return service.work()\n", encoding="utf-8"
    )
    graph = analyze_repository(tmp_path, repository_id="relative", revision_id="r1")
    relations = _relation_names(graph)
    assert ("pkg.api", RelationPredicate.IMPORTS, "pkg.service") in relations
    assert ("pkg.api.call", RelationPredicate.CALLS, "pkg.service.work") in relations


def test_collect_edge_drops_a_self_relation(tmp_path: Path) -> None:
    """A self-relation must never reach GraphEdge.

    GraphEdge rejects one, and the analyzer builds every edge in a single pass, so
    one self-relation would fail the whole revision with a 500 during indexing.
    """

    source = tmp_path / "module.py"
    source.write_text("def work():\n    return 1\n", encoding="utf-8")
    graph = analyze_repository(tmp_path, repository_id="selfedge", revision_id="r1")
    node = next(item for item in graph.nodes if item.display_name == "work")
    evidence = Evidence(
        id=evidence_id(
            path="module.py",
            start_line=1,
            start_column=0,
            end_line=2,
            end_column=12,
            excerpt_hash=content_hash("def work():"),
        ),
        path="module.py",
        start_line=1,
        start_column=0,
        end_line=2,
        end_column=12,
        excerpt_hash=content_hash("def work():"),
        explanation="module.py:1 calls work",
    )
    analyzer = PythonAnalyzer("selfedge", "r1")
    edges: defaultdict[tuple, list[Evidence]] = defaultdict(list)

    analyzer._collect_edge(edges, node, RelationPredicate.CALLS, node, node.id, evidence)

    assert not edges
    assert analyzer._materialize_edges(edges) == []
