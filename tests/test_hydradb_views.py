from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from hydra_graph.config import HydraDBConfig
from hydra_graph.hydradb import HydraDBClient
from hydra_graph.query import QueryService
from hydra_graph.views import ViewDepth, ViewMode, ViewRequest, ViewService

FIXTURE = Path(__file__).parents[1] / "fixtures" / "hydradb" / "query_authorization.json"


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
    assert view["hydradb"]["origin"] == "byog"
    assert view["edges"][0]["quality"] == "exact"
    assert view["edges"][0]["attributes"]["hydradb_origin"] == "byog"
    assert len(transport.calls) == 1


def test_edge_explanation_uses_bounded_hydradb_view_result() -> None:
    views, transport = service()
    view = views.load(ViewRequest(mode=ViewMode.TRACE, question="authorization flow"))

    explanation = views.explain_relationship(view["view_id"], "hydra-rel-calls")

    assert explanation is not None
    assert explanation["predicate"] == "CALLS"
    assert explanation["hydradb_origin"] == "byog"
    assert explanation["evidence"][0]["path"] == "src/payments/auth.py"
    assert len(transport.calls) == 1


def test_repository_file_projection_retains_contributing_edge_evidence() -> None:
    views, _ = service()

    view = views.load(
        ViewRequest(mode=ViewMode.REPOSITORY, depth=ViewDepth.FILE, question="authorization flow")
    )

    aggregate = view["aggregates"][0]
    assert aggregate["exact_relation_count"] == 1
    assert aggregate["contributing_edge_ids"] == ["hydra-rel-calls"]
    assert aggregate["contributing_evidence_ids"]


def test_unavailable_view_is_empty_and_explicit() -> None:
    views, transport = service(api_key=None)

    view = views.load(ViewRequest(mode=ViewMode.REPOSITORY))

    assert view["hydradb"]["available"] is False
    assert view["hydradb"]["status"] == "unavailable"
    assert view["nodes"] == []
    assert view["edges"] == []
    assert transport.calls == []
