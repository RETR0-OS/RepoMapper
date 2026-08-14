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

from evaluation.gold import load_and_resolve_gold
from evaluation.models import AgentRunManifest
from evaluation.reporting import completeness, read_jsonl


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
    checks.extend(_agent_manifest_checks(project_root))
    expected_revision = resolved.manifest.revision_id if resolved else None
    health_ready = bool(
        expected_revision
        and health
        and health.get("state") == "ready"
        and health.get("revision_verified") is True
        and health.get("revision_id") == expected_revision
        and health.get("collection") == "current"
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
            records = read_jsonl(results_path)
            expected = (
                tuple(question.question.id for question in resolved.questions) if resolved else ()
            )
            report = completeness(records, expected_question_ids=expected)
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


def _agent_manifest_checks(project_root: Path) -> tuple[PreflightCheck, ...]:
    checks: list[PreflightCheck] = []
    for filename in ("codex.json", "claude-code.json"):
        path = project_root / "evaluation" / "manifests" / filename
        try:
            manifest = AgentRunManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            checks.append(PreflightCheck(f"Agent manifest {filename}", False, str(error)))
        else:
            checks.append(
                PreflightCheck(
                    f"Agent manifest {filename}",
                    manifest.live_hydradb_required,
                    "observable-only live run template is valid",
                )
            )
    return tuple(checks)


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
