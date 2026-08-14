"""Stable six-mode product views built only from HydraDB query results."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import ValidationError

from .ids import edge_logical_id
from .models import Evidence, GraphEdge, GraphNode
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
                entity_kind=_specialized_entity_kind(request.mode),
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
    symbol_nodes, symbol_edges, omitted_hops = _symbol_graph(query)
    if omitted_hops:
        warnings.append(
            f"Omitted {omitted_hops} HydraDB hop(s) without grounded source-card metadata."
        )
    aggregates: list[dict[str, Any]] = []
    if mode is ViewMode.REPOSITORY and depth is not ViewDepth.SYMBOL:
        nodes, edges, aggregates = _aggregate(
            symbol_nodes, symbol_edges, depth, str(query["revision"])
        )
    else:
        nodes, edges = symbol_nodes, symbol_edges
    available_node_count = len(nodes)
    nodes = nodes[:max_nodes]
    allowed_node_ids = {node["id"] for node in nodes}
    eligible_edges = [
        edge
        for edge in edges
        if edge["source_id"] in allowed_node_ids and edge["target_id"] in allowed_node_ids
    ]
    returned_edges = eligible_edges[:max_edges]
    was_truncated = len(nodes) < available_node_count or len(returned_edges) < len(eligible_edges)
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


def _symbol_graph(
    query: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    chunks = [item for item in query.get("chunks", []) if isinstance(item, Mapping)]
    chunk_by_id = {str(item.get("chunk_id")): item for item in chunks}
    chunk_by_node = {
        str(item.get("node_id")): item
        for item in chunks
        if item.get("node_id")
    }
    chunk_by_logical = {
        str(item.get("logical_id")): item for item in chunks if item.get("logical_id")
    }
    nodes: OrderedDict[str, dict[str, Any]] = OrderedDict()
    edges: OrderedDict[str, dict[str, Any]] = OrderedDict()
    omitted_hops = 0
    groups = [
        item
        for name in ("paths", "relations")
        for item in query.get(name, [])
        if isinstance(item, Mapping)
    ]
    for group in groups:
        for hop in group.get("hops", []):
            if not isinstance(hop, Mapping):
                continue
            source = _mapping(hop.get("source"))
            target = _mapping(hop.get("target"))
            relation = _mapping(hop.get("relation"))
            source_id = _entity_id(source)
            target_id = _entity_id(target)
            envelope = _relation_evidence_envelope(relation)
            relation_id = str(
                (envelope or {}).get("edge_id")
                or relation.get("id")
                or _digest(f"{source_id}:{relation.get('predicate')}:{target_id}")
            )
            source_chunk = (
                chunk_by_id.get(str(relation.get("chunk_id")))
                or chunk_by_node.get(source_id)
                or chunk_by_logical.get(str(source.get("logical_id")))
            )
            target_chunk = chunk_by_node.get(target_id) or chunk_by_logical.get(
                str(target.get("logical_id"))
            )
            source_node = _entity_node(source, source_chunk)
            target_node = _entity_node(target, target_chunk)
            if source_node is None or target_node is None:
                omitted_hops += 1
                continue
            nodes.setdefault(source_id, source_node)
            nodes.setdefault(target_id, target_node)
            edge = _relation_edge(
                relation_id,
                source_id,
                target_id,
                relation,
                source_chunk,
                str(query.get("revision", "current")),
            )
            if edge is None:
                omitted_hops += 1
                continue
            edges.setdefault(relation_id, edge)
    return list(nodes.values()), list(edges.values()), omitted_hops


def _entity_node(
    entity: Mapping[str, Any], chunk: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    if not chunk:
        return None
    entity_id = _entity_id(entity)
    name = str(entity.get("name") or entity_id)
    display_name = name.split(" [", 1)[0].split(".")[-1]
    required = ("node_id", "path", "content_hash", "parser", "parser_version", "revision")
    if not entity_id or not all(chunk.get(key) for key in required):
        return None
    if entity_id != str(chunk["node_id"]):
        return None
    kind = str(chunk.get("entity_kind") or entity.get("kind") or "").upper()
    span = chunk.get("span") if isinstance(chunk.get("span"), Mapping) else None
    if kind not in {"REPOSITORY", "PACKAGE", "MODULE", "FILE"} and span is None:
        return None
    candidate = {
        "id": entity_id,
        "logical_id": str(chunk.get("logical_id") or entity.get("logical_id") or entity_id),
        "kind": kind,
        "display_name": display_name,
        "qualified_name": str(chunk.get("qualified_name") or name.split(" [", 1)[0]),
        "language": chunk.get("language"),
        "path": str(chunk["path"]),
        "span": span,
        "signature": chunk.get("signature"),
        "revision_id": str(chunk["revision"]),
        "content_hash": str(chunk["content_hash"]),
        "parser": str(chunk["parser"]),
        "parser_version": str(chunk["parser_version"]),
        "is_generated": bool(chunk.get("is_generated", False)),
        "attributes": {
            "hydradb_entity_id": entity.get("hydradb_entity_id"),
            "hydradb_namespace": entity.get("namespace"),
            "hydradb_origin": "repository-source-card",
        },
    }
    try:
        return GraphNode.model_validate(candidate).model_dump(mode="json")
    except ValidationError:
        return None


def _relation_edge(
    relation_id: str,
    source_id: str,
    target_id: str,
    relation: Mapping[str, Any],
    chunk: Mapping[str, Any] | None,
    revision: str,
) -> dict[str, Any] | None:
    chunk = chunk or {}
    origin = relation.get("origin")
    envelope = _relation_evidence_envelope(relation)
    if envelope:
        quality = "exact"
        context = str(envelope["summary"])
        evidence = [dict(envelope["evidence"])]
        extractor = str(envelope["extractor"])
        extractor_version = str(envelope["extractor_version"])
        stable_edge_id = str(envelope["edge_id"])
    else:
        # Source-card metadata describes its BYOG payload. It cannot upgrade an
        # auto-extracted or malformed returned relation to an exact fact.
        quality = "unknown"
        raw_context = str(relation.get("context") or "HydraDB returned this relationship.")
        context = (
            "HydraDB returned relation context without deterministic edge evidence: "
            f"{raw_context}"
        )
        evidence = []
        extractor = "hydradb-context-graph"
        extractor_version = "v2"
        stable_edge_id = relation_id
    confidence = None if quality == "exact" else relation.get("confidence")
    predicate = relation.get("predicate") or relation.get("raw_predicate")
    if not predicate:
        return None
    repository_id = chunk.get("repository_id")
    if not repository_id:
        return None
    logical_id = edge_logical_id(
        repository_id=str(repository_id),
        source_id=source_id,
        predicate=str(predicate),
        target_id=target_id,
        quality=quality,
    )
    candidate = {
        "id": stable_edge_id,
        "logical_id": logical_id,
        "source_id": source_id,
        "predicate": str(predicate),
        "target_id": target_id,
        "quality": quality,
        "confidence": confidence,
        "evidence": evidence,
        "revision_id": str(chunk.get("revision") or revision),
        "extractor": extractor,
        "extractor_version": extractor_version,
        "owner_source_id": str(chunk.get("node_id") or source_id),
        "attributes": {
            "context": context,
            "raw_predicate": relation.get("raw_predicate"),
            "hydradb_origin": origin,
            "hydradb_chunk_id": relation.get("chunk_id"),
            "hydradb_relationship_id": relation.get("id"),
        },
    }
    try:
        return GraphEdge.model_validate(candidate).model_dump(mode="json")
    except ValidationError:
        return None


def _relation_evidence_envelope(relation: Mapping[str, Any]) -> Mapping[str, Any] | None:
    if relation.get("origin") != "byog":
        return None
    context = relation.get("context")
    if not isinstance(context, str):
        return None
    try:
        envelope = json.loads(context)
    except json.JSONDecodeError:
        return None
    if not isinstance(envelope, Mapping):
        return None
    required = {
        "schema",
        "summary",
        "edge_id",
        "quality",
        "extractor",
        "extractor_version",
        "evidence",
    }
    if not required.issubset(envelope):
        return None
    if envelope.get("schema") != "hack-hydra.relation-evidence.v1":
        return None
    if envelope.get("quality") != "exact":
        return None
    if not all(
        isinstance(envelope.get(key), str) and envelope[key]
        for key in ("summary", "edge_id", "extractor", "extractor_version")
    ):
        return None
    evidence = envelope.get("evidence")
    if not isinstance(evidence, Mapping):
        return None
    try:
        Evidence.model_validate(evidence)
    except ValidationError:
        return None
    return envelope


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


def _specialized_entity_kind(mode: ViewMode) -> str | None:
    if mode is ViewMode.COMPARE:
        return "CHANGE_EVENT"
    if mode is ViewMode.PRESERVE:
        return "SYSTEM_LENS"
    return None


def _entity_id(entity: Mapping[str, Any]) -> str:
    value = entity.get("id") or entity.get("identifier") or entity.get("entity_id")
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
