# Agent Interface

## Goal

Give Codex and Claude Code a compact, repository-aware interface over the same HydraDB graph used by the VS Code extension.

The agent should receive useful structural context without loading the entire repository or relying on similarity alone.

## Central rule

> **Every production repository retrieval tool calls HydraDB.**

The MCP layer may shape queries, apply budgets, format responses, and emit observability events. It may not retrieve from a separate local graph or vector store.

## Why a custom MCP layer exists

HydraDB already offers generic MCP plumbing. This product needs repository-specific behavior on top:

- Stable repository entity and revision identifiers.
- Exact source spans and parser evidence.
- Focused graph views with `view_id` values.
- Token and node budgets.
- Agent-session event streaming to the extension.
- Saved System Lenses.
- Graph revision comparison.
- Explicit distinction between exact and inferred code relations.

## Initial tool set

### `repository_query`

Use for conceptual or mixed questions.

Input:

```json
{
  "question": "How does authorization work?",
  "revision": "current",
  "max_results": 8,
  "max_context_chars": 7000,
  "relation_quality": ["exact", "inferred"]
}
```

Behavior:

- Call HydraDB `/query` with `type: "knowledge"`.
- Default to `query_by: "hybrid"`.
- Use `mode: "thinking"` and `graph_context: true` for relational questions.
- Apply revision and repository metadata filters.
- Preserve HydraDB rank order.
- Return chunks, paths, evidence references, and a `view_id`.

### `focus_symbol`

Use when the agent already has a symbol, file, or exact identifier.

Input:

```json
{
  "symbol": "payments.auth.authorize_user",
  "path": "src/payments/auth.py",
  "relations": ["CALLS", "TESTS", "READS_FROM"],
  "direction": "both",
  "depth": 1,
  "budget": 20
}
```

Initial implementation:

- Use a literal text query and/or hybrid query with exact metadata constraints.
- Return only relations present in HydraDB graph context.
- Do not promise exhaustive neighbor enumeration until a supported relation-inspection API is proven.

If the capability spike proves exact relation inspection, the adapter may use it while keeping the public tool contract stable.

### `trace_flow`

Use for multi-hop system behavior.

Input:

```json
{
  "question": "Trace an incoming request to the database write",
  "from": "api.create_order",
  "to": "orders table",
  "max_hops": 8,
  "max_paths": 3
}
```

Behavior:

- Call HydraDB in thinking mode with graph context.
- Treat `max_hops` and `max_paths` as product response budgets, not claims that HydraDB exposes arbitrary shortest-path controls.
- Return HydraDB `query_paths`, ranked chunks, relation evidence, and unresolved gaps.
- Never invent a missing hop merely to create a continuous story.

### `explain_relationship`

Use after a returned edge is selected.

Input:

```json
{
  "view_id": "view_8f23",
  "relationship_id": "rel_42"
}
```

Return:

- Source and target.
- Predicate.
- Exact/inferred quality.
- Plain explanation.
- HydraDB relation context and origin.
- Parser evidence and source span.
- Associated source chunk.

This tool may use the bounded stored result for `view_id`; it does not need to rerun retrieval when the evidence is already in that result.

### `compare_repository_graph`

Use after a change or between two verified checkpoints.

Input:

```json
{
  "before": "revision_before",
  "after": "revision_after",
  "focus": "authentication",
  "max_changes": 50
}
```

Behavior:

- Retrieve the relevant graph-delta Knowledge from HydraDB.
- Return changed entities, relations, affected lenses, and evidence.
- If exact snapshot comparison is required, the deterministic analyzer creates the delta first and stores it in HydraDB; the agent still retrieves the product result through HydraDB.

### `open_system_lens`

Input:

```json
{
  "lens": "Authentication",
  "revision": "current"
}
```

Behavior:

- Retrieve the saved lens from HydraDB Knowledge or Memory.
- Query current repository Knowledge for the grounded path.
- Return current path, drift from the saved baseline, and a `view_id`.

### `pin_context`

Use when the programmer selects a graph node or path for the agent.

Input:

```json
{
  "view_id": "view_8f23",
  "entity_ids": ["entity_a", "entity_b"],
  "instruction": "Treat this path as the intended authorization flow"
}
```

The pinned selection is explicit user context. It must not overwrite structural graph facts.

## Response contract

All retrieval tools should return a stable product envelope:

```json
{
  "session_id": "session_42",
  "view_id": "view_8f23",
  "hydradb": {
    "database": "repo_database",
    "collections": ["current"],
    "query_by": "hybrid",
    "mode": "thinking",
    "graph_context": true
  },
  "revision": "abc123",
  "paths": [],
  "chunks": [],
  "sources": [],
  "additional_context": [],
  "warnings": [],
  "budget": {
    "max_context_chars": 7000,
    "returned_context_chars": 5810
  }
}
```

Keep raw HydraDB response fixtures for integration tests, but do not expose unstable SDK-specific shapes directly to agents or the webview.

## Context formatting

Agent context should be ordered:

1. HydraDB entity paths.
2. Ranked source chunks in HydraDB order.
3. Relations attached to each chunk through `chunk_id_to_group_ids`.
4. Forcefully related additional context.
5. Warnings and uncertainty.

Every chunk includes:

- Source title.
- Repository path and span.
- Revision.
- Relevance score where available.
- Exact/inferred relation labels.

Do not flatten paths into an unexplained list of files.

## Token control

- Set explicit `max_results` on HydraDB queries.
- Cap returned paths and visible relation triplets.
- Cap total context characters before passing to the agent.
- Prefer exact code spans over whole files.
- Include one-hop evidence first, then expand on request.
- Report truncation.
- Measure useful-context recall, not token reduction alone.

A smaller wrong context is not an improvement.

## Agent session events

Event types:

- `session_started`
- `query_started`
- `hydradb_result_returned`
- `path_replay_started`
- `path_hop_replayed`
- `context_selected`
- `evidence_opened`
- `user_context_pinned`
- `workspace_entity_changed`
- `hydradb_sync_started`
- `hydradb_revision_ready`
- `lens_drift_detected`
- `session_completed`

Minimum event fields:

```text
event_id
session_id
timestamp
type
revision_id
view_id, when applicable
entity_ids, when applicable
relationship_ids, when applicable
hydradb_query_metadata, when applicable
```

Events are product telemetry. They are not structural code facts unless explicitly converted into a separate change or activity source.

## Observable versus unobservable

Observable:

- Calls made through our MCP tools.
- HydraDB request parameters safe to display.
- HydraDB-returned paths and chunks.
- Evidence opened through our tools.
- User-pinned context.
- Workspace file changes.

Not reliably observable:

- Files read through arbitrary shell commands.
- Every internal agent decision.
- Hidden chain-of-thought.
- Every internal HydraDB traversal candidate.

Agent View must say “returned,” “selected,” “opened,” or “edited,” not “thought about.”

## Codex and Claude Code

Support both through the same MCP tool schema.

Evaluation should record:

- Tool calls.
- HydraDB queries.
- Returned path IDs.
- Context size.
- Files edited.
- Test results.

Do not build model-specific repository retrieval logic unless the MCP client requires a thin configuration adapter.
