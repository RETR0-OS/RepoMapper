from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hydra_graph.config import HydraDBConfig
from hydra_graph.events import EventBus
from hydra_graph.hydradb import HydraDBClient, HydraDBUnavailable
from hydra_graph.query import (
    QUERY_RESPONSE_SCHEMA,
    QueryRequest,
    QueryService,
    normalize_query_response,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "hydradb" / "query_authorization.json"
PRODUCT_FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "hydradb" / "product_query_authorization.json"
)


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

    assert [chunk["source_id"] for chunk in result["chunks"]] == [
        "source-authorize",
        "source-store",
        "source-decoy",
    ]
    assert result["paths"][0]["hops"][0]["relation"]["id"] == "hydra-rel-calls"
    assert result["hydradb"]["origin"] == "byog"
    assert result["revision"] == "rev-abc"
    assert result["additional_context"][0]["chunk_id"] == "chunk-auth-test"
    assert [event["type"] for event in events.recent()] == [
        "query_started",
        "hydradb_result_returned",
        "path_replay_started",
        "path_hop_replayed",
    ]
    assert set(result["chunks"][0]) == {
        "rank",
        "chunk_id",
        "source_id",
        "content",
        "content_truncated",
        "title",
        "source_type",
        "score",
        "path",
        "span",
        "revision",
        "repository_id",
        "entity_kind",
        "language",
        "relation_quality",
        "node_id",
        "logical_id",
        "qualified_name",
        "signature",
        "content_hash",
        "parser",
        "parser_version",
        "is_generated",
        "group_ids",
    }
    assert set(result["paths"][0]) == {
        "path_id",
        "rank",
        "score",
        "summary",
        "chunk_ids",
        "hops",
    }


def test_raw_hydradb_fixture_maps_to_stable_golden_product_response() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    expected = json.loads(PRODUCT_FIXTURE.read_text(encoding="utf-8"))

    result = normalize_query_response(
        raw,
        session_id="session-golden",
        view_id="view-golden",
        revision="current",
        database="repo_hack_hydra",
        collections=["current"],
        query_by="hybrid",
        mode="thinking",
        graph_context=True,
        max_context_chars=7_000,
        max_paths=3,
        max_relations=30,
    )

    assert result == expected
    assert result["response_schema"] == QUERY_RESPONSE_SCHEMA


def test_context_budget_keeps_ranked_prefix_instead_of_selecting_fixture_favorites() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    transport = FixtureTransport(raw)
    service = QueryService(client_for(transport), repository_id="hack-hydra")
    first_content = raw["data"]["chunks"][0]["chunk_content"]

    result = service.repository_query(
        QueryRequest(question="authorization", max_context_chars=len(first_content) + 12)
    )

    assert [chunk["source_id"] for chunk in result["chunks"]] == [
        "source-authorize",
        "source-store",
    ]
    assert result["chunks"][1]["content_truncated"] is True
    assert result["chunks"][1]["content"] == raw["data"]["chunks"][1]["chunk_content"][:12]
    assert result["budget"]["truncated"] is True


def test_query_results_really_come_from_mocked_hydradb_response() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["data"]["chunks"][0]["id"] = "proof-from-transport"
    raw["data"]["chunks"][0]["chunk_content"] = "transport sentinel"
    transport = FixtureTransport(raw)

    result = QueryService(client_for(transport), repository_id="hack-hydra").repository_query(
        QueryRequest(question="sentinel")
    )

    assert result["chunks"][0]["source_id"] == "proof-from-transport"
    assert result["chunks"][0]["content"] == "transport sentinel"
    assert len(transport.calls) == 1


def test_unavailable_hydradb_returns_no_fixture_or_local_graph() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    transport = FixtureTransport(raw)
    service = QueryService(client_for(transport, api_key=None), repository_id="hack-hydra")

    result = service.repository_query(QueryRequest(question="authorization"))

    assert result["status"] == "unavailable"
    assert result["response_schema"] == QUERY_RESPONSE_SCHEMA
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


def test_current_query_refuses_mixed_hydradb_revisions() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["data"]["chunks"][1]["metadata"]["revision_id"] = "rev-candidate"
    transport = FixtureTransport(raw)
    service = QueryService(client_for(transport), repository_id="hack-hydra")

    result = service.repository_query(QueryRequest(question="authorization", revision="current"))

    assert result["status"] == "degraded"
    assert result["chunks"] == []
    assert result["paths"] == []
    assert "inconsistent revision slice" in result["warnings"][0]
    assert len(transport.calls) == 1


