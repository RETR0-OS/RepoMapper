"""HydraDB-backed query planning, normalization, and response budgeting."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .events import EventBus
from .hydradb import HydraDBClient, HydraDBError, response_data

QUERY_RESPONSE_SCHEMA = "hack-hydra.query-response.v2"


@dataclass(frozen=True, slots=True)
class QueryRequest:
    question: str
    revision: str = "current"
    max_results: int = 8
    max_context_chars: int = 7_000
    max_paths: int = 3
    max_relations: int = 30
    max_hops_per_path: int | None = None
    relation_quality: tuple[str, ...] = ("exact", "inferred")
    entity_kind: str | None = None
    query_by: str = "hybrid"
    mode: str = "thinking"
    graph_context: bool = True
    session_id: str | None = None

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("question must not be blank")
        if not 1 <= self.max_results <= 50:
            raise ValueError("max_results must be between 1 and 50")
        if self.max_context_chars < 1:
            raise ValueError("max_context_chars must be positive")
        if self.max_paths < 0 or self.max_relations < 0:
            raise ValueError("path and relation budgets cannot be negative")
        if self.max_hops_per_path is not None and self.max_hops_per_path < 1:
            raise ValueError("max_hops_per_path must be positive")


class QueryService:
    def __init__(
        self,
        client: HydraDBClient,
        *,
        repository_id: str,
        events: EventBus | None = None,
        verified_revision: Callable[[], str | None] | None = None,
        current_state_indeterminate: Callable[[], bool] | None = None,
    ) -> None:
        self.client = client
        self.repository_id = repository_id
        self.events = events or EventBus()
        self._verified_revision = verified_revision or (lambda: None)
        self._current_state_indeterminate = current_state_indeterminate or (lambda: False)

    def repository_query(self, request: QueryRequest) -> dict[str, Any]:
        session_id = request.session_id or f"session_{uuid.uuid4().hex}"
        view_id = f"view_{uuid.uuid4().hex}"
        metadata_filters: dict[str, Any] = {"repository_id": self.repository_id}
        verified_revision = self._verified_revision() if request.revision == "current" else None
        requested_revision = verified_revision or request.revision
        if requested_revision != "current":
            metadata_filters["revision_id"] = requested_revision
        if request.relation_quality:
            metadata_filters["relation_quality"] = list(request.relation_quality)
        if request.entity_kind:
            metadata_filters["entity_kind"] = request.entity_kind
        query_metadata = {
            "collections": [self.client.config.collection],
            "query_by": request.query_by,
            "mode": request.mode,
            "graph_context": request.graph_context,
            "max_results": request.max_results,
        }
        self.events.emit(
            "query_started",
            session_id=session_id,
            revision_id=requested_revision,
            view_id=view_id,
            hydradb_query_metadata=query_metadata,
        )
        if request.revision == "current" and self._current_state_indeterminate():
            return self._degraded(
                request=request,
                session_id=session_id,
                view_id=view_id,
                warning=(
                    "The current HydraDB collection is indeterminate after a failed sync; "
                    "no repository context was exposed."
                ),
                query_metadata=query_metadata,
            )
        try:
            raw = self.client.query(
                query=request.question,
                query_by=request.query_by,
                mode=request.mode,
                graph_context=request.graph_context,
                max_results=request.max_results,
                metadata_filters=metadata_filters,
            )
        except HydraDBError as exc:
            return self._unavailable(
                request=request,
                session_id=session_id,
                view_id=view_id,
                warning=str(exc),
                query_metadata=query_metadata,
            )
        result = normalize_query_response(
            raw,
            session_id=session_id,
            view_id=view_id,
            revision=request.revision,
            collections=[self.client.config.collection],
            query_by=request.query_by,
            mode=request.mode,
            graph_context=request.graph_context,
            max_context_chars=request.max_context_chars,
            max_paths=request.max_paths,
            max_relations=request.max_relations,
            max_hops_per_path=request.max_hops_per_path,
            expected_revision=(requested_revision if requested_revision != "current" else None),
            expected_entity_kind=request.entity_kind,
        )
        relationship_ids = tuple(
            dict.fromkeys(
                str(hop.get("relation", {}).get("id"))
                for path in result["paths"]
                for hop in path.get("hops", [])
                if hop.get("relation", {}).get("id")
            )
        )[:100]
        entity_ids = tuple(
            dict.fromkeys(
                str(entity.get("id"))
                for path in result["paths"]
                for hop in path.get("hops", [])
                for entity in (hop.get("source", {}), hop.get("target", {}))
                if entity.get("id")
            )
        )[:100]
        self.events.emit(
            "hydradb_result_returned",
            session_id=session_id,
            revision_id=result["revision"],
            view_id=view_id,
            entity_ids=entity_ids,
            relationship_ids=relationship_ids,
            hydradb_query_metadata=query_metadata,
        )
        for path in result["paths"]:
            self.events.emit(
                "path_replay_started",
                session_id=session_id,
                revision_id=result["revision"],
                view_id=view_id,
                hydradb_query_metadata={"path_id": path["path_id"]},
            )
            for hop in path.get("hops", []):
                relation_id = hop.get("relation", {}).get("id")
                self.events.emit(
                    "path_hop_replayed",
                    session_id=session_id,
                    revision_id=result["revision"],
                    view_id=view_id,
                    relationship_ids=(str(relation_id),) if relation_id else (),
                )
        return result

    def _unavailable(
        self,
        *,
        request: QueryRequest,
        session_id: str,
        view_id: str,
        warning: str,
        query_metadata: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "response_schema": QUERY_RESPONSE_SCHEMA,
            "session_id": session_id,
            "view_id": view_id,
            "status": "unavailable",
            "hydradb": {
                **dict(query_metadata),
                "available": False,
            },
            "revision": request.revision,
            "paths": [],
            "relations": [],
            "chunk_id_to_group_ids": {},
            "chunks": [],
            "sources": [],
            "additional_context": [],
            "warnings": [warning],
            "budget": {
                "max_context_chars": request.max_context_chars,
                "returned_context_chars": 0,
                "max_paths": request.max_paths,
                "returned_paths": 0,
                "max_relations": request.max_relations,
                "returned_relations": 0,
                "truncated": False,
            },
        }

    def _degraded(
        self,
        *,
        request: QueryRequest,
        session_id: str,
        view_id: str,
        warning: str,
        query_metadata: Mapping[str, Any],
    ) -> dict[str, Any]:
        result = self._unavailable(
            request=request,
            session_id=session_id,
            view_id=view_id,
            warning=warning,
            query_metadata=query_metadata,
        )
        result["status"] = "degraded"
        result["hydradb"]["available"] = True
        result["budget"]["truncated"] = True
        return result


def normalize_query_response(
    response: Mapping[str, Any],
    *,
    session_id: str,
    view_id: str,
    revision: str,
    collections: Sequence[str],
    query_by: str,
    mode: str,
    graph_context: bool,
    max_context_chars: int,
    max_paths: int,
    max_relations: int,
    max_hops_per_path: int | None = None,
    expected_revision: str | None = None,
    expected_entity_kind: str | None = None,
) -> dict[str, Any]:
    data = response_data(response)
    raw_chunks = _mapping_list(data.get("chunks"))
    chunk_revisions = [
        str(_mapping(chunk.get("metadata")).get("revision_id"))
        for chunk in raw_chunks
        if _mapping(chunk.get("metadata")).get("revision_id")
    ]
    returned_revisions = set(chunk_revisions)
    target_revision = expected_revision or (
        next(iter(returned_revisions)) if len(returned_revisions) == 1 else None
    )
    revision_conflict = bool(
        raw_chunks
        and (
            len(chunk_revisions) != len(raw_chunks)
            or target_revision is None
            or returned_revisions != {target_revision}
            or not _related_data_matches_revision(data, target_revision, raw_chunks)
        )
    )
    if revision_conflict:
        return _revision_conflict_response(
            session_id=session_id,
            view_id=view_id,
            revision=expected_revision or revision,
            collections=collections,
            query_by=query_by,
            mode=mode,
            graph_context=graph_context,
            max_context_chars=max_context_chars,
            max_paths=max_paths,
            max_relations=max_relations,
            returned_revisions=returned_revisions,
        )
    if expected_entity_kind and any(
        _mapping(chunk.get("metadata")).get("entity_kind") != expected_entity_kind
        for chunk in raw_chunks
    ):
        return _revision_conflict_response(
            session_id=session_id,
            view_id=view_id,
            revision=target_revision or revision,
            collections=collections,
            query_by=query_by,
            mode=mode,
            graph_context=graph_context,
            max_context_chars=max_context_chars,
            max_paths=max_paths,
            max_relations=max_relations,
            returned_revisions=returned_revisions,
            warning=(
                f"HydraDB did not return the requested {expected_entity_kind} records; "
                "no generic repository chunks were presented as specialized results."
            ),
        )
    graph = _mapping(data.get("graph_context"))
    raw_paths = _mapping_list(graph.get("query_paths"))
    raw_relations = _mapping_list(graph.get("chunk_relations"))
    warnings: list[str] = []
    raw_budgeted_chunks, raw_additional, returned_chars, context_truncated = _budget_context(
        raw_chunks,
        _additional_context(data.get("additional_context")),
        max_context_chars,
    )
    if context_truncated:
        warnings.append("Context character budget truncated HydraDB content.")
    chunk_groups = _mapping(graph.get("chunk_id_to_group_ids"))
    chunks = [
        _normalize_chunk(chunk, rank=index + 1, group_ids=chunk_groups)
        for index, chunk in enumerate(raw_budgeted_chunks)
    ]
    additional = [
        _normalize_chunk(item, rank=index + 1, group_ids={})
        for index, item in enumerate(raw_additional)
    ]
    entity_ids = _entity_id_lookup(raw_chunks)
    paths, path_hops, path_truncated = _normalize_groups(
        raw_paths,
        group_limit=max_paths,
        hop_limit=max_relations,
        per_group_hop_limit=max_hops_per_path,
        entity_ids=entity_ids,
    )
    remaining_hops = max(0, max_relations - path_hops)
    relations, relation_hops, relation_truncated = _normalize_groups(
        raw_relations,
        group_limit=len(raw_relations),
        hop_limit=remaining_hops,
        per_group_hop_limit=max_hops_per_path,
        entity_ids=entity_ids,
    )
    if path_truncated:
        warnings.append("Path or hop budget truncated HydraDB returned paths.")
    if relation_truncated:
        warnings.append("Relation budget truncated HydraDB relation groups or hops.")
    revision_id = _revision_from_chunks(chunks) or target_revision or revision
    path_ids = [str(path["path_id"]) for path in paths]
    has_byog = any(
        hop.get("relation", {}).get("origin") == "byog"
        for path in (*paths, *relations)
        for hop in path.get("hops", [])
    )
    return {
        "response_schema": QUERY_RESPONSE_SCHEMA,
        "session_id": session_id,
        "view_id": view_id,
        "status": "ready",
        "hydradb": {
            "available": True,
            "collections": list(collections),
            "query_by": query_by,
            "mode": mode,
            "graph_context": graph_context,
            "path_ids": path_ids,
            "origin": "byog" if has_byog else None,
            "request_id": _mapping(response.get("meta")).get("request_id"),
        },
        "revision": revision_id,
        "paths": paths,
        "relations": relations,
        "chunk_id_to_group_ids": {
            str(chunk_id): [str(group_id) for group_id in group_ids]
            for chunk_id, group_ids in chunk_groups.items()
            if isinstance(group_ids, Sequence) and not isinstance(group_ids, (str, bytes))
        },
        # Order is exactly the order returned by HydraDB. Budgeting only removes
        # the tail or trims the final included chunk.
        "chunks": chunks,
        "sources": [_normalize_source(item) for item in _mapping_list(data.get("sources"))],
        "additional_context": additional,
        "warnings": warnings,
        "budget": {
            "max_context_chars": max_context_chars,
            "returned_context_chars": returned_chars,
            "max_paths": max_paths,
            "returned_paths": len(paths),
            "max_relations": max_relations,
            "returned_relations": path_hops + relation_hops,
            "truncated": bool(warnings),
        },
    }


def _revision_conflict_response(
    *,
    session_id: str,
    view_id: str,
    revision: str,
    collections: Sequence[str],
    query_by: str,
    mode: str,
    graph_context: bool,
    max_context_chars: int,
    max_paths: int,
    max_relations: int,
    returned_revisions: set[str],
    warning: str | None = None,
) -> dict[str, Any]:
    revisions = ", ".join(sorted(returned_revisions)) or "missing revision metadata"
    return {
        "response_schema": QUERY_RESPONSE_SCHEMA,
        "session_id": session_id,
        "view_id": view_id,
        "status": "degraded",
        "hydradb": {
            "available": True,
            "collections": list(collections),
            "query_by": query_by,
            "mode": mode,
            "graph_context": graph_context,
            "path_ids": [],
            "origin": None,
            "request_id": None,
        },
        "revision": revision,
        "paths": [],
        "relations": [],
        "chunk_id_to_group_ids": {},
        "chunks": [],
        "sources": [],
        "additional_context": [],
        "warnings": [
            warning
            or (
                "HydraDB returned an inconsistent revision slice "
                f"({revisions}); no mixed repository context was exposed."
            )
        ],
        "budget": {
            "max_context_chars": max_context_chars,
            "returned_context_chars": 0,
            "max_paths": max_paths,
            "returned_paths": 0,
            "max_relations": max_relations,
            "returned_relations": 0,
            "truncated": True,
        },
    }


def _related_data_matches_revision(
    data: Mapping[str, Any], target_revision: str, chunks: Sequence[Mapping[str, Any]]
) -> bool:
    for source in _mapping_list(data.get("sources")):
        if _mapping(source.get("metadata")).get("revision_id") != target_revision:
            return False
    for item in _additional_context(data.get("additional_context")):
        if _mapping(item.get("metadata")).get("revision_id") != target_revision:
            return False
    chunk_ids = {str(chunk.get("chunk_uuid")) for chunk in chunks if chunk.get("chunk_uuid")}
    graph = _mapping(data.get("graph_context"))
    groups = [
        *_mapping_list(graph.get("query_paths")),
        *_mapping_list(graph.get("chunk_relations")),
    ]
    for group in groups:
        linked = {str(item) for item in group.get("source_chunk_ids", [])}
        if not linked.issubset(chunk_ids):
            return False
        for triplet in group.get("triplets", []):
            relation_chunk = _mapping(_mapping(triplet).get("relation")).get("chunk_id")
            if relation_chunk and str(relation_chunk) not in chunk_ids:
                return False
    return True


def _budget_context(
    chunks: list[dict[str, Any]], additional: list[dict[str, Any]], limit: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, bool]:
    remaining = limit
    returned_chunks: list[dict[str, Any]] = []
    returned_additional: list[dict[str, Any]] = []
    truncated = False
    for source, destination in ((chunks, returned_chunks), (additional, returned_additional)):
        for index, item in enumerate(source):
            content = str(item.get("chunk_content", ""))
            if len(content) <= remaining:
                destination.append(dict(item))
                remaining -= len(content)
                continue
            if remaining:
                clipped = dict(item)
                clipped["chunk_content"] = content[:remaining]
                clipped["content_truncated"] = True
                destination.append(clipped)
                remaining = 0
            truncated = True
            # Everything after this item is lower-ranked HydraDB content.
            if index < len(source) - 1:
                truncated = True
            break
        if remaining == 0:
            if source is chunks and additional:
                truncated = True
            break
    return returned_chunks, returned_additional, limit - remaining, truncated


def _additional_context(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        return [
            {"context_id": str(key), **dict(item)}
            for key, item in value.items()
            if isinstance(item, Mapping)
        ]
    return _mapping_list(value)


def _normalize_chunk(
    chunk: Mapping[str, Any], *, rank: int, group_ids: Mapping[str, Any]
) -> dict[str, Any]:
    metadata = _mapping(chunk.get("metadata"))
    additional = _mapping(chunk.get("additional_metadata"))
    chunk_id = str(chunk.get("chunk_uuid") or chunk.get("context_id") or "")
    span = _source_span(additional)
    return {
        "rank": rank,
        "chunk_id": chunk_id,
        "source_id": str(chunk.get("id") or ""),
        "content": str(chunk.get("chunk_content") or ""),
        "content_truncated": bool(chunk.get("content_truncated", False)),
        "title": str(chunk.get("source_title") or ""),
        "source_type": str(chunk.get("source_type") or ""),
        "score": chunk.get("relevancy_score"),
        "path": additional.get("path"),
        "span": span,
        "revision": metadata.get("revision_id"),
        "repository_id": metadata.get("repository_id"),
        "entity_kind": metadata.get("entity_kind"),
        "language": metadata.get("language"),
        "relation_quality": metadata.get("relation_quality"),
        "node_id": additional.get("node_id"),
        "logical_id": additional.get("logical_id"),
        "qualified_name": additional.get("qualified_name"),
        "signature": additional.get("signature"),
        "content_hash": additional.get("content_hash"),
        "parser": additional.get("parser"),
        "parser_version": additional.get("parser_version"),
        "is_generated": bool(metadata.get("is_generated", False)),
        "group_ids": [str(item) for item in group_ids.get(chunk_id, [])],
    }


def _normalize_source(source: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _mapping(source.get("metadata"))
    additional = _mapping(source.get("additional_metadata"))
    return {
        "source_id": str(source.get("id") or ""),
        "title": str(source.get("title") or ""),
        "source_type": str(source.get("type") or ""),
        "path": additional.get("path"),
        "revision": metadata.get("revision_id"),
        "repository_id": metadata.get("repository_id"),
    }


def _normalize_groups(
    groups: Sequence[Mapping[str, Any]],
    *,
    group_limit: int,
    hop_limit: int,
    per_group_hop_limit: int | None,
    entity_ids: Mapping[str, str],
) -> tuple[list[dict[str, Any]], int, bool]:
    normalized: list[dict[str, Any]] = []
    used_hops = 0
    truncated = len(groups) > group_limit
    for rank, group in enumerate(groups[:group_limit], start=1):
        raw_hops = _mapping_list(group.get("triplets"))
        available = max(0, hop_limit - used_hops)
        group_available = (
            min(available, per_group_hop_limit) if per_group_hop_limit is not None else available
        )
        selected = raw_hops[:group_available]
        if len(selected) < len(raw_hops):
            truncated = True
        if not selected:
            if raw_hops:
                break
            continue
        hops = [
            _normalize_hop(item, index=index, entity_ids=entity_ids)
            for index, item in enumerate(selected, start=1)
        ]
        normalized.append(
            {
                "path_id": _stable_path_id(group, hops),
                "rank": rank,
                "score": group.get("relevancy_score"),
                "summary": str(group.get("combined_context") or ""),
                "chunk_ids": [str(item) for item in group.get("source_chunk_ids", [])],
                "hops": hops,
            }
        )
        used_hops += len(hops)
        if used_hops >= hop_limit:
            if rank < min(len(groups), group_limit):
                truncated = True
            break
    return normalized, used_hops, truncated


def _normalize_hop(
    triplet: Mapping[str, Any], *, index: int, entity_ids: Mapping[str, str]
) -> dict[str, Any]:
    relation = _mapping(triplet.get("relation"))
    return {
        "hop": index,
        "source": _normalize_entity(_mapping(triplet.get("source")), entity_ids),
        "relation": {
            "id": relation.get("relationship_id"),
            "predicate": relation.get("canonical_predicate") or relation.get("raw_predicate"),
            "raw_predicate": relation.get("raw_predicate"),
            "context": relation.get("context"),
            "confidence": relation.get("confidence"),
            "origin": relation.get("origin"),
            "chunk_id": relation.get("chunk_id"),
        },
        "target": _normalize_entity(_mapping(triplet.get("target")), entity_ids),
    }


def _normalize_entity(entity: Mapping[str, Any], entity_ids: Mapping[str, str]) -> dict[str, Any]:
    identifier = str(entity.get("identifier") or "")
    hydradb_id = str(entity.get("entity_id") or "")
    return {
        "id": entity_ids.get(identifier) or identifier or hydradb_id,
        "logical_id": identifier or None,
        "hydradb_entity_id": hydradb_id or None,
        "name": str(entity.get("name") or ""),
        "kind": str(entity.get("type") or "UNKNOWN"),
        "namespace": entity.get("namespace"),
    }


def _entity_id_lookup(chunks: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for chunk in chunks:
        additional = _mapping(chunk.get("additional_metadata"))
        node_id = additional.get("node_id")
        if not node_id:
            continue
        node_id = str(node_id)
        lookup[node_id] = node_id
        logical_id = additional.get("logical_id")
        if logical_id:
            lookup[str(logical_id)] = node_id
    return lookup


def _stable_path_id(group: Mapping[str, Any], hops: Sequence[Mapping[str, Any]]) -> str:
    group_id = group.get("group_id")
    if group_id:
        return str(group_id)
    relation_ids = [str(hop["relation"].get("id") or "") for hop in hops]
    joined = "-".join(item for item in relation_ids if item)
    if joined:
        return joined
    encoded = json.dumps(hops, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return f"path_{hashlib.sha256(encoded).hexdigest()[:24]}"


def _source_span(additional: Mapping[str, Any]) -> dict[str, int] | None:
    keys = ("start_line", "start_column", "end_line", "end_column")
    if not all(additional.get(key) is not None for key in keys):
        return None
    try:
        return {key: int(additional[key]) for key in keys}
    except (TypeError, ValueError):
        return None


def _revision_from_chunks(chunks: Sequence[Mapping[str, Any]]) -> str | None:
    for chunk in chunks:
        revision = chunk.get("revision")
        if revision:
            return str(revision)
    return None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]
