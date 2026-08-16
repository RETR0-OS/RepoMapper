from __future__ import annotations

import json
from typing import Any

import pytest
from hydra_graph.config import DEFAULT_API_URL, HydraDBConfig
from hydra_graph.hydradb import (
    HydraDBAPIError,
    HydraDBClient,
    HydraDBContractError,
    HydraDBError,
    HydraDBTimeout,
    HydraDBUnavailable,
    _retry_after_seconds,
    accepted_ingest_ids,
    hydradb_reason,
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
            "HYDRA_DB_EVOLUTION_COLLECTION": "evolution_a",
        }
    )

    assert result.api_key == "secret"
    assert result.database == "repo"
    assert result.collection == "revision_a"
    assert result.evolution_collection == "evolution_a"
    assert result.api_url == DEFAULT_API_URL
    assert result.configured is True


def test_polling_defaults_survive_a_repository_sized_index() -> None:
    result = HydraDBConfig.from_env({"HYDRA_DB_API_KEY": "secret", "HYDRA_DB_DATABASE": "repo"})

    assert result.poll_timeout_seconds == 1800.0
    assert result.status_batch_size == 100


def test_status_batch_size_is_overridable_and_bounded() -> None:
    overridden = HydraDBConfig.from_env(
        {
            "HYDRA_DB_API_KEY": "secret",
            "HYDRA_DB_DATABASE": "repo",
            "HYDRA_DB_STATUS_BATCH_SIZE": "250",
            "HYDRA_DB_POLL_TIMEOUT_SECONDS": "60",
        }
    )
    assert overridden.status_batch_size == 250
    assert overridden.poll_timeout_seconds == 60.0

    with pytest.raises(ValueError, match="one or greater"):
        HydraDBConfig.from_env(
            {
                "HYDRA_DB_API_KEY": "secret",
                "HYDRA_DB_DATABASE": "repo",
                "HYDRA_DB_STATUS_BATCH_SIZE": "0",
            }
        )
    with pytest.raises(ValueError, match="between 1 and 500"):
        config(status_batch_size=501)


def test_hydradb_reason_reports_only_what_hydradb_returned() -> None:
    """A refusal the person cannot read is a refusal the person cannot correct."""

    reason = hydradb_reason(HydraDBAPIError("malformed API key", code="UNAUTHORIZED", status=401))

    assert reason == "HTTP 401 | UNAUTHORIZED | malformed API key"
    assert hydradb_reason(HydraDBAPIError("")) == "HydraDB returned no reason."
    # An envelope failure carries no HTTP status but still names its cause.
    assert hydradb_reason(HydraDBAPIError("database not found")) == "database not found"
    # A non-API failure has no status or code to show, only its bounded message.
    assert hydradb_reason(HydraDBUnavailable("HydraDB is unavailable")) == "HydraDB is unavailable"
    assert hydradb_reason(HydraDBError("")) == "HydraDB returned no reason."
    long_message = hydradb_reason(HydraDBAPIError("x" * 400, code="y" * 100, status=500))
    assert long_message == f"HTTP 500 | {'y' * 60} | {'x' * 200}"


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
    assert (
        json.loads(sent["form"]["graph_payload"])["symbol-1"]["relations"][0]["predicate"]
        == "CALLS"
    )


def test_current_ingest_result_shape_reports_only_accepted_source_ids() -> None:
    response = {
        "success": True,
        "data": {
            "results": [
                {"id": "accepted", "status": "queued", "error": ""},
                {"id": "rejected", "status": "failed", "error": "invalid source"},
            ]
        },
    }

    assert accepted_ingest_ids(response) == {"accepted"}


def test_legacy_ingest_result_ids_remain_supported() -> None:
    assert accepted_ingest_ids({"data": {"ids": ["source-a", "source-b"]}}) == {
        "source-a",
        "source-b",
    }


def test_ingest_rejects_graph_for_source_not_in_request() -> None:
    client = HydraDBClient(config(), transport=RecordingTransport())

    with pytest.raises(HydraDBContractError, match="same request"):
        client.ingest(
            app_knowledge=[{"id": "present"}],
            graph_payload={"missing": {"entities": {}, "relations": []}},
        )


def test_ingest_rejects_oversized_additional_metadata_locally() -> None:
    client = HydraDBClient(config(), transport=RecordingTransport())

    with pytest.raises(HydraDBContractError, match="1024-byte serialized limit"):
        client.ingest(
            app_knowledge=[
                {
                    "id": "present",
                    "additional_metadata": {"value": "x" * 1_025},
                }
            ],
            graph_payload={},
        )


def test_ingest_rejects_an_empty_byog_entity_map_locally() -> None:
    client = HydraDBClient(config(), transport=RecordingTransport())

    with pytest.raises(HydraDBContractError, match="entities must be non-empty"):
        client.ingest(
            app_knowledge=[{"id": "present"}],
            graph_payload={"present": {"entities": {}, "relations": []}},
        )


def test_ingest_rejects_an_empty_byog_relation_list_locally() -> None:
    client = HydraDBClient(config(), transport=RecordingTransport())

    with pytest.raises(HydraDBContractError, match="relations must be non-empty"):
        client.ingest(
            app_knowledge=[{"id": "present"}],
            graph_payload={
                "present": {
                    "entities": {
                        "present": {
                            "name": "present",
                            "type": "FILE",
                            "namespace": "test",
                        }
                    },
                    "relations": [],
                }
            },
        )


