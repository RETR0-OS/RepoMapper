"""Generate explicitly offline rehearsal artifacts from checked fixtures."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

from .baseline import baseline_corpus_digest, load_baseline_documents
from .gold import load_and_resolve_gold
from .models import RunMode, is_concrete_live_run_id
from .reporting import summarize_records, write_jsonl
from .runner import (
    AblationRunner,
    FixtureHydraTransport,
    LiveHydraTransport,
    configured_evaluation_target,
    fixture_evaluation_target,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate offline evaluation rehearsal artifacts; never live claims"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true", help="use checked rehearsal fixtures")
    mode.add_argument("--live", action="store_true", help="query credentialed HydraDB")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    if args.live and (not args.run_id or not is_concrete_live_run_id(args.run_id)):
        parser.error("live evaluation requires an explicit non-rehearsal --run-id")
    run_id = args.run_id or "offline-rehearsal"
    root = Path(__file__).resolve().parents[1]
    fixtures = root / "fixtures" / "evaluation"
    gold = load_and_resolve_gold(fixtures / "gold.json")
    if args.live:
        try:
            target = configured_evaluation_target(gold, os.environ)
            transport = LiveHydraTransport.from_environment(target=target)
        except ValueError as error:
            parser.error(str(error))
        run_mode = RunMode.LIVE
    else:
        target = fixture_evaluation_target(gold)
        transport = FixtureHydraTransport(
            without_graph=_load_json(fixtures / "hydradb-without-graph.json"),
            with_graph=_load_json(fixtures / "hydradb-with-graph.json"),
        )
        run_mode = RunMode.OFFLINE
    runner = AblationRunner(
        mode=run_mode,
        hydra_transport=transport,
        target=target,
    )
    baseline_documents = load_baseline_documents(fixtures / "corpus.json")
    records = runner.run_suite(
        run_id=run_id,
        gold=gold,
        baseline_documents=baseline_documents,
    )
    output = args.output.resolve()
    raw_path = output / "raw.jsonl"
    write_jsonl(raw_path, records)
    report = summarize_records(
        records,
        expected_question_ids=tuple(question.question.id for question in gold.questions),
        expected_gold_digest=gold.digest,
        expected_baseline_corpus_digest=baseline_corpus_digest(baseline_documents),
        expected_target=target,
        csv_path=output / "summary.csv",
        markdown_path=output / "summary.md",
    )
    label = "LIVE" if args.live else "OFFLINE REHEARSAL"
    print(f"Wrote {label} artifacts to {output}")
    print(f"Comparative claims allowed: {report.comparative_claims_allowed}")
    return 0


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"evaluation fixture must be a JSON object: {path}")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
