"""Stable six-mode product views built only from HydraDB query results."""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .query import QueryRequest, QueryService


class ViewMode(StrEnum):
    REPOSITORY = "repository"
    EXPLORE = "explore"
    TRACE = "trace"
    OBSERVE = "observe"
    COMPARE = "compare"
    PRESERVE = "preserve"


class ViewDepth(StrEnum):
    PACKAGE = "package"
    FILE = "file"
    SYMBOL = "symbol"


@dataclass(frozen=True, slots=True)
class ViewRequest:
    mode: ViewMode
    revision: str = "current"
    depth: ViewDepth = ViewDepth.SYMBOL
    question: str | None = None
    max_nodes: int = 50
    max_edges: int = 80
    session_id: str | None = None

    def __post_init__(self) -> None:
        if self.max_nodes < 1 or self.max_edges < 0:
            raise ValueError("View budgets must be non-negative and include at least one node")


class ViewStore:
    """Small bounded cache of currently displayed HydraDB results."""

    def __init__(self, *, limit: int = 50) -> None:
        self.limit = limit
        self._items: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def put(self, view: Mapping[str, Any], query_result: Mapping[str, Any]) -> None:
        view_id = str(view["view_id"])
        self._items[view_id] = {"view": dict(view), "query": dict(query_result)}
        self._items.move_to_end(view_id)
        while len(self._items) > self.limit:
            self._items.popitem(last=False)

    def get(self, view_id: str) -> dict[str, Any] | None:
        item = self._items.get(view_id)
        return dict(item) if item else None


class ViewService:
    def __init__(self, query_service: QueryService, *, store: ViewStore | None = None) -> None:
        self.query_service = query_service
        self.store = store or ViewStore()

    def load(self, request: ViewRequest) -> dict[str, Any]:
        question = request.question or _default_question(request.mode, request.depth)
        query = self.query_service.repository_query(
            QueryRequest(
                question=question,
                revision=request.revision,
                max_results=min(50, max(4, request.max_nodes)),
                max_paths=max(1, min(10, request.max_edges)),
                max_relations=request.max_edges,
                session_id=request.session_id,
            )
        )
        view = build_product_view(
            query,
            mode=request.mode,
            depth=request.depth,
            max_nodes=request.max_nodes,
            max_edges=request.max_edges,
        )
        self.store.put(view, query)
        return view

    def explain_relationship(self, view_id: str, relationship_id: str) -> dict[str, Any] | None:
        stored = self.store.get(view_id)
        if not stored:
            return None
        view = stored["view"]
        edge = next((item for item in view.get("edges", []) if item["id"] == relationship_id), None)
        if edge is None:
            return None
        return {
            "view_id": view_id,
            "relationship_id": relationship_id,
            "source_id": edge["source_id"],
            "target_id": edge["target_id"],
            "predicate": edge["predicate"],
            "quality": edge["quality"],
            "explanation": edge["attributes"].get("context", "HydraDB returned this relation."),
            "hydradb_origin": edge["attributes"].get("hydradb_origin"),
            "evidence": edge["evidence"],
        }


