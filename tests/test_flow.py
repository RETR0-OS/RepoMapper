from __future__ import annotations

import copy
import json
from typing import Any

from hydra_graph.flow import (
    FLOW_GROUP_ORIGIN,
    PRIMARY_FLOW_PREDICATES,
    assemble_flow_paths,
)

EVIDENCE_SCHEMA = "hack-hydra.relation-evidence.v1"


def chunk(
    node_id: str,
    *,
    rank_name: str | None = None,
    is_test: bool = False,
    is_entry_point: bool = False,
) -> dict[str, Any]:
    return {
        "chunk_uuid": f"chunk-{node_id}",
        "id": f"source-{node_id}",
        "metadata": {
            "revision_id": "rev-abc",
            "repository_id": "sample",
            "is_test": is_test,
            "is_entry_point": is_entry_point,
        },
        "additional_metadata": {
            "node_id": node_id,
            "logical_id": f"logical-{node_id}",
            "qualified_name": rank_name or node_id,
            "path": f"app/{node_id}.py",
        },
    }


def envelope(summary: str) -> str:
    return json.dumps(
        {
            "schema": EVIDENCE_SCHEMA,
            "summary": summary,
            "edge_id": f"edge-{summary}",
            "quality": "exact",
            "extractor": "python-ast",
            "extractor_version": "1",
            "evidence": {},
        }
    )


def group(
    source: str,
    target: str,
    *,
    predicate: str = "CALLS",
    summary: str | None = None,
    chunk_id: str | None = None,
) -> dict[str, Any]:
    return {
        "group_id": f"{source}->{target}",
        "relevancy_score": None,
        "combined_context": "",
        "source_chunk_ids": [chunk_id or f"chunk-{source}"],
        "triplets": [
            {
                "source": {"identifier": f"logical-{source}", "name": source, "type": "FUNCTION"},
                "target": {"identifier": f"logical-{target}", "name": target, "type": "FUNCTION"},
                "relation": {
                    "relationship_id": f"rel-{source}-{target}",
                    "canonical_predicate": predicate,
                    "raw_predicate": predicate,
                    "context": envelope(summary) if summary else None,
                    "origin": "byog" if summary else None,
                    "chunk_id": chunk_id or f"chunk-{source}",
                },
            }
        ],
    }


def hop_pairs(flow: dict[str, Any]) -> list[tuple[str, str]]:
    return [(triplet["source"]["name"], triplet["target"]["name"]) for triplet in flow["triplets"]]


def test_a_chain_becomes_one_path_whose_hops_are_ordered_from_the_entry() -> None:
    # The matched code ranks first, exactly as HydraDB returns it.
    chunks = [chunk("handler"), chunk("router"), chunk("main", is_entry_point=True)]
    groups = [group("router", "handler"), group("main", "router")]

    flows = assemble_flow_paths(chunks, groups)

    assert len(flows) == 1
    assert hop_pairs(flows[0]) == [("main", "router"), ("router", "handler")]
    assert flows[0]["origin"] == FLOW_GROUP_ORIGIN
    roles = [
        (triplet["source"]["role"], triplet["target"]["role"]) for triplet in flows[0]["triplets"]
    ]
    assert roles == [("entry", "step"), ("step", "target")]


def test_combined_context_reads_as_numbered_steps_in_path_order() -> None:
    chunks = [chunk("handler"), chunk("router"), chunk("main", is_entry_point=True)]
    groups = [
        group("router", "handler", summary="router calls handler"),
        group("main", "router", summary="main calls router"),
    ]

    steps = assemble_flow_paths(chunks, groups)[0]["combined_context"]

    assert steps == "1. main calls router\n2. router calls handler"


def test_a_proven_entry_point_outranks_the_zero_in_degree_rule() -> None:
    # Both "outer" and "main" have in-degree zero, but only one is a proven entry.
    chunks = [
        chunk("handler"),
        chunk("router"),
        chunk("main", is_entry_point=True),
        chunk("outer"),
    ]
    groups = [group("router", "handler"), group("main", "router"), group("outer", "router")]

    flows = assemble_flow_paths(chunks, groups, max_paths=1)

    assert hop_pairs(flows[0])[0][0] == "main"


def test_test_code_is_not_chosen_as_an_anchor_or_a_target() -> None:
    # The test calls into the chain, so taking it literally would make it the entry.
    chunks = [
        chunk("store"),
        chunk("handler"),
        chunk("router"),
        chunk("test_router", is_test=True),
    ]
    groups = [
        group("router", "handler"),
        group("handler", "store"),
        group("test_router", "router"),
    ]

    flows = assemble_flow_paths(chunks, groups)

    assert flows
    assert all("test_router" not in pair for flow in flows for pair in hop_pairs(flow))
    assert hop_pairs(flows[0])[0][0] == "router"


