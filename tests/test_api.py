from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hydra_graph.api import (
    ServiceContainer,
    _contained_manifest_path,
    create_app,
    create_container,
    repository_root_fingerprint,
)
from hydra_graph.config import HydraDBConfig
from hydra_graph.events import EventBus
from hydra_graph.hydradb import HydraDBClient
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


def api(
    *,
    api_key: str | None = "test",
    repository_root: Path | None = None,
    transport_override: Any | None = None,
) -> tuple[TestClient, Any]:
    response = json.loads(FIXTURE.read_text(encoding="utf-8"))
    transport = transport_override or Transport(response)
    config = HydraDBConfig(
        api_key=api_key,
        database="repo_hack_hydra",
        collection="current",
        max_retries=0,
    )
    events = EventBus()
    hydra = HydraDBClient(config, transport=transport)
    queries = QueryService(hydra, repository_id="hack-hydra", events=events)
    views = ViewService(queries)
    sync = SyncService(hydra, repository_id="hack-hydra", events=events)
    container = ServiceContainer(
        config=config,
        client=hydra,
        events=events,
        queries=queries,
        views=views,
        sync=sync,
        repository_root=(repository_root or Path.cwd()).resolve(),
    )
    return TestClient(create_app(container)), transport


def test_health_reports_explicit_configured_and_unavailable_states() -> None:
    ready, _ = api()
    unavailable, _ = api(api_key=None)

    ready_health = ready.get("/health").json()
    assert ready_health["state"] == "unverified"
    assert ready_health["revision_verified"] is False
    assert ready_health["verification_status"] == "configured_unverified"
    assert "has not verified" in ready_health["message"]
    unavailable_health = unavailable.get("/health").json()
    assert unavailable_health["state"] == "unavailable"
    assert "HYDRA_DB_API_KEY" in unavailable_health["message"]


