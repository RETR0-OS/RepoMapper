# Evaluation and demo evidence

[Documentation home](README.md) · [Getting started](getting-started.md) · [Trust and safety](trust-and-safety.md) · [Known limits](limitations.md)

This project includes an evaluation harness because a graph UI is not proof that graph-backed retrieval helps. The harness compares three retrieval conditions, preserves the raw observations, and refuses comparative claims when the inputs are incomplete or mismatched.

## What the evaluation asks

The central question is:

> Does HydraDB with deterministic repository relations return more useful, grounded context than retrieval without graph context?

The checked evaluation repository contains a small authorization flow and tests. Each question has a hand-checked set of required nodes, relations, and source spans.

## The three conditions

| Condition | Retrieval path | Purpose |
|---|---|---|
| A | Deterministic TF-IDF over checked source-derived documents | A simple non-Hydra baseline used only by the evaluation package |
| B | HydraDB hybrid query with `graph_context=false` | Measures HydraDB retrieval without graph expansion |
| C | The same HydraDB query with `graph_context=true` | Measures the contribution of grounded BYOG paths |

B and C must differ only in `graph_context`. The harness records both the planned request and, for live runs, the actual HydraDB request body.

The TF-IDF baseline is not part of the product service and is never used as a fallback. Its corpus is validated against the checked Graph IR and source spans so it cannot be quietly tuned with unrelated text.

## What is measured

For each question and condition, the report includes raw counts and denominators for:

- required node hits;
- useful returned nodes;
- exact relation hits;
- inferred relation hits;
- evidence-span hits;
- unsupported returned relations;
- returned context characters and approximate tokens;
- request latency.

Exact and inferred relations are scored separately. Live condition C only receives graph credit for paths linked to the expected repository and revision, with `origin: byog` and valid evidence. Live condition B is rejected if it leaks graph paths.

## Offline rehearsal

The offline command checks the pipeline without contacting HydraDB:

```powershell
python -m evaluation `
  --offline `
  --output .\artifacts\offline `
  --run-id offline-rehearsal
```

It writes:

- `raw.jsonl` — one versioned observation and metric record per question and condition;
- `summary.csv` — machine-readable count columns;
- `summary.md` — a readable table and claim-guard result.

Offline output is always labeled as a rehearsal. It cannot enable comparative claims, even when all fixture checks pass.

## Live evaluation

Before a live run:

1. Set the HydraDB and repository environment variables described in [Configuration](configuration.md).
2. Point `HYDRA_REPOSITORY_ROOT` at `fixtures/evaluation/repo`.
3. Set `HYDRA_REPOSITORY_ID=evaluation-fixture`.
4. Index the fixture repository into the `current` collection at revision `eval-rev-1`.
5. Start the loopback service and confirm `/health` reports that exact database, repository, root fingerprint, collection, and revision.

Then run:

```powershell
python -m evaluation `
  --live `
  --output .\artifacts\live `
  --run-id live-2026-08-14-01
```

A live run ID must be explicit and must not contain rehearsal or placeholder wording. Missing credentials, a different root, a different repository ID, or a non-`current` collection fails before results are written.

## Codex and Claude Code outcomes

The files under `evaluation/manifests/` are templates, not proof that an agent run happened. For a real run, each manifest must contain:

- the exact agent and model version;
- the live run ID;
- the retrieval JSONL path;
- the agent-outcome JSONL path;
- all gold question IDs and A/B/C conditions.

Each `hack-hydra.agent-outcome.v1` record contains observable facts only: task completion, files changed, unnecessary files touched, repository and HydraDB tool calls, context returned, tests, outcome, and rework count. It is bound to the SHA-256 digest of the retrieval artifact. Hidden reasoning and chain-of-thought are not recorded.

The checked manifests intentionally contain null result paths. This makes preflight fail until real agent artifacts exist.

## Preflight

Use the module form from the repository root:

```powershell
python -m demo.preflight `
  --service-url http://127.0.0.1:8765 `
  --results .\artifacts\live\raw.jsonl
```

Preflight checks:

- credentials are present;
- the gold Graph IR and source-derived baseline still validate;
- the configured database, repository ID, collection, and canonical root match the gold target;
- the running service reports the same identity and verified revision;
- every A/B/C record belongs to one live run;
- stored metrics recompute from the raw observations;
- B and C request bodies are properly paired;
- Codex and Claude manifests point to complete, schema-valid, artifact-bound outcomes.

If any check fails, do not claim that graph-enabled retrieval is better.

## Five-minute demo

The timed script is in [the live demo runbook](../demo/five-minute-runbook.md). It covers:

1. establishing the HydraDB truth boundary;
2. asking a relational question in Trace;
3. observing the same MCP-backed context;
4. making and indexing a bounded edit;
5. reviewing Compare and Preserve;
6. presenting raw evaluation evidence.

Treat the runbook as a sequence, not evidence. The evidence is the live service state, raw JSONL, checked gold set, and completed agent outcomes.

## Interpreting results

Prefer statements with counts and denominators, for example:

> Condition C returned 3 of 4 required exact relations, compared with 1 of 4 in condition B, on 2 checked questions.

Avoid broad percentage claims when the question set is small. Always make the raw observations and scoring inputs available with the summary.

