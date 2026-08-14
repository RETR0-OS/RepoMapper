"""Deterministic, source-grounded repository graph primitives."""

from .analyzer import PythonAnalyzer, analyze_repository
from .cards import SourceCard, build_app_knowledge, build_graph_payload, build_source_cards
from .diff import GraphDelta, compare_graphs
from .discovery import DiscoveryReport, discover_files
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
    "DiscoveryReport",
    "GraphEdge",
    "GraphDelta",
    "GraphIR",
    "GraphNode",
    "NodeKind",
    "PythonAnalyzer",
    "ProjectionDepth",
    "RelationPredicate",
    "RelationQuality",
    "RepositoryProjection",
    "SourceCard",
    "SourceSpan",
    "analyze_repository",
    "build_app_knowledge",
    "build_graph_payload",
    "build_repository_projection",
    "build_source_cards",
    "compare_graphs",
    "discover_files",
]
