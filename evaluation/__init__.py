"""Offline and live evaluation plumbing for Hack Hydra.

This package is deliberately separate from ``hydra_graph``. The TF-IDF
baseline exists only for ablation measurement and is never a product fallback.
"""

from .baseline import (
    BaselineDocument,
    DeterministicTfidf,
    baseline_corpus_digest,
    load_baseline_documents,
)
from .gold import ResolvedQuestion, load_and_resolve_gold, load_gold, resolve_gold
from .metrics import score_observation
from .models import (
    AblationCondition,
    AgentOutcomeRecord,
    AgentRunManifest,
    EvaluationRecord,
    GoldManifest,
    QuestionMetrics,
    RetrievalObservation,
    RunMode,
    is_concrete_live_run_id,
)
from .reporting import (
    CompletenessReport,
    artifact_digest,
    read_agent_outcomes,
    summarize_records,
    write_agent_outcomes,
    write_jsonl,
)
from .runner import AblationRunner, FixtureHydraTransport, LiveHydraTransport

__all__ = [
    "AblationCondition",
    "AblationRunner",
    "AgentOutcomeRecord",
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
    "artifact_digest",
    "baseline_corpus_digest",
    "load_and_resolve_gold",
    "load_baseline_documents",
    "load_gold",
    "is_concrete_live_run_id",
    "read_agent_outcomes",
    "resolve_gold",
    "score_observation",
    "summarize_records",
    "write_agent_outcomes",
    "write_jsonl",
]
