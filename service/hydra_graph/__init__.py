"""Deterministic, source-grounded repository graph primitives."""

from .analyzer import PythonAnalyzer, analyze_repository
from .cards import SourceCard, build_app_knowledge, build_graph_payload, build_source_cards
from .checkpoints import CheckpointRef, CheckpointSlot, CheckpointStore
from .diff import GraphDelta, compare_graphs
from .discovery import DiscoveryReport, discover_files
from .evolution import (
    ChangeEventPage,
    ChangeEventRecord,
    ChangeEventSummary,
    ChangeFact,
    ChangeKind,
    ChangeNode,
    ChangeRelation,
    LensEntity,
    LensHop,
    RevisionEvidence,
    SystemLensRecord,
    build_change_event,
    build_change_event_cards,
    build_system_lens,
    build_system_lens_card,
)
from .models import (
    Evidence,
    GraphEdge,
    GraphIR,
    GraphNode,
    NodeKind,
    RelationPredicate,
    RelationQuality,
    SourceSpan,
)
from .projections import ProjectionDepth, RepositoryProjection, build_repository_projection

__all__ = [
    "Evidence",
    "CheckpointRef",
    "CheckpointSlot",
    "CheckpointStore",
    "ChangeEventPage",
    "ChangeEventRecord",
    "ChangeEventSummary",
    "ChangeFact",
    "ChangeKind",
    "ChangeNode",
    "ChangeRelation",
    "DiscoveryReport",
    "GraphEdge",
    "GraphDelta",
    "GraphIR",
    "GraphNode",
    "NodeKind",
    "LensEntity",
    "LensHop",
    "PythonAnalyzer",
    "ProjectionDepth",
    "RelationPredicate",
    "RelationQuality",
    "RepositoryProjection",
    "RevisionEvidence",
    "SourceCard",
    "SourceSpan",
    "SystemLensRecord",
    "analyze_repository",
    "build_app_knowledge",
    "build_change_event",
    "build_change_event_cards",
    "build_graph_payload",
    "build_repository_projection",
    "build_source_cards",
    "build_system_lens",
    "build_system_lens_card",
    "compare_graphs",
    "discover_files",
]
