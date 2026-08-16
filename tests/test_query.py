from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hydra_graph.config import HydraDBConfig
from hydra_graph.events import EventBus
from hydra_graph.hydradb import (
    HydraDBAPIError,
    HydraDBClient,
    HydraDBError,
    HydraDBTimeout,
    HydraDBUnavailable,
)
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

    # Rank order is kept, and the budget clips content only. Every card stays, because
    # its metadata is what grounds a node or an edge in the view.
    assert [chunk["source_id"] for chunk in result["chunks"]] == [
        "source-authorize",
        "source-store",
        "source-decoy",
    ]
    assert result["chunks"][0]["content"] == first_content
    assert result["chunks"][1]["content_truncated"] is True
    assert result["chunks"][1]["content"] == raw["data"]["chunks"][1]["chunk_content"][:12]
    assert result["chunks"][2]["content"] == ""
    assert result["chunks"][2]["content_truncated"] is True
    assert result["budget"]["returned_context_chars"] <= len(first_content) + 12
    assert result["budget"]["truncated"] is True
    store_source = next(item for item in result["sources"] if item["source_id"] == "source-store")
    assert store_source["node_id"] == "node-store"
    assert store_source["chunk_ids"] == ["chunk-store"]


def test_verified_manifest_restores_omitted_live_byog_origin() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    graph = raw["data"]["graph_context"]
    for group_name in ("query_paths", "chunk_relations"):
        for group in graph[group_name]:
            for triplet in group["triplets"]:
                triplet["relation"].pop("origin")
    transport = FixtureTransport(raw)
    service = QueryService(
        client_for(transport),
        repository_id="hack-hydra",
        verified_revision=lambda: "rev-abc",
        byog_source_ids=lambda: ("source-authorize",),
    )

    result = service.repository_query(QueryRequest(question="authorization"))

    assert result["hydradb"]["origin"] == "byog"
    assert result["paths"][0]["hops"][0]["relation"]["origin"] == "byog"


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
    # Queries decide relevance: one for implementation code and one for the test tail.
    # Every later read asks for the stored graph of a source those returned, and never
    # for anything else.
    queries = [call for call in transport.calls if call["url"].endswith("/query")]
    assert [call["json_body"]["metadata_filters"]["is_test"] for call in queries[:2]] == [
        False,
        True,
    ]
    assert all(call["url"].endswith(("/query", "/context/relations")) for call in transport.calls)


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
            raise HydraDBUnavailable("network sentinel private-database secret-api-key")

    transport = FailingTransport({})
    service = QueryService(client_for(transport), repository_id="hack-hydra")

    result = service.repository_query(QueryRequest(question="authorization"))

    assert result["status"] == "unavailable"
    assert result["chunks"] == []
    # The class of the failure chooses the sentence. The local exception message is
    # never repeated, because it can name the host, the database, or a key.
    assert result["warnings"] == [
        "HydraDB could not serve this repository query. "
        "HydraDB is unreachable, or no credential is available for this project."
    ]
    assert result["diagnostics"]["outcome"] == "hydradb_unavailable"
    assert "private-database" not in str(result)
    assert "secret-api-key" not in str(result)


def test_funnel_names_the_stage_that_emptied_a_successful_query() -> None:
    """A successful answer can still show nothing, and each cause differs.

    Without these counts the panel says "try a narrower question" for a dropped
    relation group, which sends the user to change the one thing that was correct.
    """

    def outcome_for(mutate: Any) -> dict[str, Any]:
        raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
        mutate(raw["data"])
        service = QueryService(client_for(FixtureTransport(raw)), repository_id="hack-hydra")
        return service.repository_query(QueryRequest(question="authorization"))["diagnostics"]

    assert outcome_for(lambda data: None)["outcome"] == "ok"

    def drop_chunks(data: dict[str, Any]) -> None:
        data["chunks"] = []
        data["sources"] = []

    assert outcome_for(drop_chunks)["outcome"] == "no_chunks"

    def drop_graph(data: dict[str, Any]) -> None:
        data["graph_context"] = {}

    assert outcome_for(drop_graph)["outcome"] == "no_graph_context"

    def cite_a_chunk_outside_the_window(data: dict[str, Any]) -> None:
        for group in data["graph_context"]["query_paths"]:
            group["source_chunk_ids"] = ["chunk-not-in-this-result"]
        for group in data["graph_context"]["chunk_relations"]:
            group["source_chunk_ids"] = ["chunk-not-in-this-result"]

    ungrounded = outcome_for(cite_a_chunk_outside_the_window)
    assert ungrounded["outcome"] == "all_groups_ungrounded"
    assert ungrounded["funnel"]["raw_paths"] == 1
    assert ungrounded["funnel"]["dropped_paths"] == 1
    assert ungrounded["funnel"]["kept_paths"] == 0


