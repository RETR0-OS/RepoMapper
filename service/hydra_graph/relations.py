"""Read this repository's own graph from HydraDB instead of the query's ranking.

A repository query returns a fixed, small number of relation groups, and it ranks
HydraDB's own concept relations in the same list as the graph this repository
uploaded. A question written in prose fills every slot with concept relations, and
no concept can be grounded in a source card. The uploaded graph is not lost; it is
out-ranked.

``/context/relations`` answers for one source at a time, and it returns only the
stored graph. The relations it gives back are always this repository's own, so this
module reads the graph from there and gives the query only the job it does well:
deciding which sources are relevant.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock
from typing import Any

from .diagnostics import log_event
from .hydradb import HydraDBClient, HydraDBError, response_data

MAX_RELATIONS_PER_SOURCE = 100
EVIDENCE_SCHEMA = "hack-hydra.relation-evidence.v1"
_RELATION_LIST_KEYS = ("relations", "results", "edges", "triplets")
_PREDICATE_KEYS = ("canonical_predicate", "raw_predicate", "predicate")
_RELATION_ID_KEYS = ("relationship_id", "relation_id", "id")


@dataclass(frozen=True, slots=True)
class FetchedRelations:
    """What one relation read produced, and what it cost."""

    groups: tuple[dict[str, Any], ...] = ()
    requested_sources: int = 0
    cached_sources: int = 0
    returned_pairs: int = 0
    outside_window: int = 0
    failures: int = 0
    # Logical ids of the entities a stored relation named while its chunk stayed
    # outside this answer. They are the code that joins the matched chunks, so the
    # caller can fetch them and ask again instead of showing a disconnected graph.
    outside_endpoints: tuple[str, ...] = ()


class RelationCache:
    """Bounded cache of stored relations, keyed by collection, revision, and source.

    A source is immutable inside one revision, so a hit can never serve a relation
    from another revision. The revision is part of the key for that reason.
    """

    def __init__(self, *, limit: int = 2_048) -> None:
        if limit < 1:
            raise ValueError("relation cache limit must be positive")
        self._limit = limit
        self._items: OrderedDict[tuple[str, str, str], tuple[Mapping[str, Any], ...]] = (
            OrderedDict()
        )
        self._lock = Lock()

    def get(self, key: tuple[str, str, str]) -> tuple[Mapping[str, Any], ...] | None:
        with self._lock:
            value = self._items.get(key)
            if value is not None:
                self._items.move_to_end(key)
            return value

    def put(self, key: tuple[str, str, str], value: Sequence[Mapping[str, Any]]) -> None:
        with self._lock:
            self._items[key] = tuple(value)
            self._items.move_to_end(key)
            while len(self._items) > self._limit:
                self._items.popitem(last=False)


def has_byog_envelope_marker(value: Any) -> bool:
    """Answer whether a relation context is this repository's exact evidence envelope."""

    if not isinstance(value, str):
        return False
    try:
        envelope = json.loads(value)
    except json.JSONDecodeError:
        return False
    return bool(
        isinstance(envelope, Mapping)
        and envelope.get("schema") == EVIDENCE_SCHEMA
        and envelope.get("quality") == "exact"
    )


def result_window(response: Mapping[str, Any]) -> tuple[set[str], list[str]]:
    """Return the chunk ids in this answer and its source ids in rank order."""

    data = response_data(response)
    chunks = data.get("chunks")
    chunk_ids: set[str] = set()
    source_ids: list[str] = []
    if not isinstance(chunks, Sequence) or isinstance(chunks, (str, bytes)):
        return chunk_ids, source_ids
    for chunk in chunks:
        if not isinstance(chunk, Mapping):
            continue
        if chunk.get("chunk_uuid"):
            chunk_ids.add(str(chunk["chunk_uuid"]))
        source_id = str(chunk.get("id") or "")
        if source_id and source_id not in source_ids:
            source_ids.append(source_id)
    return chunk_ids, source_ids


