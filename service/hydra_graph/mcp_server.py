"""Repository-specific MCP tools over the HydraDB query service."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from mcp.server.fastmcp import FastMCP

from .query import QueryRequest
from .views import ViewDepth, ViewMode, build_product_view


def create_mcp_server(services: Any | None = None) -> FastMCP:
    if services is None:
        from .api import create_container

        services = create_container()
    server = FastMCP(
        "hack-hydra",
        instructions=(
            "Repository observability tools backed by HydraDB. Returned paths are HydraDB query "
            "results, not hidden model reasoning. Empty unavailable results must not be replaced "
            "with local repository search."
        ),
    )

    def remember(result: dict[str, Any], mode: ViewMode = ViewMode.TRACE) -> None:
        view = build_product_view(
            result,
            mode=mode,
            depth=ViewDepth.SYMBOL,
            max_nodes=100,
            max_edges=200,
        )
        services.views.store.put(view, result)

    @server.tool(
        description="Ask a conceptual repository question using HydraDB hybrid graph retrieval."
    )
    def repository_query(
        question: str,
        revision: str = "current",
        max_results: int = 8,
        max_context_chars: int = 7_000,
        relation_quality: list[str] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        result = services.queries.repository_query(
            QueryRequest(
                question=question,
                revision=revision,
                max_results=max_results,
                max_context_chars=max_context_chars,
                relation_quality=tuple(relation_quality or ("exact", "inferred")),
                session_id=session_id,
            )
        )
        remember(result)
        return result

    @server.tool(
        description=(
            "Focus on a known symbol or file through HydraDB literal retrieval. This is "
            "retrieval-based and does not promise exhaustive neighbors."
        )
    )
    def focus_symbol(
        symbol: str,
        path: str | None = None,
        relations: list[str] | None = None,
        direction: str = "both",
        depth: int = 1,
        budget: int = 20,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if direction not in {"in", "out", "both"}:
            raise ValueError("direction must be in, out, or both")
        if not 1 <= depth <= 8:
            raise ValueError("depth must be between 1 and 8")
        details = [f"Focus on repository entity {symbol}."]
        if path:
            details.append(f"The known repository path is {path}.")
        if relations:
            details.append(f"Return HydraDB relations matching: {', '.join(relations)}.")
        details.append(f"Direction: {direction}; requested depth: {depth}.")
        result = services.queries.repository_query(
            QueryRequest(
                question=" ".join(details),
                max_results=min(50, max(1, budget)),
                max_context_chars=7_000,
                max_paths=min(8, depth),
                max_relations=max(0, budget),
                query_by="text",
                mode="fast" if depth == 1 else "thinking",
                session_id=session_id,
            )
        )
        result["warnings"].append(
            "focus_symbol uses bounded HydraDB retrieval and may not enumerate every graph "
            "neighbor."
        )
        remember(result, ViewMode.EXPLORE)
        return result

    @server.tool(
        description="Trace multi-hop repository behavior using HydraDB thinking mode paths."
    )
    def trace_flow(
        question: str,
        from_entity: str | None = None,
        to_entity: str | None = None,
        max_hops: int = 8,
        max_paths: int = 3,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= max_hops <= 20:
            raise ValueError("max_hops must be between 1 and 20")
        if not 1 <= max_paths <= 10:
            raise ValueError("max_paths must be between 1 and 10")
        endpoints = ""
        if from_entity:
            endpoints += f" Start from {from_entity}."
        if to_entity:
            endpoints += f" End at {to_entity}."
        result = services.queries.repository_query(
            QueryRequest(
                question=f"{question.strip()}{endpoints}",
                max_results=min(50, max(8, max_hops * max_paths)),
                max_context_chars=12_000,
                max_paths=max_paths,
                max_relations=max_hops * max_paths,
                max_hops_per_path=max_hops,
                query_by="hybrid",
                mode="thinking",
                graph_context=True,
                session_id=session_id,
            )
        )
        remember(result)
        return result

    @server.tool(description="Explain one relationship already returned in a bounded HydraDB view.")
    def explain_relationship(view_id: str, relationship_id: str) -> dict[str, Any]:
        explanation = services.views.explain_relationship(view_id, relationship_id)
        if explanation is None:
            return {
                "status": "not_found",
                "view_id": view_id,
                "relationship_id": relationship_id,
                "warning": "The relationship is not present in this bounded HydraDB result.",
            }
        return explanation

    @server.tool(
        description="Retrieve graph-delta Knowledge for two repository revisions from HydraDB."
    )
    def compare_repository_graph(
        before: str,
        after: str,
        focus: str | None = None,
        max_changes: int = 50,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= max_changes <= 500:
            raise ValueError("max_changes must be between 1 and 500")
        evolution = getattr(services, "evolution", None)
        if evolution is None:
            return _missing_evolution_result(services, revision=after)
        result = evolution.compare(
            before_revision_id=before,
            after_revision_id=after,
            focus=focus,
            max_changes=max_changes,
            session_id=session_id,
        )
        remember(result, ViewMode.COMPARE)
        return result

    @server.tool(
        description="Retrieve a saved system lens and its current grounded path from HydraDB."
    )
    def open_system_lens(
        lens: str,
        revision: str = "current",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        evolution = getattr(services, "evolution", None)
        if evolution is None:
            return _missing_evolution_result(services, revision=revision)
        result = evolution.open_lens(lens=lens, session_id=session_id)
        if revision != "current":
            result["warnings"].append(
                "The revision argument does not trigger cross-collection traversal; this "
                "returns the saved shared-lens record only."
            )
        remember(result, ViewMode.PRESERVE)
        return result

    @server.tool(
        description="Record explicit programmer-selected context without changing graph facts."
    )
    def pin_context(
        view_id: str,
        entity_ids: list[str],
        instruction: str,
        session_id: str,
    ) -> dict[str, Any]:
        stored = services.views.store.get(view_id)
        if stored is None:
            return {
                "status": "not_found",
                "view_id": view_id,
                "warning": "The bounded view is no longer available.",
            }
        allowed = {node["id"] for node in stored["view"].get("nodes", [])}
        unknown = sorted(set(entity_ids).difference(allowed))
        if unknown:
            return {
                "status": "invalid_selection",
                "view_id": view_id,
                "unknown_entity_ids": unknown,
            }
        revision = str(stored["view"].get("revision_id", "current"))
        event = services.events.emit(
            "user_context_pinned",
            session_id=session_id,
            revision_id=revision,
            view_id=view_id,
            entity_ids=tuple(entity_ids),
            hydradb_query_metadata={"instruction": instruction},
        )
        return {
            "status": "pinned",
            "view_id": view_id,
            "entity_ids": entity_ids,
            "instruction": instruction,
            "event_id": event.event_id,
            "structural_graph_changed": False,
        }

    return server


def tool_names(server: FastMCP) -> Sequence[str]:
    """Small test/diagnostic helper that does not depend on manager internals."""

    import asyncio

    return tuple(tool.name for tool in asyncio.run(server.list_tools()))


def _missing_evolution_result(services: Any, *, revision: str) -> dict[str, Any]:
    config = services.queries.client.config
    return {
        "response_schema": "hack-hydra.query-response.v1",
        "session_id": "unavailable_evolution",
        "view_id": "unavailable_evolution",
        "status": "unavailable",
        "hydradb": {
            "available": False,
            "database": config.database or None,
            "collections": [config.evolution_collection],
            "query_by": "hybrid",
            "mode": "thinking",
            "graph_context": True,
            "path_ids": [],
            "origin": None,
            "cross_collection_traversal": False,
            "memory_used": False,
        },
        "revision": revision,
        "paths": [],
        "relations": [],
        "chunk_id_to_group_ids": {},
        "chunks": [],
        "sources": [],
        "additional_context": [],
        "warnings": ["Evolution service is not configured; no fallback retrieval was used."],
        "budget": {
            "max_context_chars": 1,
            "returned_context_chars": 0,
            "max_paths": 0,
            "returned_paths": 0,
            "max_relations": 0,
            "returned_relations": 0,
            "truncated": False,
        },
    }
