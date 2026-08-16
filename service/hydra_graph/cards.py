"""Readable source cards and validated HydraDB BYOG payloads."""

from __future__ import annotations

import json
import tokenize
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from .hydradb import MAX_ADDITIONAL_METADATA_BYTES
from .ids import content_hash, evidence_id, source_id
from .models import (
    FrozenModel,
    GraphEdge,
    GraphIR,
    GraphNode,
    NodeKind,
    RelationQuality,
)

MAX_ENTITIES_PER_SOURCE = 5_000
MAX_RELATIONS_PER_SOURCE = 10_000
MAX_RELATIONS_PER_ENTITY = 500
MAX_ENTITY_NAME = 256
MAX_PREDICATE = 256
MAX_RELATION_CONTEXT = 2_000
MAX_CODE_EXCERPT_CHARS = 12_000
RELATION_EVIDENCE_SCHEMA = "hack-hydra.relation-evidence.v1"
_LOCAL_ONLY_ADDITIONAL_METADATA = frozenset(
    {
        # These fields remain on SourceCard for deterministic local evidence and
        # evolution round trips. HydraDB already receives equivalent data in the
        # source title/content, graph evidence, or other metadata fields.
        "display_name",
        "evidence_id",
        "excerpt_hash",
        "graph_ir_version",
        "record_json",
    }
)
_OPTIONAL_HYDRA_ADDITIONAL_METADATA = ("signature",)


class HydraEntity(FrozenModel):
    name: str = Field(min_length=1, max_length=MAX_ENTITY_NAME)
    type: str = Field(min_length=1, max_length=256)
    namespace: str = Field(min_length=1, max_length=256)
    identifier: str | None = Field(default=None, max_length=1024)


class HydraRelation(FrozenModel):
    source: str
    target: str
    predicate: str = Field(min_length=1, max_length=MAX_PREDICATE)
    context: str | None = Field(default=None, max_length=MAX_RELATION_CONTEXT)
    temporal_details: str | None = None


class HydraSourceGraph(FrozenModel):
    entities: dict[str, HydraEntity] = Field(min_length=1)
    relations: tuple[HydraRelation, ...]

    @model_validator(mode="after")
    def validate_hydra_limits(self) -> HydraSourceGraph:
        if len(self.entities) > MAX_ENTITIES_PER_SOURCE:
            raise ValueError(f"BYOG graph exceeds {MAX_ENTITIES_PER_SOURCE} entities")
        if len(self.relations) > MAX_RELATIONS_PER_SOURCE:
            raise ValueError(f"BYOG graph exceeds {MAX_RELATIONS_PER_SOURCE} relations")
        degree: Counter[str] = Counter()
        for relation in self.relations:
            if relation.source not in self.entities or relation.target not in self.entities:
                raise ValueError("BYOG relation references an unknown entity handle")
            degree[relation.source] += 1
            degree[relation.target] += 1
        if degree and max(degree.values()) > MAX_RELATIONS_PER_ENTITY:
            raise ValueError(f"BYOG graph exceeds degree {MAX_RELATIONS_PER_ENTITY}")
        return self


class SourceCard(FrozenModel):
    source_id: str
    node_id: str
    content: str = Field(min_length=1)
    metadata: dict[str, str | bool]
    additional_metadata: dict[str, str | int | bool | None]
    graph: HydraSourceGraph
    title: str | None = Field(default=None, min_length=1, max_length=512)
    source_type: str = Field(default="code_entity", min_length=1, max_length=128)


def _hydra_entity_name(node: GraphNode) -> str:
    """Create a globally unambiguous name inside HydraDB's hard limit."""

    readable = f"{node.qualified_name} [{node.kind.value.lower()}] @ {node.path}"
    if len(readable) <= MAX_ENTITY_NAME:
        return readable
    suffix = f" … [{node.id}]"
    return readable[: MAX_ENTITY_NAME - len(suffix)] + suffix


def _code_excerpt(node: GraphNode, repository_root: Path) -> str | None:
    if node.span is None:
        return None
    path = (repository_root / node.path).resolve()
    try:
        path.relative_to(repository_root.resolve())
    except ValueError as error:
        raise ValueError(f"card path escapes repository: {node.path}") from error
    if not path.is_file():
        raise ValueError(f"source file for card does not exist: {node.path}")
    with tokenize.open(path) as source_file:
        source = source_file.read()
    lines = source.splitlines()
    if node.span.end_line > len(lines):
        raise ValueError(f"node {node.id} span exceeds {node.path}")
    selected = [
        line.encode("utf-8") for line in lines[node.span.start_line - 1 : node.span.end_line]
    ]
    if len(selected) == 1:
        excerpt_bytes = selected[0][node.span.start_column : node.span.end_column]
    else:
        selected[0] = selected[0][node.span.start_column :]
        selected[-1] = selected[-1][: node.span.end_column]
        excerpt_bytes = b"\n".join(selected)
    excerpt = excerpt_bytes.decode("utf-8")
    if content_hash(excerpt) != node.content_hash:
        raise ValueError(f"source content for node {node.id} changed after analysis")
    if len(excerpt) <= MAX_CODE_EXCERPT_CHARS:
        return excerpt
    return excerpt[: MAX_CODE_EXCERPT_CHARS - 32] + "\n… [bounded source excerpt]"


