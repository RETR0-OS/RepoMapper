from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hydra_graph.api import ServiceContainer, create_app, repository_root_fingerprint
from hydra_graph.config import HydraDBConfig
from hydra_graph.events import EventBus, ObserveSessions
from hydra_graph.hydradb import HydraDBClient
from hydra_graph.query import QueryService
from hydra_graph.sync import SyncManifest, SyncService
from hydra_graph.views import ViewService, ViewStore

FIXTURE = Path(__file__).parents[1] / "fixtures" / "hydradb" / "query_authorization.json"


class Transport:
    def __init__(self) -> None:
        self.response = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.calls: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.response


def observe_app(
    tmp_path: Path,
    *,
    ready_revision: str | None = "rev-abc",
    max_active: int = 32,
    api_key: str | None = "test",
    view_limit: int = 50,
    event_history_limit: int = 500,
) -> tuple[Any, Transport]:
    config = HydraDBConfig(
        api_key=api_key,
        database="repo_hack_hydra",
        collection="current",
        max_retries=0,
    )
    transport = Transport()
    events = EventBus(history_limit=event_history_limit)
    hydra = HydraDBClient(config, transport=transport)
    sync = SyncService(
        hydra,
        repository_id="hack-hydra",
        manifest=SyncManifest(
            repository_id="hack-hydra",
            revision_id=ready_revision,
            database=config.database,
            collection=config.collection,
        ),
        events=events,
    )
    queries = QueryService(
        hydra,
        repository_id="hack-hydra",
        events=events,
        verified_revision=lambda: sync.status["ready_revision"],
        current_state_indeterminate=lambda: bool(
            sync.status["current_state_indeterminate"]
        ),
    )
    views = ViewService(queries, store=ViewStore(limit=view_limit))
    services = ServiceContainer(
        config=config,
        client=hydra,
        events=events,
        queries=queries,
        views=views,
        sync=sync,
        repository_root=tmp_path,
        observe_sessions=ObserveSessions(events, max_active=max_active),
    )
    return create_app(services), transport


def _jsonrpc_response(response: Any) -> dict[str, Any]:
    for line in response.text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise AssertionError(f"MCP response did not contain JSON-RPC data: {response.text}")


def _initialize_mcp(client: TestClient) -> tuple[dict[str, str], dict[str, Any]]:
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
    }
    response = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "observe-test", "version": "1"},
            },
        },
    )
    assert response.status_code == 200
    session_id = response.headers["mcp-session-id"]
    initialized_headers = {**headers, "mcp-session-id": session_id}
    initialized = client.post(
        "/mcp",
        headers=initialized_headers,
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert initialized.status_code == 202
    return initialized_headers, _jsonrpc_response(response)


def test_mounted_mcp_supports_initialize_and_tools_list(tmp_path: Path) -> None:
    app, _ = observe_app(tmp_path)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        headers, initialized = _initialize_mcp(client)
        listed = client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )

    assert initialized["result"]["serverInfo"]["name"] == "hack-hydra"
    tools = _jsonrpc_response(listed)["result"]["tools"]
    assert "repository_query" in {tool["name"] for tool in tools}


def test_mounted_mcp_rejects_non_loopback_host(tmp_path: Path) -> None:
    app, _ = observe_app(tmp_path)
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        "host": "attacker.example",
    }

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        response = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "host-test", "version": "1"},
                },
            },
        )

    assert response.status_code == 421


def test_mounted_mcp_query_uses_active_observe_session_and_shared_view_store(
    tmp_path: Path,
) -> None:
    app, transport = observe_app(tmp_path)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        started = client.post("/api/observe/sessions", json={})
        session_id = started.json()["session_id"]
        headers, _ = _initialize_mcp(client)
        called = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "repository_query",
                    "arguments": {"question": "How does authorization work?"},
                },
            },
        )
        result = _jsonrpc_response(called)["result"]["structuredContent"]
        view = client.get(f"/api/views/by-id/{result['view_id']}")
        events = client.get("/api/events", params={"session_id": session_id})

    assert started.status_code == 201
    assert result["session_id"] == session_id
    assert view.status_code == 200
    assert view.json()["view_id"] == result["view_id"]
    assert "chunks" not in view.json()
    assert [event["type"] for event in events.json()] == [
        "session_started",
        "query_started",
        "hydradb_result_returned",
        "path_replay_started",
        "path_hop_replayed",
    ]
    assert {event["revision_id"] for event in events.json()} == {"rev-abc"}
    assert len(transport.calls) == 1


def test_observe_session_returns_opaque_canonical_root_fingerprint(
    tmp_path: Path,
) -> None:
    app, _ = observe_app(tmp_path)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        result = client.post("/api/observe/sessions", json={}).json()

    fingerprint = result["repository_root_fingerprint"]
    assert fingerprint == repository_root_fingerprint(tmp_path)
    assert len(fingerprint) == 64
    assert "repository_root" not in result


