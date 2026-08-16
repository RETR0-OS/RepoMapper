from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from hydra_graph.config import DEFAULT_API_URL, HydraDBConfig
from hydra_graph.diagnostics import configure_logging, log_event
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


def test_managed_bootstrap_keeps_the_service_hydradb_defaults(tmp_path: Path) -> None:
    """An omitted api_url must resolve to the base URL the adapter expects.

    The adapter appends paths such as ``/query``, so a base URL that already
    carries a path segment sends every read to an address that does not exist.
    """

    start = {
        "protocol": MANAGED_PROTOCOL,
        "type": "service_start",
        "repository_root": str(tmp_path),
        "repository_id": "git:repo:1234567890abcdef1234",
        "control_key": "x" * 43,
    }
    _, settings = ManagedIpc.bootstrap(io.StringIO(json.dumps(start) + "\n"), io.StringIO())

    assert settings.api_url == DEFAULT_API_URL
    assert settings.collection == "current"
    assert settings.evolution_collection == "evolution"


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


def test_diagnostic_lines_never_reach_the_ipc_stream(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """stdout is the IPC channel, so one stray line would kill the service.

    Managed startup points ``sys.stdout`` at ``sys.stderr`` before the app is built.
    The log handler must follow that swap at write time, not capture a stream when
    the module is imported.
    """

    ipc_writer = io.StringIO()
    start = {
        "protocol": MANAGED_PROTOCOL,
        "type": "service_start",
        "repository_root": str(tmp_path),
        "repository_id": "git:repo:1234567890abcdef1234",
        "control_key": "x" * 43,
    }
    channel, _ = ManagedIpc.bootstrap(io.StringIO(json.dumps(start) + "\n"), ipc_writer)

    configure_logging()
    channel.notify("service_ready", port=8765)
    log_event("query", status="ready", outcome="ok")

    for line in ipc_writer.getvalue().splitlines():
        assert json.loads(line)["protocol"] == MANAGED_PROTOCOL
    assert "hydra.query" in capsys.readouterr().err


def test_managed_provider_caches_only_the_configured_answer_for_a_moment() -> None:
    """One query reads the sync status several times, and each read asked VS Code.

    The lease itself must stay uncached, because it carries the secret. Only the
    yes-or-no answer is held, and only for the length of one request.
    """

    clock = [1_000.0]
    channel = RespondingChannel([{"configured": True}, {"configured": False}])
    provider = ManagedCredentialProvider(
        channel,  # type: ignore[arg-type]
        monotonic=lambda: clock[0],
    )

    assert provider.configured("git:repo:1234567890abcdef1234") is True
    assert provider.configured("git:repo:1234567890abcdef1234") is True
    assert len(channel.requests) == 1

    clock[0] += 5.0
    assert provider.configured("git:repo:1234567890abcdef1234") is False
    assert [request["type"] for request in channel.requests] == [
        "credential_status",
        "credential_status",
    ]


def test_managed_provider_forgets_a_cached_answer_when_the_lease_is_refused() -> None:
    channel = RespondingChannel([{"configured": True}])
    provider = ManagedCredentialProvider(channel)  # type: ignore[arg-type]
    assert provider.configured("git:repo:1234567890abcdef1234") is True

    def refuse(message_type: str, **payload: object) -> dict[str, object]:
        channel.requests.append({"type": message_type, **payload})
        raise HydraDBUnavailable("credentials are unavailable")

    channel.request = refuse  # type: ignore[assignment]
    with pytest.raises(HydraDBUnavailable), provider.acquire("git:repo:1234567890abcdef1234"):
        pass

    # The refused lease proves the binding is gone, so the cached yes must not last:
    # the next read asks again, and it fails closed.
    assert provider.configured("git:repo:1234567890abcdef1234") is False
    assert [request["type"] for request in channel.requests] == [
        "credential_status",
        "credential_request",
        "credential_status",
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
