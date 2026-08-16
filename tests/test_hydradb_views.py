from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from hydra_graph.config import HydraDBConfig
from hydra_graph.hydradb import HydraDBClient
from hydra_graph.query import QueryService
from hydra_graph.views import ViewDepth, ViewMode, ViewRequest, ViewService
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

FIXTURE = Path(__file__).parents[1] / "fixtures" / "hydradb" / "query_authorization.json"


def validate_view(view: dict[str, Any]) -> None:
    schema_root = Path(__file__).parents[1] / "schemas"
    product_schema = json.loads(
        (schema_root / "product-view.schema.json").read_text(encoding="utf-8")
    )
    graph_schema = json.loads((schema_root / "graph-ir.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resource(graph_schema["$id"], Resource.from_contents(graph_schema))
    Draft202012Validator(product_schema, registry=registry).validate(view)


class Transport:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.response


def assert_one_query_then_relation_reads(transport: Transport) -> None:
    """Queries decide relevance; every other read is the stored graph.

    The graph no longer comes from the query's own ranked relations, so the old
    "exactly one call" rule would now hide a real regression instead of catching one.
    Retrieval is one query for implementation code and one for the test tail.
    """

    assert transport.calls[0]["method"] == "POST"
    assert transport.calls[0]["url"].endswith("/query")
    for call in transport.calls:
        if call["method"] == "POST":
            assert call["url"].endswith("/query")
        else:
            assert call["method"] == "GET"
            assert call["url"].endswith("/context/relations")


def service(*, api_key: str | None = "test") -> tuple[ViewService, Transport]:
    transport = Transport(json.loads(FIXTURE.read_text(encoding="utf-8")))
    client = HydraDBClient(
        HydraDBConfig(api_key=api_key, database="repo_hack_hydra", max_retries=0),
        transport=transport,
    )
    return ViewService(QueryService(client, repository_id="hack-hydra")), transport


def test_stored_graph_grounds_a_view_when_the_query_returns_only_concepts() -> None:
    """The query ranks HydraDB's concept relations above this repository's own.

    A question written in prose fills every returned relation slot with concepts,
    and no concept can be grounded in a source card. The graph must therefore come
    from the stored relations of the sources the query returned, not from the
    query's own ranked list.
    """

    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    stored_relation = raw["data"]["graph_context"]["query_paths"][0]["triplets"][0]["relation"]
    # Exactly what the live database returns for a prose question: HydraDB's own
    # ontology, with opaque ids that can never match a repository node.
    for group_name in ("query_paths", "chunk_relations"):
        for group in raw["data"]["graph_context"][group_name]:
            for triplet in group["triplets"]:
                triplet["source"] = {"identifier": "137a3dc0b1f35af1e158", "type": "CONCEPT"}
                triplet["target"] = {"identifier": "9861487a5e6de80d0c04", "type": "PRODUCT"}

    stored = {
        "data": {
            "relations": [
                {
                    "chunk_id": "chunk-authorize",
                    "source": {"identifier": "payments.auth.authorize_user"},
                    "target": {"identifier": "payments.store.TokenStore.resolve"},
                    "relations": [dict(stored_relation)],
                }
            ]
        }
    }

    class SplitTransport(Transport):
        def request(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(kwargs)
            return stored if kwargs["url"].endswith("/context/relations") else self.response

    transport = SplitTransport(raw)
    client = HydraDBClient(
        HydraDBConfig(api_key="test", database="repo_hack_hydra", max_retries=0),
        transport=transport,
    )
    views = ViewService(QueryService(client, repository_id="hack-hydra"))

    view = views.load(ViewRequest(mode=ViewMode.TRACE, question="how does authorization work?"))

    assert view["diagnostics"]["outcome"] == "ok"
    assert [node["id"] for node in view["nodes"]] == ["node-authorize", "node-store"]
    edge = view["edges"][0]
    assert edge["quality"] == "exact"
    assert edge["attributes"]["hydradb_origin"] == "byog"
    assert edge["evidence"][0]["path"] == "src/payments/auth.py"
    # Three sources came back, so three stored-graph reads were made. This stub
    # answers each of them with the same pair, and the duplicate is folded into one edge.
    assert view["diagnostics"]["funnel"]["relation_sources"] == 3
    assert view["diagnostics"]["funnel"]["relation_pairs"] == 3
    assert len(view["edges"]) == 1
    validate_view(view)


def test_node_labels_come_from_the_card_not_from_the_hydradb_entity_name() -> None:
    """Every node once read "py", which tells the user nothing.

    HydraDB may return any name for an entity. A name that ends in a file
    extension reduces to that extension alone. The card this repository wrote is
    the record that decides the label.
    """

    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for group_name in ("query_paths", "chunk_relations"):
        for group in raw["data"]["graph_context"][group_name]:
            for triplet in group["triplets"]:
                for end in ("source", "target"):
                    triplet[end]["name"] = "tests/test_write_tools.py"
    transport = Transport(raw)
    client = HydraDBClient(
        HydraDBConfig(api_key="test", database="repo_hack_hydra", max_retries=0),
        transport=transport,
    )
    views = ViewService(QueryService(client, repository_id="hack-hydra"))

    view = views.load(ViewRequest(mode=ViewMode.TRACE, question="authorization flow"))

    labels = [node["display_name"] for node in view["nodes"]]
    assert labels == ["authorize_user", "resolve"]
    assert "py" not in labels
    # The full name stays available for the inspector and for accessibility.
    assert view["nodes"][0]["qualified_name"] == "payments.auth.authorize_user"


def test_view_reports_when_proven_hops_lose_their_node_grounding() -> None:
    """A node needs a source card with a path, a hash, a parser, and a span.

    HydraDB can prove a relation while the card that anchors its entities is
    missing. The view is then empty for a reason the user cannot guess, so the
    stage that dropped the hop has to be named.
    """

    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for chunk in raw["data"]["chunks"]:
        chunk["additional_metadata"].pop("node_id", None)
    for source in raw["data"]["sources"]:
        source.get("additional_metadata", {}).pop("node_id", None)
    transport = Transport(raw)
    client = HydraDBClient(
        HydraDBConfig(api_key="test", database="repo_hack_hydra", max_retries=0),
        transport=transport,
    )
    views = ViewService(QueryService(client, repository_id="hack-hydra"))

    view = views.load(ViewRequest(mode=ViewMode.TRACE, question="authorization flow"))

    assert view["nodes"] == []
    assert view["diagnostics"]["outcome"] == "hops_not_grounded"
    assert view["diagnostics"]["funnel"]["dropped_hops"] > 0
    # The query stage still succeeded, so its own counts stay visible beside it.
    assert view["diagnostics"]["funnel"]["hops"] > 0
    validate_view(view)


@pytest.mark.parametrize("mode", list(ViewMode))
def test_all_modes_are_hydradb_backed_and_follow_view_contract(mode: ViewMode) -> None:
    views, transport = service()

    view = views.load(ViewRequest(mode=mode, question="authorization flow"))

    assert view["mode"] == mode.value
    assert set(view) == {
        "view_id",
        "view_schema",
        "revision_id",
        "mode",
        "depth",
        "nodes",
        "edges",
        "aggregates",
        "hydradb",
        "warnings",
        "budget",
        "diagnostics",
    }
    assert view["view_schema"] == "hack-hydra.product-view.v2"
    assert view["hydradb"]["available"] is True
    if mode in {ViewMode.COMPARE, ViewMode.PRESERVE}:
        assert view["hydradb"]["status"] == "degraded"
        assert view["edges"] == []
        assert "no generic repository chunks" in view["warnings"][0]
    else:
        assert view["hydradb"]["origin"] == "byog"
        assert view["edges"][0]["quality"] == "exact"
        assert view["edges"][0]["attributes"]["hydradb_origin"] == "byog"
    assert_one_query_then_relation_reads(transport)


def test_edge_explanation_uses_bounded_hydradb_view_result() -> None:
    views, transport = service()
    view = views.load(ViewRequest(mode=ViewMode.TRACE, question="authorization flow"))

    explanation = views.explain_relationship(view["view_id"], "edge-calls")

    assert explanation is not None
    assert explanation["predicate"] == "CALLS"
    assert explanation["hydradb_origin"] == "byog"
    assert explanation["evidence"][0]["path"] == "src/payments/auth.py"
    assert explanation["evidence"][0]["start_line"] == 14
    assert explanation["evidence"][0]["id"] == "evidence-calls"
    assert_one_query_then_relation_reads(transport)


def test_repository_file_projection_retains_contributing_edge_evidence() -> None:
    views, _ = service()

    view = views.load(
        ViewRequest(mode=ViewMode.REPOSITORY, depth=ViewDepth.FILE, question="authorization flow")
    )

    aggregate = view["aggregates"][0]
    assert aggregate["exact_relation_count"] == 1
    assert aggregate["contributing_edge_ids"] == ["edge-calls"]
    assert aggregate["contributing_evidence_ids"]


def test_unavailable_view_is_empty_and_explicit() -> None:
    views, transport = service(api_key=None)

    view = views.load(ViewRequest(mode=ViewMode.REPOSITORY))

    assert view["hydradb"]["available"] is False
    assert view["hydradb"]["status"] == "unavailable"
    assert view["nodes"] == []
    assert view["edges"] == []
    assert transport.calls == []


def test_hydradb_view_matches_shared_product_schema() -> None:
    views, _ = service()
    view = views.load(ViewRequest(mode=ViewMode.TRACE, question="authorization flow"))

    validate_view(view)


def test_non_byog_relation_cannot_be_upgraded_by_source_card_metadata() -> None:
    views, transport = service()
    relation = transport.response["data"]["graph_context"]["query_paths"][0]["triplets"][0][
        "relation"
    ]
    relation["origin"] = "extracted"
    relation["context"] = "An extracted relation with no parser evidence."

    view = views.load(ViewRequest(mode=ViewMode.TRACE, question="authorization flow"))

    edge = view["edges"][0]
    assert edge["quality"] == "unknown"
    assert edge["evidence"] == []
    validate_view(view)


def test_missing_origin_without_verified_byog_ownership_is_not_exact() -> None:
    views, transport = service()
    graph = transport.response["data"]["graph_context"]
    for group_name in ("query_paths", "chunk_relations"):
        for group in graph[group_name]:
            for triplet in group["triplets"]:
                triplet["relation"].pop("origin")

    view = views.load(ViewRequest(mode=ViewMode.TRACE, question="authorization flow"))

    assert view["edges"][0]["quality"] == "unknown"
    assert view["edges"][0]["evidence"] == []
    validate_view(view)


def test_malformed_byog_evidence_is_never_presented_as_exact() -> None:
    views, transport = service()
    relation = transport.response["data"]["graph_context"]["query_paths"][0]["triplets"][0][
        "relation"
    ]
    relation["context"] = '{"schema":"hack-hydra.relation-evidence.v1","quality":"exact"}'

    view = views.load(ViewRequest(mode=ViewMode.TRACE, question="authorization flow"))

    assert view["edges"][0]["quality"] == "unknown"
    assert view["edges"][0]["evidence"] == []
    validate_view(view)


def test_real_card_logical_identifiers_resolve_to_compact_graph_node_ids() -> None:
    views, transport = service()
    graph = transport.response["data"]["graph_context"]
    identifiers = (
        "payments.auth.authorize_user",
        "payments.store.TokenStore.resolve",
    )
    for group_name in ("query_paths", "chunk_relations"):
        triplet = graph[group_name][0]["triplets"][0]
        triplet["source"]["identifier"] = identifiers[0]
        triplet["target"]["identifier"] = identifiers[1]

    view = views.load(ViewRequest(mode=ViewMode.TRACE, question="authorization flow"))

    assert [node["id"] for node in view["nodes"]] == ["node-authorize", "node-store"]
    assert view["edges"][0]["source_id"] == "node-authorize"
    assert view["edges"][0]["target_id"] == "node-store"


def test_context_text_budget_does_not_remove_graph_grounding_metadata() -> None:
    views, transport = service()
    transport.response["data"]["chunks"][0]["chunk_content"] = "x" * 8_000

    view = views.load(ViewRequest(mode=ViewMode.TRACE, question="authorization flow"))

    assert [node["id"] for node in view["nodes"]] == ["node-authorize", "node-store"]
    assert view["edges"][0]["id"] == "edge-calls"
    assert view["edges"][0]["quality"] == "exact"
    assert any("character budget truncated" in warning for warning in view["warnings"])


def test_ungrounded_relation_target_is_omitted_instead_of_fabricated() -> None:
    views, transport = service()
    data = transport.response["data"]
    data["chunks"] = [data["chunks"][0]]
    data["graph_context"]["query_paths"] = []

    view = views.load(ViewRequest(mode=ViewMode.TRACE, question="authorization flow"))

    assert view["nodes"] == []
    assert view["edges"] == []
    assert "Omitted 1 HydraDB hop" in view["warnings"][0]


def test_invalid_predicate_or_evidence_is_omitted_or_downgraded() -> None:
    views, transport = service()
    relation = transport.response["data"]["graph_context"]["query_paths"][0]["triplets"][0][
        "relation"
    ]
    envelope = json.loads(relation["context"])
    envelope["evidence"]["excerpt_hash"] = "not-a-hash"
    relation["context"] = json.dumps(envelope)

    downgraded = views.load(ViewRequest(mode=ViewMode.TRACE, question="authorization flow"))

    assert downgraded["edges"][0]["quality"] == "unknown"
    assert downgraded["edges"][0]["evidence"] == []
    validate_view(downgraded)

    for group_name in ("query_paths", "chunk_relations"):
        invalid_relation = transport.response["data"]["graph_context"][group_name][0]["triplets"][
            0
        ]["relation"]
        invalid_relation["canonical_predicate"] = "RELATED_TO"
        invalid_relation["raw_predicate"] = "RELATED_TO"
    omitted = views.load(ViewRequest(mode=ViewMode.TRACE, question="authorization flow"))
    assert omitted["edges"] == []
    assert any("Omitted" in warning for warning in omitted["warnings"])


def test_each_mode_carries_its_intent_as_filters_instead_of_instruction_prose() -> None:
    """A mode's intent must never become search text.

    "Return the concrete repository structure" is matched against card content, so it
    retrieves whatever code discusses structure rather than the structure itself.
    """

    from hydra_graph.views import retrieval_plan

    repository = retrieval_plan(ViewMode.REPOSITORY, ViewDepth.FILE, None)
    assert repository.entity_kinds == ("PACKAGE", "FILE")
    assert "Return" not in repository.question

    symbols = retrieval_plan(ViewMode.REPOSITORY, ViewDepth.SYMBOL, None)
    assert "FUNCTION" in symbols.entity_kinds

    explore = retrieval_plan(ViewMode.EXPLORE, ViewDepth.SYMBOL, "Greeter.greet")
    assert explore.question == "Greeter.greet"
    assert explore.query_by == "text"

    trace = retrieval_plan(ViewMode.TRACE, ViewDepth.SYMBOL, "how does indexing work?")
    assert trace.question == "how does indexing work?"
    assert trace.query_by == "hybrid"

    for mode, kind in ((ViewMode.COMPARE, "CHANGE_EVENT"), (ViewMode.PRESERVE, "SYSTEM_LENS")):
        plan = retrieval_plan(mode, ViewDepth.SYMBOL, None)
        assert plan.entity_kinds == (kind,)
        assert plan.tests == "mixed"
