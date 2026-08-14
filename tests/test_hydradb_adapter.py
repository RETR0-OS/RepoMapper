from __future__ import annotations

import json
from typing import Any

import pytest
from hydra_graph.config import DEFAULT_API_URL, HydraDBConfig
from hydra_graph.hydradb import (
    HydraDBAPIError,
    HydraDBClient,
    HydraDBContractError,
    HydraDBUnavailable,
)


class RecordingTransport:
    def __init__(self, responses: list[Any] | None = None) -> None:
        self.responses = list(responses or [{"success": True, "data": {}}])
        self.requests: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> dict[str, Any]:
        self.requests.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def config(**overrides: Any) -> HydraDBConfig:
    values = {
        "api_key": "test-secret",
        "database": "repo_hack_hydra",
        "collection": "current",
        "max_retries": 0,
    }
    values.update(overrides)
    return HydraDBConfig(**values)


def test_config_reads_canonical_environment_names() -> None:
    result = HydraDBConfig.from_env(
        {
            "HYDRA_DB_API_KEY": " secret ",
            "HYDRA_DB_DATABASE": "repo",
            "HYDRA_DB_COLLECTION": "revision_a",
        }
    )

    assert result.api_key == "secret"
    assert result.database == "repo"
    assert result.collection == "revision_a"
    assert result.api_url == DEFAULT_API_URL
    assert result.configured is True


def test_ingest_uses_v2_multipart_and_matching_graph_keys() -> None:
    transport = RecordingTransport([{"success": True, "data": {"ids": ["symbol-1"]}}])
    client = HydraDBClient(config(), transport=transport)
    source = {
        "id": "symbol-1",
        "title": "authorize_user",
        "type": "code_symbol",
        "content": {"text": "authorize_user validates a token."},
        "metadata": {"repository_id": "hack-hydra", "revision_id": "abc123"},
    }
    graph = {
        "symbol-1": {
            "entities": {
                "source": {"name": "authorize_user [function] @ src/auth.py", "type": "FUNCTION"},
                "target": {"name": "token_store [class] @ src/store.py", "type": "CLASS"},
            },
            "relations": [
                {
                    "source": "source",
                    "target": "target",
                    "predicate": "CALLS",
                    "context": "src/auth.py:10 calls token_store at line 14",
                }
            ],
        }
    }

    response = client.ingest(app_knowledge=[source], graph_payload=graph)

    assert response["data"]["ids"] == ["symbol-1"]
    sent = transport.requests[0]
    assert sent["method"] == "POST"
    assert sent["url"] == "https://api.hydradb.com/context/ingest"
    assert sent["headers"]["API-Version"] == "2"
    assert sent["headers"]["Authorization"] == "Bearer test-secret"
    assert sent["form"]["type"] == "knowledge"
    assert json.loads(sent["form"]["app_knowledge"])[0]["id"] == "symbol-1"
    assert json.loads(sent["form"]["graph_payload"])["symbol-1"]["relations"][0][
        "predicate"
    ] == "CALLS"


def test_ingest_rejects_graph_for_source_not_in_request() -> None:
    client = HydraDBClient(config(), transport=RecordingTransport())

    with pytest.raises(HydraDBContractError, match="same request"):
        client.ingest(
            app_knowledge=[{"id": "present"}],
            graph_payload={"missing": {"entities": {}, "relations": []}},
        )


def test_query_uses_canonical_v2_fields_and_explicit_graph_mode() -> None:
    transport = RecordingTransport([{"success": True, "data": {"chunks": []}}])
    client = HydraDBClient(config(), transport=transport)

    client.query(
        query="How does authorization work?",
        max_results=8,
        metadata_filters={"revision_id": "abc123", "repository_id": "hack-hydra"},
    )

    sent = transport.requests[0]
    assert sent["url"].endswith("/query")
    assert sent["json_body"] == {
        "database": "repo_hack_hydra",
        "query": "How does authorization work?",
        "type": "knowledge",
        "query_by": "hybrid",
        "mode": "thinking",
        "graph_context": True,
        "query_forceful_relations": True,
        "max_results": 8,
        "collection": "current",
        "metadata_filters": {"revision_id": "abc123", "repository_id": "hack-hydra"},
    }
    assert "tenant_id" not in sent["json_body"]
    assert "sub_tenant_id" not in sent["json_body"]


def test_status_delete_and_relations_stay_behind_v2_adapter() -> None:
    transport = RecordingTransport(
        [
            {"success": True, "data": {"statuses": []}},
            {"success": True, "data": {"deleted_count": 1}},
            {"success": True, "data": {"relations": []}},
        ]
    )
    client = HydraDBClient(config(), transport=transport)

    client.status(["source-a", "source-b"])
    client.delete(["source-a"])
    client.relations("source-b", limit=25)

    status, delete, relations = transport.requests
    assert status["method"] == "GET"
    assert status["url"].endswith("/context/status")
    assert status["query"]["ids"] == "source-a,source-b"
    assert delete["method"] == "DELETE"
    assert delete["json_body"]["ids"] == ["source-a"]
    assert relations["url"].endswith("/context/relations")
    assert relations["query"]["limit"] == "25"


def test_missing_credentials_never_calls_injected_transport() -> None:
    transport = RecordingTransport([{"success": True, "data": {"chunks": [{"local": True}]}}])
    client = HydraDBClient(config(api_key=None), transport=transport)

    with pytest.raises(HydraDBUnavailable, match="unavailable"):
        client.query(query="Do not answer locally")

    assert transport.requests == []


def test_rate_limit_is_retried_but_envelope_error_is_not() -> None:
    transport = RecordingTransport(
        [
            HydraDBAPIError("slow down", code="RATE_LIMIT", status=429),
            {"success": True, "data": {"chunks": []}},
        ]
    )
    sleeps: list[float] = []
    client = HydraDBClient(
        config(max_retries=1, retry_backoff_seconds=0), transport=transport, sleep=sleeps.append
    )

    client.query(query="retry me")

    assert len(transport.requests) == 2
    assert sleeps == [0]

    failure = RecordingTransport(
        [{"success": False, "data": None, "error": {"code": "BAD", "message": "bad query"}}]
    )
    with pytest.raises(HydraDBAPIError, match="bad query"):
        HydraDBClient(config(), transport=failure).query(query="fail")


def test_retryable_5xx_is_retried_but_non_retryable_4xx_is_not() -> None:
    retryable = RecordingTransport(
        [
            HydraDBAPIError("temporary", code="UNAVAILABLE", status=503),
            {"success": True, "data": {"chunks": []}},
        ]
    )
    HydraDBClient(
        config(max_retries=1, retry_backoff_seconds=0), transport=retryable, sleep=lambda _: None
    ).query(query="retry server")
    assert len(retryable.requests) == 2

    forbidden = RecordingTransport(
        [HydraDBAPIError("forbidden", code="FORBIDDEN", status=403), {"success": True}]
    )
    with pytest.raises(HydraDBAPIError, match="forbidden"):
        HydraDBClient(
            config(max_retries=2, retry_backoff_seconds=0),
            transport=forbidden,
            sleep=lambda _: None,
        ).query(query="do not retry client errors")
    assert len(forbidden.requests) == 1
