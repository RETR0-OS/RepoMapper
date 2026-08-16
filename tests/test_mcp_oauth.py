from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from hydra_graph.api import create_app, create_container
from hydra_graph.config import HydraDBConfig
from hydra_graph.mcp_oauth import ManagedOAuthProvider
from hydra_graph.security import ManagedSecurity


class SecretChannel:
    def __init__(
        self,
        *,
        approved: bool = True,
        selected_repository: str | None = None,
    ) -> None:
        self.records: dict[str, str] = {}
        self.approved = approved
        self.selected_repository = selected_repository
        self.consent_requests: list[dict[str, Any]] = []

    def request(self, message_type: str, **payload: Any) -> dict[str, Any]:
        if message_type == "oauth_get":
            return {"ok": True, "value": self.records.get(payload["key"])}
        if message_type == "oauth_put":
            self.records[payload["key"]] = payload["value"]
            return {"ok": True}
        if message_type == "oauth_delete":
            self.records.pop(payload["key"], None)
            return {"ok": True}
        if message_type == "oauth_consent":
            self.consent_requests.append(payload)
            projects = payload.get("projects", [])
            selected = self.selected_repository or (
                projects[0]["repository_id"] if projects else None
            )
            return {
                "ok": True,
                "approved": self.approved,
                "repository_id": selected,
            }
        raise AssertionError(message_type)


def oauth_client(tmp_path: Path, channel: SecretChannel) -> TestClient:
    issuer = "http://127.0.0.1:8765"
    config = HydraDBConfig(api_key=None, database="", collection="current")
    container = create_container(
        config,
        repository_id="git:example:0123456789abcdefabcd",
        repository_root=tmp_path,
    )
    provider = ManagedOAuthProvider(
        channel,  # type: ignore[arg-type]
        repository_root=tmp_path,
        repository_id="git:example:0123456789abcdefabcd",
        issuer_url=issuer,
    )
    security = ManagedSecurity(
        "installation-control-key-with-at-least-32-characters",
        permitted_hosts={"127.0.0.1"},
    )
    return TestClient(
        create_app(
            container,
            managed_security=security,
            mcp_oauth_provider=provider,
            mcp_issuer_url=issuer,
        ),
        base_url=issuer,
    )


def register(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/register",
        json={
            "client_name": "Codex test client",
            "redirect_uris": ["http://127.0.0.1:54321/callback"],
            "token_endpoint_auth_method": "client_secret_post",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": "repository:read evidence:read observe:read",
        },
    )
    assert response.status_code == 201
    return response.json()


def authorize(client: TestClient, registered: dict[str, Any]) -> tuple[str, str]:
    verifier = "pkce-verifier-with-at-least-forty-three-characters-123456"
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    response = client.get(
        "/authorize",
        params={
            "client_id": registered["client_id"],
            "redirect_uri": "http://127.0.0.1:54321/callback",
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "repository:read evidence:read observe:read",
            "state": "opaque-state",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["state"] == ["opaque-state"]
    return query["code"][0], verifier


def exchange(
    client: TestClient,
    registered: dict[str, Any],
    code: str,
    verifier: str,
) -> dict[str, Any]:
    response = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": registered["client_id"],
            "client_secret": registered["client_secret"],
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": "http://127.0.0.1:54321/callback",
        },
    )
    assert response.status_code == 200
    return response.json()


def mcp_initialize(client: TestClient, access_token: str) -> Any:
    return client.post(
        "/mcp",
        headers={
            "authorization": f"Bearer {access_token}",
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "oauth-test", "version": "1"},
            },
        },
    )


