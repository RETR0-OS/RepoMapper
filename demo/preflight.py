"""Fail-closed checks for the live five-minute demo."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evaluation.baseline import (
    baseline_corpus_digest,
    load_baseline_documents,
    validate_baseline_documents,
)
from evaluation.gold import ResolvedGold, load_and_resolve_gold
from evaluation.metrics import score_observation
from evaluation.models import (
    AgentRunManifest,
    EvaluationRecord,
    EvaluationTarget,
    is_concrete_live_run_id,
)
from evaluation.reporting import (
    artifact_digest,
    completeness,
    read_agent_outcomes,
    read_jsonl,
)
from evaluation.runner import configured_evaluation_target


@dataclass(frozen=True, slots=True)
class PreflightCheck:
    name: str
    passed: bool
    detail: str


def run_preflight(
    *,
    project_root: Path,
    environment: Mapping[str, str],
    health: Mapping[str, Any] | None,
    results_path: Path | None,
) -> tuple[PreflightCheck, ...]:
    checks: list[PreflightCheck] = []
    credentials_present = all(
        environment.get(name, "").strip() for name in ("HYDRA_DB_API_KEY", "HYDRA_DB_DATABASE")
    )
    checks.append(
        PreflightCheck(
            "HydraDB credentials",
            credentials_present,
            "required environment variables are set"
            if credentials_present
            else "HYDRA_DB_API_KEY and HYDRA_DB_DATABASE must be set",
        )
    )
    try:
        resolved = load_and_resolve_gold(project_root / "fixtures" / "evaluation" / "gold.json")
    except ValueError as error:
        resolved = None
        checks.append(PreflightCheck("Gold fixture", False, str(error)))
    else:
        checks.append(
            PreflightCheck(
                "Gold fixture",
                True,
                f"{len(resolved.questions)} questions resolve to the checked Graph IR",
            )
        )
    corpus_digest: str | None = None
    if resolved is None:
        checks.append(
            PreflightCheck(
                "Baseline corpus", False, "the gold fixture must resolve before corpus validation"
            )
        )
    else:
        try:
            documents = load_baseline_documents(
                project_root / "fixtures" / "evaluation" / "corpus.json"
            )
            validate_baseline_documents(documents, resolved)
            corpus_digest = baseline_corpus_digest(documents)
        except ValueError as error:
            checks.append(PreflightCheck("Baseline corpus", False, str(error)))
        else:
            checks.append(
                PreflightCheck(
                    "Baseline corpus",
                    True,
                    "every document and evidence span resolves to the checked Graph IR and source",
                )
            )
    if resolved is None:
        target = None
        checks.append(
            PreflightCheck(
                "Configured evaluation target",
                False,
                "the gold fixture must resolve before target validation",
            )
        )
    else:
        try:
            target = configured_evaluation_target(resolved, environment)
        except ValueError as error:
            target = None
            checks.append(PreflightCheck("Configured evaluation target", False, str(error)))
        else:
            checks.append(
                PreflightCheck(
                    "Configured evaluation target",
                    True,
                    "database, repository ID, current collection, and root match the gold target",
                )
            )
    checks.extend(
        _agent_manifest_checks(
            project_root,
            resolved=resolved,
            target=target,
            baseline_corpus_digest=corpus_digest,
        )
    )
    expected_revision = resolved.manifest.revision_id if resolved else None
    health_ready = bool(
        expected_revision
        and health
        and health.get("state") == "ready"
        and health.get("revision_verified") is True
        and health.get("revision_id") == expected_revision
        and health.get("collection") == "current"
        and target is not None
        and health.get("database") == target.database
        and health.get("repository_id") == target.repository_id
        and health.get("repository_root_fingerprint") == target.repository_root_fingerprint
    )
    checks.append(
        PreflightCheck(
            "Verified live revision",
            health_ready,
            f"service reports the gold revision {expected_revision} in current"
            if health_ready
            else (
                "service health is absent or does not report the exact gold revision "
                f"{expected_revision} in the current collection"
            ),
        )
    )
    if results_path is None:
        checks.append(
            PreflightCheck(
                "Live A/B/C artifacts",
                False,
                "pass --results with a completed live JSONL before comparative claims",
            )
        )
    else:
        try:
            if resolved is None or target is None or corpus_digest is None:
                raise ValueError(
                    "gold, baseline corpus, and configured evaluation target must validate "
                    "before artifacts"
                )
            records = read_jsonl(results_path)
            expected = tuple(question.question.id for question in resolved.questions)
            _require_recomputed_metrics(records, resolved)
            report = completeness(
                records,
                expected_question_ids=expected,
                expected_gold_digest=resolved.digest,
                expected_baseline_corpus_digest=corpus_digest,
                expected_target=target,
            )
        except ValueError as error:
            checks.append(PreflightCheck("Live A/B/C artifacts", False, str(error)))
        else:
            checks.append(
                PreflightCheck(
                    "Live A/B/C artifacts",
                    report.comparative_claims_allowed,
                    "complete live A/B/C records with one gold digest"
                    if report.comparative_claims_allowed
                    else "records are incomplete, offline, non-ready, or use mixed gold",
                )
            )
    return tuple(checks)


def _agent_manifest_checks(
    project_root: Path,
    *,
    resolved: ResolvedGold | None,
    target: EvaluationTarget | None,
    baseline_corpus_digest: str | None,
) -> tuple[PreflightCheck, ...]:
    checks: list[PreflightCheck] = []
    for filename in ("codex.json", "claude-code.json"):
        expected_agent = Path(filename).stem
        path = project_root / "evaluation" / "manifests" / filename
        try:
            manifest = AgentRunManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            checks.append(PreflightCheck(f"Agent manifest {filename}", False, str(error)))
            continue
        if resolved is None or target is None or baseline_corpus_digest is None:
            checks.append(
                PreflightCheck(
                    f"Agent manifest {filename}",
                    False,
                    "gold, baseline corpus, and configured target must validate before "
                    "agent results",
                )
            )
            continue
        if manifest.results_path is None or manifest.retrieval_results_path is None:
            checks.append(
                PreflightCheck(
                    f"Agent manifest {filename}",
                    False,
                    "template has no live retrieval/results_path and does not prove an agent run",
                )
            )
            continue
        try:
            if manifest.agent != expected_agent:
                raise ValueError("agent manifest identity does not match its filename")
            if not is_concrete_live_run_id(manifest.run_id):
                raise ValueError("completed agent manifests require a concrete live run_id")
            if manifest.model.startswith("record-exact-"):
                raise ValueError("completed agent manifests require the exact model version")
            root = project_root.resolve()
            retrieval_path = (project_root / manifest.retrieval_results_path).resolve()
            outcome_path = (project_root / manifest.results_path).resolve()
            retrieval_path.relative_to(root)
            outcome_path.relative_to(root)
            records = read_jsonl(retrieval_path)
            outcomes = read_agent_outcomes(outcome_path)
            _require_recomputed_metrics(records, resolved)
            expected_questions = tuple(question.question.id for question in resolved.questions)
            if set(manifest.question_ids) != set(expected_questions):
                raise ValueError("agent manifest question IDs do not equal the current gold set")
            if any(record.observation.run_id != manifest.run_id for record in records):
                raise ValueError("agent retrieval run_id does not match its manifest")
            report = completeness(
                records,
                expected_question_ids=manifest.question_ids,
                expected_gold_digest=resolved.digest,
                expected_baseline_corpus_digest=baseline_corpus_digest,
                expected_target=target,
            )
            if not report.comparative_claims_allowed:
                raise ValueError("agent retrieval is not a complete bound live A/B/C run")
            expected_keys = {
                (question_id, condition)
                for question_id in manifest.question_ids
                for condition in manifest.conditions
            }
            retrieval_by_key = {
                (record.observation.question_id, record.observation.condition): record
                for record in records
            }
            outcome_keys = [(record.question_id, record.condition) for record in outcomes]
            if len(outcome_keys) != len(set(outcome_keys)) or set(outcome_keys) != expected_keys:
                raise ValueError("agent outcomes must cover each manifest question/condition once")
            digest = artifact_digest(retrieval_path)
            if any(
                outcome.agent != manifest.agent
                or outcome.model != manifest.model
                or outcome.run_id != manifest.run_id
                or outcome.retrieval_artifact_digest != digest
                for outcome in outcomes
            ):
                raise ValueError("agent outcomes do not bind their manifest and retrieval artifact")
            if any(
                outcome.context_characters_returned
                != retrieval_by_key[(outcome.question_id, outcome.condition)].metrics.context_chars
                for outcome in outcomes
            ):
                raise ValueError("agent outcome context counts do not match retrieval records")
        except (OSError, ValueError) as error:
            checks.append(PreflightCheck(f"Agent manifest {filename}", False, str(error)))
        else:
            checks.append(
                PreflightCheck(
                    f"Agent manifest {filename}",
                    manifest.live_hydradb_required,
                    "observable-only agent manifest has complete bound live results",
                )
            )
    return tuple(checks)


def _require_recomputed_metrics(
    records: tuple[EvaluationRecord, ...], resolved: ResolvedGold
) -> None:
    questions = {question.question.id: question for question in resolved.questions}
    for record in records:
        question = questions.get(record.observation.question_id)
        if question is None:
            raise ValueError("artifact references a question outside current gold")
        if score_observation(question, record.observation) != record.metrics:
            raise ValueError("artifact metrics do not recompute from current gold")


def fetch_health(service_url: str) -> Mapping[str, Any] | None:
    try:
        with urllib.request.urlopen(f"{service_url.rstrip('/')}/health", timeout=3) as response:
            payload = json.loads(response.read())
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check live Hack Hydra demo evidence")
    parser.add_argument("--service-url", default="http://127.0.0.1:8765")
    parser.add_argument("--results", type=Path)
    args = parser.parse_args(argv)
    project_root = Path(__file__).resolve().parents[1]
    checks = run_preflight(
        project_root=project_root,
        environment=os.environ,
        health=fetch_health(args.service_url),
        results_path=args.results,
    )
    for check in checks:
        marker = "PASS" if check.passed else "FAIL"
        print(f"[{marker}] {check.name}: {check.detail}")
    return 0 if all(check.passed for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