def build_product_view(
    query: Mapping[str, Any],
    *,
    mode: ViewMode,
    depth: ViewDepth,
    max_nodes: int,
    max_edges: int,
) -> dict[str, Any]:
    warnings = list(query.get("warnings", []))
    if query.get("status") != "ready":
        return {
            "view_id": str(query["view_id"]),
            "revision_id": str(query.get("revision", "current")),
            "mode": mode.value,
            "depth": depth.value,
            "nodes": [],
            "edges": [],
            "aggregates": [],
            "hydradb": _view_hydradb(query),
            "warnings": warnings or ["HydraDB is unavailable."],
            "budget": {
                "requested_nodes": max_nodes,
                "returned_nodes": 0,
                "requested_edges": max_edges,
                "returned_edges": 0,
                "truncated": False,
            },
        }
    symbol_nodes, symbol_edges = _symbol_graph(query)
    aggregates: list[dict[str, Any]] = []
    if mode is ViewMode.REPOSITORY and depth is not ViewDepth.SYMBOL:
        nodes, edges, aggregates = _aggregate(
            symbol_nodes, symbol_edges, depth, str(query["revision"])
        )
    else:
        nodes, edges = symbol_nodes, symbol_edges
    nodes = nodes[:max_nodes]
    allowed_node_ids = {node["id"] for node in nodes}
    eligible_edges = [
        edge
        for edge in edges
        if edge["source_id"] in allowed_node_ids and edge["target_id"] in allowed_node_ids
    ]
    returned_edges = eligible_edges[:max_edges]
    was_truncated = len(nodes) < len(symbol_nodes) or len(returned_edges) < len(eligible_edges)
    if was_truncated:
        warnings.append("View node or edge budget truncated the HydraDB-backed graph slice.")
    return {
        "view_id": str(query["view_id"]),
        "revision_id": str(query.get("revision", "current")),
        "mode": mode.value,
        "depth": depth.value,
        "nodes": nodes,
        "edges": returned_edges,
        "aggregates": aggregates[:max_edges],
        "hydradb": _view_hydradb(query),
        "warnings": warnings,
        "budget": {
            "requested_nodes": max_nodes,
            "returned_nodes": len(nodes),
            "requested_edges": max_edges,
            "returned_edges": len(returned_edges),
            "truncated": was_truncated or bool(query.get("budget", {}).get("truncated")),
        },
    }