def test_query_failure_reason_separates_timeout_from_refusal() -> None:
    def failing(error: HydraDBError) -> dict[str, Any]:
        class FailingTransport(FixtureTransport):
            def request(self, **kwargs: Any) -> dict[str, Any]:
                self.calls.append(kwargs)
                raise error

        service = QueryService(client_for(FailingTransport({})), repository_id="hack-hydra")
        return service.repository_query(QueryRequest(question="authorization"))

    timed_out = failing(HydraDBTimeout("network sentinel secret-api-key"))
    assert "did not answer inside" in timed_out["warnings"][0]
    assert "secret-api-key" not in str(timed_out)

    # Only an API error carries text that HydraDB itself wrote, so only that text
    # may be repeated to the user.
    refused = failing(HydraDBAPIError("rate limit reached", code="rate_limited", status=429))
    assert "HTTP 429" in refused["warnings"][0]
    assert "rate limit reached" in refused["warnings"][0]


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
    # A mixed answer is refused before the stored graph is read, so the conflict costs
    # no relation request at all.
    assert all(call["url"].endswith("/query") for call in transport.calls)


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

    # Graph context reaches neighbors of the retrieved chunks, so a path may cite a
    # chunk this response never returned. That single path is unanchored and is
    # dropped; the chunks and sources that did arrive keep their proven revision.
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["data"]["graph_context"]["query_paths"][0]["source_chunk_ids"].append("candidate-chunk")
    transport = FixtureTransport(raw)
    service = QueryService(client_for(transport), repository_id="hack-hydra")

    result = service.repository_query(QueryRequest(question="authorization"))

    assert result["status"] == "ready"
    assert result["paths"] == []
    assert result["chunks"] != []
    assert any("outside this result" in warning for warning in result["warnings"])


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


