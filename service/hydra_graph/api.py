"""FastAPI surface shared by the VS Code extension and local workflows."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Literal
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .analyzer import analyze_repository
from .cards import SourceCard, build_source_cards
from .config import HydraDBConfig
from .discovery import DiscoveryReport, discover_files
from .events import (
    EventBus,
    EventHistoryGap,
    ObserveSessionInactive,
    ObserveSessionLimit,
    ObserveSessionNotFound,
    ObserveSessions,
)
from .evolution_service import EvolutionService
from .hydradb import CredentialProvider, HydraDBClient, HydraDBError
from .ids import normalize_relative_path, normalize_repository_id
from .indexing_service import (
    IndexPreviewConflict,
    IndexPreviewStore,
    PreparedIndex,
    prepare_automatic_index,
)
from .models import GraphNode
from .query import QUERY_RESPONSE_SCHEMA, QueryService
from .security import MANAGED_SERVICE_PROTOCOL, MAX_REQUEST_BYTES, ManagedSecurity
from .sync import SyncService
from .views import ViewDepth, ViewMode, ViewRequest, ViewService, build_product_view


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QueryBody(APIModel):
    question: str = Field(min_length=1, max_length=4_000)
    depth: ViewDepth = ViewDepth.SYMBOL
    revision: str = "current"
    max_nodes: int = Field(default=50, ge=1, le=500)
    max_edges: int = Field(default=80, ge=0, le=1_000)
    max_context_chars: int = Field(default=7_000, ge=1, le=100_000)
    query_by: Literal["hybrid", "text"] = "hybrid"
    mode: Literal["fast", "thinking"] = "thinking"
    graph_context: bool = True
    session_id: str | None = None


class ActionBody(APIModel):
    selected_id: str | None = Field(default=None, max_length=1_024)
    question: str | None = Field(default=None, max_length=4_000)
    depth: ViewDepth = ViewDepth.SYMBOL
    revision: str = "current"


class IndexPreviewBody(APIModel):
    pass


class IndexConfirmBody(APIModel):
    preview_token: str = Field(min_length=40, max_length=128)


class CheckpointBody(APIModel):
    revision_id: str = Field(min_length=1, max_length=256)


class PublishDeltaBody(APIModel):
    before_revision_id: str = Field(min_length=1, max_length=256)
    after_revision_id: str = Field(min_length=1, max_length=256)
    confirm: bool = False


class SaveLensBody(APIModel):
    name: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=2_000)
    view_id: str = Field(min_length=1, max_length=256)
    notes: str | None = Field(default=None, max_length=4_000)
    confirm: bool = False


class AcceptLensBody(APIModel):
    view_id: str = Field(min_length=1, max_length=256)
    confirm: bool = False


class EmptyBody(APIModel):
    pass


class ViewItemBody(APIModel):
    item_id: str = Field(min_length=1, max_length=1_024)
    item_kind: Literal["node", "edge"]


class WorkspaceChangeBody(APIModel):
    path: str = Field(min_length=1, max_length=1_024)


class AttachProjectBody(APIModel):
    repository_root: str = Field(min_length=1, max_length=4_096)
    repository_id: str = Field(min_length=1, max_length=128)
    timestamp: int
    nonce: str = Field(min_length=16, max_length=128)
    signature: str = Field(min_length=43, max_length=128)


@dataclass(slots=True)
class ServiceContainer:
    config: HydraDBConfig
    client: HydraDBClient
    events: EventBus
    queries: QueryService
    views: ViewService
    sync: SyncService
    repository_root: Path
    evolution: EvolutionService | None = None
    observe_sessions: ObserveSessions | None = None
    credential_provider: CredentialProvider | None = None
    index_previews: IndexPreviewStore | None = None


class RepositoryScopes:
    """Keep independent repository state for each extension workspace."""

    def __init__(self, default: ServiceContainer) -> None:
        self.default = default
        self._lock = RLock()
        self._scopes: dict[tuple[str, str], ServiceContainer] = {
            self._key(default.repository_root, default.sync.repository_id): default
        }

    def get(self, repository_root: str, repository_id: str) -> ServiceContainer:
        try:
            root = Path(unquote(repository_root)).resolve()
            normalized_id = normalize_repository_id(repository_id)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Repository scope is invalid.") from exc
        if not root.is_dir():
            raise HTTPException(
                status_code=422, detail="Repository root must be an existing directory."
            )
        key = self._key(root, normalized_id)
        with self._lock:
            existing = self._scopes.get(key)
            if existing is not None:
                return existing
            events = EventBus()
            client = HydraDBClient(
                self.default.config,
                repository_id=normalized_id,
                credential_provider=self.default.credential_provider,
            )
            sync = SyncService(
                client,
                repository_id=normalized_id,
                events=events,
                manifest_path=_contained_manifest_path(root),
            )
            scoped = _build_container(
                resolved_config=self.default.config,
                resolved_repository_id=normalized_id,
                root=root,
                events=events,
                client=client,
                sync=sync,
                credential_provider=client.credential_provider,
            )
            self._scopes[key] = scoped
            return scoped

    def by_repository_id(self, repository_id: str) -> ServiceContainer:
        normalized_id = normalize_repository_id(repository_id)
        with self._lock:
            matches = [
                scope
                for scope in self._scopes.values()
                if scope.sync.repository_id == normalized_id
            ]
        if len(matches) != 1:
            raise LookupError("OAuth project is unavailable or ambiguous")
        return matches[0]

    @staticmethod
    def _key(root: Path, repository_id: str) -> tuple[str, str]:
        canonical = str(root.resolve()).replace("\\", "/")
        if os.name == "nt":
            canonical = canonical.casefold()
        return canonical.rstrip("/") or "/", repository_id


class ScopedServiceProxy:
    def __init__(self, current: ContextVar[ServiceContainer]) -> None:
        object.__setattr__(self, "_current", current)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._current.get(), name)


def create_container(
    config: HydraDBConfig | None = None,
    *,
    repository_id: str | None = None,
    repository_root: str | Path | None = None,
    credential_provider: CredentialProvider | None = None,
) -> ServiceContainer:
    resolved_config = config or HydraDBConfig.from_env()
    resolved_repository_id = (
        repository_id
        or os.environ.get("HYDRA_REPOSITORY_ID")
        or resolved_config.database
        or "unconfigured-repository"
    )
    root = Path(repository_root or os.environ.get("HYDRA_REPOSITORY_ROOT") or Path.cwd()).resolve()
    manifest_path = _contained_manifest_path(root)

    events = EventBus()
    client = HydraDBClient(
        resolved_config,
        repository_id=resolved_repository_id,
        credential_provider=credential_provider,
    )
    sync = SyncService(
        client,
        repository_id=resolved_repository_id,
        events=events,
        manifest_path=manifest_path,
    )
    return _build_container(
        resolved_config=resolved_config,
        resolved_repository_id=resolved_repository_id,
        root=root,
        events=events,
        client=client,
        sync=sync,
        credential_provider=client.credential_provider,
    )


def _contained_manifest_path(root: Path, candidate: Path | None = None) -> Path:
    root = root.resolve()
    manifest_path = (candidate or root / ".hydra-graph" / "manifest.json").resolve()
    try:
        manifest_path.relative_to(root)
    except ValueError as exc:
        raise ValueError("Sync manifest path escapes the configured repository root") from exc
    return manifest_path


def repository_root_fingerprint(root: str | Path) -> str:
    """Return a stable opaque identity for the configured canonical repository root."""

    canonical = str(Path(root).resolve()).replace("\\", "/")
    if os.name == "nt":
        canonical = canonical.lower()
    canonical = canonical.rstrip("/") or "/"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _build_container(
    *,
    resolved_config: HydraDBConfig,
    resolved_repository_id: str,
    root: Path,
    events: EventBus,
    client: HydraDBClient,
    sync: SyncService,
    credential_provider: CredentialProvider,
) -> ServiceContainer:
    queries = QueryService(
        client,
        repository_id=resolved_repository_id,
        events=events,
        verified_revision=lambda: sync.status["ready_revision"],
        current_state_indeterminate=lambda: (
            sync.status["status"] == "indexing" or bool(sync.status["current_state_indeterminate"])
        ),
    )
    views = ViewService(queries)
    from .checkpoints import CheckpointStore

    evolution = EvolutionService(
        client,
        repository_id=resolved_repository_id,
        repository_root=root,
        checkpoints=CheckpointStore(root, repository_id=resolved_repository_id),
        views=views.store,
        current_queries=queries,
        events=events,
        verified_revision=lambda: sync.status["ready_revision"],
        current_state_unsafe=lambda: (
            sync.status["status"] == "indexing" or bool(sync.status["current_state_indeterminate"])
        ),
        snapshot_verifier=sync.verifies_snapshot,
    )
    return ServiceContainer(
        config=resolved_config,
        client=client,
        events=events,
        queries=queries,
        views=views,
        sync=sync,
        repository_root=root,
        evolution=evolution,
        observe_sessions=ObserveSessions(events),
        credential_provider=credential_provider,
        index_previews=IndexPreviewStore(root, resolved_repository_id),
    )


def create_app(
    container: ServiceContainer | None = None,
    *,
    managed_security: ManagedSecurity | None = None,
    mcp_oauth_provider: Any | None = None,
    mcp_issuer_url: str | None = None,
) -> FastAPI:
    services = container or create_container()
    if services.observe_sessions is None:
        services.observe_sessions = ObserveSessions(services.events)
    repository_scopes = RepositoryScopes(services)
    current_services: ContextVar[ServiceContainer] = ContextVar(
        "hydra_repository_services", default=services
    )
    from .mcp_server import create_mcp_server

    mcp_server = create_mcp_server(
        services,
        oauth_provider=mcp_oauth_provider,
        issuer_url=mcp_issuer_url,
        service_resolver=repository_scopes.by_repository_id,
    )
    mcp_app = mcp_server.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    app = FastAPI(
        title="Hack Hydra Repository Service",
        version="0.1.0",
        description=(
            "HydraDB-backed repository views for people and coding agents. The mounted MCP "
            "endpoint is /mcp and shares this process's Observe events and views."
        ),
        lifespan=lifespan,
    )
    app.state.services = services
    app.state.mcp_server = mcp_server
    app.state.repository_scopes = repository_scopes

    @app.middleware("http")
    async def select_repository_scope(request: Request, call_next: Any) -> Any:
        if managed_security is not None:
            if not managed_security.host_is_allowed(request.headers.get("host")):
                return JSONResponse(status_code=421, content={"detail": "Loopback host required."})
            content_length = request.headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > MAX_REQUEST_BYTES:
                        return JSONResponse(
                            status_code=413, content={"detail": "Request body is too large."}
                        )
                except ValueError:
                    return JSONResponse(
                        status_code=400, content={"detail": "Content-Length is invalid."}
                    )
            oauth_paths = {
                "/mcp",
                "/authorize",
                "/token",
                "/register",
                "/revoke",
                "/.well-known/oauth-authorization-server",
                "/.well-known/oauth-protected-resource/mcp",
            }
            if request.url.path in {"/version", "/managed/challenge"} or (
                mcp_oauth_provider is not None and request.url.path in oauth_paths
            ):
                return await call_next(request)
            try:
                grant = managed_security.authorize(request.headers.get("authorization"))
                scoped = repository_scopes.get(str(grant.repository_root), grant.repository_id)
            except RuntimeError as exc:
                return JSONResponse(status_code=429, content={"detail": str(exc)})
            except (HTTPException, ValueError) as exc:
                detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
                return JSONResponse(status_code=401, content={"detail": detail})
            token = current_services.set(scoped)
            try:
                return await call_next(request)
            finally:
                current_services.reset(token)
        repository_root = request.headers.get("X-Hydra-Repository-Root")
        repository_id = request.headers.get("X-Hydra-Repository-Id")
        if repository_root is None and repository_id is None:
            return await call_next(request)
        if repository_root is None or repository_id is None:
            return JSONResponse(
                status_code=422,
                content={
                    "detail": "Repository root and repository ID headers must be provided together."
                },
            )
        try:
            scoped = repository_scopes.get(repository_root, repository_id)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        token = current_services.set(scoped)
        try:
            return await call_next(request)
        finally:
            current_services.reset(token)

    services = ScopedServiceProxy(current_services)  # type: ignore[assignment]

    @app.get("/version")
    def version() -> dict[str, Any]:
        return {
            "service": "repository-map",
            "protocol": MANAGED_SERVICE_PROTOCOL,
            "version": "0.2.0",
        }

    @app.post("/managed/challenge")
    def attach_project(body: AttachProjectBody) -> dict[str, Any]:
        if managed_security is None:
            raise HTTPException(status_code=404, detail="Managed attachment is unavailable.")
        try:
            repository_id = normalize_repository_id(body.repository_id)
            token, grant = managed_security.attach(
                repository_root=body.repository_root,
                repository_id=repository_id,
                timestamp=body.timestamp,
                nonce=body.nonce,
                signature=body.signature,
            )
            repository_scopes.get(str(grant.repository_root), grant.repository_id)
            register_project = getattr(mcp_oauth_provider, "register_project", None)
            if callable(register_project):
                register_project(grant.repository_root, grant.repository_id)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return {
            "protocol": MANAGED_SERVICE_PROTOCOL,
            "access_token": token,
            "expires_at": grant.expires_at,
            "repository_id": grant.repository_id,
        }

    @app.get("/health")
    def health() -> dict[str, Any]:
        sync_status = services.sync.status
        if not services.client.configured:
            state = "unavailable"
            message = "Configure HydraDB credentials for this project in Repository Map setup."
        elif sync_status["status"] in {"indexing", "failed", "unavailable"}:
            state = sync_status["status"]
            message = {
                "indexing": "HydraDB is indexing a candidate revision.",
                "failed": (
                    "The latest index attempt failed. The reported revision is only the last "
                    "verified "
                    "marker; current HydraDB content may be indeterminate."
                ),
                "unavailable": "HydraDB is unavailable; no local retrieval fallback is active.",
            }[state]
        else:
            verified = sync_status["ready_revision"] is not None
            state = "ready" if verified else "unverified"
            message = (
                "The reported HydraDB repository revision completed graph indexing."
                if verified
                else (
                    "HydraDB retrieval is configured, but this process has not verified the "
                    "current collection revision."
                )
            )
        return {
            "state": state,
            "revision_id": sync_status["ready_revision"] or "current",
            "revision_verified": sync_status["ready_revision"] is not None,
            "verification_status": (
                "verified" if sync_status["ready_revision"] is not None else "configured_unverified"
            ),
            "credentials_configured": services.client.configured,
            "collection": services.config.collection,
            "source_count": sync_status["source_count"],
            "repository_id": services.sync.repository_id,
            "repository_root_fingerprint": repository_root_fingerprint(services.repository_root),
            "mcp_endpoint": "/mcp",
            "message": message,
        }

    @app.post("/api/setup/test")
    def test_hydradb_access(_: EmptyBody) -> dict[str, Any]:
        try:
            services.client.query(
                query="Repository Map connection check",
                graph_context=False,
                max_results=1,
                query_by="text",
                mode="fast",
                metadata_filters={"repository_id": services.sync.repository_id},
            )
        except HydraDBError as exc:
            raise HTTPException(status_code=503, detail="HydraDB read access failed.") from exc
        return {"status": "connected", "write_performed": False}

    @app.post("/api/query")
    def query_repository(body: QueryBody) -> dict[str, Any]:
        if body.session_id is not None:
            _require_query_session(services, body)
        query_result = services.queries.repository_query(_query_request_from_api(body))
        view = build_product_view(
            query_result,
            mode=ViewMode.TRACE,
            depth=body.depth,
            max_nodes=body.max_nodes,
            max_edges=body.max_edges,
        )
        services.views.store.put(view, query_result)
        return view

    @app.post("/api/observe/sessions", status_code=201)
    def start_observe_session(_: EmptyBody) -> dict[str, Any]:
        sync_status = services.sync.status
        revision_id = sync_status.get("ready_revision")
        if (
            sync_status.get("status") != "ready"
            or not revision_id
            or not sync_status.get("hydradb_available")
            or sync_status.get("current_state_indeterminate")
        ):
            raise HTTPException(
                status_code=409,
                detail="Observe requires a currently verified HydraDB revision.",
            )
        try:
            session, event = services.observe_sessions.start(str(revision_id))
        except ObserveSessionLimit as exc:
            raise HTTPException(
                status_code=429,
                detail="Too many Observe sessions are active.",
            ) from exc
        return {
            "status": "active",
            "session_id": session.session_id,
            "revision_id": session.revision_id,
            "repository_root_fingerprint": repository_root_fingerprint(services.repository_root),
            "event": event.as_dict(),
        }

    @app.post("/api/observe/sessions/{session_id}/complete")
    def complete_observe_session(session_id: str, _: EmptyBody) -> dict[str, Any]:
        try:
            session, event = services.observe_sessions.complete(session_id)
        except ObserveSessionNotFound as exc:
            raise HTTPException(status_code=404, detail="Observe session was not found.") from exc
        except ObserveSessionInactive as exc:
            raise HTTPException(
                status_code=409,
                detail="Observe session is already complete.",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Observe session ID is invalid.") from exc
        return {
            "status": "completed",
            "session_id": session.session_id,
            "event": event.as_dict(),
        }

    @app.get("/api/views/by-id/{view_id}")
    def get_view_by_id(view_id: str) -> dict[str, Any]:
        stored = _stored_hydradb_view(services, view_id)
        return dict(stored["view"])

    @app.post("/api/views/{view_id}/selection")
    def record_selection(view_id: str, body: ViewItemBody) -> dict[str, Any]:
        return _record_view_item(
            services,
            view_id=view_id,
            body=body,
            event_type="context_selected",
            require_evidence=False,
        )

    @app.post("/api/views/{view_id}/evidence-opened")
    def record_evidence_opened(view_id: str, body: ViewItemBody) -> dict[str, Any]:
        return _record_view_item(
            services,
            view_id=view_id,
            body=body,
            event_type="evidence_opened",
            require_evidence=True,
        )

    @app.post("/api/views/{view_id}/workspace-change")
    def record_workspace_change(view_id: str, body: WorkspaceChangeBody) -> dict[str, Any]:
        stored, session_id, revision_id = _observe_view_context(services, view_id)
        try:
            relative_path = normalize_relative_path(body.path)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="Workspace change path must stay inside the configured repository.",
            ) from exc
        if relative_path == ".":
            raise HTTPException(status_code=422, detail="Workspace change path must name a file.")
        try:
            resolved = (services.repository_root / relative_path).resolve()
        except OSError as exc:
            raise HTTPException(
                status_code=422,
                detail="Workspace change path could not be validated.",
            ) from exc
        try:
            resolved.relative_to(services.repository_root.resolve())
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="Workspace change path must stay inside the configured repository.",
            ) from exc
        view = stored["view"]
        compared_path = relative_path.casefold() if os.name == "nt" else relative_path
        entity_ids = tuple(
            dict.fromkeys(
                str(node["id"])
                for node in view.get("nodes", [])
                if isinstance(node, Mapping)
                and isinstance(node.get("path"), str)
                and (str(node["path"]).casefold() if os.name == "nt" else str(node["path"]))
                == compared_path
            )
        )[:100]
        if not entity_ids:
            raise HTTPException(
                status_code=422,
                detail="Workspace change path is not shown in this bounded view.",
            )
        event = services.events.emit(
            "workspace_entity_changed",
            session_id=session_id,
            revision_id=revision_id,
            view_id=view_id,
            entity_ids=entity_ids,
        )
        return {"status": "recorded", "event": event.as_dict()}

    @app.get("/api/views/{mode}")
    def get_view(
        mode: ViewMode,
        depth: ViewDepth = ViewDepth.FILE,
        question: str | None = Query(default=None, max_length=4_000),
        revision: str = "current",
        max_nodes: int = Query(default=50, ge=1, le=500),
        max_edges: int = Query(default=80, ge=0, le=1_000),
        before_revision: str | None = Query(default=None, max_length=256),
        after_revision: str | None = Query(default=None, max_length=256),
        lens: str | None = Query(default=None, max_length=200),
    ) -> dict[str, Any]:
        if mode is ViewMode.COMPARE:
            if services.evolution is None or not before_revision or not after_revision:
                return _empty_evolution_view(
                    services,
                    mode=mode,
                    depth=depth,
                    revision=after_revision or "current",
                    max_nodes=max_nodes,
                    max_edges=max_edges,
                    warning="Compare requires captured before_revision and after_revision IDs.",
                )
            result = services.evolution.compare(
                before_revision_id=before_revision,
                after_revision_id=after_revision,
                focus=question,
                max_changes=max_edges,
            )
            return _view_from_evolution_result(services, result, mode, depth, max_nodes, max_edges)
        if mode is ViewMode.PRESERVE:
            if services.evolution is None or not lens:
                return _empty_evolution_view(
                    services,
                    mode=mode,
                    depth=depth,
                    revision=revision,
                    max_nodes=max_nodes,
                    max_edges=max_edges,
                    warning="Preserve requires a shared lens name or ID.",
                )
            result = services.evolution.open_lens(lens=lens)
            return _view_from_evolution_result(services, result, mode, depth, max_nodes, max_edges)
        return services.views.load(
            ViewRequest(
                mode=mode,
                revision=revision,
                depth=depth,
                question=question,
                max_nodes=max_nodes,
                max_edges=max_edges,
            )
        )

    @app.post("/api/views/{mode}/action")
    def view_action(mode: ViewMode, body: ActionBody) -> dict[str, Any]:
        if mode is ViewMode.REPOSITORY:
            return {
                "message": (
                    "Layout reset is presentation state and does not change repository truth."
                )
            }
        if mode is ViewMode.OBSERVE:
            return {
                "message": (
                    "Observe following is presentation state; observable events remain available."
                )
            }
        focus = body.question or body.selected_id
        question = f"Expand the HydraDB-backed repository context for {focus}." if focus else None
        view = services.views.load(
            ViewRequest(
                mode=mode,
                revision=body.revision,
                depth=body.depth,
                question=question,
            )
        )
        return {"message": f"Loaded a bounded {mode.value} result from HydraDB.", "view": view}

    @app.get("/api/sidebar")
    def sidebar() -> dict[str, Any]:
        return {
            "current_symbol": None,
            "entrypoints": [],
            "lenses": [],
            "changes": [],
            "activity": services.events.recent()[-20:],
            "health": health(),
        }

    @app.get("/api/events")
    def events(
        session_id: str = Query(min_length=1, max_length=256),
        after_event_id: str | None = Query(default=None, min_length=1, max_length=256),
    ) -> list[dict[str, Any]]:
        try:
            services.observe_sessions.require(session_id)
        except ObserveSessionNotFound as exc:
            raise HTTPException(status_code=404, detail="Observe session was not found.") from exc
        try:
            return services.events.recent(
                session_id=session_id,
                after_event_id=after_event_id,
            )
        except EventHistoryGap as exc:
            raise HTTPException(
                status_code=409,
                detail="Observe event history has a gap; restart the session.",
            ) from exc

    @app.post("/api/events", include_in_schema=False)
    def raw_event_write_is_forbidden() -> None:
        raise HTTPException(status_code=405, detail="Raw event writes are not allowed.")

    @app.get("/api/events/stream")
    def event_stream() -> StreamingResponse:
        scoped_events = services.events

        def generate() -> Iterator[str]:
            for event in scoped_events.stream():
                if event is None:
                    yield ": heartbeat\n\n"
                else:
                    yield f"event: {event.type}\ndata: {json.dumps(event.as_dict())}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    @app.post("/api/index/preview")
    def index_preview(_: IndexPreviewBody) -> dict[str, Any]:
        prepared = prepare_automatic_index(services.repository_root, services.sync.repository_id)
        store = _require_index_previews(services)
        preview_ref = store.issue(prepared)
        return _automatic_index_preview(services, prepared, preview_ref.token)

    @app.post("/api/index")
    def index_repository(body: IndexConfirmBody) -> dict[str, Any]:
        prepared = prepare_automatic_index(services.repository_root, services.sync.repository_id)
        store = _require_index_previews(services)
        try:
            store.consume(body.preview_token, prepared)
        except IndexPreviewConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        preview = _automatic_index_preview(services, prepared, body.preview_token)
        result = services.sync.sync(prepared.cards, revision_id=prepared.revision_id).as_dict()
        return {"preview": preview, "sync": result}

    @app.post("/api/evolution/checkpoints/{slot}")
    def capture_checkpoint(
        slot: Literal["before", "after"], body: CheckpointBody
    ) -> dict[str, Any]:
        evolution = _require_evolution(services)
        try:
            return evolution.capture_checkpoint(slot, revision_id=body.revision_id)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="Checkpoint capture refused.") from exc

    @app.post("/api/evolution/publish")
    def publish_delta(body: PublishDeltaBody) -> dict[str, Any]:
        evolution = _require_evolution(services)
        try:
            return evolution.publish_delta(
                before_revision_id=body.before_revision_id,
                after_revision_id=body.after_revision_id,
                confirm=body.confirm,
            )
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="Delta publication refused.") from exc

    @app.post("/api/lenses")
    def save_lens(body: SaveLensBody) -> dict[str, Any]:
        evolution = _require_evolution(services)
        try:
            return evolution.save_lens(
                name=body.name,
                purpose=body.purpose,
                view_id=body.view_id,
                notes=body.notes,
                confirm=body.confirm,
            )
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="Shared lens save refused.") from exc

    @app.post("/api/lenses/{lens_id}/accept")
    def accept_lens(lens_id: str, body: AcceptLensBody) -> dict[str, Any]:
        evolution = _require_evolution(services)
        try:
            return evolution.accept_lens(
                lens_id=lens_id,
                view_id=body.view_id,
                confirm=body.confirm,
            )
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="Shared lens update refused.") from exc

    app.mount("/", mcp_app, name="mcp")
    return app


def _require_evolution(services: ServiceContainer) -> EvolutionService:
    if services.evolution is None:
        raise HTTPException(status_code=503, detail="Evolution service is not configured.")
    return services.evolution


def _require_query_session(services: ServiceContainer, body: QueryBody) -> None:
    assert body.session_id is not None
    try:
        session = services.observe_sessions.require(body.session_id, active=True)
    except ObserveSessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Observe session was not found.") from exc
    except ObserveSessionInactive as exc:
        raise HTTPException(status_code=409, detail="Observe session is complete.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Observe session ID is invalid.") from exc
    if body.revision == "current":
        sync_status = services.sync.status
        compatible = bool(
            sync_status.get("status") == "ready"
            and not sync_status.get("current_state_indeterminate")
            and sync_status.get("ready_revision") == session.revision_id
        )
    else:
        compatible = body.revision == session.revision_id
    if not compatible:
        raise HTTPException(
            status_code=409,
            detail="Query revision does not match the active Observe session.",
        )


def _stored_hydradb_view(services: ServiceContainer, view_id: str) -> dict[str, Any]:
    if not view_id.strip() or len(view_id) > 256:
        raise HTTPException(status_code=404, detail="HydraDB view was not found.")
    stored = services.views.store.get(view_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="HydraDB view was not found.")
    view = stored.get("view")
    query = stored.get("query")
    if not isinstance(view, Mapping) or not isinstance(query, Mapping):
        raise HTTPException(status_code=404, detail="HydraDB view was not found.")
    query_hydradb = query.get("hydradb")
    view_hydradb = view.get("hydradb")
    if (
        query.get("response_schema") != QUERY_RESPONSE_SCHEMA
        or query.get("status") != "ready"
        or query.get("view_id") != view_id
        or view.get("view_id") != view_id
        or not isinstance(query_hydradb, Mapping)
        or query_hydradb.get("available") is not True
        or not isinstance(view_hydradb, Mapping)
        or view_hydradb.get("available") is not True
    ):
        raise HTTPException(status_code=404, detail="HydraDB view was not found.")
    return {"view": dict(view), "query": dict(query)}


def _observe_view_context(
    services: ServiceContainer, view_id: str
) -> tuple[dict[str, Any], str, str]:
    stored = _stored_hydradb_view(services, view_id)
    session_id = stored["query"].get("session_id")
    revision_id = stored["view"].get("revision_id")
    if not isinstance(session_id, str) or not isinstance(revision_id, str):
        raise HTTPException(status_code=404, detail="Observe session was not found.")
    try:
        session = services.observe_sessions.require(session_id, active=True)
    except ObserveSessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Observe session was not found.") from exc
    except ObserveSessionInactive as exc:
        raise HTTPException(status_code=409, detail="Observe session is complete.") from exc
    if session.revision_id != revision_id:
        raise HTTPException(
            status_code=409,
            detail="HydraDB view revision does not match the Observe session.",
        )
    return stored, session_id, revision_id


def _record_view_item(
    services: ServiceContainer,
    *,
    view_id: str,
    body: ViewItemBody,
    event_type: Literal["context_selected", "evidence_opened"],
    require_evidence: bool,
) -> dict[str, Any]:
    stored, session_id, revision_id = _observe_view_context(services, view_id)
    collection = "nodes" if body.item_kind == "node" else "edges"
    item = next(
        (
            candidate
            for candidate in stored["view"].get(collection, [])
            if isinstance(candidate, Mapping) and candidate.get("id") == body.item_id
        ),
        None,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="View item was not found.")
    if require_evidence and not _has_openable_evidence(item, body.item_kind):
        raise HTTPException(
            status_code=422,
            detail="View item has no grounded source evidence to open.",
        )
    event = services.events.emit(
        event_type,
        session_id=session_id,
        revision_id=revision_id,
        view_id=view_id,
        entity_ids=(body.item_id,) if body.item_kind == "node" else (),
        relationship_ids=(body.item_id,) if body.item_kind == "edge" else (),
    )
    return {"status": "recorded", "event": event.as_dict()}


def _has_openable_evidence(item: Mapping[str, Any], item_kind: str) -> bool:
    if item_kind == "node":
        span = item.get("span")
        return bool(
            item.get("path") not in {None, "."}
            and isinstance(span, Mapping)
            and span.get("start_line")
            and span.get("end_line")
        )
    evidence = item.get("evidence")
    return bool(
        isinstance(evidence, list)
        and any(
            isinstance(record, Mapping)
            and record.get("path") not in {None, "."}
            and record.get("start_line")
            and record.get("end_line")
            for record in evidence
        )
    )


def _view_from_evolution_result(
    services: ServiceContainer,
    result: Mapping[str, Any],
    mode: ViewMode,
    depth: ViewDepth,
    max_nodes: int,
    max_edges: int,
) -> dict[str, Any]:
    view = build_product_view(
        result,
        mode=mode,
        depth=depth,
        max_nodes=max_nodes,
        max_edges=max_edges,
    )
    if result.get("status") == "ready":
        record_nodes = _evolution_record_nodes(result)
        # Record nodes are first so Compare's review action and Preserve's lens
        # selection remain visible within the same explicit node budget.
        deduplicated: list[dict[str, Any]] = []
        seen: set[str] = set()
        for node in [*record_nodes, *view["nodes"]]:
            if node["id"] not in seen:
                deduplicated.append(node)
                seen.add(node["id"])
        view["nodes"] = deduplicated[:max_nodes]
        allowed = {node["id"] for node in view["nodes"]}
        view["edges"] = [
            edge
            for edge in view["edges"]
            if edge["source_id"] in allowed and edge["target_id"] in allowed
        ][:max_edges]
        view["budget"]["returned_nodes"] = len(view["nodes"])
        view["budget"]["returned_edges"] = len(view["edges"])
        view["budget"]["truncated"] = view["budget"]["truncated"] or len(deduplicated) > max_nodes
    services.views.store.put(view, result)
    return view


def _evolution_record_nodes(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    lens = result.get("lens")
    lens = lens if isinstance(lens, Mapping) else {}
    drift = result.get("drift")
    drift = drift if isinstance(drift, Mapping) else {}
    chunks = [
        item
        for item in (
            *result.get("chunks", []),
            *result.get("evolution_chunks", []),
        )
        if isinstance(item, Mapping) and item.get("entity_kind") in {"CHANGE_EVENT", "SYSTEM_LENS"}
    ]
    fact_state: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for record in result.get("records", []):
        if not isinstance(record, Mapping):
            continue
        for fact in record.get("facts", []):
            if not isinstance(fact, Mapping):
                continue
            kind = str(fact.get("kind") or "")
            state = (
                "added"
                if kind in {"node_added", "relation_added"}
                else "removed"
                if kind in {"node_removed", "relation_removed"}
                else "modified"
            )
            fact_state[str(fact.get("fact_id") or "")] = (state, fact)
    nodes: list[dict[str, Any]] = []
    for chunk in chunks:
        node_id = str(chunk.get("node_id") or "")
        required = ("logical_id", "title", "revision", "content_hash", "parser", "parser_version")
        if not node_id or not all(chunk.get(key) for key in required):
            continue
        state, fact = fact_state.get(node_id, ("modified", {}))
        attributes: dict[str, Any] = {
            "hydradb_source_id": chunk.get("source_id"),
            "hydradb_rank": chunk.get("rank"),
            "state": state,
        }
        if fact:
            attributes.update(
                {
                    "change_kind": fact.get("kind"),
                    "quality": fact.get("quality"),
                    "explanation": fact.get("explanation"),
                }
            )
        if chunk.get("entity_kind") == "SYSTEM_LENS" and lens:
            attributes.update(
                {
                    "name": lens.get("name"),
                    "purpose": lens.get("purpose"),
                    "saved_revision_id": lens.get("saved_revision_id"),
                    "ownership": lens.get("ownership"),
                    "drift_classification": drift.get("classification") or drift.get("kind"),
                    "drift_explanation": drift.get("explanation"),
                }
            )
        candidate = {
            "id": node_id,
            "logical_id": str(chunk["logical_id"]),
            "kind": str(chunk["entity_kind"]),
            "display_name": str(lens.get("name") or chunk["title"]),
            "qualified_name": str(
                lens.get("name") or chunk.get("qualified_name") or chunk["title"]
            ),
            "language": None,
            "path": str(chunk.get("path") or "."),
            "span": None,
            "signature": None,
            "revision_id": str(chunk["revision"]),
            "content_hash": str(chunk["content_hash"]),
            "parser": str(chunk["parser"]),
            "parser_version": str(chunk["parser_version"]),
            "is_generated": False,
            "attributes": attributes,
        }
        try:
            nodes.append(GraphNode.model_validate(candidate).model_dump(mode="json"))
        except ValueError:
            continue
    return nodes


def _empty_evolution_view(
    services: ServiceContainer,
    *,
    mode: ViewMode,
    depth: ViewDepth,
    revision: str,
    max_nodes: int,
    max_edges: int,
    warning: str,
) -> dict[str, Any]:
    result = {
        "view_id": f"view_{uuid.uuid4().hex}",
        "status": "degraded",
        "revision": revision,
        "paths": [],
        "relations": [],
        "chunks": [],
        "warnings": [warning],
        "hydradb": {
            "available": services.client.configured,
            "collections": [services.config.evolution_collection],
            "graph_context": True,
            "path_ids": [],
            "origin": None,
        },
        "budget": {"truncated": False},
    }
    return _view_from_evolution_result(services, result, mode, depth, max_nodes, max_edges)


def _query_request_from_api(body: QueryBody):
    # Kept local to avoid turning Pydantic transport models into query-domain
    # models or allowing extension defaults to bypass service validation.
    from .query import QueryRequest

    return QueryRequest(
        question=body.question,
        revision=body.revision,
        max_results=min(50, max(4, body.max_nodes)),
        max_context_chars=body.max_context_chars,
        max_paths=max(1, min(10, body.max_edges)),
        max_relations=body.max_edges,
        query_by=body.query_by,
        mode=body.mode,
        graph_context=body.graph_context,
        session_id=body.session_id,
    )


def _require_index_previews(services: ServiceContainer) -> IndexPreviewStore:
    if services.index_previews is None:
        services.index_previews = IndexPreviewStore(
            services.repository_root, services.sync.repository_id
        )
    return services.index_previews


def _automatic_index_preview(
    services: ServiceContainer, prepared: PreparedIndex, preview_token: str
) -> dict[str, Any]:
    sources = [
        {
            "source_id": card.source_id,
            "node_id": card.node_id,
            "path": card.additional_metadata.get("path"),
            "display_name": card.additional_metadata.get("display_name"),
            "entity_kind": card.metadata.get("entity_kind"),
            "content_chars": len(card.content),
            "exact_relation_count": len(card.graph.relations),
        }
        for card in prepared.cards
    ]
    return {
        "preview_token": preview_token,
        "repository_root": str(services.repository_root),
        "repository_id": services.sync.repository_id,
        "revision_id": prepared.revision_id,
        "revision_source": prepared.revision_source,
        "discovered_file_count": len(prepared.discovery.files),
        "ignored_count": len(prepared.discovery.ignored),
        "ignored_counts": prepared.discovery.ignored_counts,
        "node_count": prepared.node_count,
        "edge_count": prepared.edge_count,
        "source_count": len(prepared.cards),
        "sources": sources,
        "diagnostics": list(prepared.diagnostics),
        "uploads_performed": False,
    }


def prepare_index(
    services: ServiceContainer, *, revision_id: str
) -> tuple[DiscoveryReport, tuple[SourceCard, ...], dict[str, Any]]:
    """Analyze only the configured root and return an upload preview."""

    if not revision_id.strip():
        raise ValueError("revision_id must not be blank")
    discovery = discover_files(services.repository_root)
    graph = analyze_repository(
        services.repository_root,
        repository_id=services.sync.repository_id,
        revision_id=revision_id,
        discovery=discovery,
    )
    cards = build_source_cards(graph, services.repository_root)
    sources = [
        {
            "source_id": card.source_id,
            "node_id": card.node_id,
            "path": card.additional_metadata.get("path"),
            "display_name": card.additional_metadata.get("display_name"),
            "entity_kind": card.metadata.get("entity_kind"),
            "content_chars": len(card.content),
            "exact_relation_count": len(card.graph.relations),
        }
        for card in cards
    ]
    preview = {
        "repository_root": str(services.repository_root),
        "repository_id": services.sync.repository_id,
        "revision_id": revision_id,
        "discovered_file_count": len(discovery.files),
        "ignored_count": len(discovery.ignored),
        "ignored_counts": discovery.ignored_counts,
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "source_count": len(cards),
        "sources": sources,
        "diagnostics": list(graph.diagnostics),
        "uploads_performed": False,
    }
    return discovery, cards, preview


app = create_app()