def _relation_context(edge: GraphEdge, nodes: dict[str, GraphNode]) -> str:
    evidence = edge.evidence[0]
    source = nodes[edge.source_id].qualified_name
    target = nodes[edge.target_id].qualified_name
    location = evidence.path
    if evidence.start_line is not None:
        location += f":{evidence.start_line}"
    summary = f"{source} {edge.predicate.value.lower()} {target} at {location}."
    envelope = {
        "schema": RELATION_EVIDENCE_SCHEMA,
        "summary": summary,
        "edge_id": edge.id,
        "quality": edge.quality.value,
        "extractor": edge.extractor,
        "extractor_version": edge.extractor_version,
        "evidence": evidence.model_dump(mode="json", exclude_none=True),
    }

    def encode(candidate_summary: str) -> str:
        envelope["summary"] = candidate_summary
        return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    context = encode(summary)
    if len(context) <= MAX_RELATION_CONTEXT:
        return context

    # Preserve the original evidence exactly. Only the human-readable duplicate
    # summary may be shortened to meet HydraDB's hard relation-context limit.
    suffix = "…"
    low, high = 1, len(summary)
    fitted: str | None = None
    while low <= high:
        midpoint = (low + high) // 2
        candidate = encode(summary[:midpoint].rstrip() + suffix)
        if len(candidate) <= MAX_RELATION_CONTEXT:
            fitted = candidate
            low = midpoint + 1
        else:
            high = midpoint - 1
    if fitted is None:
        raise ValueError(
            f"relation evidence envelope for edge {edge.id} cannot fit HydraDB's "
            f"{MAX_RELATION_CONTEXT}-character context limit"
        )
    return fitted


def _source_graph(
    owner: GraphNode,
    owned_edges: list[GraphEdge],
    nodes: dict[str, GraphNode],
    repository_id: str,
) -> HydraSourceGraph:
    exact_edges = [edge for edge in owned_edges if edge.quality is RelationQuality.EXACT]
    # Keep the focal repository node in the local card even when it has no exact
    # relations. The payload builder omits that relation-free graph at the API
    # boundary instead of inventing a self-relation.
    entity_ids = {
        owner.id,
        *(node_id for edge in exact_edges for node_id in (edge.source_id, edge.target_id)),
    }
    entities = {
        node_identifier: HydraEntity(
            name=_hydra_entity_name(nodes[node_identifier]),
            type=nodes[node_identifier].kind.value,
            namespace=repository_id,
            identifier=nodes[node_identifier].logical_id,
        )
        for node_identifier in sorted(entity_ids)
    }
    relations = tuple(
        HydraRelation(
            source=edge.source_id,
            target=edge.target_id,
            predicate=edge.predicate.value,
            context=_relation_context(edge, nodes),
        )
        for edge in sorted(exact_edges, key=lambda item: item.id)
    )
    return HydraSourceGraph(entities=entities, relations=relations)


