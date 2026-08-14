"""Strict, versioned records for reproducible evaluation artifacts."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

GOLD_SCHEMA = "hack-hydra.evaluation-gold.v1"
OBSERVATION_SCHEMA = "hack-hydra.retrieval-observation.v1"
AGENT_RUN_SCHEMA = "hack-hydra.agent-run.v1"
AGENT_OUTCOME_SCHEMA = "hack-hydra.agent-outcome.v1"
EVALUATION_RECORD_SCHEMA = "hack-hydra.evaluation-record.v1"
AGENT_OBSERVABLE_FIELDS = frozenset(
    {
        "task_completed",
        "correct_files_changed",
        "unnecessary_files_opened_or_edited",
        "repository_tool_calls",
        "hydradb_query_calls",
        "context_characters_returned",
        "tests_passed",
        "outcome",
        "rework_count",
    }
)
LIVE_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,255}$")


def is_concrete_live_run_id(value: str) -> bool:
    normalized = value.casefold()
    return bool(
        value == value.strip()
        and LIVE_RUN_ID_PATTERN.fullmatch(value)
        and "rehearsal" not in normalized
        and "offline" not in normalized
        and "placeholder" not in normalized
        and "replace-with" not in normalized
    )


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunMode(StrEnum):
    OFFLINE = "offline"
    LIVE = "live"


class AblationCondition(StrEnum):
    BASELINE = "A"
    HYDRA_NO_GRAPH = "B"
    HYDRA_GRAPH = "C"


class EvaluationTarget(StrictModel):
    database: str = Field(min_length=1, max_length=256)
    collection: Literal["current"] = "current"
    repository_id: str = Field(min_length=1, max_length=128)
    revision_id: str = Field(min_length=1, max_length=256)
    repository_root_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvaluationMetadataFilters(StrictModel):
    repository_id: str = Field(min_length=1, max_length=128)
    revision_id: str = Field(min_length=1, max_length=256)


class HydraQueryPlan(StrictModel):
    query: str = Field(min_length=1, max_length=1_000)
    query_by: Literal["hybrid"] = "hybrid"
    mode: Literal["thinking"] = "thinking"
    graph_context: bool
    max_results: int = Field(ge=1, le=50)
    collection: Literal["current"] = "current"
    metadata_filters: EvaluationMetadataFilters


class HydraDBRequestBody(HydraQueryPlan):
    database: str = Field(min_length=1, max_length=256)
    type: Literal["knowledge"] = "knowledge"
    query_forceful_relations: Literal[True] = True


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
    origin: str = Field(default="unknown", min_length=1, max_length=64)
    evidence: tuple[EvidenceObservation, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def exact_requires_byog_grounding(self) -> RelationObservation:
        if self.quality != "exact":
            return self
        if self.origin != "byog" or not self.evidence:
            raise ValueError("exact observed relations require BYOG origin and evidence")
        if any(
            item.start_line is None
            or item.start_column is None
            or item.end_line is None
            or item.end_column is None
            or item.excerpt_hash is None
            for item in self.evidence
        ):
            raise ValueError("exact observed relation evidence must be line-addressable")
        return self


class RetrievalObservation(StrictModel):
    observation_schema: str = OBSERVATION_SCHEMA
    run_id: str = Field(min_length=1, max_length=256)
    question_id: str = Field(min_length=1, max_length=64)
    condition: AblationCondition
    mode: RunMode
    status: str = Field(pattern=r"^(ready|degraded|unavailable|error)$")
    target: EvaluationTarget
    request_plan: HydraQueryPlan | None = None
    hydradb_request_body: HydraDBRequestBody | None = None
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
        if self.mode is RunMode.LIVE and not is_concrete_live_run_id(self.run_id):
            raise ValueError("live observations require a concrete non-rehearsal run_id")
        if self.condition is AblationCondition.BASELINE:
            if self.request_plan is not None or self.hydradb_request_body is not None:
                raise ValueError("the local baseline does not create a HydraDB request")
            return self
        if self.request_plan is None:
            raise ValueError("HydraDB conditions require the transport request plan")
        if (
            self.request_plan.collection != self.target.collection
            or self.request_plan.metadata_filters.repository_id != self.target.repository_id
            or self.request_plan.metadata_filters.revision_id != self.target.revision_id
        ):
            raise ValueError("the request plan is not bound to the evaluation target")
        if self.mode is RunMode.OFFLINE and self.hydradb_request_body is not None:
            raise ValueError("offline fixtures cannot claim an actual HydraDB request body")
        if self.mode is RunMode.LIVE:
            if self.hydradb_request_body is None:
                raise ValueError("live HydraDB conditions require the actual adapter request body")
            expected_body = {
                **self.request_plan.model_dump(mode="json"),
                "database": self.target.database,
                "type": "knowledge",
                "query_forceful_relations": True,
            }
            if self.hydradb_request_body.model_dump(mode="json") != expected_body:
                raise ValueError("the actual HydraDB body does not match its request plan")
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
    baseline_corpus_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
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


class AgentOutcomeRecord(StrictModel):
    outcome_schema: str = AGENT_OUTCOME_SCHEMA
    retrieval_artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_id: str = Field(min_length=1, max_length=256)
    agent: Literal["codex", "claude-code"]
    model: str = Field(min_length=1, max_length=256)
    question_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    condition: AblationCondition
    task_completed: bool
    correct_files_changed: tuple[str, ...] = Field(default=(), max_length=1_000)
    unnecessary_files_opened_or_edited: tuple[str, ...] = Field(default=(), max_length=1_000)
    repository_tool_calls: int = Field(ge=0)
    hydradb_query_calls: int = Field(ge=0)
    context_characters_returned: int = Field(ge=0)
    tests_passed: bool
    outcome: Literal["completed", "incomplete", "failed"]
    rework_count: int = Field(ge=0)

    @model_validator(mode="after")
    def observable_and_consistent(self) -> AgentOutcomeRecord:
        if self.outcome_schema != AGENT_OUTCOME_SCHEMA:
            raise ValueError(f"unsupported agent outcome schema: {self.outcome_schema}")
        if self.task_completed != (self.outcome == "completed"):
            raise ValueError("agent outcome and task_completed disagree")
        if not is_concrete_live_run_id(self.run_id):
            raise ValueError("agent outcomes require a concrete live run_id")
        if self.condition is AblationCondition.BASELINE and self.hydradb_query_calls != 0:
            raise ValueError("condition A agent outcomes cannot claim HydraDB query calls")
        if self.condition is not AblationCondition.BASELINE and self.hydradb_query_calls < 1:
            raise ValueError("conditions B/C agent outcomes require a HydraDB query call")
        if self.hydradb_query_calls > self.repository_tool_calls:
            raise ValueError("HydraDB query calls cannot exceed repository tool calls")
        paths = (*self.correct_files_changed, *self.unnecessary_files_opened_or_edited)
        if any(
            not path
            or len(path) > 1_024
            or path.startswith(("/", "\\"))
            or ":" in path.split("/")[0]
            or ".." in path.replace("\\", "/").split("/")
            for path in paths
        ):
            raise ValueError("agent outcome file paths must be bounded repository-relative paths")
        if len(paths) != len(set(paths)):
            raise ValueError("agent outcome file lists must be unique and disjoint")
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
    retrieval_results_path: str | None = Field(default=None, max_length=1_024)
    results_path: str | None = Field(default=None, max_length=1_024)

    @model_validator(mode="after")
    def honest_agent_manifest(self) -> AgentRunManifest:
        if self.agent_run_schema != AGENT_RUN_SCHEMA:
            raise ValueError(f"unsupported agent run schema: {self.agent_run_schema}")
        forbidden = {"reasoning", "hidden_reasoning", "chain_of_thought", "internal_traversal"}
        if forbidden.intersection(field.lower() for field in self.observable_fields):
            raise ValueError("agent manifests may record observable outcomes and tool use only")
        if set(self.observable_fields) != AGENT_OBSERVABLE_FIELDS:
            raise ValueError("agent manifests must declare the complete observable outcome fields")
        if len(self.observable_fields) != len(set(self.observable_fields)):
            raise ValueError("agent manifest observable fields must be unique")
        if set(self.conditions) != set(AblationCondition):
            raise ValueError("agent manifests must run all three A/B/C conditions")
        if len(self.question_ids) != len(set(self.question_ids)):
            raise ValueError("agent manifest question IDs must be unique")
        if not self.live_hydradb_required:
            raise ValueError("agent evaluation manifests must require live HydraDB")
        if (self.results_path is not None or self.retrieval_results_path is not None) and not (
            self.results_path is not None
            and self.retrieval_results_path is not None
            and is_concrete_live_run_id(self.run_id)
        ):
            raise ValueError("completed agent manifests require both paths and a concrete run_id")
        return self
