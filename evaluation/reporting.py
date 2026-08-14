"""Raw artifact writing and completeness-gated summaries."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .models import (
    AblationCondition,
    AgentOutcomeRecord,
    EvaluationRecord,
    EvaluationTarget,
    HydraDBRequestBody,
    HydraQueryPlan,
    RetrievalObservation,
    RunMode,
    is_concrete_live_run_id,
)


@dataclass(frozen=True, slots=True)
class CompletenessReport:
    complete: bool
    live_results: bool
    comparative_claims_allowed: bool
    missing: tuple[str, ...]


def write_jsonl(path: str | Path, records: tuple[EvaluationRecord, ...]) -> None:
    if not records:
        raise ValueError("evaluation JSONL cannot be empty")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(record.model_dump(mode="json"), separators=(",", ":"), sort_keys=True)
        for record in records
    ]
    _atomic_text(target, "\n".join(lines) + "\n")


def read_jsonl(path: str | Path) -> tuple[EvaluationRecord, ...]:
    records: list[EvaluationRecord] = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError(f"cannot read evaluation JSONL: {path}") from error
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            records.append(EvaluationRecord.model_validate_json(line))
        except ValueError as error:
            raise ValueError(f"invalid evaluation record on line {line_number}") from error
    if not records:
        raise ValueError("evaluation JSONL contains no records")
    return tuple(records)


def write_agent_outcomes(path: str | Path, records: tuple[AgentOutcomeRecord, ...]) -> None:
    if not records:
        raise ValueError("agent outcome JSONL cannot be empty")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(record.model_dump(mode="json"), separators=(",", ":"), sort_keys=True)
        for record in records
    ]
    _atomic_text(target, "\n".join(lines) + "\n")


def read_agent_outcomes(path: str | Path) -> tuple[AgentOutcomeRecord, ...]:
    records: list[AgentOutcomeRecord] = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError(f"cannot read agent outcome JSONL: {path}") from error
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            records.append(AgentOutcomeRecord.model_validate_json(line))
        except ValueError as error:
            raise ValueError(f"invalid agent outcome record on line {line_number}") from error
    if not records:
        raise ValueError("agent outcome JSONL contains no records")
    return tuple(records)


def artifact_digest(path: str | Path) -> str:
    try:
        content = Path(path).read_bytes()
    except OSError as error:
        raise ValueError(f"cannot hash evaluation artifact: {path}") from error
    return hashlib.sha256(content).hexdigest()


def completeness(
    records: tuple[EvaluationRecord, ...],
    *,
    expected_question_ids: tuple[str, ...],
    expected_gold_digest: str,
    expected_baseline_corpus_digest: str,
    expected_target: EvaluationTarget,
) -> CompletenessReport:
    missing: list[str] = []
    run_ids = {record.observation.run_id for record in records}
    if len(run_ids) != 1:
        missing.append("records must contain exactly one run_id")
    modes = {record.observation.mode for record in records}
    if len(modes) != 1:
        missing.append("records use mixed run modes")
    if RunMode.LIVE in modes and any(not is_concrete_live_run_id(run_id) for run_id in run_ids):
        missing.append("live records require a concrete non-rehearsal run_id")
    if any(record.gold_digest != expected_gold_digest for record in records):
        missing.append("records do not match the current gold digest")
    if any(record.baseline_corpus_digest != expected_baseline_corpus_digest for record in records):
        missing.append("records do not match the current validated baseline corpus")
    if any(record.observation.target != expected_target for record in records):
        missing.append("records do not match the configured evaluation target")
    if any(
        not _observation_matches_target(record.observation, expected_target) for record in records
    ):
        missing.append("recorded request contracts do not match the evaluation target")
    expected_conditions = set(AblationCondition)
    by_question: dict[str, list[EvaluationRecord]] = {}
    for record in records:
        by_question.setdefault(record.observation.question_id, []).append(record)
    for question_id in expected_question_ids:
        question_records = by_question.get(question_id, [])
        counts = {
            condition: sum(record.observation.condition is condition for record in question_records)
            for condition in expected_conditions
        }
        for condition, count in sorted(counts.items(), key=lambda item: item[0].value):
            if count != 1:
                missing.append(f"{question_id}:{condition.value} count={count}")
        if any(record.observation.status != "ready" for record in question_records):
            missing.append(f"{question_id}:non-ready result")
        by_condition = {
            record.observation.condition: record.observation for record in question_records
        }
        without_graph = by_condition.get(AblationCondition.HYDRA_NO_GRAPH)
        with_graph = by_condition.get(AblationCondition.HYDRA_GRAPH)
        if without_graph is not None and with_graph is not None:
            if not _paired_payloads(
                without_graph.request_plan,
                with_graph.request_plan,
                expected_false=False,
                expected_true=True,
            ):
                missing.append(f"{question_id}:B/C request plans are not paired")
            if RunMode.LIVE in modes and not _paired_payloads(
                without_graph.hydradb_request_body,
                with_graph.hydradb_request_body,
                expected_false=False,
                expected_true=True,
            ):
                missing.append(f"{question_id}:B/C actual HydraDB bodies are not paired")
    unexpected = sorted(set(by_question) - set(expected_question_ids))
    missing.extend(f"unexpected question:{question_id}" for question_id in unexpected)
    complete = not missing and bool(expected_question_ids)
    live_results = bool(records) and all(
        record.observation.mode is RunMode.LIVE for record in records
    )
    return CompletenessReport(
        complete=complete,
        live_results=live_results,
        comparative_claims_allowed=complete and live_results,
        missing=tuple(missing),
    )


def summarize_records(
    records: tuple[EvaluationRecord, ...],
    *,
    expected_question_ids: tuple[str, ...],
    expected_gold_digest: str,
    expected_baseline_corpus_digest: str,
    expected_target: EvaluationTarget,
    csv_path: str | Path,
    markdown_path: str | Path,
) -> CompletenessReport:
    report = completeness(
        records,
        expected_question_ids=expected_question_ids,
        expected_gold_digest=expected_gold_digest,
        expected_baseline_corpus_digest=expected_baseline_corpus_digest,
        expected_target=expected_target,
    )
    ordered = tuple(
        sorted(
            records,
            key=lambda item: (item.observation.question_id, item.observation.condition.value),
        )
    )
    _write_csv(Path(csv_path), ordered)
    _write_markdown(Path(markdown_path), ordered, report)
    return report


def _paired_payloads(
    without_graph: HydraQueryPlan | HydraDBRequestBody | None,
    with_graph: HydraQueryPlan | HydraDBRequestBody | None,
    *,
    expected_false: bool,
    expected_true: bool,
) -> bool:
    if without_graph is None or with_graph is None:
        return False
    left = without_graph.model_dump(mode="json")
    right = with_graph.model_dump(mode="json")
    if left.pop("graph_context", None) is not expected_false:
        return False
    if right.pop("graph_context", None) is not expected_true:
        return False
    return left == right


def _observation_matches_target(
    observation: RetrievalObservation, target: EvaluationTarget
) -> bool:
    if observation.condition is AblationCondition.BASELINE:
        return observation.request_plan is None and observation.hydradb_request_body is None
    plan = observation.request_plan
    if plan is None or (
        plan.collection != target.collection
        or plan.metadata_filters.repository_id != target.repository_id
        or plan.metadata_filters.revision_id != target.revision_id
    ):
        return False
    if observation.mode is RunMode.OFFLINE:
        return observation.hydradb_request_body is None
    body = observation.hydradb_request_body
    if body is None:
        return False
    expected = {
        **plan.model_dump(mode="json"),
        "database": target.database,
        "type": "knowledge",
        "query_forceful_relations": True,
    }
    return body.model_dump(mode="json") == expected


def _write_csv(path: Path, records: tuple[EvaluationRecord, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = (
        "question_id",
        "condition",
        "mode",
        "status",
        "node_hits",
        "required_nodes",
        "useful_returned_nodes",
        "returned_nodes",
        "exact_relation_hits",
        "required_exact_relations",
        "inferred_relation_hits",
        "required_inferred_relations",
        "evidence_hits",
        "required_evidence",
        "unsupported_relations",
        "returned_other_relations",
        "context_chars",
        "context_tokens",
        "latency_ms",
    )
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", dir=path.parent, delete=False
    ) as temporary:
        writer = csv.DictWriter(temporary, fieldnames=columns)
        writer.writeheader()
        for record in records:
            metrics = record.metrics
            writer.writerow(
                {
                    "question_id": metrics.question_id,
                    "condition": metrics.condition.value,
                    "mode": record.observation.mode.value,
                    "status": record.observation.status,
                    "node_hits": metrics.required_node_hits,
                    "required_nodes": metrics.required_nodes,
                    "useful_returned_nodes": metrics.useful_returned_nodes,
                    "returned_nodes": metrics.returned_nodes,
                    "exact_relation_hits": metrics.exact_relation_hits,
                    "required_exact_relations": metrics.required_exact_relations,
                    "inferred_relation_hits": metrics.inferred_relation_hits,
                    "required_inferred_relations": metrics.required_inferred_relations,
                    "evidence_hits": metrics.evidence_hits,
                    "required_evidence": metrics.required_evidence,
                    "unsupported_relations": metrics.unsupported_relations,
                    "returned_other_relations": metrics.returned_other_relations,
                    "context_chars": metrics.context_chars,
                    "context_tokens": metrics.context_tokens,
                    "latency_ms": f"{metrics.latency_ms:.3f}",
                }
            )
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)


def _write_markdown(
    path: Path, records: tuple[EvaluationRecord, ...], report: CompletenessReport
) -> None:
    rows = [
        "# Evaluation summary",
        "",
        "Raw counts retain their denominators. Exact and inferred relations are separate.",
        "",
        "| Question | Condition | Nodes | Exact relations | Inferred relations | "
        "Evidence | Unsupported | Context tokens | Status |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for record in records:
        metrics = record.metrics
        rows.append(
            "| "
            f"{metrics.question_id} | {metrics.condition.value} | "
            f"{metrics.required_node_hits}/{metrics.required_nodes} | "
            f"{metrics.exact_relation_hits}/{metrics.required_exact_relations} | "
            f"{metrics.inferred_relation_hits}/{metrics.required_inferred_relations} | "
            f"{metrics.evidence_hits}/{metrics.required_evidence} | "
            f"{metrics.unsupported_relations} | {metrics.context_tokens} | "
            f"{record.observation.status} |"
        )
    rows.extend(["", "## Claim guard", ""])
    if report.comparative_claims_allowed:
        rows.append(
            "The A/B/C set is complete and live. Comparative interpretation is allowed only "
            "after reviewing the raw JSONL and gold manifest."
        )
    else:
        reasons = list(report.missing)
        if not report.live_results:
            reasons.append("results are not a complete live HydraDB run")
        rows.append("Comparative claims are not allowed. " + "; ".join(reasons) + ".")
    _atomic_text(path, "\n".join(rows) + "\n")


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
    ) as temporary:
        temporary.write(content)
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)