def build_source_cards(graph: GraphIR, repository_root: str | Path) -> tuple[SourceCard, ...]:
    """Build one deterministic card per concrete repository entity."""

    root = Path(repository_root).resolve()
    nodes = graph.node_map()
    owned: dict[str, list[GraphEdge]] = {node.id: [] for node in graph.nodes}
    incident: dict[str, list[GraphEdge]] = {node.id: [] for node in graph.nodes}
    for edge in graph.edges:
        owned[edge.owner_source_id].append(edge)
        incident[edge.source_id].append(edge)
        incident[edge.target_id].append(edge)

    cards: list[SourceCard] = []
    for node in sorted(graph.nodes, key=lambda item: item.id):
        if node.kind in {NodeKind.SYSTEM_LENS, NodeKind.CHANGE_EVENT}:
            continue
        lines = [
            f"Entity: {node.display_name}",
            f"Qualified name: {node.qualified_name}",
            f"Kind: {node.kind.value.lower()}",
        ]
        if node.language:
            lines.append(f"Language: {node.language}")
        lines.append(f"Path: {node.path}")
        if node.span:
            lines.append(f"Lines: {node.span.start_line}-{node.span.end_line}")
        if node.signature:
            lines.append(f"Signature: {node.signature}")
        docstring = node.attributes.get("docstring")
        if isinstance(docstring, str) and docstring.strip():
            lines.append(f"Documentation: {docstring.strip()}")
        excerpt = _code_excerpt(node, root)
        if excerpt is not None:
            lines.extend(["", "Code:", excerpt])
        exact_relations = sorted(
            (edge for edge in incident[node.id] if edge.quality is RelationQuality.EXACT),
            key=lambda item: item.id,
        )
        if exact_relations:
            lines.extend(["", "Known exact relations:"])
            for edge in exact_relations:
                direction = "outgoing" if edge.source_id == node.id else "incoming"
                other = nodes[edge.target_id if direction == "outgoing" else edge.source_id]
                lines.append(f"- {direction} {edge.predicate.value}: {other.qualified_name}")

        metadata: dict[str, str | bool] = {
            "repository_id": graph.repository_id,
            "revision_id": graph.revision_id,
            "entity_kind": node.kind.value,
            "language": node.language or "none",
            "relation_quality": "exact",
            "is_generated": node.is_generated,
            "is_test": bool(node.attributes.get("is_test", False)),
            "is_entry_point": bool(node.attributes.get("is_entry_point", False)),
        }
        additional: dict[str, str | int | bool | None] = {
            "path": node.path,
            "start_line": node.span.start_line if node.span else None,
            "start_column": node.span.start_column if node.span else None,
            "end_line": node.span.end_line if node.span else None,
            "end_column": node.span.end_column if node.span else None,
            "qualified_name": node.qualified_name,
            "display_name": node.display_name,
            "logical_id": node.logical_id,
            "signature": node.signature,
            "parser": node.parser,
            "parser_version": node.parser_version,
            "content_hash": node.content_hash,
            "excerpt_hash": node.content_hash,
            "evidence_id": evidence_id(
                path=node.path,
                start_line=node.span.start_line if node.span else None,
                start_column=node.span.start_column if node.span else None,
                end_line=node.span.end_line if node.span else None,
                end_column=node.span.end_column if node.span else None,
                excerpt_hash=node.content_hash,
            ),
            "graph_ir_version": graph.graph_ir_version,
            "node_id": node.id,
        }
        cards.append(
            SourceCard(
                source_id=source_id(node.id),
                node_id=node.id,
                content="\n".join(lines),
                metadata=metadata,
                additional_metadata=additional,
                graph=_source_graph(node, owned[node.id], nodes, graph.repository_id),
            )
        )
    return tuple(cards)


def build_graph_payload(
    cards: tuple[SourceCard, ...] | list[SourceCard],
) -> dict[str, dict[str, Any]]:
    """Return valid exact BYOG entries for HydraDB `graph_payload`.

    HydraDB requires every keyed source graph to contain both entities and a
    relation. Relation-free cards remain in ``app_knowledge`` for retrieval,
    but they are omitted here instead of inventing or duplicating an edge.
    """

    return {
        card.source_id: card.graph.model_dump(mode="json", exclude_none=True)
        for card in sorted(cards, key=lambda item: item.source_id)
        if card.graph.relations
    }


def build_app_knowledge(cards: tuple[SourceCard, ...] | list[SourceCard]) -> list[dict[str, Any]]:
    """Build the app-source records paired with `build_graph_payload`."""

    sources: list[dict[str, Any]] = []
    for card in sorted(cards, key=lambda item: item.source_id):
        sources.append(
            {
                "id": card.source_id,
                "title": card.title
                or str(card.additional_metadata.get("display_name") or card.source_id),
                "type": card.source_type,
                "content": {"text": card.content},
                "metadata": card.metadata,
                "additional_metadata": _hydra_additional_metadata(card),
            }
        )
    return sources


def _hydra_additional_metadata(card: SourceCard) -> dict[str, str | int | bool]:
    """Project rich local card metadata into HydraDB's bounded wire field."""

    projected = {
        key: value
        for key, value in card.additional_metadata.items()
        if value is not None and key not in _LOCAL_ONLY_ADDITIONAL_METADATA
    }
    for optional_key in _OPTIONAL_HYDRA_ADDITIONAL_METADATA:
        if _additional_metadata_size(projected) <= MAX_ADDITIONAL_METADATA_BYTES:
            break
        projected.pop(optional_key, None)
    size = _additional_metadata_size(projected)
    if size > MAX_ADDITIONAL_METADATA_BYTES:
        raise ValueError(
            f"Source card {card.source_id} additional_metadata requires {size} serialized "
            f"bytes after removing redundant fields; HydraDB allows "
            f"{MAX_ADDITIONAL_METADATA_BYTES}"
        )
    return projected


def _additional_metadata_size(metadata: dict[str, str | int | bool]) -> int:
    return len(
        json.dumps(
            metadata,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def graph_payload_json(cards: tuple[SourceCard, ...] | list[SourceCard]) -> str:
    """Serialize deterministically for multipart upload and fixture comparison."""

    return json.dumps(build_graph_payload(cards), separators=(",", ":"), sort_keys=True)