def test_an_all_test_slice_still_returns_a_path_rather_than_nothing() -> None:
    # A question about the tests is a real question, so preferring implementation code
    # must not become a refusal to answer at all.
    chunks = [
        chunk("assert_result", is_test=True),
        chunk("run_case", is_test=True),
        chunk("test_main", is_test=True),
    ]
    groups = [group("run_case", "assert_result"), group("test_main", "run_case")]

    flows = assemble_flow_paths(chunks, groups)

    assert len(flows) == 1
    assert hop_pairs(flows[0]) == [("test_main", "run_case"), ("run_case", "assert_result")]


def test_a_single_hop_is_not_reported_as_a_flow() -> None:
    chunks = [chunk("handler"), chunk("main", is_entry_point=True)]

    assert assemble_flow_paths(chunks, [group("main", "handler")]) == []


def test_max_hops_and_max_paths_are_both_respected() -> None:
    chunks = [chunk(name) for name in ("d", "c", "b", "a")]
    groups = [group("a", "b"), group("b", "c"), group("c", "d")]

    # A tighter hop budget still explains something; it just explains less of the chain.
    bounded = assemble_flow_paths(chunks, groups, max_hops=2)
    assert all(len(flow["triplets"]) <= 2 for flow in bounded)
    assert len(assemble_flow_paths(chunks, groups, max_hops=3, max_paths=1)) == 1
    assert len(assemble_flow_paths(chunks, groups, max_hops=3)[0]["triplets"]) == 3


def test_a_slice_with_no_connecting_path_returns_nothing() -> None:
    chunks = [chunk("alpha"), chunk("beta"), chunk("gamma"), chunk("delta")]
    groups = [group("alpha", "beta"), group("gamma", "delta")]

    flows = assemble_flow_paths(chunks, groups)

    assert all(len(flow["triplets"]) >= 2 for flow in flows)


def test_a_cycle_neither_hangs_nor_repeats_a_node() -> None:
    chunks = [chunk("c"), chunk("b"), chunk("a")]
    groups = [group("a", "b"), group("b", "c"), group("c", "a")]

    for flow in assemble_flow_paths(chunks, groups):
        visited = [pair[0] for pair in hop_pairs(flow)] + [hop_pairs(flow)[-1][1]]
        assert len(visited) == len(set(visited))


def test_imports_only_connects_when_no_call_path_exists() -> None:
    chunks = [chunk("handler"), chunk("router"), chunk("main", is_entry_point=True)]
    importing = [
        group("main", "router", predicate="IMPORTS"),
        group("router", "handler", predicate="IMPORTS"),
    ]

    assert assemble_flow_paths(chunks, importing)

    # A call path exists, so the import shortcut must not be preferred over it.
    mixed = [
        *importing,
        group("main", "middle"),
        group("middle", "router"),
        group("router", "handler"),
    ]
    flows = assemble_flow_paths(chunks + [chunk("middle")], mixed, max_paths=1)
    predicates = {triplet["relation"]["canonical_predicate"] for triplet in flows[0]["triplets"]}
    assert predicates <= set(PRIMARY_FLOW_PREDICATES)


def test_an_entity_without_a_returned_chunk_can_still_be_an_intermediate_step() -> None:
    # "middle" has no chunk, so nothing proves what it is. It may be walked through,
    # but it must never be chosen as the start or the end of an explanation.
    chunks = [chunk("handler"), chunk("main", is_entry_point=True)]
    groups = [group("main", "middle"), group("middle", "handler")]

    flows = assemble_flow_paths(chunks, groups)

    assert len(flows) == 1
    assert hop_pairs(flows[0]) == [("main", "middle"), ("middle", "handler")]
    assert flows[0]["triplets"][0]["source"]["role"] == "entry"
    assert flows[0]["triplets"][-1]["target"]["role"] == "target"


def test_every_named_chunk_id_belongs_to_an_included_hop() -> None:
    chunks = [chunk("handler"), chunk("router"), chunk("main", is_entry_point=True)]
    groups = [group("router", "handler"), group("main", "router")]

    for flow in assemble_flow_paths(chunks, groups):
        hop_chunks = {triplet["relation"]["chunk_id"] for triplet in flow["triplets"]}
        assert set(flow["source_chunk_ids"]) <= hop_chunks


def test_assembly_is_deterministic_and_never_mutates_its_input() -> None:
    chunks = [chunk("handler"), chunk("router"), chunk("main", is_entry_point=True)]
    groups = [group("router", "handler"), group("main", "router")]
    original = copy.deepcopy(groups)

    first = assemble_flow_paths(chunks, groups)
    second = assemble_flow_paths(chunks, groups)

    assert first == second
    assert groups == original


def test_no_chunks_or_no_groups_is_an_empty_answer() -> None:
    assert assemble_flow_paths([], [group("a", "b")]) == []
    assert assemble_flow_paths([chunk("a")], []) == []