def test_mcp_oauth_requires_pkce_consent_and_uses_secret_storage(tmp_path: Path) -> None:
    channel = SecretChannel()
    with oauth_client(tmp_path, channel) as client:
        metadata = client.get("/.well-known/oauth-authorization-server")
        protected = client.get("/.well-known/oauth-protected-resource/mcp")
        unauthenticated = mcp_initialize(client, "not-a-token")
        registered = register(client)
        code, verifier = authorize(client, registered)
        bad = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": registered["client_id"],
                "client_secret": registered["client_secret"],
                "code": code,
                "code_verifier": "wrong-verifier-that-is-long-enough-to-be-well-formed-123",
                "redirect_uri": "http://127.0.0.1:54321/callback",
            },
        )
        tokens = exchange(client, registered, code, verifier)
        initialized = mcp_initialize(client, tokens["access_token"])

    assert metadata.status_code == 200
    assert metadata.json()["code_challenge_methods_supported"] == ["S256"]
    assert protected.status_code == 200
    assert unauthenticated.status_code == 401
    assert bad.status_code == 400
    assert bad.json()["error"] == "invalid_grant"
    assert initialized.status_code == 200
    # Only a drive-lettered root folds case, so a POSIX temporary folder that
    # holds an upper-case segment keeps that segment in the fingerprint.
    canonical = str(tmp_path.resolve())
    fingerprint_input = canonical.lower() if Path(canonical).drive else canonical
    assert channel.consent_requests[0]["projects"] == [
        {
            "repository_id": "git:example:0123456789abcdefabcd",
            "project_name": tmp_path.name,
            "root_fingerprint": hashlib.sha256(fingerprint_input.encode()).hexdigest(),
        }
    ]
    assert set(channel.consent_requests[0]["scopes"]) == {
        "repository:read",
        "evidence:read",
        "observe:read",
    }
    assert any(key.startswith("client/") for key in channel.records)
    assert any(key.startswith("access/") for key in channel.records)
    assert all(tokens["access_token"] not in key for key in channel.records)
    durable_grants = "\n".join(channel.records.values())
    assert str(tmp_path) not in durable_grants
    assert "repository_root_fingerprint" in durable_grants


def test_refresh_rotates_both_tokens_and_revocation_removes_family(tmp_path: Path) -> None:
    channel = SecretChannel()
    with oauth_client(tmp_path, channel) as client:
        registered = register(client)
        code, verifier = authorize(client, registered)
        first = exchange(client, registered, code, verifier)
        refreshed_response = client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": registered["client_id"],
                "client_secret": registered["client_secret"],
                "refresh_token": first["refresh_token"],
            },
        )
        assert refreshed_response.status_code == 200
        refreshed = refreshed_response.json()
        old_access = mcp_initialize(client, first["access_token"])
        new_access = mcp_initialize(client, refreshed["access_token"])
        revoked = client.post(
            "/revoke",
            data={
                "client_id": registered["client_id"],
                "client_secret": registered["client_secret"],
                "token": refreshed["refresh_token"],
                "token_type_hint": "refresh_token",
            },
        )
        after_revoke = mcp_initialize(client, refreshed["access_token"])

    assert refreshed["access_token"] != first["access_token"]
    assert refreshed["refresh_token"] != first["refresh_token"]
    assert old_access.status_code == 401
    assert new_access.status_code == 200
    assert revoked.status_code == 200
    assert after_revoke.status_code == 401


def test_dynamic_registration_rejects_non_loopback_redirects(tmp_path: Path) -> None:
    channel = SecretChannel()
    with oauth_client(tmp_path, channel) as client:
        response = client.post(
            "/register",
            json={
                "client_name": "Unsafe client",
                "redirect_uris": ["https://attacker.example/callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"
    assert not channel.records


def test_consent_binds_token_to_explicit_registered_project(tmp_path: Path) -> None:
    second_root = tmp_path / "second-project"
    second_root.mkdir()
    second_id = "git:second:fedcba9876543210abcd"
    channel = SecretChannel(selected_repository=second_id)
    issuer = "http://127.0.0.1:8765"
    provider = ManagedOAuthProvider(
        channel,  # type: ignore[arg-type]
        repository_root=tmp_path,
        repository_id="git:example:0123456789abcdefabcd",
        issuer_url=issuer,
    )
    provider.register_project(second_root, second_id)
    config = HydraDBConfig(api_key=None, database="", collection="current")
    container = create_container(
        config,
        repository_id="git:example:0123456789abcdefabcd",
        repository_root=tmp_path,
    )
    security = ManagedSecurity(
        "installation-control-key-with-at-least-32-characters",
        permitted_hosts={"127.0.0.1"},
    )
    with TestClient(
        create_app(
            container,
            managed_security=security,
            mcp_oauth_provider=provider,
            mcp_issuer_url=issuer,
        ),
        base_url=issuer,
    ) as client:
        registered = register(client)
        code, verifier = authorize(client, registered)
        tokens = exchange(client, registered, code, verifier)
        access_records = [
            value for key, value in channel.records.items() if key.startswith("access/")
        ]

    assert channel.consent_requests[0]["projects"][1]["repository_id"] == second_id
    assert len(access_records) == 1
    assert f'"subject":"{second_id}"' in access_records[0]
    assert str(second_root) not in access_records[0]
    assert tokens["token_type"] == "Bearer"