def test_current_query_filters_to_last_verified_revision_when_known() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    transport = FixtureTransport(raw)
    service = QueryService(
        client_for(transport),
        repository_id="hack-hydra",
        verified_revision=lambda: "rev-abc",
    )

    result = service.repository_query(QueryRequest(question="authorization", revision="current"))

    assert result["status"] == "ready"
    assert transport.calls[0]["json_body"]["metadata_filters"]["revision_id"] == "rev-abc"


def test_expected_revision_requires_revision_metadata_and_anchored_paths() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["data"]["chunks"][0]["metadata"].pop("revision_id")
    transport = FixtureTransport(raw)
    service = QueryService(
        client_for(transport),
        repository_id="hack-hydra",
        verified_revision=lambda: "rev-abc",
    )

    result = service.repository_query(QueryRequest(question="authorization"))

    assert result["status"] == "degraded"
    assert result["chunks"] == []

    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["data"]["graph_context"]["query_paths"][0]["source_chunk_ids"].append("candidate-chunk")
    transport = FixtureTransport(raw)
    service = QueryService(client_for(transport), repository_id="hack-hydra")

    result = service.repository_query(QueryRequest(question="authorization"))

    assert result["status"] == "degraded"
    assert result["paths"] == []


def test_indeterminate_current_state_is_gated_without_hydradb_or_local_fallback() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    transport = FixtureTransport(raw)
    service = QueryService(
        client_for(transport),
        repository_id="hack-hydra",
        verified_revision=lambda: "rev-abc",
        current_state_indeterminate=lambda: True,
    )

    result = service.repository_query(QueryRequest(question="authorization"))

    assert result["status"] == "degraded"
    assert result["hydradb"]["available"] is True
    assert result["chunks"] == []
    assert result["paths"] == []
    assert "indeterminate" in result["warnings"][0]
    assert transport.calls == []


def test_event_bus_rejects_unbounded_or_blank_external_fields() -> None:
    events = EventBus(subscriber_queue_limit=1)

    try:
        events.emit("evidence_opened", session_id=" ", revision_id="rev")
    except ValueError as exc:
        assert "session_id" in str(exc)
    else:
        raise AssertionError("blank session ID was accepted")

    try:
        events.emit(
            "evidence_opened",
            session_id="session",
            revision_id="rev",
            hydradb_query_metadata={"large": "x" * 16_001},
        )
    except ValueError as exc:
        assert "16000" in str(exc)
    else:
        raise AssertionError("unbounded metadata was accepted")


def test_one_large_hydradb_path_cannot_bypass_per_path_hop_budget() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    group = raw["data"]["graph_context"]["query_paths"][0]
    group["triplets"] = group["triplets"] * 100
    raw["data"]["graph_context"]["chunk_relations"] = []
    transport = FixtureTransport(raw)

    result = QueryService(client_for(transport), repository_id="hack-hydra").repository_query(
        QueryRequest(
            question="authorization",
            max_paths=2,
            max_relations=50,
            max_hops_per_path=4,
        )
    )

    assert len(result["paths"][0]["hops"]) == 4
    assert result["budget"]["returned_relations"] == 4
    assert result["budget"]["truncated"] is True


def test_large_result_caps_observational_event_references_without_failing_query() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    template = raw["data"]["graph_context"]["query_paths"][0]
    groups = []
    for index in range(101):
        group = json.loads(json.dumps(template))
        group["group_id"] = f"path-{index}"
        group["triplets"][0]["relation"]["relationship_id"] = f"relation-{index}"
        groups.append(group)
    raw["data"]["graph_context"]["query_paths"] = groups
    raw["data"]["graph_context"]["chunk_relations"] = []
    events = EventBus()

    result = QueryService(
        client_for(FixtureTransport(raw)),
        repository_id="hack-hydra",
        events=events,
    ).repository_query(QueryRequest(question="authorization", max_paths=101, max_relations=101))

    returned = next(
        event for event in events.recent() if event["type"] == "hydradb_result_returned"
    )
    assert result["budget"]["returned_relations"] == 101
    assert len(returned["relationship_ids"]) == 100
