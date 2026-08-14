"""Versioned, validated Graph IR records.

The model rejects ungrounded repository nodes and prevents inferred or semantic
relations from being represented as exact facts by accident.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .ids import normalize_relative_path


GRAPH_IR_VERSION = "1.0"


class NodeKind(StrEnum):
    REPOSITORY = "REPOSITORY"
    PACKAGE = "PACKAGE"
    MODULE = "MODULE"
    FILE = "FILE"
    CLASS = "CLASS"
    INTERFACE = "INTERFACE"
    TYPE = "TYPE"
    FUNCTION = "FUNCTION"
    METHOD = "METHOD"
    VARIABLE = "VARIABLE"
    CONSTANT = "CONSTANT"
    TEST = "TEST"
    ENTRYPOINT = "ENTRYPOINT"
    CONFIG_BLOCK = "CONFIG_BLOCK"
    INFRA_BLOCK = "INFRA_BLOCK"
    BUILD_TARGET = "BUILD_TARGET"
    ROUTE = "ROUTE"
    EVENT = "EVENT"
    DATASTORE = "DATASTORE"
    EXTERNAL_SERVICE = "EXTERNAL_SERVICE"
    SYSTEM_LENS = "SYSTEM_LENS"
    CHANGE_EVENT = "CHANGE_EVENT"


class RelationPredicate(StrEnum):
    CONTAINS = "CONTAINS"
    DEFINES = "DEFINES"
    DECLARES = "DECLARES"
    IMPORTS = "IMPORTS"
    EXPORTS = "EXPORTS"
    REFERENCES = "REFERENCES"
    EXTENDS = "EXTENDS"
    IMPLEMENTS = "IMPLEMENTS"
    OVERRIDES = "OVERRIDES"
    RETURNS = "RETURNS"
    ACCEPTS = "ACCEPTS"
    INSTANTIATES = "INSTANTIATES"
    CALLS = "CALLS"
    MAY_CALL = "MAY_CALL"
    DISPATCHES_TO = "DISPATCHES_TO"
    HANDLES = "HANDLES"
    EMITS = "EMITS"
    SUBSCRIBES_TO = "SUBSCRIBES_TO"
    READS_FROM = "READS_FROM"
    WRITES_TO = "WRITES_TO"
    THROWS = "THROWS"
    TESTS = "TESTS"
    MOCKS = "MOCKS"
    ASSERTS_BEHAVIOR_OF = "ASSERTS_BEHAVIOR_OF"
    USES_FIXTURE = "USES_FIXTURE"
    CONFIGURES = "CONFIGURES"
    RESOLVES_TO = "RESOLVES_TO"
    LOADS = "LOADS"
    PROVIDES = "PROVIDES"
    DEPLOYS = "DEPLOYS"
    INVOKES = "INVOKES"
    ADDED_IN = "ADDED_IN"
    REMOVED_IN = "REMOVED_IN"
    CHANGED_IN = "CHANGED_IN"
    RENAMED_TO = "RENAMED_TO"
    REPLACES = "REPLACES"
    DRIFTS_FROM = "DRIFTS_FROM"


class RelationQuality(StrEnum):
    EXACT = "exact"
    INFERRED = "inferred"
    SEMANTIC = "semantic"
    UNKNOWN = "unknown"


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=False)


class SourceSpan(FrozenModel):
    """A one-based line and zero-based column range, end-exclusive."""

    start_line: int = Field(ge=1)
    start_column: int = Field(ge=0)
    end_line: int = Field(ge=1)
    end_column: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_order(self) -> SourceSpan:
        start = (self.start_line, self.start_column)
        end = (self.end_line, self.end_column)
        if end < start:
            raise ValueError("source span ends before it starts")
        return self


class Evidence(FrozenModel):
    id: str
    path: str
    start_line: int | None = Field(default=None, ge=1)
    start_column: int | None = Field(default=None, ge=0)
    end_line: int | None = Field(default=None, ge=1)
    end_column: int | None = Field(default=None, ge=0)
    excerpt_hash: str = Field(min_length=64, max_length=64)
    explanation: str = Field(min_length=1, max_length=2000)

    @field_validator("path")
    @classmethod
    def normalize_path(cls, value: str) -> str:
        return normalize_relative_path(value)

    @model_validator(mode="after")
    def validate_location(self) -> Evidence:
        location = (self.start_line, self.start_column, self.end_line, self.end_column)
        provided = [part is not None for part in location]
        if any(provided) and not all(provided):
            raise ValueError("evidence must provide a complete source range or no range")
        if all(provided):
            assert self.start_line is not None
            assert self.start_column is not None
            assert self.end_line is not None
            assert self.end_column is not None
            SourceSpan(
                start_line=self.start_line,
                start_column=self.start_column,
                end_line=self.end_line,
                end_column=self.end_column,
            )
        return self

    @property
    def span(self) -> SourceSpan | None:
        if self.start_line is None:
            return None
        return SourceSpan(
            start_line=self.start_line,
            start_column=self.start_column or 0,
            end_line=self.end_line or self.start_line,
            end_column=self.end_column or 0,
        )


_LINE_ADDRESSABLE = {
    NodeKind.CLASS,
    NodeKind.INTERFACE,
    NodeKind.TYPE,
    NodeKind.FUNCTION,
    NodeKind.METHOD,
    NodeKind.VARIABLE,
    NodeKind.CONSTANT,
    NodeKind.TEST,
    NodeKind.ENTRYPOINT,
    NodeKind.CONFIG_BLOCK,
    NodeKind.INFRA_BLOCK,
    NodeKind.BUILD_TARGET,
    NodeKind.ROUTE,
    NodeKind.EVENT,
    NodeKind.DATASTORE,
    NodeKind.EXTERNAL_SERVICE,
}


class GraphNode(FrozenModel):
    id: str
    logical_id: str
    kind: NodeKind
    display_name: str = Field(min_length=1)
    qualified_name: str = Field(min_length=1)
    language: str | None = None
    path: str
    span: SourceSpan | None = None
    signature: str | None = None
    revision_id: str = Field(min_length=1)
    content_hash: str = Field(min_length=64, max_length=64)
    parser: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    is_generated: bool = False
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("path")
    @classmethod
    def normalize_path(cls, value: str) -> str:
        return normalize_relative_path(value)

    @model_validator(mode="after")
    def validate_grounding(self) -> GraphNode:
        if self.kind in _LINE_ADDRESSABLE and self.span is None:
            raise ValueError(f"{self.kind.value} nodes require an exact source span")
        if self.kind in {NodeKind.SYSTEM_LENS, NodeKind.CHANGE_EVENT}:
            # These are product records. They are valid Graph IR but projections
            # explicitly exclude them from repository structure views.
            return self
        if self.path == "." and self.kind is not NodeKind.REPOSITORY:
            raise ValueError(f"{self.kind.value} nodes require a concrete repository path")
        return self


class GraphEdge(FrozenModel):
    id: str
    logical_id: str
    source_id: str
    predicate: RelationPredicate
    target_id: str
    quality: RelationQuality
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: tuple[Evidence, ...]
    revision_id: str = Field(min_length=1)
    extractor: str = Field(min_length=1)
    extractor_version: str = Field(min_length=1)
    owner_source_id: str
    attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_provenance(self) -> GraphEdge:
        if self.source_id == self.target_id:
            raise ValueError("self-relations are not valid repository graph edges")
        if self.quality is RelationQuality.EXACT:
            if self.confidence is not None:
                raise ValueError("exact relations do not use decorative confidence")
            if not self.evidence:
                raise ValueError("exact relations require deterministic evidence")
        elif self.quality in {RelationQuality.INFERRED, RelationQuality.SEMANTIC}:
            if self.confidence is None:
                raise ValueError(f"{self.quality.value} relations require a defined confidence")
        return self


class GraphIR(FrozenModel):
    graph_ir_version: str = GRAPH_IR_VERSION
    repository_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    diagnostics: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_graph(self) -> GraphIR:
        if self.graph_ir_version != GRAPH_IR_VERSION:
            raise ValueError(f"unsupported Graph IR version: {self.graph_ir_version}")
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Graph IR contains duplicate node IDs")
        edge_ids = [edge.id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("Graph IR contains duplicate edge IDs")
        known_nodes = set(node_ids)
        for edge in self.edges:
            if edge.source_id not in known_nodes or edge.target_id not in known_nodes:
                raise ValueError(f"edge {edge.id} references a missing node")
            if edge.owner_source_id not in known_nodes:
                raise ValueError(f"edge {edge.id} has a missing canonical owner")
            if edge.revision_id != self.revision_id:
                raise ValueError(f"edge {edge.id} belongs to another revision")
        if any(node.revision_id != self.revision_id for node in self.nodes):
            raise ValueError("all nodes must belong to the Graph IR revision")
        return self

    def node_map(self) -> dict[str, GraphNode]:
        return {node.id: node for node in self.nodes}

