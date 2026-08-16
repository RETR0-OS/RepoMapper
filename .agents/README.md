# Project Context

## Read this first

This repository is a Track B hackathon project about code graphs for IDE assistants.

The product is a VS Code extension for **repository observability in the age of agentic coding**. It gives programmers a living, navigable view of their repository and gives coding agents access to the same underlying graph.

The working promise is:

> **See your code like your agent. Watch where the agent goes. Understand what it changes.**

## The central rule

> **HydraDB is the product's knowledge and retrieval substrate, not an optional integration.**

HydraDB must store the graph-backed repository knowledge, return the graph paths used by human and agent experiences, and power semantic plus relational retrieval. The local analyzer may extract deterministic facts. The VS Code extension may render the current result. Neither may become a competing graph database or retrieval system.

If a proposed feature works just as well after replacing HydraDB with a local JSON graph, it is not yet using HydraDB deeply enough.

## What to read

Read these documents before making architectural or product changes:

1. [product.md](product.md) — the problem, promise, users, and product modes.
2. [hydradb.md](hydradb.md) — verified HydraDB capabilities, limits, and product mapping.
3. [architecture.md](architecture.md) — component boundaries and data flow.
4. [graph-model.md](graph-model.md) — nodes, relations, evidence, and revisions.
5. [vscode-experience.md](vscode-experience.md) — the human-facing extension.
6. [agent-interface.md](agent-interface.md) — the agent-facing tools and path events.
7. [ingestion-and-sync.md](ingestion-and-sync.md) — deterministic analysis and HydraDB synchronization.
8. [evolution.md](evolution.md) — graph changes and living system lenses.
9. [evaluation.md](evaluation.md) — proof that graph-backed HydraDB retrieval improves results.
10. [roadmap.md](roadmap.md) — build order and acceptance criteria.
11. [decisions.md](decisions.md) — decisions already made.
12. [open-questions.md](open-questions.md) — unresolved choices and current recommendations.

## Product truths

- Index broadly, but never render the entire symbol graph at once.
- Use several focused graph views instead of one universal hairball.
- The repository map contains concrete repository entities only. Do not invent abstract concept nodes.
- Repository structure is presented in 2D at package, file, and symbol depth. Do not build a 3D graph.
- Every edge presented as exact is deterministic. Inferred relations are separate and hidden by default.
- Graph layout is user-controlled presentation state. Position, distance, and clustering do not imply architecture or confidence.
- Selecting a node opens its source range. Selecting an edge opens the source range that proves the relation.
- Repository-level flow and function-local control flow are different products. The MVP prioritizes repository-level flow.
- Every structural relation must include evidence and provenance.
- Exact and inferred relations must never look identical.
- The human and the agent use the same HydraDB-backed repository model through different interfaces.
- “Agent path” means an observable HydraDB-returned path or an explicit agent tool sequence. It does not mean hidden model reasoning.
- The product must remain useful on repositories containing several supported languages.
- HydraDB failures must be visible. Do not silently fall back to a local retrieval engine.

## Working style

- Write in plain, direct language.
- Prefer evidence over claims.
- Keep APIs behind adapters because HydraDB documentation currently includes both current API v2 names and deprecated aliases.
- Do not mention or copy branding from unrelated donor projects.
- Preserve user changes and do not overwrite unrelated work.
- Record material decisions in [decisions.md](decisions.md).
- Record new HydraDB findings in [research/sources.md](research/sources.md) with a verification date.

## Current status

This is still primarily a product and architecture workspace, not an implementation repository. A standalone interactive UI mockup has established the current human-facing direction:

- A VS Code-like shell with seven modes: Repository, Explore, Trace, Observe, Compare, Preserve, and Contrast.
- A deterministic 2D repository map with package, file, and symbol depth.
- Movable nodes, panning, zooming, relation filters, and resettable layouts.
- Direct node and edge navigation to source evidence.
- An evidence inspector that explains why an item exists, how it was derived, its stable ID, and its HydraDB revision.

The mockup validates the interaction contract, not the implementation. HydraDB API behavior, source granularity, exact expansion, synchronization, and performance still require the capability spike in [roadmap.md](roadmap.md).
