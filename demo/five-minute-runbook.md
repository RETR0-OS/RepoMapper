# Five-minute live demo runbook

This runbook is a timed script, not evidence that a live run has happened. Run
`python -m demo.preflight --results <live-results.jsonl>` first. Do not show an
improvement claim unless every preflight check passes.

Generate the live evaluation artifacts with:

`python -m evaluation --live --output <artifact-directory> --run-id <run-id>`

Before starting, restore `fixtures/evaluation/repo` to its checked state, configure
`HYDRA_REPOSITORY_ROOT` to that exact directory, and index it into the `current`
collection as revision `eval-rev-1`. Generate the live evaluation artifacts and
run preflight before making the demo edit. The gold manifest does not apply to a
different repository root or revision.

Complete both files in `evaluation/manifests/` with the exact live run ID, model
version, retrieval JSONL path, and observable agent-outcome JSONL path. The
checked files are intentionally incomplete templates; do not fabricate results
to make preflight pass.

## 0:00–0:35 — Establish the truth boundary

- Show `/health` with a concrete verified HydraDB revision.
- State that HydraDB is the retrieval substrate and failures do not fall back to local search.
- Show the ingestion status badge. Do not expose credential values.

## 0:35–1:35 — Ask a relational question

- Ask the authorization-flow gold question in Trace mode.
- Show the returned HydraDB path and its `origin: byog` marker.
- Open one exact edge and its line-addressable source evidence.

## 1:35–2:20 — Show the shared human and agent context

- Run the same question through `repository_query` over MCP.
- Use the mounted `http://127.0.0.1:8765/mcp` endpoint so Observe and MCP share one event bus.
- Show only observable tool calls and returned context.
- Switch to Observe and replay the returned, selected, and evidence-opened states.

## 2:20–3:15 — Make and index one bounded edit

- Save and review the current authorization flow as the shared System Lens.
- Capture the `eval-rev-1` before checkpoint.
- In `eval_app/api.py`, replace `if not authorize(user):` with `if user != "admin":`.
- Run the fixture test, capture/index `eval-rev-2`, and keep the earlier live evaluation
  artifacts unchanged as the revision-1 measurement.
- Show indexing as in progress, then a new verified HydraDB revision.
- If indexing fails or remains indeterminate, stop and state that the demo is degraded.

## 3:15–4:10 — Compare and Preserve

- Open Compare and show one grounded node or relation delta.
- Open the shared System Lens and show its deterministic drift classification.
- Accept drift only after reviewing the new exact path.

## 4:10–5:00 — Show evaluation evidence

- Show raw JSONL, the gold manifest, and the CSV/Markdown count table.
- Confirm B and C request plans and recorded HydraDB request bodies differ only in
  `graph_context`.
- Show exact and inferred relation counts separately, with denominators.
- Make no percentage or “better” claim unless preflight reports a complete live A/B/C set.

## Rehearsal fallback

Offline fixtures may rehearse screen order only. Label them `OFFLINE REHEARSAL`.
They may not support live HydraDB, performance, or comparative retrieval claims.