def test_repository_root_fingerprint_resolves_symlinks_and_windows_case(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    direct = repository_root_fingerprint(repository)
    assert direct == repository_root_fingerprint(repository / ".")
    assert direct == repository_root_fingerprint(f"{repository}{os.sep}")
    if os.name == "nt":
        assert direct == repository_root_fingerprint(Path(str(repository).swapcase()))
    link = tmp_path / "repository-link"
    try:
        os.symlink(repository, link, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    assert direct == repository_root_fingerprint(link)


def test_repository_root_fingerprint_uses_mirrorable_windows_lowercase(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "Straße"
    repository.mkdir()
    canonical = str(repository.resolve()).replace("\\", "/")
    if os.name == "nt":
        canonical = canonical.lower()
    canonical = canonical.rstrip("/") or "/"

    assert repository_root_fingerprint(repository) == hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def test_observe_interactions_are_derived_from_stored_view_and_event_bus(
    tmp_path: Path,
) -> None:
    app, _ = observe_app(tmp_path)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        session_id = client.post("/api/observe/sessions", json={}).json()["session_id"]
        queried = client.post(
            "/api/query",
            json={"question": "authorization", "session_id": session_id},
        ).json()
        view_id = queried["view_id"]
        before = client.get(f"/api/views/by-id/{view_id}").json()
        selected = client.post(
            f"/api/views/{view_id}/selection",
            json={"item_id": "node-authorize", "item_kind": "node"},
        )
        opened = client.post(
            f"/api/views/{view_id}/evidence-opened",
            json={"item_id": "edge-calls", "item_kind": "edge"},
        )
        changed = client.post(
            f"/api/views/{view_id}/workspace-change",
            json={"path": "src/payments/auth.py"},
        )
        after = client.get(f"/api/views/by-id/{view_id}").json()
        history = client.get("/api/events", params={"session_id": session_id}).json()

    assert selected.json()["event"]["entity_ids"] == ["node-authorize"]
    assert opened.json()["event"]["relationship_ids"] == ["edge-calls"]
    assert "node-authorize" in changed.json()["event"]["entity_ids"]
    assert changed.json()["event"]["relationship_ids"] == []
    assert history[-3:][0]["type"] == "context_selected"
    assert history[-2]["type"] == "evidence_opened"
    assert history[-1]["type"] == "workspace_entity_changed"
    assert before == after


def test_observe_rejects_unverified_unknown_inactive_and_unshown_inputs(
    tmp_path: Path,
) -> None:
    unverified, _ = observe_app(tmp_path, ready_revision=None)
    with TestClient(unverified, base_url="http://127.0.0.1:8765") as client:
        assert client.post("/api/observe/sessions", json={}).status_code == 409

    app, _ = observe_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.post("/api/observe/sessions", json={"id": "caller"}).status_code == 422
        session_id = client.post("/api/observe/sessions", json={}).json()["session_id"]
        view = client.post(
            "/api/query",
            json={"question": "authorization", "session_id": session_id},
        ).json()
        view_id = view["view_id"]
        assert client.get("/api/events", params={"session_id": "unknown"}).status_code == 404
        assert client.get("/api/views/by-id/unknown").status_code == 404
        assert client.post(
            f"/api/views/{view_id}/selection",
            json={"item_id": "not-shown", "item_kind": "node"},
        ).status_code == 404
        assert client.post(
            f"/api/views/{view_id}/workspace-change",
            json={"path": "../outside.py"},
        ).status_code == 422
        assert client.post(
            f"/api/views/{view_id}/workspace-change",
            json={"path": "src/not-shown.py"},
        ).status_code == 422
        completed = client.post(
            f"/api/observe/sessions/{session_id}/complete", json={}
        )
        assert completed.status_code == 200
        assert completed.json()["event"]["type"] == "session_completed"
        assert client.post(
            f"/api/observe/sessions/{session_id}/complete", json={}
        ).status_code == 409
        assert client.post(
            f"/api/observe/sessions/{session_id}/complete", json={"caller": "data"}
        ).status_code == 422
        assert client.post(
            f"/api/views/{view_id}/selection",
            json={"item_id": "node-authorize", "item_kind": "node"},
        ).status_code == 409


def test_api_query_rejects_invalid_observe_session_before_hydradb(tmp_path: Path) -> None:
    app, transport = observe_app(tmp_path)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        unknown = client.post(
            "/api/query",
            json={"question": "authorization", "session_id": "unknown"},
        )
        session_id = client.post("/api/observe/sessions", json={}).json()["session_id"]
        mismatched = client.post(
            "/api/query",
            json={
                "question": "authorization",
                "session_id": session_id,
                "revision": "rev-other",
            },
        )
        app.state.services.sync.manifest = SyncManifest(
            repository_id="hack-hydra",
            revision_id="rev-new",
            database="repo_hack_hydra",
            collection="current",
        )
        changed_current = client.post(
            "/api/query",
            json={"question": "authorization", "session_id": session_id},
        )
        client.post(f"/api/observe/sessions/{session_id}/complete", json={})
        inactive = client.post(
            "/api/query",
            json={"question": "authorization", "session_id": session_id},
        )

    assert unknown.status_code == 404
    assert mismatched.status_code == 409
    assert changed_current.status_code == 409
    assert inactive.status_code == 409
    assert transport.calls == []


def test_event_cursor_returns_only_later_session_events(tmp_path: Path) -> None:
    app, _ = observe_app(tmp_path)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        started = client.post("/api/observe/sessions", json={}).json()
        session_id = started["session_id"]
        client.post(
            "/api/query",
            json={"question": "authorization", "session_id": session_id},
        )
        initial = client.get("/api/events", params={"session_id": session_id}).json()
        later = client.get(
            "/api/events",
            params={
                "session_id": session_id,
                "after_event_id": initial[0]["event_id"],
            },
        ).json()
        empty = client.get(
            "/api/events",
            params={
                "session_id": session_id,
                "after_event_id": initial[-1]["event_id"],
            },
        ).json()

    assert later == initial[1:]
    assert empty == []


def test_event_cursor_rejects_wrong_session_and_evicted_history(tmp_path: Path) -> None:
    app, _ = observe_app(tmp_path, event_history_limit=10)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        first = client.post("/api/observe/sessions", json={}).json()
        second = client.post("/api/observe/sessions", json={}).json()
        wrong_session = client.get(
            "/api/events",
            params={
                "session_id": first["session_id"],
                "after_event_id": second["event"]["event_id"],
            },
        )

    overflow_app, _ = observe_app(tmp_path, event_history_limit=3)
    with TestClient(
        overflow_app, base_url="http://127.0.0.1:8765"
    ) as overflow_client:
        first = overflow_client.post("/api/observe/sessions", json={}).json()
        overflow_client.post(
            "/api/observe/sessions", json={}
        )
        overflow_client.post(
            "/api/query",
            json={"question": "authorization", "session_id": first["session_id"]},
        )
        evicted = overflow_client.get(
            "/api/events",
            params={
                "session_id": first["session_id"],
                "after_event_id": first["event"]["event_id"],
            },
        )

    assert evicted.status_code == 409
    assert wrong_session.status_code == 409
    assert evicted.json() == {
        "detail": "Observe event history has a gap; restart the session."
    }


def test_observe_active_session_bound_rejects_without_evicting(tmp_path: Path) -> None:
    app, _ = observe_app(tmp_path, max_active=1)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        first = client.post("/api/observe/sessions", json={})
        second = client.post("/api/observe/sessions", json={})
        history = client.get(
            "/api/events", params={"session_id": first.json()["session_id"]}
        )

    assert first.status_code == 201
    assert second.status_code == 429
    assert history.status_code == 200


def test_observe_refuses_persisted_marker_without_hydradb_credentials(
    tmp_path: Path,
) -> None:
    app, transport = observe_app(tmp_path, api_key=None)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        response = client.post("/api/observe/sessions", json={})

    assert response.status_code == 409
    assert transport.calls == []


def test_expired_view_is_not_returned_or_accepted(tmp_path: Path) -> None:
    app, _ = observe_app(tmp_path, view_limit=1)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        session_id = client.post("/api/observe/sessions", json={}).json()["session_id"]
        first = client.post(
            "/api/query", json={"question": "first", "session_id": session_id}
        ).json()
        client.post(
            "/api/query", json={"question": "second", "session_id": session_id}
        )
        fetched = client.get(f"/api/views/by-id/{first['view_id']}")
        selected = client.post(
            f"/api/views/{first['view_id']}/selection",
            json={"item_id": "node-authorize", "item_kind": "node"},
        )

    assert fetched.status_code == 404
    assert selected.status_code == 404


def test_workspace_change_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    try:
        os.symlink(outside, tmp_path / "src", target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    app, _ = observe_app(tmp_path)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        session_id = client.post("/api/observe/sessions", json={}).json()["session_id"]
        view = client.post(
            "/api/query",
            json={"question": "authorization", "session_id": session_id},
        ).json()
        response = client.post(
            f"/api/views/{view['view_id']}/workspace-change",
            json={"path": "src/payments/auth.py"},
        )

    assert response.status_code == 422


def test_omitted_mcp_session_rejects_ambiguous_active_sessions(tmp_path: Path) -> None:
    app, transport = observe_app(tmp_path)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.post("/api/observe/sessions", json={}).status_code == 201
        assert client.post("/api/observe/sessions", json={}).status_code == 201
        headers, _ = _initialize_mcp(client)
        called = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "repository_query",
                    "arguments": {"question": "authorization"},
                },
            },
        )

    assert _jsonrpc_response(called)["result"]["isError"] is True
    assert transport.calls == []