def test_ingest_omits_optional_graph_payload_when_no_card_has_exact_relations() -> None:
    transport = RecordingTransport([{"success": True, "data": {"ids": ["present"]}}])
    client = HydraDBClient(config(), transport=transport)

    client.ingest(app_knowledge=[{"id": "present"}], graph_payload={})

    assert "graph_payload" not in transport.requests[0]["form"]


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


def test_evolution_helpers_use_one_explicit_collection() -> None:
    transport = RecordingTransport(
        [
            {"success": True, "data": {"ids": ["delta-1"]}},
            {"success": True, "data": {"chunks": []}},
        ]
    )
    client = HydraDBClient(config(evolution_collection="evolution_records"), transport=transport)

    client.ingest_evolution(
        app_knowledge=[{"id": "delta-1"}],
        graph_payload={},
    )
    client.query_evolution(
        query="changes",
        metadata_filters={"entity_kind": "CHANGE_EVENT"},
    )

    assert transport.requests[0]["form"]["collection"] == "evolution_records"
    query = transport.requests[1]["json_body"]
    assert query["collection"] == "evolution_records"
    assert "collections" not in query


def test_current_and_evolution_collections_must_be_distinct() -> None:
    with pytest.raises(ValueError, match="must be distinct"):
        config(collection="same", evolution_collection="same")


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
    assert status["query"] == {
        "database": "repo_hack_hydra",
        "collection": "current",
        "ids": "source-a,source-b",
    }
    assert delete["method"] == "DELETE"
    assert delete["json_body"] == {
        "database": "repo_hack_hydra",
        "collection": "current",
        "ids": ["source-a"],
        "type": "knowledge",
    }
    assert delete["headers"]["X-HydraDB-Delete-Status"] == "strict"
    assert relations["url"].endswith("/context/relations")
    assert relations["query"]["limit"] == "25"


def test_status_can_target_the_evolution_collection() -> None:
    transport = RecordingTransport([{"success": True, "data": {"statuses": []}}])
    client = HydraDBClient(config(evolution_collection="evolution_records"), transport=transport)

    client.status(["delta-a"], collection=client.config.evolution_collection)

    assert transport.requests[0]["query"]["collection"] == "evolution_records"


def test_missing_credentials_never_calls_injected_transport() -> None:
    transport = RecordingTransport([{"success": True, "data": {"chunks": [{"local": True}]}}])
    client = HydraDBClient(config(api_key=None), transport=transport)

    with pytest.raises(HydraDBUnavailable, match="unavailable"):
        client.query(query="Do not answer locally")

    assert transport.requests == []


def test_slow_query_budget_covers_a_thinking_mode_answer() -> None:
    result = HydraDBConfig.from_env({"HYDRA_DB_API_KEY": "secret", "HYDRA_DB_DATABASE": "repo"})

    # A thinking-mode view query measured about 33 s on a 6,210-source repository.
    assert result.request_timeout_seconds == 90.0


def test_timeout_is_not_retried_because_the_server_keeps_working() -> None:
    transport = RecordingTransport(
        [
            HydraDBTimeout("HydraDB did not answer within 90 seconds"),
            {"success": True, "data": {"chunks": []}},
        ]
    )
    sleeps: list[float] = []
    client = HydraDBClient(
        config(max_retries=2, retry_backoff_seconds=0.25), transport=transport, sleep=sleeps.append
    )

    with pytest.raises(HydraDBTimeout, match="did not answer"):
        client.query(query="a slow thinking-mode question")

    # Three attempts would have made the caller wait three whole budgets for one answer.
    assert len(transport.requests) == 1
    assert sleeps == []


def test_refused_connection_is_still_retried() -> None:
    transport = RecordingTransport(
        [
            HydraDBUnavailable("HydraDB is unavailable"),
            {"success": True, "data": {"chunks": []}},
        ]
    )
    client = HydraDBClient(
        config(max_retries=1, retry_backoff_seconds=0), transport=transport, sleep=lambda _: None
    )

    client.query(query="retry a dropped connection")

    assert len(transport.requests) == 2


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


def test_rate_limit_honors_hydradb_retry_delay() -> None:
    transport = RecordingTransport(
        [
            HydraDBAPIError(
                "items rate limit exceeded; please retry in 11 second(s)",
                code="RATE_LIMITED",
                status=429,
                retry_after_seconds=11,
            ),
            {"success": True, "data": {"chunks": []}},
        ]
    )
    sleeps: list[float] = []
    client = HydraDBClient(
        config(max_retries=1, retry_backoff_seconds=0.25),
        transport=transport,
        sleep=sleeps.append,
    )

    client.query(query="retry after the server delay")

    assert len(transport.requests) == 2
    assert sleeps == [11]


def test_retry_delay_parses_hydradb_header_and_live_message_shape() -> None:
    assert _retry_after_seconds("12", None) == 12
    assert (
        _retry_after_seconds(
            None,
            "ingestion_items rate limit exceeded. Please retry in 11 second(s).",
        )
        == 11
    )
    assert _retry_after_seconds("9999", None) == 300


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
