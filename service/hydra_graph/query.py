"""HydraDB-backed query planning, normalization, and response budgeting."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .events import EventBus
from .hydradb import HydraDBClient, HydraDBError, response_data


@dataclass(frozen=True, slots=True)
class QueryRequest:
    question: str
    revision: str = "current"
    max_results: int = 8
    max_context_chars: int = 7_000
    max_paths: int = 3
    max_relations: int = 30
    relation_quality: tuple[str, ...] = ("exact", "inferred")
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


class QueryService:
    def __init__(
        self,
        client: HydraDBClient,
        *,
        repository_id: str,
        events: EventBus | None = None,
    ) -> None:
        self.client = client
        self.repository_id = repository_id
        self.events = events or EventBus()

    def repository_query(self, request: QueryRequest) -> dict[str, Any]:
        session_id = request.session_id or f"session_{uuid.uuid4().hex}"
        view_id = f"view_{uuid.uuid4().hex}"
        metadata_filters: dict[str, Any] = {"repository_id": self.repository_id}
        if request.revision != "current":
            metadata_filters["revision_id"] = request.revision
        if request.relation_quality:
            metadata_filters["relation_quality"] = list(request.relation_quality)
        query_metadata = {
            "database": self.client.config.database,
            "collections": [self.client.config.collection],
            "query_by": request.query_by,
            "mode": request.mode,
            "graph_context": request.graph_context,
            "max_results": request.max_results,
        }
        self.events.emit(
            "query_started",
            session_id=session_id,
            revision_id=request.revision,
            view_id=view_id,
            hydradb_query_metadata=query_metadata,
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
            database=self.client.config.database,
            collections=[self.client.config.collection],
            query_by=request.query_by,
            mode=request.mode,
            graph_context=request.graph_context,
            max_context_chars=request.max_context_chars,
            max_paths=request.max_paths,
            max_relations=request.max_relations,
        )
        relationship_ids = tuple(
            str(triplet.get("relation", {}).get("relationship_id"))
            for path in result["paths"]
            for triplet in path.get("triplets", [])
            if triplet.get("relation", {}).get("relationship_id")
        )
        entity_ids = tuple(
            str(entity.get("identifier") or entity.get("entity_id"))
            for path in result["paths"]
            for triplet in path.get("triplets", [])
            for entity in (triplet.get("source", {}), triplet.get("target", {}))
            if entity.get("identifier") or entity.get("entity_id")
        )
        self.events.emit(
            "hydradb_result_returned",
            session_id=session_id,
            revision_id=result["revision"],
            view_id=view_id,
            entity_ids=tuple(dict.fromkeys(entity_ids)),
            relationship_ids=tuple(dict.fromkeys(relationship_ids)),
            hydradb_query_metadata=query_metadata,
        )
        for path in result["paths"]:
            self.events.emit(
                "path_replay_started",
                session_id=session_id,
                revision_id=result["revision"],
                view_id=view_id,
                hydradb_query_metadata={"path_id": _path_id(path)},
            )
            for triplet in path.get("triplets", []):
                relation_id = triplet.get("relation", {}).get("relationship_id")
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


def normalize_query_response(
    response: Mapping[str, Any],
    *,
    session_id: str,
    view_id: str,
    revision: str,
    database: str,
    collections: Sequence[str],
    query_by: str,
    mode: str,
    graph_context: bool,
    max_context_chars: int,
    max_paths: int,
    max_relations: int,
) -> dict[str, Any]:
    data = response_data(response)
    graph = _mapping(data.get("graph_context"))
    raw_paths = _mapping_list(graph.get("query_paths"))
    raw_relations = _mapping_list(graph.get("chunk_relations"))
    paths = raw_paths[:max_paths]
    relations = raw_relations[:max_relations]
    warnings: list[str] = []
    if len(paths) < len(raw_paths):
        warnings.append(f"Path budget truncated {len(raw_paths) - len(paths)} HydraDB path(s).")
    if len(relations) < len(raw_relations):
        relation_difference = len(raw_relations) - len(relations)
        warnings.append(
            f"Relation budget truncated {relation_difference} HydraDB relation group(s)."
        )
    chunks, additional, returned_chars, context_truncated = _budget_context(
        _mapping_list(data.get("chunks")),
        _additional_context(data.get("additional_context")),
        max_context_chars,
    )
    if context_truncated:
        warnings.append("Context character budget truncated HydraDB content.")
    revision_id = _revision_from_chunks(chunks) or revision
    path_ids = [_path_id(path) for path in paths]
    has_byog = any(
        triplet.get("relation", {}).get("origin") == "byog"
        for path in (*paths, *relations)
        for triplet in path.get("triplets", [])
    )
    return {
        "session_id": session_id,
        "view_id": view_id,
        "status": "ready",
        "hydradb": {
            "available": True,
            "database": database,
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
        "chunk_id_to_group_ids": dict(_mapping(graph.get("chunk_id_to_group_ids"))),
        # Order is exactly the order returned by HydraDB. Budgeting only removes
        # the tail or trims the final included chunk.
        "chunks": chunks,
        "sources": _mapping_list(data.get("sources")),
        "additional_context": additional,
        "warnings": warnings,
        "budget": {
            "max_context_chars": max_context_chars,
            "returned_context_chars": returned_chars,
            "max_paths": max_paths,
            "returned_paths": len(paths),
            "max_relations": max_relations,
            "returned_relations": len(relations),
            "truncated": bool(warnings),
        },
    }


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


def _path_id(path: Mapping[str, Any]) -> str:
    group = path.get("group_id")
    if group:
        return str(group)
    relations = [
        str(item.get("relation", {}).get("relationship_id", ""))
        for item in path.get("triplets", [])
    ]
    joined = "-".join(part for part in relations if part)
    return joined or f"path_{uuid.uuid4().hex}"


def _revision_from_chunks(chunks: Sequence[Mapping[str, Any]]) -> str | None:
    for chunk in chunks:
        revision = _mapping(chunk.get("metadata")).get("revision_id")
        if revision:
            return str(revision)
    return None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]
