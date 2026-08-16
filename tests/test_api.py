from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from hydra_graph import api as api_module
from hydra_graph.api import (
    ServiceContainer,
    _contained_manifest_path,
    create_app,
    create_container,
    repository_root_fingerprint,
)
from hydra_graph.config import HydraDBConfig
from hydra_graph.events import EventBus
from hydra_graph.hydradb import HydraDBAPIError, HydraDBClient, hydradb_reason
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


class FakeSyncResult:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def as_dict(self) -> dict[str, Any]:
        return dict(self.payload)


class FakeSync:
    """A sync service the test can hold open, so no test waits on the clock."""

    def __init__(
        self,
        repository_id: str,
        *,
        failure: Exception | None = None,
        result_status: str = "ready",
        warning: str | None = None,
    ) -> None:
        self.repository_id = repository_id
        self.batch_size = 25
        self.failure = failure
        self.result_status = result_status
        self.warning = warning
        self.calls: list[tuple[str, int]] = []
        self.progress: list[tuple[str, int, int]] = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.status = {
            "status": "idle",
            "ready_revision": None,
            "source_count": 0,
            "hydradb_available": True,
            "collection": "current",
            "current_state_indeterminate": False,
        }

    def sync(
        self,
        cards: Sequence[Any],
        *,
        revision_id: str,
        progress: Callable[[str, int, int], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> FakeSyncResult:
        self.calls.append((revision_id, len(cards)))
        if progress is not None:
            progress("uploading", 1, 1)
            self.progress.append(("uploading", 1, 1))
        self.entered.set()
        if self.failure is not None:
            raise self.failure
        self.release.wait(10)
        cancelled = should_cancel is not None and should_cancel()
        status = "failed" if cancelled else self.result_status
        return FakeSyncResult(
            {
                "status": status,
                "candidate_revision": revision_id,
                "ready_revision": revision_id if status == "ready" else None,
                "added": [],
                "replaced": [],
                "deleted": [],
                "pending": [],
                "failed": {"__cancelled__": "cancelled by request"} if cancelled else {},
                "current_state_indeterminate": cancelled,
                "warning": "Indexing was cancelled." if cancelled else self.warning,
            }
        )


def join_index_workers(timeout: float = 20.0) -> None:
    """Wait for the background index threads by name, never on a sleep."""

    for thread in threading.enumerate():
        if thread.name.startswith("hydra-index-"):
            thread.join(timeout)
            assert not thread.is_alive()


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
    assert "Repository Map setup" in unavailable_health["message"]
    assert "database" not in ready_health
    assert "database" not in unavailable_health
    assert ready_health["credentials_configured"] is True
    assert unavailable_health["credentials_configured"] is False


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

    assert (
        alias_health["repository_root_fingerprint"]
        == canonical_health["repository_root_fingerprint"]
    )
    assert str(repository) not in alias_health.values()
    assert str(alias) not in alias_health.values()


def test_extension_scope_headers_select_the_workspace_without_environment_configuration(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "Customer Portal"
    repository.mkdir()
    (repository / "app.py").write_text("value = 1\n", encoding="utf-8")
    client, transport = api()
    headers = {
        "X-Hydra-Repository-Root": quote(str(repository.resolve()), safe=""),
        "X-Hydra-Repository-Id": "Customer-Portal-a1b2c3d4e5f6",
    }

    health = client.get("/health", headers=headers).json()
    preview = client.post("/api/index/preview", json={}, headers=headers).json()

    assert health["repository_id"] == "Customer-Portal-a1b2c3d4e5f6"
    assert health["repository_root_fingerprint"] == repository_root_fingerprint(repository)
    assert preview["repository_root"] == str(repository.resolve())
    assert preview["repository_id"] == "Customer-Portal-a1b2c3d4e5f6"
    assert {item["path"] for item in preview["sources"]} == {".", "app.py"}
    assert transport.calls == []


def test_extension_repository_scopes_are_isolated(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    client, _ = api()
    first_headers = {
        "X-Hydra-Repository-Root": quote(str(first.resolve()), safe=""),
        "X-Hydra-Repository-Id": "first-a1b2c3d4e5f6",
    }
    second_headers = {
        "X-Hydra-Repository-Root": quote(str(second.resolve()), safe=""),
        "X-Hydra-Repository-Id": "second-a1b2c3d4e5f6",
    }

    first_health = client.get("/health", headers=first_headers).json()
    second_health = client.get("/health", headers=second_headers).json()

    assert first_health["repository_id"] == "first-a1b2c3d4e5f6"
    assert second_health["repository_id"] == "second-a1b2c3d4e5f6"
    scopes = client.app.state.repository_scopes
    assert scopes.by_repository_id("first-a1b2c3d4e5f6").repository_root == first.resolve()
    assert scopes.by_repository_id("second-a1b2c3d4e5f6").repository_root == second.resolve()
    assert (
        first_health["repository_root_fingerprint"] != second_health["repository_root_fingerprint"]
    )


def test_extension_repository_scope_requires_both_headers(tmp_path: Path) -> None:
    client, _ = api()

    response = client.get(
        "/health",
        headers={"X-Hydra-Repository-Root": quote(str(tmp_path.resolve()), safe="")},
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Repository root and repository ID headers must be provided together."
    }


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


def test_setup_connection_check_is_read_only_and_discloses_no_credentials() -> None:
    client, transport = api()

    response = client.post("/api/setup/test", json={})

    assert response.status_code == 200
    assert response.json() == {"status": "connected", "write_performed": False}
    assert len(transport.calls) == 1
    assert transport.calls[0]["method"] == "POST"
    assert transport.calls[0]["url"].endswith("/query")
    assert transport.calls[0]["json_body"]["graph_context"] is False
    assert "api_key" not in json.dumps(response.json())
    assert "database" not in json.dumps(response.json())


def test_hydradb_refusal_reason_keeps_the_remote_status_and_message() -> None:
    """Setup must show why HydraDB refused, or the person cannot correct it."""

    reason = hydradb_reason(HydraDBAPIError("malformed API key", code="UNAUTHORIZED", status=401))

    assert reason == "HTTP 401 | UNAUTHORIZED | malformed API key"
    assert hydradb_reason(HydraDBAPIError("")) == "HydraDB returned no reason."
    # An envelope failure carries no HTTP status but still names its cause.
    assert hydradb_reason(HydraDBAPIError("database not found")) == "database not found"


def test_all_extension_view_routes_are_callable() -> None:
    client, transport = api()

    for mode in ("repository", "explore", "trace", "observe", "compare", "preserve"):
        response = client.get(f"/api/views/{mode}?depth=file")
        assert response.status_code == 200
        assert response.json()["mode"] == mode

    # Compare and Preserve require explicit evolution identifiers and must not
    # fall through to generic current-collection retrieval.
    queries = [call for call in transport.calls if call["url"].endswith("/query")]
    relation_reads = [
        call for call in transport.calls if call["url"].endswith("/context/relations")
    ]
    # Four modes retrieve. Compare and Preserve add none, so no query ever asks for
    # their evolution record kinds against the current collection.
    assert queries
    assert not any(
        kind in str(call["json_body"].get("metadata_filters", {}).get("entity_kind", ""))
        for call in queries
        for kind in ("CHANGE_EVENT", "SYSTEM_LENS")
    )
    assert len(queries) + len(relation_reads) == len(transport.calls)
    # The stored graph is cached per revision and source, so four views read each
    # source exactly once instead of once per view.
    read_ids = [call["query"]["id"] for call in relation_reads]
    assert read_ids and len(set(read_ids)) == len(read_ids)


def test_unavailable_query_never_returns_fixture_data() -> None:
    client, transport = api(api_key=None)

    response = client.post("/api/query", json={"question": "authorization"})

    assert response.status_code == 200
    view = response.json()
    assert view["hydradb"]["available"] is False
    assert view["nodes"] == []
    assert view["edges"] == []
    assert view["warnings"][0] == (
        "HydraDB could not serve this repository query. "
        "HydraDB is unreachable, or no credential is available for this project."
    )
    assert view["diagnostics"]["outcome"] == "hydradb_unavailable"
    assert "HYDRA_DB_API_KEY" not in view["warnings"][0]
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

    response = client.post("/api/index/preview", json={})

    assert response.status_code == 200
    preview = response.json()
    assert preview["repository_root"] == str(tmp_path.resolve())
    assert preview["revision_id"].startswith("content:")
    assert preview["revision_source"] == "content-digest"
    assert len(preview["preview_token"]) >= 40
    assert preview["discovered_file_count"] == 1
    assert preview["source_count"] >= 2
    assert preview["uploads_performed"] is False
    assert {item["path"] for item in preview["sources"]} == {".", "app.py"}
    assert transport.calls == []


def test_index_route_accepts_the_job_and_runs_the_pipeline_in_the_background(
    tmp_path: Path,
) -> None:
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

    preview_response = client.post("/api/index/preview", json={})
    assert preview_response.status_code == 200
    preview = preview_response.json()
    accepted = client.post("/api/index", json={"preview_token": preview["preview_token"]})
    join_index_workers()

    assert accepted.status_code == 202
    job = accepted.json()
    assert job["state"] == "running"
    assert job["revision_id"] == preview["revision_id"]
    assert job["total_sources"] == preview["source_count"]
    assert job["result"] is None
    # The record must never suggest that the run survives a service restart.
    assert job["durable"] is False
    assert "not saved to disk" in job["message"]
    finished = client.get(f"/api/index/jobs/{job['job_id']}")
    assert finished.status_code == 200
    record = finished.json()
    assert record["state"] == "completed"
    assert record["phase"] == "done"
    assert record["error"] is None
    assert record["failed"] == {}
    assert record["result"]["sync"]["status"] == "ready"
    assert record["result"]["sync"]["ready_revision"] == preview["revision_id"]
    assert record["result"]["preview"]["repository_root"] == str(tmp_path.resolve())
    assert [call["method"] for call in transport.calls] == ["POST", "GET"]


def test_index_confirmation_reuses_the_preview_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Confirming must not repeat the analysis the preview already paid for."""

    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    client, _ = api(repository_root=tmp_path)
    fake = FakeSync("hack-hydra")
    client.app.state.services.sync = fake
    fake.release.set()
    analyses: list[str] = []
    original = api_module.prepare_automatic_index

    def counted(repository_root: Path, repository_id: str) -> Any:
        analyses.append(repository_id)
        return original(repository_root, repository_id)

    monkeypatch.setattr(api_module, "prepare_automatic_index", counted)

    token = client.post("/api/index/preview", json={}).json()["preview_token"]
    accepted = client.post("/api/index", json={"preview_token": token})
    join_index_workers()

    assert accepted.status_code == 202
    assert analyses == ["hack-hydra"]
    assert len(fake.calls) == 1


def test_second_index_job_for_the_same_project_is_refused(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    client, _ = api(repository_root=tmp_path)
    fake = FakeSync("hack-hydra")
    client.app.state.services.sync = fake

    first_token = client.post("/api/index/preview", json={}).json()["preview_token"]
    second_token = client.post("/api/index/preview", json={}).json()["preview_token"]
    accepted = client.post("/api/index", json={"preview_token": first_token})
    assert fake.entered.wait(5)
    conflict = client.post("/api/index", json={"preview_token": second_token})
    fake.release.set()
    join_index_workers()

    assert accepted.status_code == 202
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "An index job is already running for this project."}
    # The refusal must not spend the caller's preview token: the same
    # confirmation works once the running job is done.
    assert client.post("/api/index", json={"preview_token": second_token}).status_code == 202
    join_index_workers()


def test_index_job_cancellation_reports_a_cancelled_outcome(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    client, _ = api(repository_root=tmp_path)
    fake = FakeSync("hack-hydra")
    client.app.state.services.sync = fake

    token = client.post("/api/index/preview", json={}).json()["preview_token"]
    job_id = client.post("/api/index", json={"preview_token": token}).json()["job_id"]
    assert fake.entered.wait(5)
    cancelled = client.post(f"/api/index/jobs/{job_id}/cancel", json={})
    fake.release.set()
    join_index_workers()

    assert cancelled.status_code == 200
    assert cancelled.json()["job_id"] == job_id
    record = client.get(f"/api/index/jobs/{job_id}").json()
    assert record["state"] == "cancelled"
    assert record["failed"] == {"__cancelled__": "cancelled by request"}
    assert record["result"]["sync"]["current_state_indeterminate"] is True


def test_index_job_failure_keeps_a_named_reason(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    client, _ = api(repository_root=tmp_path)
    fake = FakeSync("hack-hydra", failure=RuntimeError("HydraDB refused the upload"))
    fake.release.set()
    client.app.state.services.sync = fake

    token = client.post("/api/index/preview", json={}).json()["preview_token"]
    accepted = client.post("/api/index", json={"preview_token": token})
    join_index_workers()

    assert accepted.status_code == 202
    record = client.get(f"/api/index/jobs/{accepted.json()['job_id']}").json()
    assert record["state"] == "failed"
    assert record["error"] == "Indexing failed. RuntimeError: HydraDB refused the upload"
    assert record["result"] is None


def test_index_job_marks_an_unready_sync_result_as_failed(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    client, _ = api(repository_root=tmp_path)
    reason = "HydraDB refused the write. HTTP 400 | INVALID_INPUT | empty graph"
    fake = FakeSync("hack-hydra", result_status="unavailable", warning=reason)
    fake.release.set()
    client.app.state.services.sync = fake

    token = client.post("/api/index/preview", json={}).json()["preview_token"]
    accepted = client.post("/api/index", json={"preview_token": token})
    join_index_workers()

    record = client.get(f"/api/index/jobs/{accepted.json()['job_id']}").json()
    assert record["state"] == "failed"
    assert record["error"] == reason
    assert record["result"]["sync"]["status"] == "unavailable"


def test_unknown_index_job_is_a_named_404() -> None:
    client, _ = api()

    missing = client.get("/api/index/jobs/idx_does_not_exist")
    cancelled = client.post("/api/index/jobs/idx_does_not_exist/cancel", json={})

    assert missing.status_code == 404
    assert missing.json() == {"detail": "Index job was not found."}
    assert cancelled.status_code == 404
    assert cancelled.json() == {"detail": "Index job was not found."}


def test_index_job_worker_stays_inside_the_scope_that_started_it(tmp_path: Path) -> None:
    """A worker thread must never inherit or re-read another workspace's scope."""

    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "app.py").write_text("value = 1\n", encoding="utf-8")
    (second / "app.py").write_text("value = 2\n", encoding="utf-8")
    client, _ = api()
    first_headers = {
        "X-Hydra-Repository-Root": quote(str(first.resolve()), safe=""),
        "X-Hydra-Repository-Id": "first-a1b2c3d4e5f6",
    }
    second_headers = {
        "X-Hydra-Repository-Root": quote(str(second.resolve()), safe=""),
        "X-Hydra-Repository-Id": "second-a1b2c3d4e5f6",
    }
    client.get("/health", headers=first_headers)
    client.get("/health", headers=second_headers)
    scopes = client.app.state.repository_scopes
    first_sync = FakeSync("first-a1b2c3d4e5f6")
    second_sync = FakeSync("second-a1b2c3d4e5f6")
    default_sync = FakeSync("hack-hydra")
    scopes.by_repository_id("first-a1b2c3d4e5f6").sync = first_sync
    scopes.by_repository_id("second-a1b2c3d4e5f6").sync = second_sync
    client.app.state.services.sync = default_sync
    first_sync.release.set()

    token = client.post("/api/index/preview", json={}, headers=first_headers).json()[
        "preview_token"
    ]
    accepted = client.post("/api/index", json={"preview_token": token}, headers=first_headers)
    join_index_workers()

    assert accepted.status_code == 202
    job = accepted.json()
    assert job["repository_id"] == "first-a1b2c3d4e5f6"
    assert len(first_sync.calls) == 1
    assert second_sync.calls == []
    assert default_sync.calls == []
    # Job records belong to the scope that started them.
    assert client.get(f"/api/index/jobs/{job['job_id']}", headers=second_headers).status_code == 404
    record = client.get(f"/api/index/jobs/{job['job_id']}", headers=first_headers).json()
    assert record["state"] == "completed"
    assert record["result"]["preview"]["repository_root"] == str(first.resolve())
    assert record["result"]["preview"]["repository_id"] == "first-a1b2c3d4e5f6"


def test_index_confirmation_rejects_changed_snapshot_and_manual_revision(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")
    client, transport = api(repository_root=tmp_path)

    manual = client.post("/api/index/preview", json={"revision_id": "caller-controlled"})
    preview = client.post("/api/index/preview", json={}).json()
    source.write_text("value = 2\n", encoding="utf-8")
    changed = client.post("/api/index", json={"preview_token": preview["preview_token"]})

    assert manual.status_code == 422
    assert changed.status_code == 409
    assert "changed" in changed.json()["detail"]
    assert transport.calls == []


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
