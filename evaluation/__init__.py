"""Offline and live evaluation plumbing for Hack Hydra.

This package is deliberately separate from ``hydra_graph``. The TF-IDF
baseline exists only for ablation measurement and is never a product fallback.
"""

from .baseline import BaselineDocument, DeterministicTfidf, load_baseline_documents
from .gold import ResolvedQuestion, load_and_resolve_gold, load_gold, resolve_gold
from .metrics import score_observation
from .models import (
    AblationCondition,
    AgentRunManifest,
    EvaluationRecord,
    GoldManifest,
    QuestionMetrics,
    RetrievalObservation,
    RunMode,
)
from .reporting import CompletenessReport, summarize_records, write_jsonl
from .runner import AblationRunner, FixtureHydraTransport, LiveHydraTransport

__all__ = [
    "AblationCondition",
    "AblationRunner",
    "AgentRunManifest",
    "BaselineDocument",
    "CompletenessReport",
    "DeterministicTfidf",
    "EvaluationRecord",
    "FixtureHydraTransport",
    "GoldManifest",
    "LiveHydraTransport",
    "QuestionMetrics",
    "ResolvedQuestion",
    "RetrievalObservation",
    "RunMode",
    "load_and_resolve_gold",
    "load_baseline_documents",
    "load_gold",
    "resolve_gold",
    "score_observation",
    "summarize_records",
    "write_jsonl",
]