def _symbol_graph(query: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    chunks = [item for item in query.get("chunks", []) if isinstance(item, Mapping)]
    chunk_by_id = {str(item.get("chunk_uuid")): item for item in chunks}
    chunk_by_node = {
        str(_mapping(item.get("additional_metadata")).get("node_id")): item
        for item in chunks
        if _mapping(item.get("additional_metadata")).get("node_id")
    }
    nodes: OrderedDict[str, dict[str, Any]] = OrderedDict()
    edges: OrderedDict[str, dict[str, Any]] = OrderedDict()
    groups = [
        item
        for name in ("paths", "relations")
        for item in query.get(name, [])
        if isinstance(item, Mapping)
    ]
    for group in groups:
        for triplet in group.get("triplets", []):
            if not isinstance(triplet, Mapping):
                continue
            source = _mapping(triplet.get("source"))
            target = _mapping(triplet.get("target"))
            relation = _mapping(triplet.get("relation"))
            source_id = _entity_id(source)
            target_id = _entity_id(target)
            relation_id = str(
                relation.get("relationship_id")
                or _digest(f"{source_id}:{relation.get('canonical_predicate')}:{target_id}")
            )
            chunk = chunk_by_id.get(str(relation.get("chunk_id"))) or chunk_by_node.get(source_id)
            nodes.setdefault(
                source_id, _entity_node(source, chunk, str(query.get("revision", "current")))
            )
            nodes.setdefault(
                target_id,
                _entity_node(
                    target, chunk_by_node.get(target_id), str(query.get("revision", "current"))
                ),
            )
            edges.setdefault(
                relation_id,
                _relation_edge(
                    relation_id,
                    source_id,
                    target_id,
                    relation,
                    chunk,
                    str(query.get("revision", "current")),
                ),
            )
    return list(nodes.values()), list(edges.values())


def _entity_node(
    entity: Mapping[str, Any], chunk: Mapping[str, Any] | None, revision: str
) -> dict[str, Any]:
    chunk = chunk or {}
    metadata = _mapping(chunk.get("metadata"))
    additional = _mapping(chunk.get("additional_metadata"))
    entity_id = _entity_id(entity)
    name = str(entity.get("name") or entity_id)
    display_name = name.split(" [", 1)[0].split(".")[-1]
    path = str(additional.get("path") or _path_from_entity_name(name) or ".")
    span = _span(additional)
    return {
        "id": entity_id,
        "logical_id": str(additional.get("logical_id") or entity.get("identifier") or entity_id),
        "kind": str(metadata.get("entity_kind") or entity.get("type") or "FILE").upper(),
        "display_name": display_name,
        "qualified_name": str(additional.get("qualified_name") or name.split(" [", 1)[0]),
        "language": metadata.get("language"),
        "path": path,
        "span": span,
        "signature": additional.get("signature"),
        "revision_id": str(metadata.get("revision_id") or revision),
        "content_hash": str(additional.get("content_hash") or _digest(name)),
        "parser": str(additional.get("parser") or "hydradb"),
        "parser_version": str(additional.get("parser_version") or "v2"),
        "is_generated": bool(metadata.get("is_generated", False)),
        "attributes": {
            "hydradb_entity_id": entity.get("entity_id"),
            "hydradb_namespace": entity.get("namespace"),
        },
    }


def _relation_edge(
    relation_id: str,
    source_id: str,
    target_id: str,
    relation: Mapping[str, Any],
    chunk: Mapping[str, Any] | None,
    revision: str,
) -> dict[str, Any]:
    chunk = chunk or {}
    metadata = _mapping(chunk.get("metadata"))
    additional = _mapping(chunk.get("additional_metadata"))
    origin = relation.get("origin")
    quality = str(metadata.get("relation_quality") or ("exact" if origin == "byog" else "unknown"))
    context = str(relation.get("context") or "HydraDB returned this relationship.")
    evidence: dict[str, Any] = {
        "id": str(additional.get("evidence_id") or f"evidence_{_digest(relation_id)[:24]}"),
        "path": str(additional.get("path") or _path_from_context(context) or "."),
        "excerpt_hash": str(additional.get("excerpt_hash") or _digest(context)),
        "explanation": context,
    }
    span = _span(additional)
    if span:
        evidence.update(span)
    confidence = None if quality == "exact" else relation.get("confidence")
    return {
        "id": relation_id,
        "logical_id": str(relation.get("relationship_id") or relation_id),
        "source_id": source_id,
        "predicate": str(
            relation.get("canonical_predicate") or relation.get("raw_predicate") or "RELATED_TO"
        ),
        "target_id": target_id,
        "quality": quality
        if quality in {"exact", "inferred", "semantic", "unknown"}
        else "unknown",
        "confidence": confidence,
        "evidence": [evidence],
        "revision_id": str(metadata.get("revision_id") or revision),
        "extractor": "hydradb-byog" if origin == "byog" else "hydradb-context-graph",
        "extractor_version": "v2",
        "owner_source_id": str(additional.get("node_id") or source_id),
        "attributes": {
            "context": context,
            "raw_predicate": relation.get("raw_predicate"),
            "hydradb_origin": origin,
            "hydradb_chunk_id": relation.get("chunk_id"),
        },
    }


def _aggregate(
    nodes: Sequence[dict[str, Any]],
    edges: Sequence[dict[str, Any]],
    depth: ViewDepth,
    revision: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    group_nodes: OrderedDict[str, dict[str, Any]] = OrderedDict()
    node_groups: dict[str, str] = {}
    for node in nodes:
        group_path = _group_path(str(node["path"]), depth)
        group_id = f"{depth.value}_{_digest(group_path)[:24]}"
        node_groups[node["id"]] = group_id
        group_nodes.setdefault(group_id, _group_node(group_id, group_path, depth, revision))
    buckets: OrderedDict[tuple[str, str, str], list[dict[str, Any]]] = OrderedDict()
    for edge in edges:
        source_group = node_groups.get(edge["source_id"])
        target_group = node_groups.get(edge["target_id"])
        if (
            not source_group
            or not target_group
            or source_group == target_group
            or edge["quality"] != "exact"
        ):
            continue
        buckets.setdefault((source_group, edge["predicate"], target_group), []).append(edge)
    aggregate_edges: list[dict[str, Any]] = []
    aggregates: list[dict[str, Any]] = []
    for (source_group, predicate, target_group), items in buckets.items():
        aggregate_id = f"aggregate_{_digest(f'{source_group}:{predicate}:{target_group}')[:24]}"
        evidence = [evidence for item in items for evidence in item["evidence"]]
        aggregate_edges.append(
            {
                "id": aggregate_id,
                "logical_id": aggregate_id,
                "source_id": source_group,
                "predicate": predicate,
                "target_id": target_group,
                "quality": "exact",
                "confidence": None,
                "evidence": evidence,
                "revision_id": revision,
                "extractor": "deterministic-aggregate",
                "extractor_version": "1",
                "owner_source_id": source_group,
                "attributes": {"contributing_edge_ids": [item["id"] for item in items]},
            }
        )
        aggregates.append(
            {
                "id": aggregate_id,
                "source_group_id": source_group,
                "predicate": predicate,
                "target_group_id": target_group,
                "exact_relation_count": len(items),
                "contributing_edge_ids": [item["id"] for item in items],
                "contributing_evidence_ids": [item["id"] for item in evidence],
                "revision_id": revision,
            }
        )
    return list(group_nodes.values()), aggregate_edges, aggregates


def _group_node(group_id: str, path: str, depth: ViewDepth, revision: str) -> dict[str, Any]:
    return {
        "id": group_id,
        "logical_id": path,
        "kind": "PACKAGE" if depth is ViewDepth.PACKAGE else "FILE",
        "display_name": path.rsplit("/", 1)[-1],
        "qualified_name": path,
        "language": None,
        "path": path,
        "span": None,
        "signature": None,
        "revision_id": revision,
        "content_hash": _digest(path),
        "parser": "deterministic-aggregate",
        "parser_version": "1",
        "is_generated": False,
        "attributes": {"projection_depth": depth.value},
    }


def _view_hydradb(query: Mapping[str, Any]) -> dict[str, Any]:
    source = _mapping(query.get("hydradb"))
    return {
        "available": bool(source.get("available", query.get("status") == "ready")),
        "database": source.get("database"),
        "collections": list(source.get("collections", [])),
        "query_by": source.get("query_by"),
        "mode": source.get("mode"),
        "graph_context": bool(source.get("graph_context", False)),
        "path_ids": list(source.get("path_ids", [])),
        "origin": source.get("origin"),
        "status": str(query.get("status", "unavailable")),
    }


def _default_question(mode: ViewMode, depth: ViewDepth) -> str:
    prompts = {
        ViewMode.REPOSITORY: (
            f"Return the concrete repository structure at {depth.value} depth and its exact "
            "relations."
        ),
        ViewMode.EXPLORE: (
            "Return a bounded concrete repository neighborhood for the current focus."
        ),
        ViewMode.TRACE: "Trace the main request or event flow across concrete repository entities.",
        ViewMode.OBSERVE: (
            "Return the repository path and context most recently requested by the coding agent."
        ),
        ViewMode.COMPARE: (
            "Return graph change events and changed repository relations for the current task."
        ),
        ViewMode.PRESERVE: (
            "Return saved system lenses and their grounded current repository paths."
        ),
    }
    return prompts[mode]


def _entity_id(entity: Mapping[str, Any]) -> str:
    value = entity.get("identifier") or entity.get("entity_id")
    if value:
        return str(value)
    return f"entity_{_digest(str(sorted(entity.items())))[:24]}"


def _span(metadata: Mapping[str, Any]) -> dict[str, int] | None:
    keys = ("start_line", "start_column", "end_line", "end_column")
    if not all(metadata.get(key) is not None for key in keys):
        return None
    return {key: int(metadata[key]) for key in keys}


def _path_from_entity_name(name: str) -> str | None:
    marker = " @ "
    return name.rsplit(marker, 1)[1] if marker in name else None


def _path_from_context(context: str) -> str | None:
    first = context.split(":", 1)[0]
    return first if "/" in first or "\\" in first else None


def _group_path(path: str, depth: ViewDepth) -> str:
    normalized = path.replace("\\", "/")
    if depth is ViewDepth.FILE:
        return normalized
    return normalized.split("/", 1)[0]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
