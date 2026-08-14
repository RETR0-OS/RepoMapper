# Open Questions

These questions materially affect scope or architecture. Each includes a working recommendation so implementation can continue while the decision is discussed.

## Settled since the initial draft

The following are no longer open:

- Product framing is repository observability with “See your code like your agent” as the signature promise.
- The UI uses Repository, Explore, Trace, Observe, Compare, and Preserve.
- Repository visualization is deterministic and 2D, with no abstract concept nodes or 3D mode.
- Node and edge selection is source-first and exposes derivation evidence.
- Package/file edges may be deterministic aggregates only when their contributing facts remain inspectable.

## Resolved: What is the primary product message?

Options:

- Repository observability: understand how code evolves under agentic development.
- Shared human-agent graph: see the exact repository context the agent receives.

Decision: use **repository observability** as the category and **See your code like your agent** as the signature experience. See D-003 and D-004.

## 2. What is the demo climax?

Options:

- Live highlighted Observe traversal.
- Before/after Compare view and System Lens drift.

Recommendation: show Observe first for immediate visual impact, then use Compare as the climax because it proves lasting developer value.

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

Recommendation: Observe initially guarantees observation only for our graph tools, returned context, evidence opened through our tool, and workspace edits. Treat broader tool telemetry as an optional adapter, not an MVP promise.

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

## Resolved: How prominently should HydraDB branding appear?

Decision: show HydraDB prominently on indexing, query mode, graph path, relation origin, Memory, and revision readiness. Do not put the name on unrelated local editor actions.

## Resolved for MVP: What is the minimum parser relationship depth for the demo?

Decision: require exact containment, imports, calls for the main language, test links, and at least one configuration/runtime edge on the anchor flow. Use every verified parser for broader symbol coverage, but do not delay the core path while chasing perfect parity.

## 13. Where should user-adjusted graph layouts be stored?

The layout is useful personal state, but it is not repository truth.

Recommendation: store bounded positions, pan, zoom, and filters in VS Code workspace state keyed by repository, view, depth, and revision. Consider HydraDB Memory only after the local interaction is stable and cross-device value is proven. Never put layout into Graph IR or BYOG structural relations.

## 14. How should large package/file aggregates be paged?

A whole-repository package or file projection may still exceed the webview budget even without symbol labels.

Recommendation: return the highest-count exact aggregates first, report truncation, and let users expand one group or predicate explicitly. Every aggregate must retain contributing edge and evidence IDs. Validate the ordering and budget against the demo repository rather than implying architectural importance from edge count.

## Decisions needed from the project owner

The highest-value decisions to settle next are:

1. Choose the demo repository and the exact agent change.
2. Complete the HydraDB capability spike for exact relation inspection and expansion.
3. Decide symbol-level versus file-level HydraDB source granularity from measurements.
4. Decide whether one personal System Lens is enough for the hackathon or whether shared lenses are required.
5. Decide whether adjusted layouts remain workspace-local or need HydraDB Memory after MVP.
6. Confirm whether Observe should be the first demo visual moment or whether Compare should be the climax.
