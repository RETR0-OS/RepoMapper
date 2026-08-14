# Open Questions

These questions materially affect scope or architecture. Each includes a working recommendation so implementation can continue while the decision is discussed.

## 1. What is the primary product message?

Options:

- Repository observability: understand how code evolves under agentic development.
- Shared human-agent graph: see the exact repository context the agent receives.

Recommendation: use **repository observability** as the category and **See your code like your agent** as the signature experience. The first explains the lasting problem; the second creates the memorable demo.

## 2. What is the demo climax?

Options:

- Live highlighted Agent View traversal.
- Before/after graph change and System Lens drift.

Recommendation: show Agent View first for immediate visual impact, then use Change Map as the climax because it proves lasting developer value.

## 3. Should agent traversal be forced into small explicit steps?

Forcing step-by-step calls creates a genuinely live animation but may slow the agent and produce unnecessary round trips.

Recommendation: hybrid approach. Animate explicit MCP calls live and replay each HydraDB-returned multi-hop path immediately after its query. Do not force HydraDB's whole path into separate tool calls merely for animation.

## 4. Symbol-level or file-level HydraDB sources?

Recommendation: symbol-level sources plus file summaries. Validate against file-level sources in Phase 0. Decide using retrieval precision, path quality, upload count, indexing latency, and deletion complexity.

## 5. How much history belongs in HydraDB?

Options:

- Full immutable revision collections.
- Current state plus immutable graph-delta sources.
- One before/after checkpoint pair for the hackathon.

Recommendation: one checkpoint pair for the demo, delta sources for ongoing use, and full revision storage only after cost and collection semantics are proven.

## 6. Can exact interactive node expansion use HydraDB directly?

The current public query docs guarantee graph-enriched ranked retrieval, not arbitrary Cypher-style traversal. Some documentation describes relation inspection by source in another API surface.

Recommendation: test supported relation inspection in Phase 0. If unavailable or unsuitable, make expansion a targeted HydraDB query and label it retrieval-based rather than exhaustive.

## 7. How do we observe agent file reads outside our tools?

Codex and Claude Code may read files through shell tools that our MCP server cannot see.

Recommendation: Agent View initially guarantees observation only for our graph tools, returned context, evidence opened through our tool, and workspace edits. Treat broader tool telemetry as an optional adapter, not an MVP promise.

## 8. Who owns System Lenses?

Options:

- Personal only.
- Shared team objects.
- Both.

Recommendation: personal lens first in HydraDB Memory, with one “promote to shared” path into Knowledge if time permits.

## 9. Which repository anchors the demo?

The demo repository needs:

- Several modules.
- A recognizable request or event path.
- Tests.
- Configuration or infrastructure wiring.
- At least two languages if possible.
- A safe, deterministic agent edit that produces a clear graph delta.

Recommendation: choose the repository before Phase 1 ends. Build the gold question set around real flows in it.

## 10. What should the product be called?

Recommendation: defer naming until the central experience works. The category and promise are more important than a premature name.

## 11. How prominently should HydraDB branding appear?

Recommendation: very prominently on actions and results actually powered by HydraDB: indexing, query mode, graph path, relation origin, Memory, and revision readiness. Avoid putting the name on unrelated local editor actions so the emphasis remains credible.

## 12. What is the minimum parser relationship depth for the demo?

Recommendation: require exact containment, imports, calls for the main language, test links, and at least one configuration/runtime edge on the anchor flow. Use every verified parser for broader symbol coverage, but do not delay the core path while chasing perfect parity.

## Decisions needed from the project owner

The highest-value decisions to settle next are:

1. Confirm the product framing: repository observability plus shared Agent View.
2. Choose the demo repository and the exact agent change.
3. Decide whether one personal System Lens is enough for the hackathon or whether shared lenses are required.
4. Confirm whether Agent View should be the first visual moment or whether Change Map should open the demo.
