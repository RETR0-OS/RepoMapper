from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydra_graph.config import HydraDBConfig
from hydra_graph.events import EventBus
from hydra_graph.hydradb import HydraDBClient
from hydra_graph.mcp_server import create_mcp_server
from hydra_graph.query import QueryService
from hydra_graph.sync import SyncService
from hydra_graph.views import ViewService

FIXTURE = Path(__file__).parents[1] / "fixtures" / "hydradb" / "query_authorization.json"


class Transport:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.response


@dataclass
class Services:
    queries: QueryService
    views: ViewService
    events: EventBus
    sync: SyncService


def mcp(*, api_key: str | None = "test") -> tuple[Any, Transport, Services]:
    transport = Transport(json.loads(FIXTURE.read_text(encoding="utf-8")))
    config = HydraDBConfig(api_key=api_key, database="repo_hack_hydra", max_retries=0)
    events = EventBus()
    client = HydraDBClient(config, transport=transport)
    queries = QueryService(client, repository_id="hack-hydra", events=events)
    views = ViewService(queries)
    services = Services(
        queries=queries,
        views=views,
        events=events,
        sync=SyncService(client, repository_id="hack-hydra", events=events),
    )
    return create_mcp_server(services), transport, services


def call(server: Any, name: str, arguments: dict[str, Any]) -> Any:
    _, structured = asyncio.run(server.call_tool(name, arguments))
    return structured


def test_mcp_exposes_repository_specific_tool_contracts() -> None:
    server, _, _ = mcp()

    tools = asyncio.run(server.list_tools())

    assert {tool.name for tool in tools} == {
        "repository_query",
        "focus_symbol",
        "trace_flow",
        "explain_relationship",
        "compare_repository_graph",
        "open_system_lens",
        "pin_context",
    }


def test_repository_query_returns_mocked_hydradb_rank_and_can_explain_edge() -> None:
    server, transport, _ = mcp()

    result = call(server, "repository_query", {"question": "How does authorization work?"})

    assert result["chunks"][0]["source_id"] == "source-authorize"
    assert result["chunks"][1]["source_id"] == "source-store"
    assert result["hydradb"]["origin"] == "byog"
    explanation = call(
        server,
        "explain_relationship",
        {"view_id": result["view_id"], "relationship_id": "edge-calls"},
    )
    assert explanation["predicate"] == "CALLS"
    assert explanation["hydradb_origin"] == "byog"
    assert len(transport.calls) == 1


def test_focus_symbol_plans_literal_hydradb_query_without_local_expansion() -> None:
    server, transport, _ = mcp()

    result = call(
        server,
        "focus_symbol",
        {
            "symbol": "payments.auth.authorize_user",
            "path": "src/payments/auth.py",
            "relations": ["CALLS"],
            "budget": 10,
        },
    )

    sent = transport.calls[0]["json_body"]
    assert sent["query_by"] == "text"
    assert sent["mode"] == "fast"
    assert "payments.auth.authorize_user" in sent["query"]
    assert "may not enumerate every graph neighbor" in result["warnings"][-1]


def test_trace_flow_preserves_hydradb_path_and_product_budgets() -> None:
    server, transport, _ = mcp()

    result = call(
        server,
        "trace_flow",
        {
            "question": "Trace authorization",
            "from_entity": "authorize_user",
            "to_entity": "TokenStore.resolve",
            "max_hops": 4,
            "max_paths": 2,
        },
    )

    assert result["paths"][0]["path_id"] == "path-auth"
    assert result["budget"]["max_paths"] == 2
    assert transport.calls[0]["json_body"]["mode"] == "thinking"


def test_pin_context_emits_explicit_event_and_does_not_change_graph() -> None:
    server, _, services = mcp()
    result = call(server, "repository_query", {"question": "authorization"})

    pinned = call(
        server,
        "pin_context",
        {
            "view_id": result["view_id"],
            "entity_ids": ["node-authorize"],
            "instruction": "Use this flow",
            "session_id": result["session_id"],
        },
    )

    assert pinned["status"] == "pinned"
    assert pinned["structural_graph_changed"] is False
    assert services.events.recent()[-1]["type"] == "user_context_pinned"


def test_unavailable_mcp_tool_returns_no_fixture_or_local_graph() -> None:
    server, transport, _ = mcp(api_key=None)

    result = call(server, "repository_query", {"question": "authorization"})

    assert result["status"] == "unavailable"
    assert result["chunks"] == []
    assert result["paths"] == []
    assert transport.calls == []


def test_compare_does_not_relabel_generic_chunks_as_change_events() -> None:
    server, transport, _ = mcp()

    result = call(
        server,
        "compare_repository_graph",
        {"before": "rev-old", "after": "rev-abc"},
    )

    assert result["status"] == "unavailable"
    assert result["chunks"] == []
    assert "no fallback retrieval" in result["warnings"][0]
    assert transport.calls == []


def test_lens_does_not_relabel_generic_chunks_as_saved_lens() -> None:
    server, transport, _ = mcp()

    result = call(server, "open_system_lens", {"lens": "payments"})

    assert result["status"] == "unavailable"
    assert result["chunks"] == []
    assert "no fallback retrieval" in result["warnings"][0]
    assert transport.calls == []


def test_missing_evolution_result_matches_query_envelope_contract() -> None:
    server, transport, _ = mcp()

    result = call(
        server,
        "compare_repository_graph",
        {"before": "rev-old", "after": "rev-new"},
    )

    assert result["response_schema"] == "hack-hydra.query-response.v1"
    assert result["chunk_id_to_group_ids"] == {}
    assert result["budget"]["max_context_chars"] > 0
    assert transport.calls == []