class ScriptedTransport:
    """Answer each HydraDB call from a queue, so composed queries can differ."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if kwargs["url"].endswith("/context/relations"):
            return {"data": {"relations": []}}
        index = min(len(self.query_calls) - 1, len(self.responses) - 1)
        return self.responses[index]

    @property
    def query_calls(self) -> list[dict[str, Any]]:
        return [call for call in self.calls if call["url"].endswith("/query")]


def chunk_payload(name: str, *, is_test: bool) -> dict[str, Any]:
    return {
        "chunk_uuid": f"chunk-{name}",
        "id": f"source-{name}",
        "chunk_content": name,
        "metadata": {
            "revision_id": "rev-abc",
            "repository_id": "hack-hydra",
            "is_test": is_test,
        },
        "additional_metadata": {"node_id": f"node-{name}", "path": f"app/{name}.py"},
    }


def answer(*names: tuple[str, bool]) -> dict[str, Any]:
    return {
        "data": {
            "chunks": [chunk_payload(name, is_test=is_test) for name, is_test in names],
            "sources": [],
            "graph_context": {},
        }
    }


def test_implementation_code_is_answered_before_test_code() -> None:
    transport = ScriptedTransport([answer(("authorize", False)), answer(("test_authorize", True))])
    service = QueryService(client_for(transport), repository_id="hack-hydra")

    result = service.repository_query(QueryRequest(question="how does authorization work?"))

    assert [chunk["source_id"] for chunk in result["chunks"]] == [
        "source-authorize",
        "source-test_authorize",
    ]
    filters = [call["json_body"]["metadata_filters"]["is_test"] for call in transport.query_calls]
    assert filters == [False, True]
    assert result["diagnostics"]["funnel"]["raw_test_chunks"] == 1


def test_a_failed_test_tail_query_keeps_the_implementation_answer() -> None:
    class HalfBrokenTransport(ScriptedTransport):
        def request(self, **kwargs: Any) -> dict[str, Any]:
            if kwargs["url"].endswith("/query") and len(self.query_calls) == 1:
                self.calls.append(kwargs)
                raise HydraDBUnavailable("second query failed")
            return super().request(**kwargs)

    transport = HalfBrokenTransport([answer(("authorize", False))])
    service = QueryService(client_for(transport), repository_id="hack-hydra")

    result = service.repository_query(QueryRequest(question="authorization"))

    assert result["status"] == "ready"
    assert [chunk["source_id"] for chunk in result["chunks"]] == ["source-authorize"]
    assert any("Test-code results were omitted" in item for item in result["warnings"])


def test_the_mixed_policy_asks_once_and_filters_nothing() -> None:
    transport = ScriptedTransport([answer(("authorize", False))])
    service = QueryService(client_for(transport), repository_id="hack-hydra")

    service.repository_query(QueryRequest(question="authorization", tests="mixed"))

    assert len(transport.query_calls) == 1
    assert "is_test" not in transport.query_calls[0]["json_body"]["metadata_filters"]


def test_entity_kinds_travel_as_a_metadata_filter_not_as_prose() -> None:
    transport = ScriptedTransport([answer(("authorize", False))])
    service = QueryService(client_for(transport), repository_id="hack-hydra")

    service.repository_query(
        QueryRequest(question="repository", entity_kinds=("PACKAGE", "FILE"), tests="mixed")
    )

    body = transport.query_calls[0]["json_body"]
    assert body["metadata_filters"]["entity_kind"] == ["PACKAGE", "FILE"]
    assert body["query"] == "repository"


def test_the_connecting_card_is_fetched_so_the_graph_is_not_disconnected() -> None:
    """The code that joins two matched symbols is rarely a word match for the question.

    Without a second read it stays outside the window, every relation through it is
    dropped as ungrounded, and the graph arrives as unlinked pairs.
    """

    stored_relation = {
        "chunk_id": "chunk-router",
        "source": {"identifier": "repo:hack-hydra:python:app/router.py:FUNCTION:app.router.route"},
        "target": {"identifier": "repo:hack-hydra:python:app/authorize.py:FUNCTION:authorize"},
        "relations": [{"relationship_id": "rel-1", "canonical_predicate": "CALLS"}],
    }

    class CompletionTransport(ScriptedTransport):
        def request(self, **kwargs: Any) -> dict[str, Any]:
            if kwargs["url"].endswith("/context/relations"):
                self.calls.append(kwargs)
                return {"data": {"relations": [stored_relation]}}
            return super().request(**kwargs)

    transport = CompletionTransport(
        [
            answer(("authorize", False)),
            answer(("test_authorize", True)),
            answer(("router", False)),
        ]
    )
    service = QueryService(client_for(transport), repository_id="hack-hydra")

    result = service.repository_query(
        QueryRequest(question="how does authorization work?", revision="rev-abc")
    )

    completion = transport.query_calls[-1]
    assert completion["json_body"]["query_by"] == "text"
    assert "app.router.route" in completion["json_body"]["query"]
    assert "chunk-router" in {chunk["chunk_id"] for chunk in result["chunks"]}
    assert result["diagnostics"]["funnel"]["completion_chunks"] == 1


def test_a_completion_card_from_another_revision_is_refused() -> None:
    stored_relation = {
        "chunk_id": "chunk-router",
        "source": {"identifier": "repo:hack-hydra:python:app/router.py:FUNCTION:app.router.route"},
        "target": {"identifier": "repo:hack-hydra:python:app/authorize.py:FUNCTION:authorize"},
        "relations": [{"relationship_id": "rel-1", "canonical_predicate": "CALLS"}],
    }
    stale = answer(("router", False))
    stale["data"]["chunks"][0]["metadata"]["revision_id"] = "rev-old"

    class CompletionTransport(ScriptedTransport):
        def request(self, **kwargs: Any) -> dict[str, Any]:
            if kwargs["url"].endswith("/context/relations"):
                self.calls.append(kwargs)
                return {"data": {"relations": [stored_relation]}}
            return super().request(**kwargs)

    transport = CompletionTransport(
        [answer(("authorize", False)), answer(("test_authorize", True)), stale]
    )
    service = QueryService(client_for(transport), repository_id="hack-hydra")

    result = service.repository_query(QueryRequest(question="authorization", revision="rev-abc"))

    assert result["status"] == "ready"
    assert "chunk-router" not in {chunk["chunk_id"] for chunk in result["chunks"]}
    assert result["diagnostics"]["funnel"]["completion_dropped_revision"] == 1


def test_the_caller_of_the_matched_code_is_found_and_the_flow_is_ordered() -> None:
    """A card's stored graph holds only the relations it owns, so a callee's card
    cannot name its caller. Every card does list its incoming relations by name, so
    searching for the matched name is what makes the calling code reachable at all.
    """

    def entity(name: str) -> dict[str, Any]:
        return {"identifier": f"logical-{name}", "name": name, "type": "FUNCTION"}

    def envelope(text: str, edge: str) -> str:
        return json.dumps(
            {
                "schema": "hack-hydra.relation-evidence.v1",
                "summary": text,
                "edge_id": edge,
                "quality": "exact",
                "extractor": "python-ast",
                "extractor_version": "1",
                "evidence": {},
            }
        )

    def owned(source: str, target: str, edge: str, summary: str) -> dict[str, Any]:
        return {
            "chunk_id": f"chunk-{source}",
            "source": entity(source),
            "target": entity(target),
            "relations": [
                {
                    "relationship_id": edge,
                    "canonical_predicate": "CALLS",
                    "context": envelope(summary, edge),
                    "origin": "byog",
                }
            ],
        }

    def card(name: str) -> dict[str, Any]:
        payload = chunk_payload(name, is_test=False)
        payload["additional_metadata"]["logical_id"] = f"logical-{name}"
        payload["additional_metadata"]["qualified_name"] = name
        return payload

    stored = {
        "source-dispatch": [owned("dispatch", "run", "edge-2", "dispatch calls run")],
        "source-serve": [owned("serve", "dispatch", "edge-1", "serve calls dispatch")],
    }

    class CallerTransport(ScriptedTransport):
        def request(self, **kwargs: Any) -> dict[str, Any]:
            if kwargs["url"].endswith("/context/relations"):
                self.calls.append(kwargs)
                return {"data": {"relations": stored.get(kwargs["query"]["id"], [])}}
            return super().request(**kwargs)

    def answer_with(*names: str) -> dict[str, Any]:
        return {"data": {"chunks": [card(name) for name in names], "sources": []}}

    transport = CallerTransport(
        [
            answer_with("run"),
            {"data": {"chunks": [], "sources": []}},
            answer_with("dispatch"),
            answer_with("serve"),
        ]
    )
    service = QueryService(client_for(transport), repository_id="hack-hydra")

    result = service.repository_query(
        QueryRequest(question="how do tools work?", revision="rev-abc")
    )

    assert result["diagnostics"]["funnel"]["assembled_paths"] == 1
    flow = result["paths"][0]
    assert flow["origin"] == "assembled-flow"
    assert flow["summary"] == "1. serve calls dispatch\n2. dispatch calls run"
    assert [hop["source"]["name"] for hop in flow["hops"]] == ["serve", "dispatch"]
    assert flow["hops"][0]["source"]["role"] == "entry"
    assert flow["hops"][-1]["target"]["role"] == "target"
    # The completion reads never widen the answer with test sources.
    completion = [call for call in transport.query_calls if call["json_body"]["query_by"] == "text"]
    assert completion and all(
        call["json_body"]["metadata_filters"]["is_test"] is False for call in completion
    )
