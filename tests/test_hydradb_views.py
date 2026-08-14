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


def service(*, api_key: str | None = "test") -> tuple[ViewService, Transport]:
    transport = Transport(json.loads(FIXTURE.read_text(encoding="utf-8")))
    client = HydraDBClient(
        HydraDBConfig(api_key=api_key, database="repo_hack_hydra", max_retries=0),
        transport=transport,
    )
    return ViewService(QueryService(client, repository_id="hack-hydra")), transport


@pytest.mark.parametrize("mode", list(ViewMode))
def test_all_modes_are_hydradb_backed_and_follow_view_contract(mode: ViewMode) -> None:
    views, transport = service()

    view = views.load(ViewRequest(mode=mode, question="authorization flow"))

    assert view["mode"] == mode.value
    assert set(view) == {
        "view_id",
        "revision_id",
        "mode",
        "depth",
        "nodes",
        "edges",
        "aggregates",
        "hydradb",
        "warnings",
        "budget",
    }
    assert view["hydradb"]["available"] is True
    if mode in {ViewMode.COMPARE, ViewMode.PRESERVE}:
        assert view["hydradb"]["status"] == "degraded"
        assert view["edges"] == []
        assert "no generic repository chunks" in view["warnings"][0]
    else:
        assert view["hydradb"]["origin"] == "byog"
        assert view["edges"][0]["quality"] == "exact"
        assert view["edges"][0]["attributes"]["hydradb_origin"] == "byog"
    assert len(transport.calls) == 1


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
    assert len(transport.calls) == 1


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
