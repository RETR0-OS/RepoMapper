# Product Definition

## One sentence

A HydraDB-backed VS Code extension that lets programmers explore how a repository works, watch the graph context used by coding agents, and understand how agent edits change the system.

## Category

**Repository observability for agentic coding.**

Traditional observability helps people understand a running system. This product helps people understand a changing codebase: what exists, how it connects, what an agent examined, and what an edit changed.

## Problem

Agentic coding increases the rate at which repositories change. A programmer can approve many edits without rebuilding a reliable mental model of the system. Over time, the programmer loses track of:

- Where important behavior lives.
- Which entrypoint leads to which outcome.
- Which symbols and systems depend on one another.
- Which tests protect an important path.
- How configuration and infrastructure reach runtime code.
- What repository evidence an agent used.
- What structural effect an agent's change had.

Code search helps locate text. Static diagrams become stale. A generic force-directed graph becomes unreadable. The product must connect live source evidence, relational structure, semantic questions, and code evolution.

## Promise

> **See your code like your agent.**

This has a literal meaning. When an agent queries HydraDB, the extension can render the returned `query_paths`, `chunk_relations`, and source chunks. The programmer sees the same repository slice that was given to the agent.

## Target users

### Primary

- Developers supervising coding agents.
- Developers onboarding to an unfamiliar repository.
- Maintainers reviewing a broad agent-generated change.
- Engineers trying to recover a lost mental model of a fast-changing system.

### Secondary

- Technical leads preserving knowledge of critical systems.
- Reviewers checking cross-module impact.
- Teams documenting important flows without maintaining static diagrams by hand.

## Core product modes

### 1. Repository

Orient to the repository through a deterministic 2D structure map. Move progressively between real packages/directories, files, and symbols. Relations are parser- or resolver-derived. The default view shows exact relations only and never invents abstract concept nodes.

### 2. Explore

Select a file, symbol, test, configuration block, or module. See a focused neighborhood with callers, callees, definitions, references, tests, types, and runtime/configuration links.

### 3. Trace

Ask a question such as “How does an API request become a database write?” HydraDB performs hybrid retrieval with graph context. The result is shown as a readable path with exact source evidence.

### 4. Observe

Highlight the paths and source chunks returned to the agent. Show the agent's explicit graph queries, selected context, opened evidence, and observed edits. Allow the user to replay the traversal.

This is the product mode previously described as Agent View. **Observe** is the UI label.

### 5. Compare

Compare the graph before and after an edit. Show added, removed, and changed entities and relations. Explain which saved system flows changed.

This is the product mode previously described as Change Map. **Compare** is the UI label.

### 6. Preserve

Let a developer save an important path such as authentication, checkout, job processing, or deployment. Ground the lens in graph entity IDs and relations. When the code changes, show drift instead of leaving behind a stale diagram.

This is the UI for Living System Lenses. **Preserve** is the UI label.

## Product verbs

The interface should be organized around one orientation mode and five verbs:

- **Repository** — orient to what concretely exists.
- **Explore** what exists.
- **Trace** how it works.
- **Observe** what the agent retrieved.
- **Compare** what changed.
- **Preserve** important system knowledge as a living lens.

## Interaction and explainability contract

The graph is useful only when it leads back to code and explains its own claims.

- Nodes represent concrete repository entities with stable IDs and source locations.
- Edges represent explicit predicates produced by a named parser, compiler service, framework adapter, or deterministic resolver.
- Clicking a node opens the corresponding file and selects its stored line range.
- Clicking an edge opens the source range that proves the relation.
- The evidence inspector shows: why the item is shown, derivation method, exact/inferred quality, stable ID, source range, revision, and HydraDB origin.
- Users may drag nodes, pan, zoom, filter relations, and reset the layout. These actions change presentation only.
- Edge endpoints remain attached while nodes move.
- Inferred relations are visually distinct and hidden by default in the repository map.
- The UI never treats spatial proximity as evidence.

## What makes this different

Many Track B submissions may create a code graph and expose a retrieval tool. This product adds a shared human-agent interface and repository evolution:

- The programmer and agent use the same HydraDB-backed graph.
- HydraDB-returned paths become visible, inspectable UI objects.
- Agent activity is presented as observable evidence, not hidden reasoning.
- Important system maps remain connected to live code.
- Graph diffs explain structural change after agent edits.
- Every edge can be traced to source evidence.

## What the product is not

- It is not a generic diagram editor.
- It is not a full local graph database with HydraDB added for branding.
- It is not a replacement for the VS Code text editor.
- It is not a runtime debugger in the MVP.
- It does not claim perfect static knowledge of reflection, dynamic dispatch, generated code, or runtime state.
- It does not expose private model chain-of-thought.
- It does not render every repository node at once.
- It does not generate abstract “concept” nodes for the repository map.
- It does not use a 3D graph.
- It does not assign architectural meaning to node position or graph distance.

## HydraDB must be visible in the product

**HydraDB should be visible wherever it provides a distinct capability.** This is both honest product design and important hackathon positioning.

The UI should include:

- A “HydraDB indexed” repository status with current collection and revision.
- A HydraDB retrieval mode indicator: hybrid, text, fast, or thinking.
- A result inspector showing HydraDB relevance, relation evidence, and BYOG origin when available.
- A HydraDB Graph Path label on returned path views.
- A HydraDB activity section in Observe.
- A clear degraded state when HydraDB is unavailable or indexing is incomplete.

Do not put the HydraDB name on local-only actions such as opening a file. Use the name when HydraDB actually stores, retrieves, filters, ranks, or traverses the relevant information.

## Five-minute demo story

1. Open an unfamiliar repository in VS Code and orient with the Repository map.
2. Move from package to file to symbol depth and open one concrete symbol from the graph.
3. Ask: “How does an incoming request become a database write?”
4. Show **HydraDB hybrid retrieval and context-graph traversal** returning a multi-hop path.
5. Animate that path and open source evidence for a node and an edge.
6. Give Codex or Claude Code a change request.
7. Open Observe and show each HydraDB result returned to the agent.
8. Let the agent make the change and re-index the changed symbols into HydraDB.
9. Open Compare to review the structural delta.
10. Open Preserve to review and explicitly accept or reject drift in a saved System Lens.

The story is:

> **Understand the system, watch the agent work, and understand what the agent changed.**
