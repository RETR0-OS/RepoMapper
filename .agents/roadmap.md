# Build Roadmap

## Ordering principle

Prove HydraDB's critical path before building the polished graph canvas. A beautiful visualization over invented fixtures does not validate the product.

## Phase 0: HydraDB capability spike

Deliverables:

- HydraDB v2 adapter using environment-based credentials.
- One database and explicit metadata schema.
- Two or more symbol cards ingested as Knowledge.
- Deterministic BYOG call/type/test relations.
- Ingestion status polling.
- Hybrid thinking query with graph context.
- Captured `query_paths`, `chunk_relations`, chunks, sources, and additional context.
- Re-ingest replacement test.
- Deletion test.
- Metadata filter test.
- Collection and Memory experiment.
- Relation-inspection feasibility result.

Exit criteria:

- At least one returned relation is marked `origin: "byog"`.
- A conceptual query returns an accurate path grounded in code sources.
- Limits and actual SDK request shapes are recorded in tests and research notes.

## Phase 1: deterministic repository model

Deliverables:

- File discovery and ignore behavior.
- Versioned Graph IR.
- Adapters for every verified parser available to the project.
- Stable node and edge identifiers.
- Exact/inferred provenance.
- Symbol and file summary cards.
- Canonical relation ownership.
- Multilingual fixtures.

Exit criteria:

- Capability matrix is measured.
- No duplicate owned relations.
- Every displayed exact edge opens valid source evidence.

## Phase 2: reliable HydraDB synchronization

Deliverables:

- Batch source ingestion.
- BYOG payload generation.
- Source add/replace/delete lifecycle.
- Revision readiness state.
- Incremental file change handling.
- Visible HydraDB indexing status.
- Secret exclusion and ingestion preview.

Exit criteria:

- Add, edit, delete, and rename fixtures leave no stale current edges.
- Failed indexing preserves the prior verified revision.
- No local retrieval database exists.

## Phase 3: agent retrieval interface

Deliverables:

- Custom MCP server.
- `repository_query`.
- `focus_symbol` with documented non-exhaustive behavior if necessary.
- `trace_flow`.
- `explain_relationship`.
- Stable product response schema.
- Token/node budgets.
- Codex and Claude Code configurations.

Exit criteria:

- Both agents answer the anchor repository questions using HydraDB-backed tools.
- Returned context includes paths and exact source evidence.
- Tool events contain session and view IDs.

## Phase 4: VS Code comprehension experience

Deliverables:

- Activity Bar container and Tree Views.
- Interactive graph webview.
- Current-symbol focus.
- HydraDB question/trace view.
- Evidence inspector.
- Source navigation.
- HydraDB status and result badges.
- Accessible textual path list.

Exit criteria:

- A user can move from a conceptual question to an exact code range through a HydraDB path.
- Default views remain readable on the demo repository.

## Phase 5: Agent View

Deliverables:

- Session event transport.
- Live MCP query events.
- HydraDB returned-path animation.
- Context-selected and evidence-opened states.
- Workspace edit overlay.
- Timeline replay.

Exit criteria:

- The UI accurately distinguishes returned, selected, opened, and edited states.
- No UI text claims hidden reasoning or internal traversal access.

## Phase 6: evolution and System Lenses

Deliverables:

- Before/after task checkpoints.
- Deterministic Graph IR diff.
- HydraDB change-event Knowledge.
- Change Map with stable layout.
- One saved System Lens.
- Lens drift classification.
- `compare_repository_graph` and `open_system_lens` tools.

Exit criteria:

- One agent edit produces an understandable structural delta.
- The saved lens truthfully reports whether its path changed.

## Phase 7: evaluation and demo hardening

Deliverables:

- Gold question set.
- Three-condition ablation.
- Codex and Claude Code runs.
- Retrieval and token metrics.
- Small human comprehension exercise if possible.
- Scripted five-minute demo.
- Offline response fixtures only for automated tests and demo rehearsal.

Exit criteria:

- Live demo uses real HydraDB.
- Graph-enabled HydraDB shows measurable value on relational questions.
- Every major judge-facing claim has evidence.

## Scope cuts if time is short

Cut in this order:

1. Complete Git history.
2. Team sharing for System Lenses.
3. Function-local control-flow graphs.
4. Automatic structural warnings beyond one or two examples.
5. Exact live node expansion if the HydraDB API does not expose it.
6. Multiple graph layout families.

Do not cut:

- Real HydraDB BYOG ingestion.
- HydraDB graph-context querying.
- Exact evidence.
- Human graph path view.
- Agent MCP access.
- One before/after graph change.
- HydraDB ablation.

## Key sequencing risk

Do not spend most of the hackathon perfecting parser coverage before proving that HydraDB returns paths suitable for the agent and visualization. Phase 0 exists to prevent that failure.
