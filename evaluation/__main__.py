"""Generate explicitly offline rehearsal artifacts from checked fixtures."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .baseline import load_baseline_documents
from .gold import load_and_resolve_gold
from .models import RunMode
from .reporting import summarize_records, write_jsonl
from .runner import AblationRunner, FixtureHydraTransport, LiveHydraTransport


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate offline evaluation rehearsal artifacts; never live claims"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true", help="use checked rehearsal fixtures")
    mode.add_argument("--live", action="store_true", help="query credentialed HydraDB")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", default="offline-rehearsal")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    fixtures = root / "fixtures" / "evaluation"
    gold = load_and_resolve_gold(fixtures / "gold.json")
    if args.live:
        try:
            transport = LiveHydraTransport.from_environment(
                repository_id=gold.manifest.repository_id,
                revision_id=gold.manifest.revision_id,
            )
        except ValueError as error:
            parser.error(str(error))
        run_mode = RunMode.LIVE
    else:
        transport = FixtureHydraTransport(
            without_graph=_load_json(fixtures / "hydradb-without-graph.json"),
            with_graph=_load_json(fixtures / "hydradb-with-graph.json"),
        )
        run_mode = RunMode.OFFLINE
    runner = AblationRunner(
        mode=run_mode,
        hydra_transport=transport,
        repository_id=gold.manifest.repository_id,
        revision_id=gold.manifest.revision_id,
    )
    records = runner.run_suite(
        run_id=args.run_id,
        gold=gold,
        baseline_documents=load_baseline_documents(fixtures / "corpus.json"),
    )
    output = args.output.resolve()
    raw_path = output / "raw.jsonl"
    write_jsonl(raw_path, records)
    report = summarize_records(
        records,
        expected_question_ids=tuple(question.question.id for question in gold.questions),
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
