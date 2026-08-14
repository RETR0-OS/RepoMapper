from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hydra_graph.config import HydraDBConfig
from hydra_graph.events import EventBus
from hydra_graph.hydradb import HydraDBClient, HydraDBUnavailable
from hydra_graph.query import QueryRequest, QueryService

FIXTURE = Path(__file__).parents[1] / "fixtures" / "hydradb" / "query_authorization.json"


class FixtureTransport:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.response


def client_for(transport: FixtureTransport, *, api_key: str | None = "test") -> HydraDBClient:
    return HydraDBClient(
        HydraDBConfig(
            api_key=api_key,
            database="repo_hack_hydra",
            max_retries=0,
        ),
        transport=transport,
    )


def test_query_preserves_hydradb_rank_and_path_data() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    transport = FixtureTransport(raw)
    events = EventBus()
    service = QueryService(client_for(transport), repository_id="hack-hydra", events=events)

    result = service.repository_query(QueryRequest(question="How does authorization work?"))

    assert [chunk["id"] for chunk in result["chunks"]] == [
        "source-authorize",
        "source-store",
        "source-decoy",
    ]
    assert result["paths"][0]["triplets"][0]["relation"]["relationship_id"] == "hydra-rel-calls"
    assert result["hydradb"]["origin"] == "byog"
    assert result["revision"] == "rev-abc"
    assert result["additional_context"][0]["context_id"] == "source-auth-test"
    assert [event["type"] for event in events.recent()] == [
        "query_started",
        "hydradb_result_returned",
        "path_replay_started",
        "path_hop_replayed",
    ]


def test_context_budget_keeps_ranked_prefix_instead_of_selecting_fixture_favorites() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    transport = FixtureTransport(raw)
    service = QueryService(client_for(transport), repository_id="hack-hydra")
    first_content = raw["data"]["chunks"][0]["chunk_content"]

    result = service.repository_query(
        QueryRequest(question="authorization", max_context_chars=len(first_content) + 12)
    )

    assert [chunk["id"] for chunk in result["chunks"]] == ["source-authorize", "source-store"]
    assert result["chunks"][1]["content_truncated"] is True
    assert result["chunks"][1]["chunk_content"] == raw["data"]["chunks"][1]["chunk_content"][:12]
    assert result["budget"]["truncated"] is True


def test_query_results_really_come_from_mocked_hydradb_response() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["data"]["chunks"][0]["id"] = "proof-from-transport"
    raw["data"]["chunks"][0]["chunk_content"] = "transport sentinel"
    transport = FixtureTransport(raw)

    result = QueryService(client_for(transport), repository_id="hack-hydra").repository_query(
        QueryRequest(question="sentinel")
    )

    assert result["chunks"][0]["id"] == "proof-from-transport"
    assert result["chunks"][0]["chunk_content"] == "transport sentinel"
    assert len(transport.calls) == 1


def test_unavailable_hydradb_returns_no_fixture_or_local_graph() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    transport = FixtureTransport(raw)
    service = QueryService(client_for(transport, api_key=None), repository_id="hack-hydra")

    result = service.repository_query(QueryRequest(question="authorization"))

    assert result["status"] == "unavailable"
    assert result["hydradb"]["available"] is False
    assert result["chunks"] == []
    assert result["paths"] == []
    assert transport.calls == []


def test_transport_failure_is_visible_and_not_replaced() -> None:
    class FailingTransport(FixtureTransport):
        def request(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(kwargs)
            raise HydraDBUnavailable("network sentinel")

    transport = FailingTransport({})
    service = QueryService(client_for(transport), repository_id="hack-hydra")

    result = service.repository_query(QueryRequest(question="authorization"))

    assert result["status"] == "unavailable"
    assert result["chunks"] == []
    assert result["warnings"] == ["network sentinel"]
