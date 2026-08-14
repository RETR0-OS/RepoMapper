"""Strict, versioned records for reproducible evaluation artifacts."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

GOLD_SCHEMA = "hack-hydra.evaluation-gold.v1"
OBSERVATION_SCHEMA = "hack-hydra.retrieval-observation.v1"
AGENT_RUN_SCHEMA = "hack-hydra.agent-run.v1"
EVALUATION_RECORD_SCHEMA = "hack-hydra.evaluation-record.v1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunMode(StrEnum):
    OFFLINE = "offline"
    LIVE = "live"


class AblationCondition(StrEnum):
    BASELINE = "A"
    HYDRA_NO_GRAPH = "B"
    HYDRA_GRAPH = "C"


class GoldEvidence(StrictModel):
    evidence_id: str = Field(min_length=1, max_length=256)
    path: str = Field(min_length=1, max_length=1_024)
    start_line: int = Field(ge=1)
    start_column: int = Field(ge=0)
    end_line: int = Field(ge=1)
    end_column: int = Field(ge=0)
    excerpt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def ordered_span(self) -> GoldEvidence:
        if (self.end_line, self.end_column) < (self.start_line, self.start_column):
            raise ValueError("gold evidence ends before it starts")
        return self


class GoldRelation(StrictModel):
    edge_id: str = Field(min_length=1, max_length=256)
    source_logical_id: str = Field(min_length=1, max_length=2_000)
    predicate: str = Field(min_length=1, max_length=64)
    target_logical_id: str = Field(min_length=1, max_length=2_000)
    quality: str = Field(pattern=r"^(exact|inferred)$")
    evidence: tuple[GoldEvidence, ...] = Field(min_length=1, max_length=20)


class GoldQuestion(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    prompt: str = Field(min_length=3, max_length=1_000)
    category: str = Field(min_length=1, max_length=64)
    required_node_logical_ids: tuple[str, ...] = Field(min_length=1, max_length=100)
    required_relations: tuple[GoldRelation, ...] = Field(min_length=1, max_length=100)


class GoldManifest(StrictModel):
    gold_schema: str = GOLD_SCHEMA
    repository_id: str = Field(min_length=1, max_length=128)
    revision_id: str = Field(min_length=1, max_length=256)
    fixture_root: str = Field(min_length=1, max_length=1_024)
    graph_ir_path: str = Field(min_length=1, max_length=1_024)
    questions: tuple[GoldQuestion, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def supported_schema_and_unique_questions(self) -> GoldManifest:
        if self.gold_schema != GOLD_SCHEMA:
            raise ValueError(f"unsupported gold schema: {self.gold_schema}")
        ids = [question.id for question in self.questions]
        if len(ids) != len(set(ids)):
            raise ValueError("gold question IDs must be unique")
        return self


class EvidenceObservation(StrictModel):
    evidence_id: str = Field(min_length=1, max_length=256)
    path: str = Field(min_length=1, max_length=1_024)
    start_line: int | None = Field(default=None, ge=1)
    start_column: int | None = Field(default=None, ge=0)
    end_line: int | None = Field(default=None, ge=1)
    end_column: int | None = Field(default=None, ge=0)
    excerpt_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def complete_ordered_span(self) -> EvidenceObservation:
        span = (self.start_line, self.start_column, self.end_line, self.end_column)
        partially_provided = any(value is not None for value in span)
        completely_provided = all(value is not None for value in span)
        if partially_provided and not completely_provided:
            raise ValueError("observed evidence must contain a complete span or no span")
        if all(value is not None for value in span):
            assert self.start_line is not None
            assert self.start_column is not None
            assert self.end_line is not None
            assert self.end_column is not None
            if (self.end_line, self.end_column) < (self.start_line, self.start_column):
                raise ValueError("observed evidence ends before it starts")
        return self


class RelationObservation(StrictModel):
    edge_id: str = Field(min_length=1, max_length=256)
    source_id: str = Field(min_length=1, max_length=256)
    predicate: str = Field(min_length=1, max_length=64)
    target_id: str = Field(min_length=1, max_length=256)
    quality: str = Field(pattern=r"^(exact|inferred|semantic|unknown)$")
    evidence: tuple[EvidenceObservation, ...] = Field(default=(), max_length=20)


class RetrievalObservation(StrictModel):
    observation_schema: str = OBSERVATION_SCHEMA
    run_id: str = Field(min_length=1, max_length=256)
    question_id: str = Field(min_length=1, max_length=64)
    condition: AblationCondition
    mode: RunMode
    status: str = Field(pattern=r"^(ready|degraded|unavailable|error)$")
    request_body: dict[str, Any] | None = None
    returned_node_ids: tuple[str, ...] = Field(default=(), max_length=1_000)
    returned_relations: tuple[RelationObservation, ...] = Field(default=(), max_length=1_000)
    returned_evidence: tuple[EvidenceObservation, ...] = Field(default=(), max_length=2_000)
    context_chars: int = Field(ge=0)
    context_tokens: int = Field(ge=0)
    latency_ms: float = Field(ge=0)
    warnings: tuple[str, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def supported_schema_and_request_shape(self) -> RetrievalObservation:
        if self.observation_schema != OBSERVATION_SCHEMA:
            raise ValueError(f"unsupported observation schema: {self.observation_schema}")
        if self.condition is AblationCondition.BASELINE and self.request_body is not None:
            raise ValueError("the local baseline does not send a HydraDB request body")
        if self.condition is not AblationCondition.BASELINE and self.request_body is None:
            raise ValueError("HydraDB conditions require the exact request body used")
        return self


class QuestionMetrics(StrictModel):
    question_id: str
    condition: AblationCondition
    required_nodes: int = Field(ge=0)
    returned_nodes: int = Field(ge=0)
    useful_returned_nodes: int = Field(ge=0)
    required_node_hits: int = Field(ge=0)
    required_exact_relations: int = Field(ge=0)
    exact_relation_hits: int = Field(ge=0)
    required_inferred_relations: int = Field(ge=0)
    inferred_relation_hits: int = Field(ge=0)
    required_evidence: int = Field(ge=0)
    evidence_hits: int = Field(ge=0)
    supported_returned_exact: int = Field(ge=0)
    returned_exact_relations: int = Field(ge=0)
    supported_returned_inferred: int = Field(ge=0)
    returned_inferred_relations: int = Field(ge=0)
    returned_other_relations: int = Field(ge=0)
    unsupported_relations: int = Field(ge=0)
    context_chars: int = Field(ge=0)
    context_tokens: int = Field(ge=0)
    latency_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def bounded_counts(self) -> QuestionMetrics:
        pairs = (
            (self.required_node_hits, self.required_nodes, "node recall"),
            (self.useful_returned_nodes, self.returned_nodes, "context precision"),
            (self.exact_relation_hits, self.required_exact_relations, "exact recall"),
            (self.inferred_relation_hits, self.required_inferred_relations, "inferred recall"),
            (self.evidence_hits, self.required_evidence, "evidence recall"),
            (
                self.supported_returned_exact,
                self.returned_exact_relations,
                "exact path correctness",
            ),
            (
                self.supported_returned_inferred,
                self.returned_inferred_relations,
                "inferred path correctness",
            ),
        )
        for numerator, denominator, name in pairs:
            if numerator > denominator:
                raise ValueError(f"{name} numerator exceeds its denominator")
        total_relations = (
            self.returned_exact_relations
            + self.returned_inferred_relations
            + self.returned_other_relations
        )
        if self.unsupported_relations > total_relations:
            raise ValueError("unsupported relation count exceeds returned relations")
        return self


class EvaluationRecord(StrictModel):
    record_schema: str = EVALUATION_RECORD_SCHEMA
    gold_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation: RetrievalObservation
    metrics: QuestionMetrics

    @model_validator(mode="after")
    def supported_schema(self) -> EvaluationRecord:
        if self.record_schema != EVALUATION_RECORD_SCHEMA:
            raise ValueError(f"unsupported evaluation record schema: {self.record_schema}")
        if self.metrics.question_id != self.observation.question_id:
            raise ValueError("metrics and observation question IDs differ")
        if self.metrics.condition is not self.observation.condition:
            raise ValueError("metrics and observation conditions differ")
        return self


class AgentRunManifest(StrictModel):
    agent_run_schema: str = AGENT_RUN_SCHEMA
    run_id: str = Field(min_length=1, max_length=256)
    agent: str = Field(pattern=r"^(codex|claude-code)$")
    model: str = Field(min_length=1, max_length=256)
    question_ids: tuple[str, ...] = Field(min_length=1, max_length=100)
    conditions: tuple[AblationCondition, ...] = Field(min_length=1, max_length=3)
    mcp_transport: str = Field(pattern=r"^streamable-http$")
    mcp_endpoint: str = Field(pattern=r"^http://(?:127\.0\.0\.1|localhost):[0-9]{1,5}/mcp$")
    observable_fields: tuple[str, ...] = Field(min_length=1, max_length=50)
    live_hydradb_required: bool = True
    results_path: str | None = Field(default=None, max_length=1_024)

    @model_validator(mode="after")
    def honest_agent_manifest(self) -> AgentRunManifest:
        if self.agent_run_schema != AGENT_RUN_SCHEMA:
            raise ValueError(f"unsupported agent run schema: {self.agent_run_schema}")
        forbidden = {"reasoning", "hidden_reasoning", "chain_of_thought", "internal_traversal"}
        if forbidden.intersection(field.lower() for field in self.observable_fields):
            raise ValueError("agent manifests may record observable outcomes and tool use only")
        if set(self.conditions) != set(AblationCondition):
            raise ValueError("agent manifests must run all three A/B/C conditions")
        return self
