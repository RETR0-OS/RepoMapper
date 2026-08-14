from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from hydra_graph.config import HydraDBConfig
from hydra_graph.hydradb import HydraDBClient, HydraDBUnavailable
from hydra_graph.managed import MANAGED_PROTOCOL, ManagedCredentialProvider, ManagedIpc


class RespondingChannel:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = responses
        self.requests: list[dict[str, object]] = []

    def request(self, message_type: str, **payload: object) -> dict[str, object]:
        self.requests.append({"type": message_type, **payload})
        return self.responses.pop(0)


def test_managed_bootstrap_never_uses_environment_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HYDRA_DB_API_KEY", "must-not-be-read")
    start = {
        "protocol": MANAGED_PROTOCOL,
        "type": "service_start",
        "repository_root": str(tmp_path),
        "repository_id": "git:repo:1234567890abcdef1234",
        "control_key": "x" * 43,
    }
    reader = io.StringIO(json.dumps(start) + "\n")
    writer = io.StringIO()
    _, settings = ManagedIpc.bootstrap(reader, writer)
    assert settings.repository_root == tmp_path.resolve()
    assert settings.repository_id == "git:repo:1234567890abcdef1234"
    hello = json.loads(writer.getvalue())
    assert hello["type"] == "service_hello"
    assert "must-not-be-read" not in writer.getvalue()


def test_managed_provider_acquires_every_operation_without_caching() -> None:
    channel = RespondingChannel(
        [
            {"api_key": "first-secret", "database": "first-db"},
            {"api_key": "second-secret", "database": "second-db"},
        ]
    )
    provider = ManagedCredentialProvider(channel)  # type: ignore[arg-type]
    with provider.acquire("git:repo:1234567890abcdef1234") as first:
        assert (first.api_key, first.database) == ("first-secret", "first-db")
    with provider.acquire("git:repo:1234567890abcdef1234") as second:
        assert (second.api_key, second.database) == ("second-secret", "second-db")
    assert [request["type"] for request in channel.requests] == [
        "credential_request",
        "credential_request",
    ]


def test_managed_provider_fails_closed_without_valid_secret_values() -> None:
    provider = ManagedCredentialProvider(
        RespondingChannel([{"api_key": "short", "database": "db"}])  # type: ignore[arg-type]
    )
    with (
        pytest.raises(HydraDBUnavailable, match="invalid credentials"),
        provider.acquire("git:repo:1234567890abcdef1234"),
    ):
        pass


def test_hydradb_client_requests_a_fresh_managed_lease_for_each_query() -> None:
    channel = RespondingChannel(
        [
            {"api_key": "first-secret", "database": "first-db"},
            {"api_key": "second-secret", "database": "second-db"},
        ]
    )

    class Transport:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def request(self, **kwargs: object) -> dict[str, object]:
            self.calls.append(kwargs)
            return {"success": True, "data": {"chunks": []}}

    transport = Transport()
    client = HydraDBClient(
        HydraDBConfig(api_key=None, database="", max_retries=0),
        repository_id="git:repo:1234567890abcdef1234",
        credential_provider=ManagedCredentialProvider(channel),  # type: ignore[arg-type]
        transport=transport,
    )
    client.query(query="first")
    client.query(query="second")

    assert len(channel.requests) == 2
    assert transport.calls[0]["json_body"]["database"] == "first-db"  # type: ignore[index]
    assert transport.calls[1]["json_body"]["database"] == "second-db"  # type: ignore[index]
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer first-secret"  # type: ignore[index]
    assert transport.calls[1]["headers"]["Authorization"] == "Bearer second-secret"  # type: ignore[index]
