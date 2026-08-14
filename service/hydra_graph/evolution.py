"""Deterministic change-event and shared System Lens Knowledge records."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from .cards import (
    MAX_RELATION_CONTEXT,
    RELATION_EVIDENCE_SCHEMA,
    HydraEntity,
    HydraRelation,
    HydraSourceGraph,
    SourceCard,
)
from .diff import GraphDelta, compare_graphs
from .ids import edge_logical_id, evidence_id, node_logical_id, source_id
from .models import (
    Evidence,
    FrozenModel,
    GraphEdge,
    GraphIR,
    GraphNode,
    NodeKind,
    RelationPredicate,
    RelationQuality,
    SourceSpan,
)

CHANGE_EVENT_SCHEMA = "hack-hydra.change-event.v1"
CHANGE_EVENT_PAGE_SCHEMA = "hack-hydra.change-event-page.v1"
SYSTEM_LENS_SCHEMA = "hack-hydra.system-lens.v1"
EVOLUTION_EXTRACTOR = "hack-hydra.graph-diff"
EVOLUTION_EXTRACTOR_VERSION = "1"
MAX_CHANGE_FACTS = 49
MAX_EVOLUTION_CARD_CHARS = 12_000
MAX_LENS_ENTITIES = 25
MAX_LENS_HOPS = 24
MAX_LENS_ANCHORS = 10


class ChangeKind(StrEnum):
    NODE_ADDED = "node_added"
    NODE_REMOVED = "node_removed"
    NODE_MODIFIED = "node_modified"
    RENAME_HYPOTHESIS = "rename_hypothesis"
    RELATION_ADDED = "relation_added"
    RELATION_REMOVED = "relation_removed"
    EVIDENCE_MOVED = "evidence_moved"
    RELATION_QUALITY_CHANGED = "relation_quality_changed"


class LensImpactStatus(StrEnum):
    NOT_EVALUATED = "not_evaluated"
    EVALUATED = "evaluated"


class LensDriftKind(StrEnum):
    UNCHANGED = "unchanged"
    PATH_EXTENDED = "path_extended"
    PATH_SHORTENED = "path_shortened"
    ANCHOR_REMOVED = "anchor_removed"
    RELATION_CHANGED = "relation_changed"
    TEST_COVERAGE_RELATION_CHANGED = "test_coverage_relation_changed"
    UNRESOLVED = "unresolved"


class RevisionEvidence(FrozenModel):
    revision_id: str = Field(min_length=1)
    evidence: Evidence


class ChangeNode(FrozenModel):
    revision_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    logical_id: str = Field(min_length=1)
    kind: NodeKind
    display_name: str = Field(min_length=1)
    qualified_name: str = Field(min_length=1)
    path: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence: RevisionEvidence

    @model_validator(mode="after")
    def validate_evidence(self) -> ChangeNode:
        if self.evidence.revision_id != self.revision_id:
            raise ValueError("change node evidence belongs to another revision")
        if self.evidence.evidence.path != self.path:
            raise ValueError("change node evidence belongs to another path")
        if self.evidence.evidence.excerpt_hash != self.content_hash:
            raise ValueError("change node evidence hash does not match the node")
        return self


class ChangeRelation(FrozenModel):
    revision_id: str = Field(min_length=1)
    edge_id: str = Field(min_length=1)
    logical_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    predicate: RelationPredicate
    target_id: str = Field(min_length=1)
    quality: RelationQuality
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: tuple[RevisionEvidence, ...] = Field(min_length=1)
    extractor: str = Field(min_length=1)
    extractor_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_relation(self) -> ChangeRelation:
        if any(item.revision_id != self.revision_id for item in self.evidence):
            raise ValueError("change relation evidence belongs to another revision")
        if self.quality is RelationQuality.EXACT and self.confidence is not None:
            raise ValueError("exact relations do not use confidence")
        if (
            self.quality in {RelationQuality.INFERRED, RelationQuality.SEMANTIC}
            and self.confidence is None
        ):
            raise ValueError("inferred and semantic relations require confidence")
        return self


class ChangeFact(FrozenModel):
    fact_id: str = Field(min_length=1)
    kind: ChangeKind
    quality: RelationQuality
    confidence: float | None = Field(default=None, ge=0, le=1)
    explanation: str = Field(min_length=1, max_length=2000)
    changed_fields: tuple[str, ...] = ()
    matched_signals: tuple[str, ...] = ()
    before_nodes: tuple[ChangeNode, ...] = ()
    after_nodes: tuple[ChangeNode, ...] = ()
    before_relations: tuple[ChangeRelation, ...] = ()
    after_relations: tuple[ChangeRelation, ...] = ()

    @model_validator(mode="after")
    def validate_provenance(self) -> ChangeFact:
        if self.quality not in {RelationQuality.EXACT, RelationQuality.INFERRED}:
            raise ValueError("change facts must be exact or inferred")
        if self.quality is RelationQuality.EXACT and self.confidence is not None:
            raise ValueError("exact change facts do not use confidence")
        if self.quality is RelationQuality.INFERRED and self.confidence is None:
            raise ValueError("inferred change facts require confidence")
        if not any(
            (
                self.before_nodes,
                self.after_nodes,
                self.before_relations,
                self.after_relations,
            )
        ):
            raise ValueError("change facts require grounded before or after records")
        return self


class ChangeEventRecord(FrozenModel):
    record_schema: Literal["hack-hydra.change-event.v1"] = CHANGE_EVENT_SCHEMA
    event_id: str = Field(min_length=1)
    repository_id: str = Field(min_length=1)
    before_revision_id: str = Field(min_length=1)
    after_revision_id: str = Field(min_length=1)
    facts: tuple[ChangeFact, ...] = Field(max_length=MAX_CHANGE_FACTS)
    structural_warnings: tuple[str, ...] = ()
    lens_impact_status: LensImpactStatus = LensImpactStatus.NOT_EVALUATED
    affected_lens_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_event(self) -> ChangeEventRecord:
        fact_ids = [fact.fact_id for fact in self.facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("change event contains duplicate fact IDs")
        allowed = {self.before_revision_id, self.after_revision_id}
        for fact in self.facts:
            revisions = {
                item.revision_id
                for item in (
                    *fact.before_nodes,
                    *fact.after_nodes,
                    *fact.before_relations,
                    *fact.after_relations,
                )
            }
            if not revisions.issubset(allowed):
                raise ValueError("change fact references an unrelated revision")
        if self.lens_impact_status is LensImpactStatus.NOT_EVALUATED and self.affected_lens_ids:
            raise ValueError("unevaluated lens impact cannot claim affected lenses")
        return self


class ChangeEventSummary(FrozenModel):
    record_schema: Literal["hack-hydra.change-event.v1"] = CHANGE_EVENT_SCHEMA
    event_id: str
    repository_id: str
    before_revision_id: str
    after_revision_id: str
    fact_count: int = Field(ge=0, le=MAX_CHANGE_FACTS)
    page_count: int = Field(ge=0, le=MAX_CHANGE_FACTS)
    structural_warnings: tuple[str, ...] = ()
    lens_impact_status: LensImpactStatus
    affected_lens_ids: tuple[str, ...] = ()


class ChangeEventPage(FrozenModel):
    record_schema: Literal["hack-hydra.change-event-page.v1"] = CHANGE_EVENT_PAGE_SCHEMA
    event_id: str
    repository_id: str
    before_revision_id: str
    after_revision_id: str
    page_index: int = Field(ge=1, le=MAX_CHANGE_FACTS)
    page_count: int = Field(ge=1, le=MAX_CHANGE_FACTS)
    fact: ChangeFact


class LensEntity(FrozenModel):
    node_id: str
    logical_id: str
    kind: NodeKind
    display_name: str
    qualified_name: str
    path: str
    span: SourceSpan | None = None
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence: Evidence

    @model_validator(mode="after")
    def validate_grounding(self) -> LensEntity:
        if self.evidence.path != self.path:
            raise ValueError("lens entity evidence belongs to another path")
        if self.evidence.excerpt_hash != self.content_hash:
            raise ValueError("lens entity evidence hash does not match the node")
        return self


class LensHop(FrozenModel):
    edge_id: str
    logical_id: str
    source_node_id: str
    predicate: RelationPredicate
    target_node_id: str
    evidence: tuple[Evidence, ...] = Field(min_length=1)
    extractor: str
    extractor_version: str


class SystemLensRecord(FrozenModel):
    record_schema: Literal["hack-hydra.system-lens.v1"] = SYSTEM_LENS_SCHEMA
    lens_id: str
    repository_id: str
    name: str = Field(min_length=1, max_length=120)
    purpose: str = Field(min_length=1, max_length=1000)
    saved_revision_id: str = Field(min_length=1)
    ownership: Literal["shared"] = "shared"
    source_view_id: str = Field(min_length=1)
    entities: tuple[LensEntity, ...] = Field(min_length=2, max_length=MAX_LENS_ENTITIES)
    anchor_node_ids: tuple[str, ...] = Field(min_length=1, max_length=MAX_LENS_ANCHORS)
    baseline_hops: tuple[LensHop, ...] = Field(min_length=1, max_length=MAX_LENS_HOPS)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_baseline(self) -> SystemLensRecord:
        entity_ids = [entity.node_id for entity in self.entities]
        if len(entity_ids) != len(set(entity_ids)):
            raise ValueError("system lens contains duplicate entities")
        if len(self.anchor_node_ids) != len(set(self.anchor_node_ids)):
            raise ValueError("system lens contains duplicate anchors")
        known = set(entity_ids)
        if not set(self.anchor_node_ids).issubset(known):
            raise ValueError("system lens anchor is missing from its grounded entities")
        hop_ids = [hop.edge_id for hop in self.baseline_hops]
        if len(hop_ids) != len(set(hop_ids)):
            raise ValueError("system lens contains duplicate hops")
        if any(
            hop.source_node_id not in known or hop.target_node_id not in known
            for hop in self.baseline_hops
        ):
            raise ValueError("system lens hop references an unknown entity")
        return self


class LensDrift(FrozenModel):
    lens_id: str
    repository_id: str
    baseline_revision_id: str
    current_revision_id: str | None = None
    classification: LensDriftKind
    added_hop_ids: tuple[str, ...] = ()
    removed_hop_ids: tuple[str, ...] = ()
    removed_anchor_node_ids: tuple[str, ...] = ()
    explanation: str = Field(min_length=1, max_length=2000)


def build_change_event(
    delta: GraphDelta,
    before: GraphIR,
    after: GraphIR,
) -> ChangeEventRecord:
    """Bind a delta to its complete verified graphs and original evidence."""

    _validate_delta_inputs(delta, before, after)
    before_nodes, after_nodes = before.node_map(), after.node_map()
    before_edges = {edge.id: edge for edge in before.edges}
    after_edges = {edge.id: edge for edge in after.edges}
    facts: list[ChangeFact] = []

    renamed_before = {item.before_node_id for item in delta.renamed_nodes}
    renamed_after = {item.after_node_id for item in delta.renamed_nodes}
    for node_id in sorted(set(delta.removed_node_ids).union(renamed_before)):
        node = _change_node(before_nodes[node_id])
        facts.append(
            _fact(
                delta,
                ChangeKind.NODE_REMOVED,
                explanation=f"Node {node_id} is absent from the after revision.",
                before_nodes=(node,),
            )
        )
    for node_id in sorted(set(delta.added_node_ids).union(renamed_after)):
        node = _change_node(after_nodes[node_id])
        facts.append(
            _fact(
                delta,
                ChangeKind.NODE_ADDED,
                explanation=f"Node {node_id} is new in the after revision.",
                after_nodes=(node,),
            )
        )
    for modification in delta.modified_nodes:
        facts.append(
            _fact(
                delta,
                ChangeKind.NODE_MODIFIED,
                explanation=modification.explanation,
                changed_fields=modification.changed_fields,
                before_nodes=(_change_node(before_nodes[modification.node_id]),),
                after_nodes=(_change_node(after_nodes[modification.node_id]),),
            )
        )
    for rename in delta.renamed_nodes:
        facts.append(
            _fact(
                delta,
                ChangeKind.RENAME_HYPOTHESIS,
                quality=RelationQuality.INFERRED,
                confidence=rename.score,
                explanation=rename.explanation,
                matched_signals=rename.matched_signals,
                before_nodes=(_change_node(before_nodes[rename.before_node_id]),),
                after_nodes=(_change_node(after_nodes[rename.after_node_id]),),
            )
        )

    quality_before = {item.before_edge_id for item in delta.relation_quality_changes}
    quality_after = {item.after_edge_id for item in delta.relation_quality_changes}
    for edge_id in sorted(set(delta.removed_edge_ids).union(quality_before)):
        edge = before_edges[edge_id]
        facts.append(
            _fact(
                delta,
                ChangeKind.RELATION_REMOVED,
                explanation=f"Relation {edge_id} is absent from the after revision.",
                before_nodes=tuple(
                    _change_node(before_nodes[node_id])
                    for node_id in sorted({edge.source_id, edge.target_id})
                ),
                before_relations=(_change_relation(edge),),
            )
        )
    for edge_id in sorted(set(delta.added_edge_ids).union(quality_after)):
        edge = after_edges[edge_id]
        facts.append(
            _fact(
                delta,
                ChangeKind.RELATION_ADDED,
                explanation=f"Relation {edge_id} is new in the after revision.",
                after_nodes=tuple(
                    _change_node(after_nodes[node_id])
                    for node_id in sorted({edge.source_id, edge.target_id})
                ),
                after_relations=(_change_relation(edge),),
            )
        )
    for move in delta.evidence_moves:
        before_edge, after_edge = before_edges[move.edge_id], after_edges[move.edge_id]
        facts.append(
            _fact(
                delta,
                ChangeKind.EVIDENCE_MOVED,
                explanation=move.explanation,
                before_nodes=tuple(
                    _change_node(before_nodes[node_id])
                    for node_id in sorted({before_edge.source_id, before_edge.target_id})
                ),
                after_nodes=tuple(
                    _change_node(after_nodes[node_id])
                    for node_id in sorted({after_edge.source_id, after_edge.target_id})
                ),
                before_relations=(_change_relation(before_edge),),
                after_relations=(_change_relation(after_edge),),
            )
        )
    for change in delta.relation_quality_changes:
        before_edge = before_edges[change.before_edge_id]
        after_edge = after_edges[change.after_edge_id]
        facts.append(
            _fact(
                delta,
                ChangeKind.RELATION_QUALITY_CHANGED,
                explanation=change.explanation,
                before_nodes=tuple(
                    _change_node(before_nodes[node_id])
                    for node_id in sorted({before_edge.source_id, before_edge.target_id})
                ),
                after_nodes=tuple(
                    _change_node(after_nodes[node_id])
                    for node_id in sorted({after_edge.source_id, after_edge.target_id})
                ),
                before_relations=(_change_relation(before_edge),),
                after_relations=(_change_relation(after_edge),),
            )
        )

    facts = sorted(facts, key=lambda item: item.fact_id)
    if len(facts) > MAX_CHANGE_FACTS:
        raise ValueError(
            f"change event contains {len(facts)} facts; the bounded limit is {MAX_CHANGE_FACTS}"
        )
    return ChangeEventRecord(
        event_id=_stable_id(
            "change",
            f"{delta.repository_id}:{delta.before_revision_id}:{delta.after_revision_id}",
        ),
        repository_id=delta.repository_id,
        before_revision_id=delta.before_revision_id,
        after_revision_id=delta.after_revision_id,
        facts=tuple(facts),
        structural_warnings=delta.structural_warnings,
    )


def build_change_event_cards(
    delta: GraphDelta,
    before: GraphIR,
    after: GraphIR,
) -> tuple[SourceCard, ...]:
    """Create a complete summary plus one lossless bounded card per fact."""

    event = build_change_event(delta, before, after)
    page_count = len(event.facts)
    summary = ChangeEventSummary(
        event_id=event.event_id,
        repository_id=event.repository_id,
        before_revision_id=event.before_revision_id,
        after_revision_id=event.after_revision_id,
        fact_count=page_count,
        page_count=page_count,
        structural_warnings=event.structural_warnings,
        lens_impact_status=event.lens_impact_status,
        affected_lens_ids=event.affected_lens_ids,
    )
    cards = [_change_summary_card(summary, after.graph_ir_version)]
    for index, fact in enumerate(event.facts, start=1):
        page = ChangeEventPage(
            event_id=event.event_id,
            repository_id=event.repository_id,
            before_revision_id=event.before_revision_id,
            after_revision_id=event.after_revision_id,
            page_index=index,
            page_count=page_count,
            fact=fact,
        )
        cards.append(_change_page_card(page, after.graph_ir_version))
    return tuple(sorted(cards, key=lambda item: item.source_id))


def build_system_lens(
    *,
    repository_id: str,
    name: str,
    purpose: str,
    view: Mapping[str, Any],
    anchor_node_ids: Sequence[str],
    edge_ids: Sequence[str] | None = None,
    notes: str | None = None,
) -> SystemLensRecord:
    """Save one exact, bounded baseline from an already validated HydraDB view."""

    hydradb = view.get("hydradb")
    if not isinstance(hydradb, Mapping) or hydradb.get("available") is not True:
        raise ValueError("system lens requires an available HydraDB view")
    revision = str(view.get("revision_id") or "")
    if not revision or revision == "current":
        raise ValueError("system lens requires a concrete verified revision")
    view_id = str(view.get("view_id") or "")
    if not view_id:
        raise ValueError("system lens requires a HydraDB view ID")

    nodes = {
        node.id: node
        for item in _mapping_items(view.get("nodes"))
        for node in (GraphNode.model_validate(item),)
    }
    edges = {
        edge.id: edge
        for item in _mapping_items(view.get("edges"))
        for edge in (GraphEdge.model_validate(item),)
    }
    selected_edge_ids = sorted(set(edge_ids) if edge_ids is not None else edges)
    selected_anchor_ids = tuple(sorted(set(anchor_node_ids)))
    if not selected_anchor_ids:
        raise ValueError("system lens requires at least one anchor")
    if not selected_edge_ids:
        raise ValueError("system lens requires at least one grounded hop")
    unknown_edges = set(selected_edge_ids).difference(edges)
    unknown_anchors = set(selected_anchor_ids).difference(nodes)
    if unknown_edges or unknown_anchors:
        raise ValueError("system lens selection is not present in the stored HydraDB view")

    selected_edges = [edges[edge_id] for edge_id in selected_edge_ids]
    entity_ids = set(selected_anchor_ids)
    for edge in selected_edges:
        if edge.quality is not RelationQuality.EXACT or not edge.evidence:
            raise ValueError("system lens baseline accepts exact grounded hops only")
        if edge.attributes.get("hydradb_origin") != "byog":
            raise ValueError("system lens baseline accepts validated HydraDB BYOG hops only")
        if edge.revision_id != revision:
            raise ValueError("system lens contains a mixed-revision hop")
        _validate_edge_identity(repository_id, edge)
        entity_ids.update((edge.source_id, edge.target_id))
    if not entity_ids.issubset(nodes):
        raise ValueError("system lens hop endpoint is missing from the HydraDB view")
    selected_nodes = [nodes[node_id] for node_id in sorted(entity_ids)]
    for node in selected_nodes:
        if node.revision_id != revision:
            raise ValueError("system lens contains a mixed-revision entity")
        if node.attributes.get("hydradb_origin") != "repository-source-card":
            raise ValueError("system lens accepts HydraDB-grounded repository entities only")
        if node.id != _stable_id("node", node.logical_id):
            raise ValueError("system lens entity ID does not match its logical identity")
        expected_prefix = node_logical_id(
            repository_id=repository_id,
            path=node.path,
            language=node.language,
            kind=node.kind.value,
            qualified_name=node.qualified_name,
        )
        if node.logical_id != expected_prefix and not node.logical_id.startswith(
            f"{expected_prefix}:"
        ):
            raise ValueError("system lens entity belongs to another repository or identity")
    _validate_connected(entity_ids, selected_edges)

    return SystemLensRecord(
        lens_id=_stable_id("lens", f"{repository_id}:shared-workspace-primary"),
        repository_id=repository_id,
        name=name.strip(),
        purpose=purpose.strip(),
        saved_revision_id=revision,
        source_view_id=view_id,
        entities=tuple(_lens_entity(node) for node in selected_nodes),
        anchor_node_ids=selected_anchor_ids,
        baseline_hops=tuple(_lens_hop(edge) for edge in selected_edges),
        notes=notes.strip() if notes and notes.strip() else None,
    )


def build_system_lens_card(lens: SystemLensRecord) -> SourceCard:
    """Serialize the shared lens as Knowledge without duplicating graph facts."""

    record_json = _model_json(lens)
    lines = [
        f"System Lens: {lens.name}",
        f"Purpose: {lens.purpose}",
        f"Saved revision: {lens.saved_revision_id}",
        "Ownership: shared workspace Knowledge",
        "Anchors: " + ", ".join(lens.anchor_node_ids),
        "Grounded baseline:",
    ]
    entity_names = {entity.node_id: entity.qualified_name for entity in lens.entities}
    lines.extend(
        f"- {entity_names[hop.source_node_id]} {hop.predicate.value} "
        f"{entity_names[hop.target_node_id]} ({hop.edge_id})"
        for hop in lens.baseline_hops
    )
    if lens.notes:
        lines.append(f"Notes: {lens.notes}")
    lines.extend(["", "Record JSON:", record_json])
    content = "\n".join(lines)
    _validate_card_size(content)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return SourceCard(
        source_id=source_id(lens.lens_id),
        node_id=lens.lens_id,
        title=f"System Lens: {lens.name}",
        source_type="system_lens",
        content=content,
        metadata={
            "repository_id": lens.repository_id,
            "revision_id": lens.saved_revision_id,
            "entity_kind": NodeKind.SYSTEM_LENS.value,
            "relation_quality": RelationQuality.EXACT.value,
            "record_schema": SYSTEM_LENS_SCHEMA,
            "ownership": lens.ownership,
        },
        additional_metadata={
            "record_kind": "system_lens",
            "record_schema": SYSTEM_LENS_SCHEMA,
            "record_json": record_json,
            "lens_id": lens.lens_id,
            "path": ".",
            "qualified_name": lens.name,
            "display_name": lens.name,
            "logical_id": lens.lens_id,
            "parser": "hack-hydra-system-lens",
            "parser_version": "1",
            "content_hash": digest,
            "graph_ir_version": "1.0",
            "node_id": lens.lens_id,
        },
        # Re-storing baseline triples would create a second canonical owner.
        # Their complete exact evidence remains in the structured Knowledge.
        graph=HydraSourceGraph(entities={}, relations=()),
    )


def classify_lens_drift(
    saved: SystemLensRecord,
    current: SystemLensRecord | None,
) -> LensDrift:
    """Classify one refreshed exact path with explicit, deterministic precedence."""

    if current is None:
        return LensDrift(
            lens_id=saved.lens_id,
            repository_id=saved.repository_id,
            baseline_revision_id=saved.saved_revision_id,
            classification=LensDriftKind.UNRESOLVED,
            explanation="HydraDB did not return a complete grounded current path.",
        )
    if current.lens_id != saved.lens_id or current.repository_id != saved.repository_id:
        raise ValueError("cannot compare System Lens records with different identities")

    saved_hops = {hop.edge_id: hop for hop in saved.baseline_hops}
    current_hops = {hop.edge_id: hop for hop in current.baseline_hops}
    added = tuple(sorted(set(current_hops).difference(saved_hops)))
    removed = tuple(sorted(set(saved_hops).difference(current_hops)))
    current_entities = {entity.node_id for entity in current.entities}
    removed_anchors = tuple(sorted(set(saved.anchor_node_ids).difference(current_entities)))
    if removed_anchors:
        classification = LensDriftKind.ANCHOR_REMOVED
        explanation = "One or more saved anchor entities are absent from the current path."
    else:
        changed_hops = [
            hop
            for hop_id in (*removed, *added)
            for hop in (saved_hops.get(hop_id) or current_hops.get(hop_id),)
            if hop is not None
        ]
        if any(hop.predicate is RelationPredicate.TESTS for hop in changed_hops):
            classification = LensDriftKind.TEST_COVERAGE_RELATION_CHANGED
            explanation = "An exact TESTS relationship changed in the saved path."
        elif not added and not removed:
            classification = LensDriftKind.UNCHANGED
            explanation = "The grounded relation path is unchanged."
        elif set(saved_hops).issubset(current_hops):
            classification = LensDriftKind.PATH_EXTENDED
            explanation = "The current path contains every saved hop plus new exact hops."
        elif set(current_hops).issubset(saved_hops):
            classification = LensDriftKind.PATH_SHORTENED
            explanation = "The current path retains only a subset of the saved exact hops."
        else:
            classification = LensDriftKind.RELATION_CHANGED
            explanation = "The current path replaced one or more saved relationships."
    return LensDrift(
        lens_id=saved.lens_id,
        repository_id=saved.repository_id,
        baseline_revision_id=saved.saved_revision_id,
        current_revision_id=current.saved_revision_id,
        classification=classification,
        added_hop_ids=added,
        removed_hop_ids=removed,
        removed_anchor_node_ids=removed_anchors,
        explanation=explanation,
    )


def _validate_delta_inputs(delta: GraphDelta, before: GraphIR, after: GraphIR) -> None:
    if before.repository_id != delta.repository_id or after.repository_id != delta.repository_id:
        raise ValueError("GraphDelta and checkpoints belong to different repositories")
    if before.revision_id != delta.before_revision_id:
        raise ValueError("GraphDelta before revision does not match its checkpoint")
    if after.revision_id != delta.after_revision_id:
        raise ValueError("GraphDelta after revision does not match its checkpoint")
    _validate_graph_identities(before)
    _validate_graph_identities(after)
    if compare_graphs(before, after) != delta:
        raise ValueError("GraphDelta does not match a fresh deterministic checkpoint comparison")


def _validate_graph_identities(graph: GraphIR) -> None:
    for node in graph.nodes:
        if node.id != _stable_id("node", node.logical_id):
            raise ValueError(f"node {node.id} does not match its logical identity")
        expected_prefix = node_logical_id(
            repository_id=graph.repository_id,
            path=node.path,
            language=node.language,
            kind=node.kind.value,
            qualified_name=node.qualified_name,
        )
        if node.logical_id != expected_prefix and not node.logical_id.startswith(
            f"{expected_prefix}:"
        ):
            raise ValueError(f"node {node.id} logical identity does not match its fields")
    for edge in graph.edges:
        _validate_edge_identity(graph.repository_id, edge)


def _validate_edge_identity(repository_id: str, edge: GraphEdge) -> None:
    logical = edge_logical_id(
        repository_id=repository_id,
        source_id=edge.source_id,
        predicate=edge.predicate.value,
        target_id=edge.target_id,
        quality=edge.quality.value,
    )
    if edge.logical_id != logical or edge.id != _stable_id("edge", logical):
        raise ValueError(f"edge {edge.id} does not match its relation identity")
    for item in edge.evidence:
        expected = evidence_id(
            path=item.path,
            start_line=item.start_line,
            start_column=item.start_column,
            end_line=item.end_line,
            end_column=item.end_column,
            excerpt_hash=item.excerpt_hash,
        )
        if item.id != expected:
            raise ValueError(f"evidence {item.id} does not match its source identity")


def _change_node(node: GraphNode) -> ChangeNode:
    evidence = _node_evidence(node)
    return ChangeNode(
        revision_id=node.revision_id,
        node_id=node.id,
        logical_id=node.logical_id,
        kind=node.kind,
        display_name=node.display_name,
        qualified_name=node.qualified_name,
        path=node.path,
        content_hash=node.content_hash,
        evidence=RevisionEvidence(revision_id=node.revision_id, evidence=evidence),
    )


def _change_relation(edge: GraphEdge) -> ChangeRelation:
    return ChangeRelation(
        revision_id=edge.revision_id,
        edge_id=edge.id,
        logical_id=edge.logical_id,
        source_id=edge.source_id,
        predicate=edge.predicate,
        target_id=edge.target_id,
        quality=edge.quality,
        confidence=edge.confidence,
        evidence=tuple(
            RevisionEvidence(revision_id=edge.revision_id, evidence=item) for item in edge.evidence
        ),
        extractor=edge.extractor,
        extractor_version=edge.extractor_version,
    )


def _fact(
    delta: GraphDelta,
    kind: ChangeKind,
    *,
    explanation: str,
    quality: RelationQuality = RelationQuality.EXACT,
    confidence: float | None = None,
    changed_fields: tuple[str, ...] = (),
    matched_signals: tuple[str, ...] = (),
    before_nodes: tuple[ChangeNode, ...] = (),
    after_nodes: tuple[ChangeNode, ...] = (),
    before_relations: tuple[ChangeRelation, ...] = (),
    after_relations: tuple[ChangeRelation, ...] = (),
) -> ChangeFact:
    identity = {
        "repository_id": delta.repository_id,
        "before_revision_id": delta.before_revision_id,
        "after_revision_id": delta.after_revision_id,
        "kind": kind.value,
        "before_nodes": [item.node_id for item in before_nodes],
        "after_nodes": [item.node_id for item in after_nodes],
        "before_relations": [item.edge_id for item in before_relations],
        "after_relations": [item.edge_id for item in after_relations],
    }
    return ChangeFact(
        fact_id=_stable_id("change_fact", _json(identity)),
        kind=kind,
        quality=quality,
        confidence=confidence,
        explanation=explanation,
        changed_fields=tuple(sorted(changed_fields)),
        matched_signals=tuple(sorted(matched_signals)),
        before_nodes=tuple(sorted(before_nodes, key=lambda item: item.node_id)),
        after_nodes=tuple(sorted(after_nodes, key=lambda item: item.node_id)),
        before_relations=tuple(sorted(before_relations, key=lambda item: item.edge_id)),
        after_relations=tuple(sorted(after_relations, key=lambda item: item.edge_id)),
    )


def _change_summary_card(summary: ChangeEventSummary, graph_ir_version: str) -> SourceCard:
    record_json = _model_json(summary)
    warnings = "\n".join(f"- {item}" for item in summary.structural_warnings) or "- None"
    content = (
        f"Change event: {summary.before_revision_id} -> {summary.after_revision_id}\n"
        f"Deterministic fact count: {summary.fact_count}\n"
        f"Lens impact: {summary.lens_impact_status.value}\n"
        f"Structural diagnostics:\n{warnings}\n\nRecord JSON:\n{record_json}"
    )
    _validate_card_size(content)
    return _product_card(
        source_identifier=source_id(f"{summary.event_id}:summary"),
        node_identifier=summary.event_id,
        title=f"Change {summary.before_revision_id} to {summary.after_revision_id}",
        source_type="change_event",
        content=content,
        repository_id=summary.repository_id,
        revision_id=summary.after_revision_id,
        relation_quality=RelationQuality.EXACT,
        record_kind="change_event_summary",
        record_schema=CHANGE_EVENT_SCHEMA,
        record_json=record_json,
        graph_ir_version=graph_ir_version,
        extra={
            "event_id": summary.event_id,
            "before_revision_id": summary.before_revision_id,
            "after_revision_id": summary.after_revision_id,
            "page_index": 0,
            "page_count": summary.page_count,
        },
        graph=HydraSourceGraph(entities={}, relations=()),
    )


def _change_page_card(page: ChangeEventPage, graph_ir_version: str) -> SourceCard:
    record_json = _model_json(page)
    fact = page.fact
    content = (
        f"Change fact: {fact.kind.value}\n"
        f"Quality: {fact.quality.value}\n"
        f"Explanation: {fact.explanation}\n"
        f"Before revision: {page.before_revision_id}\n"
        f"After revision: {page.after_revision_id}\n\n"
        f"Record JSON:\n{record_json}"
    )
    _validate_card_size(content)
    return _product_card(
        source_identifier=source_id(fact.fact_id),
        node_identifier=fact.fact_id,
        title=f"{fact.kind.value.replace('_', ' ').title()}: {fact.fact_id}",
        source_type="change_event",
        content=content,
        repository_id=page.repository_id,
        revision_id=page.after_revision_id,
        relation_quality=fact.quality,
        record_kind="change_event_page",
        record_schema=CHANGE_EVENT_PAGE_SCHEMA,
        record_json=record_json,
        graph_ir_version=graph_ir_version,
        extra={
            "event_id": page.event_id,
            "fact_id": fact.fact_id,
            "change_kind": fact.kind.value,
            "before_revision_id": page.before_revision_id,
            "after_revision_id": page.after_revision_id,
            "page_index": page.page_index,
            "page_count": page.page_count,
        },
        graph=_change_fact_graph(page.repository_id, fact),
    )


def _product_card(
    *,
    source_identifier: str,
    node_identifier: str,
    title: str,
    source_type: str,
    content: str,
    repository_id: str,
    revision_id: str,
    relation_quality: RelationQuality,
    record_kind: str,
    record_schema: str,
    record_json: str,
    graph_ir_version: str,
    extra: Mapping[str, str | int | bool | None],
    graph: HydraSourceGraph,
) -> SourceCard:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    additional: dict[str, str | int | bool | None] = {
        "record_kind": record_kind,
        "record_schema": record_schema,
        "record_json": record_json,
        "path": ".",
        "qualified_name": title,
        "display_name": title,
        "logical_id": node_identifier,
        "parser": EVOLUTION_EXTRACTOR,
        "parser_version": EVOLUTION_EXTRACTOR_VERSION,
        "content_hash": digest,
        "graph_ir_version": graph_ir_version,
        "node_id": node_identifier,
        **extra,
    }
    return SourceCard(
        source_id=source_identifier,
        node_id=node_identifier,
        title=title,
        source_type=source_type,
        content=content,
        metadata={
            "repository_id": repository_id,
            "revision_id": revision_id,
            "entity_kind": NodeKind.CHANGE_EVENT.value,
            "relation_quality": relation_quality.value,
            "record_schema": record_schema,
        },
        additional_metadata=additional,
        graph=graph,
    )


def _change_fact_graph(repository_id: str, fact: ChangeFact) -> HydraSourceGraph:
    nodes = {
        item.node_id: item
        for item in (
            *fact.before_nodes,
            *fact.after_nodes,
        )
    }
    entities = {
        node_id: HydraEntity(
            name=_entity_name(node),
            type=node.kind.value,
            namespace=repository_id,
            identifier=node.logical_id,
        )
        for node_id, node in sorted(nodes.items())
    }
    entities[fact.fact_id] = HydraEntity(
        name=f"{fact.kind.value.replace('_', ' ').title()} [{fact.fact_id}]",
        type=NodeKind.CHANGE_EVENT.value,
        namespace=repository_id,
        identifier=fact.fact_id,
    )
    relations: list[HydraRelation] = []
    if fact.kind is ChangeKind.RENAME_HYPOTHESIS:
        before_node, after_node = fact.before_nodes[0], fact.after_nodes[0]
        evidence = after_node.evidence.evidence
        relations.append(
            HydraRelation(
                source=before_node.node_id,
                target=after_node.node_id,
                predicate=RelationPredicate.RENAMED_TO.value,
                context=_change_relation_context(
                    fact,
                    before_node.node_id,
                    after_node.node_id,
                    evidence,
                    RelationPredicate.RENAMED_TO,
                ),
            )
        )
    else:
        predicate = {
            ChangeKind.NODE_ADDED: RelationPredicate.ADDED_IN,
            ChangeKind.NODE_REMOVED: RelationPredicate.REMOVED_IN,
        }.get(fact.kind, RelationPredicate.CHANGED_IN)
        subjects = fact.after_nodes or fact.before_nodes
        relation_evidence = (
            fact.after_relations[0].evidence[0].evidence
            if fact.after_relations
            else fact.before_relations[0].evidence[0].evidence
            if fact.before_relations
            else None
        )
        for node in subjects:
            evidence = relation_evidence or node.evidence.evidence
            relations.append(
                HydraRelation(
                    source=node.node_id,
                    target=fact.fact_id,
                    predicate=predicate.value,
                    context=_change_relation_context(
                        fact,
                        node.node_id,
                        fact.fact_id,
                        evidence,
                        predicate,
                    ),
                )
            )
    return HydraSourceGraph(
        entities=entities,
        relations=tuple(sorted(relations, key=lambda item: (item.source, item.target))),
    )


def _change_relation_context(
    fact: ChangeFact,
    source_node_id: str,
    target_node_id: str,
    evidence: Evidence,
    predicate: RelationPredicate,
) -> str:
    edge_identifier = _stable_id(
        "change_edge",
        f"{fact.fact_id}:{source_node_id}:{predicate.value}:{target_node_id}",
    )
    envelope: dict[str, Any] = {
        "schema": RELATION_EVIDENCE_SCHEMA,
        "summary": fact.explanation,
        "edge_id": edge_identifier,
        "quality": fact.quality.value,
        "extractor": EVOLUTION_EXTRACTOR,
        "extractor_version": EVOLUTION_EXTRACTOR_VERSION,
        "evidence": evidence.model_dump(mode="json", exclude_none=True),
    }
    if fact.confidence is not None:
        envelope["confidence"] = fact.confidence
    context = _json(envelope)
    if len(context) <= MAX_RELATION_CONTEXT:
        return context
    summary = fact.explanation
    low, high = 1, len(summary)
    fitted: str | None = None
    while low <= high:
        midpoint = (low + high) // 2
        envelope["summary"] = summary[:midpoint].rstrip() + "…"
        candidate = _json(envelope)
        if len(candidate) <= MAX_RELATION_CONTEXT:
            fitted = candidate
            low = midpoint + 1
        else:
            high = midpoint - 1
    if fitted is None:
        raise ValueError(
            f"change evidence for fact {fact.fact_id} cannot fit HydraDB's context limit"
        )
    return fitted


def _lens_entity(node: GraphNode) -> LensEntity:
    return LensEntity(
        node_id=node.id,
        logical_id=node.logical_id,
        kind=node.kind,
        display_name=node.display_name,
        qualified_name=node.qualified_name,
        path=node.path,
        span=node.span,
        content_hash=node.content_hash,
        evidence=_node_evidence(node),
    )


def _lens_hop(edge: GraphEdge) -> LensHop:
    return LensHop(
        edge_id=edge.id,
        logical_id=edge.logical_id,
        source_node_id=edge.source_id,
        predicate=edge.predicate,
        target_node_id=edge.target_id,
        evidence=edge.evidence,
        extractor=edge.extractor,
        extractor_version=edge.extractor_version,
    )


def _node_evidence(node: GraphNode) -> Evidence:
    span = node.span
    return Evidence(
        id=evidence_id(
            path=node.path,
            start_line=span.start_line if span else None,
            start_column=span.start_column if span else None,
            end_line=span.end_line if span else None,
            end_column=span.end_column if span else None,
            excerpt_hash=node.content_hash,
        ),
        path=node.path,
        start_line=span.start_line if span else None,
        start_column=span.start_column if span else None,
        end_line=span.end_line if span else None,
        end_column=span.end_column if span else None,
        excerpt_hash=node.content_hash,
        explanation=f"Graph node {node.id} at revision {node.revision_id}.",
    )


def _validate_connected(entity_ids: set[str], edges: Sequence[GraphEdge]) -> None:
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in entity_ids}
    for edge in edges:
        adjacency[edge.source_id].add(edge.target_id)
        adjacency[edge.target_id].add(edge.source_id)
    reached: set[str] = set()
    pending = [min(entity_ids)]
    while pending:
        node_id = pending.pop()
        if node_id in reached:
            continue
        reached.add(node_id)
        pending.extend(sorted(adjacency[node_id].difference(reached)))
    if reached != entity_ids:
        raise ValueError("system lens baseline must be one connected grounded path")


def _mapping_items(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("HydraDB view nodes and edges must be lists")
    if any(not isinstance(item, Mapping) for item in value):
        raise ValueError("HydraDB view contains a malformed node or edge")
    return list(value)


def _entity_name(node: ChangeNode) -> str:
    readable = f"{node.qualified_name} [{node.kind.value.lower()}] @ {node.path}"
    if len(readable) <= 256:
        return readable
    suffix = f" … [{node.node_id}]"
    return readable[: 256 - len(suffix)] + suffix


def _validate_card_size(content: str) -> None:
    if len(content) > MAX_EVOLUTION_CARD_CHARS:
        raise ValueError(
            f"evolution Knowledge card exceeds the {MAX_EVOLUTION_CARD_CHARS}-character limit"
        )


def _stable_id(prefix: str, logical_identity: str) -> str:
    digest = hashlib.sha256(logical_identity.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _model_json(model: FrozenModel) -> str:
    return _json(model.model_dump(mode="json", exclude_none=True))


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
