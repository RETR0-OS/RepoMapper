"""Repository-specific MCP tools over the HydraDB query service."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from mcp.server.auth.settings import (
    AuthSettings,
    ClientRegistrationOptions,
    RevocationOptions,
)
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .query import QUERY_RESPONSE_SCHEMA, QueryRequest
from .views import ViewDepth, ViewMode, build_product_view


def create_mcp_server(
    services: Any | None = None,
    *,
    oauth_provider: Any | None = None,
    issuer_url: str | None = None,
    service_resolver: Callable[[str], Any] | None = None,
) -> FastMCP:
    if services is None:
        from .api import create_container

        services = create_container()
    oauth_options: dict[str, Any] = {}
    if oauth_provider is not None:
        if issuer_url is None:
            raise ValueError("OAuth issuer URL is required")
        from .mcp_oauth import READ_ONLY_SCOPES

        oauth_options = {
            "auth_server_provider": oauth_provider,
            "auth": AuthSettings(
                issuer_url=issuer_url,
                resource_server_url=f"{issuer_url.rstrip('/')}/mcp",
                required_scopes=[READ_ONLY_SCOPES[0]],
                client_registration_options=ClientRegistrationOptions(
                    enabled=True,
                    client_secret_expiry_seconds=86_400,
                    valid_scopes=list(READ_ONLY_SCOPES),
                    default_scopes=list(READ_ONLY_SCOPES),
                ),
                revocation_options=RevocationOptions(enabled=True),
            ),
        }
    server = FastMCP(
        "hack-hydra",
        instructions=(
            "Repository observability tools backed by HydraDB. Returned paths are HydraDB query "
            "results, not hidden model reasoning. Empty unavailable results must not be replaced "
            "with local repository search."
        ),
        streamable_http_path="/mcp",
        max_request_body_size=1_048_576,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[
                "127.0.0.1",
                "127.0.0.1:*",
                "localhost",
                "localhost:*",
                "[::1]",
                "[::1]:*",
            ],
            allowed_origins=[
                "http://127.0.0.1:*",
                "http://localhost:*",
                "http://[::1]:*",
            ],
        ),
        **oauth_options,
    )

    def current_services() -> Any:
        if oauth_provider is None:
            return services
        from mcp.server.auth.middleware.auth_context import get_access_token

        access = get_access_token()
        if access is None or not access.subject or service_resolver is None:
            raise ValueError("Authenticated MCP project is unavailable")
        try:
            return service_resolver(access.subject)
        except LookupError as exc:
            raise ValueError("Authenticated MCP project is unavailable") from exc

    def remember(
        scoped: Any,
        result: dict[str, Any],
        mode: ViewMode = ViewMode.TRACE,
    ) -> None:
        view = build_product_view(
            result,
            mode=mode,
            depth=ViewDepth.SYMBOL,
            max_nodes=100,
            max_edges=200,
        )
        scoped.views.store.put(view, result)

    @server.tool(
        description="Ask a conceptual repository question using HydraDB hybrid graph retrieval."
    )
    def repository_query(
        question: str,
        revision: str = "current",
        max_results: int = 8,
        max_context_chars: int = 100_000,
        relation_quality: list[str] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        scoped = current_services()
        result = scoped.queries.repository_query(
            QueryRequest(
                question=question,
                revision=revision,
                max_results=max_results,
                max_context_chars=max_context_chars,
                relation_quality=tuple(relation_quality or ("exact", "inferred")),
                session_id=_observe_session_id(scoped, session_id),
            )
        )
        remember(scoped, result)
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
        scoped = current_services()
        if direction not in {"in", "out", "both"}:
            raise ValueError("direction must be in, out, or both")
        if not 1 <= depth <= 8:
            raise ValueError("depth must be between 1 and 8")
        # Only the symbol and its path are searched for. Direction, depth, and the
        # relation list are selection rules; as prose they would become search terms
        # and match whatever text resembles them.
        result = scoped.queries.repository_query(
            QueryRequest(
                question=f"{symbol} {path}".strip() if path else symbol,
                max_results=min(50, max(1, budget)),
                max_context_chars=100_000,
                max_paths=min(8, depth),
                max_relations=max(0, budget),
                query_by="text",
                mode="fast" if depth == 1 else "thinking",
                session_id=_observe_session_id(scoped, session_id),
            )
        )
        removed = _select_hops(result, symbol=symbol, relations=relations, direction=direction)
        result["warnings"].append(
            "focus_symbol uses bounded HydraDB retrieval and may not enumerate every graph "
            "neighbor."
        )
        if removed:
            result["warnings"].append(
                f"Hid {removed} returned hop(s) that did not match the requested relations or "
                "direction. No stored fact was changed."
            )
        remember(scoped, result, ViewMode.EXPLORE)
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
        scoped = current_services()
        if not 1 <= max_hops <= 20:
            raise ValueError("max_hops must be between 1 and 20")
        if not 1 <= max_paths <= 10:
            raise ValueError("max_paths must be between 1 and 10")
        endpoints = ""
        if from_entity:
            endpoints += f" Start from {from_entity}."
        if to_entity:
            endpoints += f" End at {to_entity}."
        result = scoped.queries.repository_query(
            QueryRequest(
                question=f"{question.strip()}{endpoints}",
                max_results=min(50, max(8, max_hops * max_paths)),
                max_context_chars=100_000,
                max_paths=max_paths,
                max_relations=max_hops * max_paths,
                max_hops_per_path=max_hops,
                query_by="hybrid",
                mode="thinking",
                graph_context=True,
                session_id=_observe_session_id(scoped, session_id),
            )
        )
        remember(scoped, result)
        return result

    @server.tool(description="Explain one relationship already returned in a bounded HydraDB view.")
    def explain_relationship(view_id: str, relationship_id: str) -> dict[str, Any]:
        scoped = current_services()
        explanation = scoped.views.explain_relationship(view_id, relationship_id)
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
        scoped = current_services()
        if not 1 <= max_changes <= 500:
            raise ValueError("max_changes must be between 1 and 500")
        evolution = getattr(scoped, "evolution", None)
        if evolution is None:
            return _missing_evolution_result(scoped, revision=after)
        result = evolution.compare(
            before_revision_id=before,
            after_revision_id=after,
            focus=focus,
            max_changes=max_changes,
            session_id=_observe_session_id(scoped, session_id),
        )
        remember(scoped, result, ViewMode.COMPARE)
        return result

    @server.tool(
        description="Retrieve a saved system lens and its current grounded path from HydraDB."
    )
    def open_system_lens(
        lens: str,
        revision: str = "current",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        scoped = current_services()
        evolution = getattr(scoped, "evolution", None)
        if evolution is None:
            return _missing_evolution_result(scoped, revision=revision)
        result = evolution.open_lens(
            lens=lens,
            session_id=_observe_session_id(scoped, session_id),
        )
        if revision != "current":
            result["warnings"].append(
                "The revision argument does not trigger cross-collection traversal; this "
                "returns the saved shared-lens record only."
            )
        remember(scoped, result, ViewMode.PRESERVE)
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
        scoped = current_services()
        session_id = _observe_session_id(scoped, session_id) or session_id
        stored = scoped.views.store.get(view_id)
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
        event = scoped.events.emit(
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

    @server.tool(
        description="""Signal entry into a graph point. 
        Starts a new traversal track from the named entity."""
    )
    def traversal_enter(
        entity: str,
        path: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        scoped = current_services()
        resolved_session = _observe_session_id(scoped, session_id)
        if not resolved_session:
            return {"status": "no_session", 
            "warning": "No active Observe session. Start one before traversing."}
        result = scoped.queries.repository_query(
            QueryRequest(
                question=f"{entity} {path}".strip() if path else entity,
                max_results=12,
                max_context_chars=100_000,
                query_by="text",
                mode="fast",
                session_id=resolved_session,
            )
        )
        entity_ids = tuple(
            str(chunk.get("node_id"))
            for chunk in result.get("chunks", [])
            if chunk.get("node_id")
        )
        session = scoped.observe_sessions.require(resolved_session, active=True)
        scoped.events.emit(
            "traversal_entered",
            session_id=resolved_session,
            revision_id=session.revision_id,
            entity_ids=entity_ids[:100],
            hydradb_query_metadata={"entity": entity, "path": path},
        )
        remember(scoped, result, ViewMode.EXPLORE)
        return result

    @server.tool(
        description="""Follow an edge from one entity to another. 
        Signals the agent is navigating deeper along a relationship."""
    )
    def traversal_follow(
        from_entity: str,
        edge_predicate: str,
        to_entity: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        scoped = current_services()
        resolved_session = _observe_session_id(scoped, session_id)
        if not resolved_session:
            return {"status": "no_session", 
            "warning": "No active Observe session. Start one before traversing."
        }
        result = scoped.queries.repository_query(
            QueryRequest(
                question=to_entity,
                max_results=12,
                max_context_chars=100_000,
                max_relations=20,
                query_by="text",
                mode="fast",
                relation_quality=("exact", "inferred"),
                session_id=resolved_session,
            )
        )
        entity_ids = tuple(
            str(chunk.get("node_id"))
            for chunk in result.get("chunks", [])
            if chunk.get("node_id")
        )
        relationship_ids = tuple(
            str(hop.get("relation", {}).get("id"))
            for group in result.get("relations", [])
            for hop in group.get("hops", [])
            if hop.get("relation", {}).get("id")
            and str(hop.get("relation", {}).get("predicate", "")).upper() == edge_predicate.upper()
        )
        session = scoped.observe_sessions.require(resolved_session, active=True)
        scoped.events.emit(
            "traversal_followed",
            session_id=resolved_session,
            revision_id=session.revision_id,
            entity_ids=entity_ids[:100],
            relationship_ids=relationship_ids[:100],
            hydradb_query_metadata={"from_entity": from_entity, 
            "edge_predicate": edge_predicate, 
            "to_entity": to_entity},
        )
        remember(scoped, result, ViewMode.EXPLORE)
        return result

    @server.tool(
        description="""Abandon the current traversal path. 
        Signals the agent gathered enough context or hit a dead end."""
    )
    def traversal_abandon(
        reason: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        scoped = current_services()
        resolved_session = _observe_session_id(scoped, session_id)
        if not resolved_session:
            return {"status": "no_session", 
            "warning": "No active Observe session. Start one before traversing."}
        session = scoped.observe_sessions.require(resolved_session, active=True)
        scoped.events.emit(
            "traversal_abandoned",
            session_id=resolved_session,
            revision_id=session.revision_id,
            hydradb_query_metadata={"reason": reason} if reason else None,
        )
        return {"status": "abandoned", "reason": reason}

    return server


def _select_hops(
    result: dict[str, Any],
    *,
    symbol: str,
    relations: Sequence[str] | None,
    direction: str,
) -> int:
    """Keep only the hops the caller asked for, and report how many were hidden.

    This selects among facts HydraDB already returned and proved. It removes nothing
    from the repository and upgrades nothing: a hidden hop stays a stored fact, exactly
    as clearing a predicate chip does in the panel.
    """

    wanted = {str(item).strip().upper() for item in relations or () if str(item).strip()}
    if not wanted and direction == "both":
        return 0
    focus = {
        str(chunk.get("node_id"))
        for chunk in result.get("chunks", [])
        if chunk.get("node_id")
        and symbol.strip()
        and str(chunk.get("qualified_name") or "").split(".")[-1] == symbol.strip().split(".")[-1]
    }

    def keep(hop: dict[str, Any]) -> bool:
        predicate = str(hop.get("relation", {}).get("predicate") or "").upper()
        if wanted and predicate not in wanted:
            return False
        if direction == "both" or not focus:
            return True
        side = "source" if direction == "out" else "target"
        return str(hop.get(side, {}).get("id") or "") in focus

    removed = 0
    for name in ("paths", "relations"):
        groups = []
        for group in result.get(name, []):
            hops = [hop for hop in group.get("hops", []) if keep(hop)]
            removed += len(group.get("hops", [])) - len(hops)
            if hops:
                groups.append({**group, "hops": hops})
        result[name] = groups
    return removed


def _observe_session_id(services: Any, session_id: str | None) -> str | None:
    sessions = getattr(services, "observe_sessions", None)
    if sessions is None:
        return session_id
    if session_id is not None:
        try:
            sessions.require(session_id, active=True)
        except LookupError:
            # Explicit bounded IDs remain valid independent MCP correlation IDs.
            return session_id
        except RuntimeError as exc:
            raise ValueError("Observe session is inactive") from exc
        return session_id
    try:
        resolved = sessions.resolve(None)
    except RuntimeError as exc:
        raise ValueError("Observe session is ambiguous") from exc
    return resolved.session_id if resolved is not None else None


def tool_names(server: FastMCP) -> Sequence[str]:
    """Small test/diagnostic helper that does not depend on manager internals."""

    import asyncio

    return tuple(tool.name for tool in asyncio.run(server.list_tools()))


def _missing_evolution_result(services: Any, *, revision: str) -> dict[str, Any]:
    config = services.queries.client.config
    return {
        "response_schema": QUERY_RESPONSE_SCHEMA,
        "session_id": "unavailable_evolution",
        "view_id": "unavailable_evolution",
        "status": "unavailable",
        "hydradb": {
            "available": False,
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