def fetch_repository_relations(
    client: HydraDBClient,
    *,
    source_ids: Sequence[str],
    chunk_window: set[str],
    revision: str,
    max_sources: int,
    workers: int,
    limit: int = MAX_RELATIONS_PER_SOURCE,
    cache: RelationCache | None = None,
) -> FetchedRelations:
    """Read the stored graph for the most relevant sources in one answer.

    Only relations whose chunk came back in this same answer are kept. That is the
    same rule the query path already applies: a chunk outside the answer carries no
    proof of its revision here, so a relation that cites it cannot be shown.
    """

    selected = [source_id for source_id in source_ids if source_id][:max_sources]
    if not selected or not chunk_window:
        return FetchedRelations(requested_sources=0)

    collection = client.config.collection
    records: dict[str, tuple[Mapping[str, Any], ...]] = {}
    cached = 0
    pending: list[str] = []
    for source_id in selected:
        hit = cache.get((collection, revision, source_id)) if cache else None
        if hit is None:
            pending.append(source_id)
        else:
            records[source_id] = hit
            cached += 1

    failures = 0
    if pending:
        # One read per source is the only shape this endpoint offers, so the reads
        # run together. The credential lease still serializes, and that is bounded.
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(pending)))) as pool:
            for source_id, result in zip(
                pending,
                pool.map(lambda item: _read_one(client, item, limit), pending),
                strict=True,
            ):
                if result is None:
                    failures += 1
                    continue
                records[source_id] = result
                if cache:
                    cache.put((collection, revision, source_id), result)

    groups: list[dict[str, Any]] = []
    returned_pairs = 0
    outside_window = 0
    outside_endpoints: list[str] = []
    seen_endpoints: set[str] = set()
    for source_id in selected:
        for record in records.get(source_id, ()):
            returned_pairs += 1
            group = _group_from_record(record, chunk_window)
            if group is None:
                outside_window += 1
                for identifier in _record_endpoints(record):
                    if identifier not in seen_endpoints:
                        seen_endpoints.add(identifier)
                        outside_endpoints.append(identifier)
                continue
            groups.append(group)
    return FetchedRelations(
        groups=tuple(groups),
        requested_sources=len(selected),
        cached_sources=cached,
        returned_pairs=returned_pairs,
        outside_window=outside_window,
        failures=failures,
        outside_endpoints=tuple(outside_endpoints),
    )


def _record_endpoints(record: Mapping[str, Any]) -> list[str]:
    """Return the logical ids this stored relation names on either side."""

    identifiers: list[str] = []
    for key in ("source", "target"):
        entity = _entity(record.get(key))
        identifier = (entity or {}).get("identifier")
        if identifier:
            identifiers.append(str(identifier))
    return identifiers


def _read_one(
    client: HydraDBClient, source_id: str, limit: int
) -> tuple[Mapping[str, Any], ...] | None:
    """Return the stored relations for one source, or ``None`` when the read failed.

    One unreadable source must never fail the whole query. The count of failures is
    reported instead, so a silent partial graph is impossible.
    """

    try:
        data = response_data(client.relations(source_id, limit=limit))
    except HydraDBError as exc:
        log_event("relations.failed", source=source_id, error=type(exc).__name__)
        return None
    for key in _RELATION_LIST_KEYS:
        value = data.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return tuple(item for item in value if isinstance(item, Mapping))
    return ()


def _group_from_record(record: Mapping[str, Any], chunk_window: set[str]) -> dict[str, Any] | None:
    """Shape one stored entity pair as a HydraDB relation group.

    Downstream normalization and budgeting stay unchanged, because the result uses
    the same shape the query's own graph context uses.
    """

    chunk_id = record.get("chunk_id")
    if not chunk_id or str(chunk_id) not in chunk_window:
        return None
    source = _entity(record.get("source"))
    target = _entity(record.get("target"))
    if not source or not target:
        return None
    details = record.get("relations")
    if not isinstance(details, Sequence) or isinstance(details, (str, bytes)):
        details = [record]
    triplets: list[dict[str, Any]] = []
    for detail in details:
        if not isinstance(detail, Mapping):
            continue
        predicate = _first(detail, _PREDICATE_KEYS)
        if not predicate:
            continue
        context = detail.get("context")
        triplets.append(
            {
                "source": source,
                "target": target,
                "relation": {
                    "relationship_id": _first(detail, _RELATION_ID_KEYS),
                    "canonical_predicate": predicate,
                    "raw_predicate": detail.get("raw_predicate") or predicate,
                    "context": context,
                    "confidence": detail.get("confidence"),
                    # The envelope is the proof, so only an envelope earns the claim.
                    "origin": "byog" if has_byog_envelope_marker(context) else detail.get("origin"),
                    "chunk_id": str(chunk_id),
                },
            }
        )
    if not triplets:
        return None
    return {
        "group_id": _group_id(triplets),
        "relevancy_score": None,
        "combined_context": "",
        "source_chunk_ids": [str(chunk_id)],
        "triplets": triplets,
    }


def _entity(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    identifier = str(value.get("identifier") or "")
    entity_id = str(value.get("entity_id") or "")
    if not identifier and not entity_id:
        return None
    return {
        "identifier": identifier or None,
        "entity_id": entity_id or None,
        "name": value.get("name"),
        "type": value.get("type"),
        "namespace": value.get("namespace"),
    }


def _first(record: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        value = record.get(key)
        if value:
            return value
    return None


def _group_id(triplets: Sequence[Mapping[str, Any]]) -> str:
    ids = [str(item["relation"].get("relationship_id") or "") for item in triplets]
    joined = "-".join(value for value in ids if value)
    if joined:
        return joined
    encoded = json.dumps(triplets, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return f"relations_{hashlib.sha256(encoded).hexdigest()[:24]}"
