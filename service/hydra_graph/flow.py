"""Order already-grounded relations into paths from an entry point to matched code.

A repository answer returns relation pairs, and a pair carries no order. A developer
asks how a request reaches the code that matched the question, and a bag of pairs
cannot answer that. This module selects and orders relations HydraDB already returned
and that were already proven grounded. Assembly is presentation order only: no hop, no
node, and no transitive edge is created here.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .relations import has_byog_envelope_marker

# The order is also the preference order between two edges that leave one node.
PRIMARY_FLOW_PREDICATES: tuple[str, ...] = (
    "CALLS",
    "INVOKES",
    "DISPATCHES_TO",
    "INSTANTIATES",
    "HANDLES",
)
FALLBACK_FLOW_PREDICATES: tuple[str, ...] = ("IMPORTS",)
# These say where code lives, not what calls what, so they never make a step.
STRUCTURAL_PREDICATES: frozenset[str] = frozenset({"CONTAINS", "DEFINES"})
FLOW_GROUP_ORIGIN = "assembled-flow"

_PRIMARY: frozenset[str] = frozenset(PRIMARY_FLOW_PREDICATES)
_WITH_FALLBACK: frozenset[str] = _PRIMARY | frozenset(FALLBACK_FLOW_PREDICATES)
_PREDICATE_RANK: dict[str, int] = {
    name: index for index, name in enumerate((*PRIMARY_FLOW_PREDICATES, *FALLBACK_FLOW_PREDICATES))
}
_TRUE_TEXT = frozenset({"true", "1", "yes"})


@dataclass(frozen=True, slots=True)
class _Edge:
    source: str
    target: str
    predicate: str
    relation_id: str
    chunk_id: str
    order: int
    triplet: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class _ChunkFacts:
    rank: int
    is_test: bool
    is_entry_point: bool


def assemble_flow_paths(
    chunks: Sequence[Mapping[str, Any]],
    groups: Sequence[Mapping[str, Any]],
    *,
    max_paths: int = 3,
    max_hops: int = 8,
    min_hops: int = 2,
) -> list[dict[str, Any]]:
    """Return grounded relation groups whose hops read as ordered steps.

    An empty list is a correct answer. It is returned when no chunk, no group, no flow
    relation, no anchor, or no path exists, because inventing a step is not permitted.

    A path shorter than ``min_hops`` is not returned. One hop is a single relation,
    which the answer already carries; presenting it as a flow would add an ordering
    claim without adding an explanation, and it would displace a longer real path.
    """

    if not chunks or not groups or max_paths < 1 or max_hops < min_hops:
        return []
    node_ids = _node_id_lookup(chunks)
    facts = _chunk_facts(chunks, node_ids)
    edges = _flow_edges(groups, node_ids)
    if not edges:
        return []
    # An entity that resolves to no returned chunk can still be a step, but it can never
    # be an anchor or a target, because nothing here proves what it is.
    charted = [node for node in _graph_nodes(edges) if node in facts]
    anchors = _anchors(charted, facts, edges)
    targets = _targets(charted, facts)
    if not anchors or not targets:
        return []
    adjacency = _adjacency(edges)
    found: list[list[_Edge]] = []
    emitted: list[set[tuple[str, str, str, str]]] = []
    for target in targets:
        if len(found) >= max_paths:
            break
        for anchor in anchors:
            if anchor == target:
                continue
            path = _shortest_path(adjacency, anchor, target, max_hops, _PRIMARY)
            if path is None:
                path = _shortest_path(adjacency, anchor, target, max_hops, _WITH_FALLBACK)
            if path is None or len(path) < min_hops:
                continue
            signature = {_edge_signature(edge) for edge in path}
            if any(signature <= seen for seen in emitted):
                continue
            emitted.append(signature)
            found.append(path)
            if len(found) >= max_paths:
                break
    return [_flow_group(path) for path in found]


def _node_id_lookup(chunks: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """Map every id a chunk answers to onto that chunk's node id.

    Triplet entities carry the logical id and chunks carry the node id. Without this one
    id space, an anchor and a target could never match an edge endpoint.
    """

    lookup: dict[str, str] = {}
    for chunk in chunks:
        additional = _mapping(_mapping(chunk).get("additional_metadata"))
        node_id = additional.get("node_id")
        if not node_id:
            continue
        node_id = str(node_id)
        lookup[node_id] = node_id
        logical_id = additional.get("logical_id")
        if logical_id:
            lookup[str(logical_id)] = node_id
    return lookup


def _chunk_facts(
    chunks: Sequence[Mapping[str, Any]], node_ids: Mapping[str, str]
) -> dict[str, _ChunkFacts]:
    facts: dict[str, _ChunkFacts] = {}
    for rank, raw in enumerate(chunks):
        chunk = _mapping(raw)
        additional = _mapping(chunk.get("additional_metadata"))
        metadata = _mapping(chunk.get("metadata"))
        key = str(additional.get("node_id") or additional.get("logical_id") or "")
        if not key:
            continue
        node = node_ids.get(key, key)
        if node in facts:
            continue
        facts[node] = _ChunkFacts(
            rank=rank,
            is_test=_flag(metadata, additional, "is_test"),
            is_entry_point=_flag(metadata, additional, "is_entry_point"),
        )
    return facts


def _flow_edges(groups: Sequence[Mapping[str, Any]], node_ids: Mapping[str, str]) -> list[_Edge]:
    edges: list[_Edge] = []
    for group in groups:
        for triplet in _mappings(_mapping(group).get("triplets")):
            relation = _mapping(triplet.get("relation"))
            predicate = _predicate(relation)
            if predicate not in _WITH_FALLBACK:
                continue
            source = _resolved(triplet.get("source"), node_ids)
            target = _resolved(triplet.get("target"), node_ids)
            # A relation onto itself cannot advance a path, and counting it would give
            # its node a false in-degree and remove it from the anchor rule.
            if not source or not target or source == target:
                continue
            edges.append(
                _Edge(
                    source=source,
                    target=target,
                    predicate=predicate,
                    relation_id=str(relation.get("relationship_id") or ""),
                    chunk_id=str(relation.get("chunk_id") or ""),
                    order=len(edges),
                    triplet=triplet,
                )
            )
    return edges


def _graph_nodes(edges: Sequence[_Edge]) -> list[str]:
    nodes: set[str] = set()
    for edge in edges:
        nodes.add(edge.source)
        nodes.add(edge.target)
    return sorted(nodes)


def _adjacency(edges: Sequence[_Edge]) -> dict[str, list[_Edge]]:
    adjacency: dict[str, list[_Edge]] = {}
    for edge in edges:
        adjacency.setdefault(edge.source, []).append(edge)
    for outgoing in adjacency.values():
        outgoing.sort(
            key=lambda edge: (
                _PREDICATE_RANK[edge.predicate],
                edge.target,
                edge.relation_id,
                edge.order,
            )
        )
    return adjacency


def _anchors(
    charted: Sequence[str], facts: Mapping[str, _ChunkFacts], edges: Sequence[_Edge]
) -> list[str]:
    """Return where a path may start, best first.

    A test is a poor entry point for a question about the system, but a question can also
    be about the tests themselves. So a non-test entity is preferred and never required.
    """

    pool = [node for node in charted if not facts[node].is_test] or list(charted)
    if not pool:
        return []
    ordered = sorted(pool, key=lambda node: (facts[node].rank, node))
    entry_points = [node for node in ordered if facts[node].is_entry_point]
    if entry_points:
        return entry_points
    reached = {edge.target for edge in edges if edge.predicate in _PRIMARY}
    roots = [node for node in ordered if node not in reached]
    return roots or ordered


def _targets(charted: Sequence[str], facts: Mapping[str, _ChunkFacts]) -> list[str]:
    pool = [node for node in charted if not facts[node].is_test] or list(charted)
    return sorted(pool, key=lambda node: (facts[node].rank, node))


def _shortest_path(
    adjacency: Mapping[str, list[_Edge]],
    anchor: str,
    target: str,
    max_hops: int,
    allowed: frozenset[str],
) -> list[_Edge] | None:
    """Return the fewest hops from ``anchor`` to ``target``, or ``None``.

    The visited set is what makes a cycle end and what keeps a node out of a path twice.
    """

    parents: dict[str, _Edge] = {}
    depth: dict[str, int] = {anchor: 0}
    visited: set[str] = {anchor}
    queue: deque[str] = deque([anchor])
    while queue:
        node = queue.popleft()
        if depth[node] >= max_hops:
            continue
        for edge in adjacency.get(node, ()):
            if edge.predicate not in allowed or edge.target in visited:
                continue
            visited.add(edge.target)
            depth[edge.target] = depth[node] + 1
            parents[edge.target] = edge
            if edge.target == target:
                return _walk_back(parents, anchor, target)
            queue.append(edge.target)
    return None


def _walk_back(parents: Mapping[str, _Edge], anchor: str, target: str) -> list[_Edge]:
    ordered: list[_Edge] = []
    node = target
    while node != anchor:
        edge = parents[node]
        ordered.append(edge)
        node = edge.source
    ordered.reverse()
    return ordered


def _flow_group(path: Sequence[_Edge]) -> dict[str, Any]:
    last = len(path) - 1
    return {
        "group_id": _flow_group_id(path),
        "relevancy_score": None,
        "combined_context": "\n".join(
            f"{index}. {_step_text(edge)}" for index, edge in enumerate(path, start=1)
        ),
        # The caller proves grounding again, so only a chunk of an included hop is named.
        "source_chunk_ids": list(dict.fromkeys(edge.chunk_id for edge in path if edge.chunk_id)),
        "triplets": [
            _roled_triplet(edge, entry=index == 0, arrival=index == last)
            for index, edge in enumerate(path)
        ],
        "origin": FLOW_GROUP_ORIGIN,
    }


def _roled_triplet(edge: _Edge, *, entry: bool, arrival: bool) -> dict[str, Any]:
    triplet = dict(edge.triplet)
    triplet["source"] = {
        **dict(_mapping(edge.triplet.get("source"))),
        "role": "entry" if entry else "step",
    }
    triplet["target"] = {
        **dict(_mapping(edge.triplet.get("target"))),
        "role": "target" if arrival else "step",
    }
    triplet["relation"] = dict(_mapping(edge.triplet.get("relation")))
    return triplet


def _step_text(edge: _Edge) -> str:
    relation = _mapping(edge.triplet.get("relation"))
    summary = _envelope_summary(relation.get("context"))
    if summary:
        return summary
    source = _entity_text(edge.triplet.get("source"), edge.source)
    target = _entity_text(edge.triplet.get("target"), edge.target)
    return f"{source} {edge.predicate} {target}"


def _envelope_summary(context: Any) -> str | None:
    if not has_byog_envelope_marker(context):
        return None
    # The marker rule already proved this decodes to an exact envelope. Reading it again
    # keeps one definition of what counts as this repository's evidence.
    envelope = json.loads(str(context))
    summary = envelope.get("summary") if isinstance(envelope, Mapping) else None
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    return None


def _entity_text(value: Any, fallback: str) -> str:
    entity = _mapping(value)
    for key in ("name", "identifier", "entity_id"):
        text = entity.get(key)
        if isinstance(text, str) and text.strip():
            return text.strip()
    return fallback


def _flow_group_id(path: Sequence[_Edge]) -> str:
    payload = "|".join(
        f"{edge.relation_id}>{edge.source}>{edge.predicate}>{edge.target}" for edge in path
    )
    return f"flow_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def _edge_signature(edge: _Edge) -> tuple[str, str, str, str]:
    return (edge.source, edge.predicate, edge.target, edge.relation_id)


def _predicate(relation: Mapping[str, Any]) -> str:
    value = relation.get("canonical_predicate") or relation.get("raw_predicate")
    return str(value).strip().upper() if value else ""


def _resolved(value: Any, node_ids: Mapping[str, str]) -> str:
    entity = _mapping(value)
    key = str(entity.get("identifier") or entity.get("entity_id") or "")
    return node_ids.get(key, key)


def _flag(metadata: Mapping[str, Any], additional: Mapping[str, Any], key: str) -> bool:
    value = metadata.get(key)
    return _truthy(additional.get(key) if value is None else value)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in _TRUE_TEXT
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]
