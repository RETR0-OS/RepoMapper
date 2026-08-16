from __future__ import annotations

import json
from typing import Any

from hydra_graph.config import HydraDBConfig
from hydra_graph.hydradb import HydraDBClient, HydraDBUnavailable
from hydra_graph.relations import (
    RelationCache,
    fetch_repository_relations,
    has_byog_envelope_marker,
    result_window,
)

ENVELOPE = json.dumps(
    {
        "schema": "hack-hydra.relation-evidence.v1",
        "summary": "authorize_user calls store_token",
        "edge_id": "edge-calls",
        "quality": "exact",
        "extractor": "python-ast",
        "extractor_version": "1",
        "evidence": {
            "id": "evidence-calls",
            "path": "src/payments/auth.py",
            "start_line": 14,
            "start_column": 4,
            "end_line": 14,
            "end_column": 30,
        },
    }
)


def stored_pair(
    chunk_id: str = "chunk-authorize", context: str | None = ENVELOPE
) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "source": {"identifier": "repo:demo:python:a.py:function:a.one", "entity_id": "e1"},
        "target": {"identifier": "repo:demo:python:a.py:function:a.two", "entity_id": "e2"},
        "relations": [
            {
                "relationship_id": "rel-1",
                "canonical_predicate": "CALLS",
                "context": context,
                "confidence": 0.9,
            }
        ],
    }


class RelationTransport:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.payload


def client_for(transport: Any) -> HydraDBClient:
    return HydraDBClient(
        HydraDBConfig(api_key="test", database="repo_demo", max_retries=0),
        transport=transport,
    )


def test_result_window_reports_chunk_ids_and_sources_in_rank_order() -> None:
    response = {
        "data": {
            "chunks": [
                {"chunk_uuid": "c1", "id": "source-b"},
                {"chunk_uuid": "c2", "id": "source-a"},
                {"chunk_uuid": "c3", "id": "source-b"},
            ]
        }
    }

    chunk_ids, source_ids = result_window(response)

    assert chunk_ids == {"c1", "c2", "c3"}
    # Rank order decides which sources are read first when the budget is small.
    assert source_ids == ["source-b", "source-a"]


def test_stored_relations_become_grounded_groups() -> None:
    transport = RelationTransport({"data": {"relations": [stored_pair()]}})
    fetched = fetch_repository_relations(
        client_for(transport),
        source_ids=["source-authorize"],
        chunk_window={"chunk-authorize"},
        revision="rev-abc",
        max_sources=10,
        workers=2,
    )

    assert fetched.requested_sources == 1
    assert fetched.returned_pairs == 1
    assert fetched.outside_window == 0
    group = fetched.groups[0]
    assert group["source_chunk_ids"] == ["chunk-authorize"]
    hop = group["triplets"][0]
    assert hop["relation"]["canonical_predicate"] == "CALLS"
    assert hop["relation"]["chunk_id"] == "chunk-authorize"
    # The envelope is the only proof of an exact repository relation.
    assert hop["relation"]["origin"] == "byog"


def test_a_relation_without_an_envelope_is_never_claimed_as_byog() -> None:
    transport = RelationTransport({"data": {"relations": [stored_pair(context="prose only")]}})
    fetched = fetch_repository_relations(
        client_for(transport),
        source_ids=["source-authorize"],
        chunk_window={"chunk-authorize"},
        revision="rev-abc",
        max_sources=10,
        workers=2,
    )

    assert fetched.groups[0]["triplets"][0]["relation"]["origin"] is None


def test_a_relation_outside_the_answer_is_dropped_and_counted() -> None:
    """A chunk outside this answer carries no proof of its revision here."""

    payload = {"data": {"relations": [stored_pair(chunk_id="chunk-elsewhere")]}}
    transport = RelationTransport(payload)
    fetched = fetch_repository_relations(
        client_for(transport),
        source_ids=["source-authorize"],
        chunk_window={"chunk-authorize"},
        revision="rev-abc",
        max_sources=10,
        workers=2,
    )

    assert fetched.groups == ()
    assert fetched.outside_window == 1


def test_one_unreadable_source_never_fails_the_whole_query() -> None:
    class FailingTransport(RelationTransport):
        def request(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(kwargs)
            if kwargs["query"]["id"] == "source-bad":
                raise HydraDBUnavailable("network sentinel secret-api-key")
            return self.payload

    transport = FailingTransport({"data": {"relations": [stored_pair()]}})
    fetched = fetch_repository_relations(
        client_for(transport),
        source_ids=["source-bad", "source-good"],
        chunk_window={"chunk-authorize"},
        revision="rev-abc",
        max_sources=10,
        workers=2,
    )

    assert fetched.failures == 1
    assert len(fetched.groups) == 1
    assert "secret-api-key" not in str(fetched)


def test_source_budget_bounds_the_number_of_reads() -> None:
    transport = RelationTransport({"data": {"relations": []}})
    fetched = fetch_repository_relations(
        client_for(transport),
        source_ids=[f"source-{index}" for index in range(30)],
        chunk_window={"chunk-authorize"},
        revision="rev-abc",
        max_sources=4,
        workers=4,
    )

    assert fetched.requested_sources == 4
    assert len(transport.calls) == 4


def test_cache_serves_a_repeated_source_without_another_read() -> None:
    transport = RelationTransport({"data": {"relations": [stored_pair()]}})
    client = client_for(transport)
    cache = RelationCache()
    for _ in range(3):
        fetched = fetch_repository_relations(
            client,
            source_ids=["source-authorize"],
            chunk_window={"chunk-authorize"},
            revision="rev-abc",
            max_sources=10,
            workers=2,
            cache=cache,
        )
        assert len(fetched.groups) == 1

    assert len(transport.calls) == 1
    assert fetched.cached_sources == 1


def test_cache_never_serves_a_relation_from_another_revision() -> None:
    transport = RelationTransport({"data": {"relations": [stored_pair()]}})
    client = client_for(transport)
    cache = RelationCache()
    for revision in ("rev-a", "rev-b"):
        fetch_repository_relations(
            client,
            source_ids=["source-authorize"],
            chunk_window={"chunk-authorize"},
            revision=revision,
            max_sources=10,
            workers=2,
            cache=cache,
        )

    assert len(transport.calls) == 2


def test_envelope_marker_accepts_only_this_repositorys_exact_evidence() -> None:
    assert has_byog_envelope_marker(ENVELOPE) is True
    assert has_byog_envelope_marker("not json") is False
    assert has_byog_envelope_marker(None) is False
    assert has_byog_envelope_marker(json.dumps({"schema": "other", "quality": "exact"})) is False
    assert (
        has_byog_envelope_marker(
            json.dumps({"schema": "hack-hydra.relation-evidence.v1", "quality": "inferred"})
        )
        is False
    )
