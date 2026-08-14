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
