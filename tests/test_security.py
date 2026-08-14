from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from hydra_graph.api import create_app, create_container
from hydra_graph.config import HydraDBConfig
from hydra_graph.security import MANAGED_SERVICE_PROTOCOL, ManagedSecurity


def managed_api(
    root: Path,
    *,
    now: Any = None,
) -> tuple[TestClient, ManagedSecurity]:
    config = HydraDBConfig(api_key=None, database="", collection="current")
    container = create_container(
        config,
        repository_id="git:example:0123456789abcdefabcd",
        repository_root=root,
    )
    security = ManagedSecurity(
        "installation-control-key-with-at-least-32-characters",
        permitted_hosts={"127.0.0.1"},
        **({"now": now} if now is not None else {}),
    )
    return TestClient(
        create_app(container, managed_security=security),
        base_url="http://127.0.0.1",
    ), security


def attach(
    client: TestClient,
    security: ManagedSecurity,
    root: Path,
    *,
    timestamp: int,
    nonce: str = "0123456789abcdef0123456789abcdef",
) -> dict[str, Any]:
    repository_id = "git:example:0123456789abcdefabcd"
    signature = security.sign_challenge(
        repository_root=root,
        repository_id=repository_id,
        timestamp=timestamp,
        nonce=nonce,
    )
    response = client.post(
        "/managed/challenge",
        json={
            "repository_root": str(root),
            "repository_id": repository_id,
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_managed_service_exposes_only_version_without_authentication(tmp_path: Path) -> None:
    client, _ = managed_api(tmp_path)

    version = client.get("/version")
    health = client.get("/health")
    legacy_headers = client.get(
        "/health",
        headers={
            "X-Hydra-Repository-Root": str(tmp_path),
            "X-Hydra-Repository-Id": "git:example:0123456789abcdefabcd",
        },
    )

    assert version.status_code == 200
    assert version.json()["protocol"] == MANAGED_SERVICE_PROTOCOL
    assert health.status_code == 401
    assert legacy_headers.status_code == 401


def test_signed_attachment_issues_a_project_bound_short_lived_token(tmp_path: Path) -> None:
    clock = [1_800_000_000]
    client, security = managed_api(tmp_path, now=lambda: clock[0])
    response = attach(client, security, tmp_path, timestamp=clock[0])

    health = client.get(
        "/health", headers={"Authorization": f"Bearer {response['access_token']}"}
    )
    assert health.status_code == 200
    assert health.json()["repository_id"] == "git:example:0123456789abcdefabcd"
    assert response["expires_at"] == clock[0] + 300
    assert str(tmp_path) not in json.dumps(response)

    clock[0] += 301
    expired = client.get(
        "/health", headers={"Authorization": f"Bearer {response['access_token']}"}
    )
    assert expired.status_code == 401


def test_attachment_rejects_replay_bad_signature_and_wrong_host(tmp_path: Path) -> None:
    clock = [1_800_000_000]
    client, security = managed_api(tmp_path, now=lambda: clock[0])
    nonce = "fedcba9876543210fedcba9876543210"
    attach(client, security, tmp_path, timestamp=clock[0], nonce=nonce)

    repository_id = "git:example:0123456789abcdefabcd"
    signature = security.sign_challenge(
        repository_root=tmp_path,
        repository_id=repository_id,
        timestamp=clock[0],
        nonce=nonce,
    )
    replay = client.post(
        "/managed/challenge",
        json={
            "repository_root": str(tmp_path),
            "repository_id": repository_id,
            "timestamp": clock[0],
            "nonce": nonce,
            "signature": signature,
        },
    )
    invalid = client.post(
        "/managed/challenge",
        json={
            "repository_root": str(tmp_path),
            "repository_id": repository_id,
            "timestamp": clock[0],
            "nonce": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "signature": "x" * 43,
        },
    )
    wrong_host = client.get("/version", headers={"Host": "attacker.example"})

    assert replay.status_code == 401
    assert invalid.status_code == 401
    assert wrong_host.status_code == 421


def test_managed_request_size_limit_is_applied_before_routing(tmp_path: Path) -> None:
    client, _ = managed_api(tmp_path)

    response = client.post(
        "/managed/challenge",
        content=b"{}",
        headers={"Content-Length": "1048577", "Content-Type": "application/json"},
    )

    assert response.status_code == 413
