from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from hydra_graph.analyzer import analyze_repository
from hydra_graph.models import Evidence, GraphIR
from jsonschema import Draft202012Validator
from pydantic import ValidationError

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "fixtures" / "sample_repo"
QUERY_FIXTURE = ROOT / "fixtures" / "hydradb" / "product_query_authorization.json"


def graph_payload() -> dict[str, Any]:
    graph = analyze_repository(FIXTURE, repository_id="sample", revision_id="r1")
    return graph.model_dump(mode="json")


def graph_validator() -> Draft202012Validator:
    schema = json.loads((ROOT / "schemas" / "graph-ir.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def query_validator() -> Draft202012Validator:
    schema = json.loads(
        (ROOT / "schemas" / "query-response.schema.json").read_text(encoding="utf-8")
    )
    return Draft202012Validator(schema)


def _set(payload: dict[str, Any], path: tuple[str | int, ...], value: Any) -> None:
    target: Any = payload
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value


def test_python_graph_ir_serialization_matches_shared_schema() -> None:
    graph_validator().validate(graph_payload())


def test_schema_rejects_values_forbidden_by_graph_models() -> None:
    valid = graph_payload()
    line_node_index = next(
        index for index, node in enumerate(valid["nodes"]) if node["kind"] == "FUNCTION"
    )
    edge_index = next(index for index, edge in enumerate(valid["edges"]) if edge["evidence"])
    mutations = {
        "unknown node kind": (("nodes", line_node_index, "kind"), "CONCEPT"),
        "invalid node hash": (("nodes", line_node_index, "content_hash"), "A" * 64),
        "missing line-addressable span": (("nodes", line_node_index, "span"), None),
        "ungrounded line-addressable path": (("nodes", line_node_index, "path"), "."),
        "absolute node path": (("nodes", line_node_index, "path"), "/tmp/example.py"),
        "unknown predicate": (("edges", edge_index, "predicate"), "LOOKS_LIKE"),
        "decorative exact confidence": (("edges", edge_index, "confidence"), 1.0),
        "missing exact evidence": (("edges", edge_index, "evidence"), []),
        "inferred without confidence": (("edges", edge_index, "quality"), "inferred"),
        "semantic without confidence": (("edges", edge_index, "quality"), "semantic"),
        "invalid evidence hash": (
            ("edges", edge_index, "evidence", 0, "excerpt_hash"),
            "not-a-sha256",
        ),
        "parent evidence path": (
            ("edges", edge_index, "evidence", 0, "path"),
            "../outside.py",
        ),
        "partial evidence range": (
            ("edges", edge_index, "evidence", 0, "end_column"),
            None,
        ),
    }
    validator = graph_validator()

    for label, (path, value) in mutations.items():
        candidate = deepcopy(valid)
        _set(candidate, path, value)
        assert list(validator.iter_errors(candidate)), label

    duplicate = deepcopy(valid)
    duplicate["nodes"].append(deepcopy(duplicate["nodes"][0]))
    assert list(validator.iter_errors(duplicate))


@pytest.mark.parametrize("remove_range", [False, True])
def test_schema_accepts_complete_or_absent_evidence_range(remove_range: bool) -> None:
    payload = graph_payload()
    evidence = payload["edges"][0]["evidence"][0]
    range_fields = ("start_line", "start_column", "end_line", "end_column")
    for field in range_fields:
        if remove_range:
            evidence.pop(field)
        else:
            evidence[field] = None

    graph_validator().validate(payload)


def test_cross_record_and_range_order_rules_remain_pydantic_enforced() -> None:
    # Draft 2020-12 cannot compare two numeric fields or require an edge ID to
    # occur in a separate node array. Keep these cross-field rules at the
    # Pydantic boundary and prove they cannot silently disappear.
    payload = graph_payload()
    reversed_range = deepcopy(payload["edges"][0]["evidence"][0])
    reversed_range.update(
        start_line=10,
        start_column=0,
        end_line=9,
        end_column=0,
    )
    with pytest.raises(ValidationError, match="ends before it starts"):
        Evidence.model_validate(reversed_range)

    dangling = deepcopy(payload)
    dangling["edges"][0]["target_id"] = "node_missing"
    with pytest.raises(ValidationError, match="references a missing node"):
        GraphIR.model_validate(dangling)


def test_golden_query_response_matches_versioned_shared_schema() -> None:
    query_validator().validate(json.loads(QUERY_FIXTURE.read_text(encoding="utf-8")))


def test_query_schema_accepts_honest_empty_degraded_and_unavailable_results() -> None:
    ready = json.loads(QUERY_FIXTURE.read_text(encoding="utf-8"))
    validator = query_validator()
    for status, available in (("degraded", True), ("unavailable", False)):
        candidate = deepcopy(ready)
        candidate["status"] = status
        candidate["hydradb"].update(
            available=available,
            origin=None,
            path_ids=[],
            request_id=None,
        )
        candidate["paths"] = []
        candidate["relations"] = []
        candidate["chunk_id_to_group_ids"] = {}
        candidate["chunks"] = []
        candidate["sources"] = []
        candidate["additional_context"] = []
        candidate["warnings"] = [f"Explicit {status} result."]
        candidate["budget"].update(
            returned_context_chars=0,
            returned_paths=0,
            returned_relations=0,
            truncated=status == "degraded",
        )
        validator.validate(candidate)


def test_query_schema_rejects_raw_or_misrepresented_product_results() -> None:
    valid = json.loads(QUERY_FIXTURE.read_text(encoding="utf-8"))
    validator = query_validator()
    mutations = {
        "wrong schema version": (("response_schema",), "hydradb-sdk-v2"),
        "unknown status": (("status",), "complete"),
        "ready marked unavailable": (("hydradb", "available"), False),
        "partial source span": (("chunks", 0, "span", "end_column"), None),
        "invalid content hash": (("chunks", 0, "content_hash"), "not-a-hash"),
        "invalid relation confidence": (
            ("paths", 0, "hops", 0, "relation", "confidence"),
            "high",
        ),
        "incomplete budget": (("budget", "max_context_chars"), None),
        "database disclosure": (("hydradb", "database"), "secret-database"),
    }
    for label, (path, value) in mutations.items():
        candidate = deepcopy(valid)
        if label == "incomplete budget":
            candidate["budget"].pop("max_context_chars")
        else:
            _set(candidate, path, value)
        assert list(validator.iter_errors(candidate)), label

    raw_leak = deepcopy(valid)
    raw_leak["data"] = {"chunks": []}
    assert list(validator.iter_errors(raw_leak))

    unavailable_with_local_content = deepcopy(valid)
    unavailable_with_local_content["status"] = "unavailable"
    unavailable_with_local_content["hydradb"]["available"] = False
    unavailable_with_local_content["warnings"] = ["HydraDB unavailable."]
    assert list(validator.iter_errors(unavailable_with_local_content))


def test_query_schema_allows_only_named_evolution_envelope_extensions() -> None:
    candidate = json.loads(QUERY_FIXTURE.read_text(encoding="utf-8"))
    lens = {
        "record_schema": "hack-hydra.system-lens.v1",
        "lens_id": "lens_123",
        "repository_id": "hack-hydra",
        "name": "Authorization",
        "purpose": "Keep the exact authorization path visible.",
        "saved_revision_id": "rev-abc",
        "ownership": "shared",
        "source_view_id": "view-saved",
        "entities": [{"node_id": "one"}, {"node_id": "two"}],
        "anchor_node_ids": ["one", "two"],
        "baseline_hops": [{"edge_id": "edge-one-two"}],
        "notes": None,
    }
    candidate["records"] = [lens]
    candidate["evolution_chunks"] = []
    candidate["evolution_hydradb"] = {
        **candidate["hydradb"],
        "collections": ["evolution"],
        "cross_collection_traversal": False,
        "memory_used": False,
    }
    candidate["lens"] = lens
    candidate["drift"] = {"kind": "unresolved", "explanation": "No current path."}
    query_validator().validate(candidate)

    candidate["unversioned_extension"] = []
    assert list(query_validator().iter_errors(candidate))

    candidate.pop("unversioned_extension")
    candidate["records"][0].pop("record_schema")
    assert list(query_validator().iter_errors(candidate))
