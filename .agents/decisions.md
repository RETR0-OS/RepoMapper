# Decisions

This file records current product and architecture decisions. Provisional decisions may change after evidence.

## D-001 — Track B

Status: accepted.

The project targets Track B: code graphs for IDE assistants.

## D-002 — Independent product

Status: accepted.

The product is independent and intended for coding agents and repositories generally. Do not describe it as a feature of another project.

## D-003 — Product category

Status: accepted.

Position the product as **repository observability for agentic coding**.

## D-004 — Product promise

Status: accepted.

Use **“See your code like your agent”** as the central promise. It means the extension can display the same HydraDB-returned paths and chunks delivered to the agent.

## D-005 — HydraDB centrality

Status: accepted and non-negotiable.

HydraDB is the shared knowledge, graph, and retrieval substrate. No production local graph or vector database may replace its role.

## D-006 — Deterministic facts through BYOG

Status: accepted.

Parser-known code relations are supplied to HydraDB through BYOG. Do not use LLM extraction for facts already known exactly.

## D-007 — Human and agent share one model

Status: accepted.

The VS Code extension and MCP server query the same HydraDB-backed repository state.

## D-008 — VS Code first

Status: accepted.

The first human interface is a VS Code extension with native views plus a webview graph canvas.

## D-009 — Codex and Claude Code first

Status: accepted.

Both use the same custom MCP contracts. Model-specific behavior is kept to configuration adapters.

## D-010 — Broad parser coverage

Status: accepted.

Index every language supported by verified parsers. Publish different relationship depths honestly rather than restricting all ingestion to a few languages.

## D-011 — Focused graph slices

Status: accepted.

Everything useful may be indexed, but the UI never renders the whole symbol graph by default. Use semantic zoom and task-specific views.

## D-012 — Agent path honesty

Status: accepted.

Animate HydraDB-returned paths and explicit MCP tool events. Do not claim visibility into hidden model reasoning or every internal HydraDB search step.

## D-013 — Repository-level flow first

Status: accepted.

Prioritize cross-file calls, routing, tests, types, configuration, and runtime wiring. Generate function-local control flow only on demand and outside the first critical path.

## D-014 — Symbol-level HydraDB sources

Status: provisional.

Prefer one source per symbol or logical configuration block, plus file/module summaries. Validate against file-level ingestion for quality, indexing time, and operational limits.

## D-015 — Evolution is core

Status: accepted.

The MVP includes one before/after agent-task graph comparison. Full repository history is not required.

## D-016 — Living System Lenses

Status: accepted with narrow MVP scope.

Support at least one saved, grounded system flow whose drift can be checked after re-indexing.

## D-017 — Python service and TypeScript extension

Status: provisional.

Use Python for analysis, HydraDB integration, query orchestration, events, and MCP. Use TypeScript for VS Code and the graph webview. Revisit only if capability or packaging evidence demands it.

## D-018 — API v2 behind adapter

Status: accepted.

Target HydraDB API v2 and isolate SDK/API naming in one adapter. Do not spread deprecated alias names through the codebase.

## D-019 — No silent local fallback

Status: accepted.

If HydraDB is unavailable, graph retrieval and related agent tools show a degraded state. The analyzer does not silently become the product query engine.

## D-020 — Deterministic 2D repository structure map

Status: accepted.

The finished extension includes an explicit 2D repository structure map. It contains only concrete repository entities such as directories, files, symbols, tests, configuration keys, schemas, and infrastructure resources. It must not create abstract concept nodes.

Every exact structural edge is produced deterministically by a parser, compiler, framework adapter, or explicit source resolver. Inferred relations remain separate and hidden by default. The full-repository view expands progressively through package, file, and symbol levels instead of rendering every symbol label at once.

Use two complementary interaction patterns:

- A global structural graph for navigating real packages, files, and aggregated exact relations.
- A local graph centered on one selected entity, with labeled relations and controlled expansion.

Do not include a 3D graph. Spatial presentation must not imply certainty, architecture, or runtime behavior that cannot be derived from repository evidence.

## D-021 — Graph interaction is source-first

Status: accepted.

Repository and focused graph nodes can be rearranged for readability, but their positions do not change graph meaning. Edges stay attached while nodes move.

Selecting a concrete node opens its real source file at the stored line range. Selecting an exact edge opens the source range that proves the relation. The inspector must show why the item exists, which deterministic resolver produced it, its stable ID, and the HydraDB revision. Layout is a user-controlled view; source evidence is the authority.

## D-022 — Six-mode VS Code shell

Status: accepted.

The primary editor toolbar uses six modes:

- **Repository** for package, file, and symbol orientation.
- **Explore** for a bounded neighborhood around one entity.
- **Trace** for a HydraDB-returned system path.
- **Observe** for explicit agent queries, returned context, opened evidence, and edits.
- **Compare** for verified before/after graph changes.
- **Preserve** for saved System Lenses and drift review.

Observe is the UI name for Agent View. Compare is the UI name for Change Map. Preserve is the UI surface for Living System Lenses.

## D-023 — Higher-level edges are deterministic aggregates

Status: accepted.

Package- and file-level views may combine many exact lower-level relations into one labeled edge. An aggregate must retain its predicate, exact relation count, contributing edge IDs, evidence IDs, and revision. Selecting it opens the contributing facts.

Aggregation is presentation compression. It must not create a new semantic or inferred architectural claim.

## D-024 — Local service boundary

Status: accepted for the MVP.

Run the Python HTTP service on loopback and the repository MCP server over stdio. The TypeScript VS Code extension talks only to the loopback service. HydraDB credentials stay in the Python process and are never sent to the webview.

The deterministic analyzer may build upload payloads and bounded diff artifacts, but product retrieval remains HydraDB-only. When credentials, indexing, or a query are unavailable, the service returns an explicit empty degraded result. The interactive UI fixture is labeled as a preview and is never returned as repository truth.

## D-025 — Exact relation evidence envelope

Status: accepted.

Serialize every deterministic BYOG relation context as the bounded, versioned `hack-hydra.relation-evidence.v1` JSON envelope. It carries the readable summary, stable edge ID, extractor identity, and original exact evidence record. A returned relation is exact only when its BYOG origin and evidence envelope both validate. Missing, malformed, or automatically extracted relation context must be downgraded or omitted without inventing a source range.

## D-026 — Confirmed manual indexing

Status: accepted for the MVP.

Index only the service-configured repository root. Require an explicit revision ID, show the discovered files and complete source-card upload scope, and require confirmation before contacting HydraDB. A manual `Index now` flow is the MVP editing loop; automatic file watching remains future work.

Stable source replacement in the `current` collection is not transactional. If an upsert or deletion fails after HydraDB accepts part of a candidate, report the current collection as indeterminate. The prior revision is only the last verified marker, not a promise that every prior source is still queryable. Immutable revision collections remain provisional until live collection semantics are proven.