def test_health_exposes_repository_identity_without_raw_root(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    client, _ = api(repository_root=repository)

    health = client.get("/health").json()

    assert health["repository_id"] == "hack-hydra"
    assert health["repository_root_fingerprint"] == repository_root_fingerprint(repository)
    assert len(health["repository_root_fingerprint"]) == 64
    assert "repository_root" not in health
    assert all(str(repository) not in str(value) for value in health.values())


def test_health_root_fingerprint_resolves_repository_symlink(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    alias = tmp_path / "repository-alias"
    repository.mkdir()
    try:
        os.symlink(repository, alias, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    canonical, _ = api(repository_root=repository)
    through_alias, _ = api(repository_root=alias)

    canonical_health = canonical.get("/health").json()
    alias_health = through_alias.get("/health").json()

    assert alias_health["repository_root_fingerprint"] == canonical_health[
        "repository_root_fingerprint"
    ]
    assert str(repository) not in alias_health.values()
    assert str(alias) not in alias_health.values()


def test_extension_query_route_returns_hydradb_backed_trace_view() -> None:
    client, transport = api()

    response = client.post(
        "/api/query",
        json={
            "question": "How does authorization work?",
            "depth": "symbol",
            "query_by": "hybrid",
            "mode": "thinking",
            "graph_context": True,
        },
    )

    assert response.status_code == 200
    view = response.json()
    assert view["mode"] == "trace"
    assert view["hydradb"]["available"] is True
    assert view["edges"][0]["attributes"]["hydradb_origin"] == "byog"
    assert transport.calls[0]["url"].endswith("/query")


def test_all_extension_view_routes_are_callable() -> None:
    client, transport = api()

    for mode in ("repository", "explore", "trace", "observe", "compare", "preserve"):
        response = client.get(f"/api/views/{mode}?depth=file")
        assert response.status_code == 200
        assert response.json()["mode"] == mode

    # Compare and Preserve require explicit evolution identifiers and must not
    # fall through to generic current-collection retrieval.
    assert len(transport.calls) == 4


def test_unavailable_query_never_returns_fixture_data() -> None:
    client, transport = api(api_key=None)

    response = client.post("/api/query", json={"question": "authorization"})

    assert response.status_code == 200
    view = response.json()
    assert view["hydradb"]["available"] is False
    assert view["nodes"] == []
    assert view["edges"] == []
    assert "HYDRA_DB_API_KEY" in view["warnings"][0]
    assert transport.calls == []


def test_raw_ingest_and_delete_routes_are_not_public() -> None:
    client, _ = api()

    assert client.post("/api/ingest", json={"graph_ir": {}}).status_code == 404
    assert client.request("DELETE", "/api/context", json={"ids": ["source-a"]}).status_code == 404
    assert client.get("/api/status?ids=source-a").status_code == 404


def test_index_preview_analyzes_only_configured_root_without_upload(
    tmp_path: Path,
) -> None:
    source = tmp_path / "app.py"
    source.write_text("def ready():\n    return True\n", encoding="utf-8")
    client, transport = api()
    client.app.state.services.repository_root = tmp_path.resolve()

    response = client.post("/api/index/preview", json={"revision_id": "rev-preview"})

    assert response.status_code == 200
    preview = response.json()
    assert preview["repository_root"] == str(tmp_path.resolve())
    assert preview["revision_id"] == "rev-preview"
    assert preview["discovered_file_count"] == 1
    assert preview["source_count"] >= 2
    assert preview["uploads_performed"] is False
    assert {item["path"] for item in preview["sources"]} == {".", "app.py"}
    assert transport.calls == []


def test_index_route_runs_analyze_card_ingest_and_status_pipeline(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def ready():\n    return True\n", encoding="utf-8")

    class IndexTransport:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def request(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(kwargs)
            if kwargs["url"].endswith("/context/ingest"):
                source_ids = [item["id"] for item in json.loads(kwargs["form"]["app_knowledge"])]
                return {"success": True, "data": {"ids": source_ids}}
            if kwargs["url"].endswith("/context/status"):
                return {
                    "success": True,
                    "data": {
                        "statuses": [
                            {
                                "id": source_id,
                                "indexing_status": "completed",
                                "success": True,
                                "error_code": "",
                            }
                            for source_id in kwargs["query"]["ids"].split(",")
                        ]
                    },
                }
            raise AssertionError(kwargs)

    transport = IndexTransport()
    client, _ = api(repository_root=tmp_path, transport_override=transport)

    response = client.post("/api/index", json={"revision_id": "rev-index"})

    assert response.status_code == 200
    result = response.json()
    assert result["sync"]["status"] == "ready"
    assert result["sync"]["ready_revision"] == "rev-index"
    assert result["preview"]["repository_root"] == str(tmp_path.resolve())
    assert [call["method"] for call in transport.calls] == ["POST", "GET"]


def test_action_route_keeps_presentation_state_explicit() -> None:
    client, _ = api()

    action = client.post("/api/views/repository/action", json={}).json()
    assert "presentation state" in action["message"]
    assert client.post("/api/events", json={}).status_code == 405


def test_manifest_symlink_cannot_escape_configured_repository(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    outside = tmp_path / "outside"
    repository.mkdir()
    outside.mkdir()
    try:
        os.symlink(outside, repository / ".hydra-graph", target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    config = HydraDBConfig(api_key="test", database="repo_hack_hydra")

    try:
        create_container(
            config,
            repository_id="hack-hydra",
            repository_root=repository,
        )
    except ValueError as exc:
        assert "escapes" in str(exc)
    else:
        raise AssertionError("manifest symlink escape was accepted")


def test_manifest_path_helper_rejects_outside_candidate(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    outside = tmp_path / "outside" / "manifest.json"

    with pytest.raises(ValueError, match="escapes"):
        _contained_manifest_path(repository, outside)


def test_checkpoint_body_is_exact_and_contains_no_confirm_flag() -> None:
    class Evolution:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def capture_checkpoint(self, slot: str, *, revision_id: str) -> dict[str, Any]:
            self.calls.append((slot, revision_id))
            return {
                "status": "captured",
                "operation": "capture_checkpoint",
                "slot": slot,
                "revision_id": revision_id,
            }

    client, _ = api()
    evolution = Evolution()
    client.app.state.services.evolution = evolution

    response = client.post("/api/evolution/checkpoints/before", json={"revision_id": "rev-ready"})
    rejected = client.post(
        "/api/evolution/checkpoints/before",
        json={"revision_id": "rev-ready", "confirm": True},
    )

    assert response.status_code == 200
    assert evolution.calls == [("before", "rev-ready")]
    assert rejected.status_code == 422


@pytest.mark.parametrize(
    ("path", "body", "detail"),
    [
        (
            "/api/evolution/checkpoints/after",
            {"revision_id": "unverified"},
            "Checkpoint capture refused.",
        ),
        (
            "/api/evolution/publish",
            {
                "before_revision_id": "missing",
                "after_revision_id": "after",
                "confirm": False,
            },
            "Delta publication refused.",
        ),
        (
            "/api/lenses",
            {
                "name": "Flow",
                "purpose": "Preserve flow",
                "view_id": "expired",
                "notes": None,
                "confirm": False,
            },
            "Shared lens save refused.",
        ),
    ],
)
def test_evolution_domain_failures_are_bounded_conflicts(
    path: str, body: dict[str, Any], detail: str
) -> None:
    class Evolution:
        def capture_checkpoint(self, *_: Any, **__: Any) -> Any:
            raise ValueError("C:/secret/workspace/path")

        def publish_delta(self, **_: Any) -> Any:
            raise ValueError('{"record_json":"secret"}')

        def save_lens(self, **_: Any) -> Any:
            raise ValueError("no exact path at C:/secret")

    client, _ = api()
    client.app.state.services.evolution = Evolution()

    response = client.post(path, json=body)

    assert response.status_code == 409
    assert response.json() == {"detail": detail}
