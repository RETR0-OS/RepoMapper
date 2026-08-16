# Project layout

[Documentation home](README.md) · [Development guide](development.md) · [Architecture](architecture.md)

The repository separates product documentation, runtime code, shared contracts, fixtures, and evaluation evidence.

## Top-level map

| Path | Purpose |
|---|---|
| `.agents/` | Product direction, internal architecture records, decisions, research, roadmap, and open questions |
| `docs/` | Human-facing end-to-end guides |
| `service/hydra_graph/` | Python analyzer, HydraDB integration, service, MCP, Observe, and evolution logic |
| `extension/` | TypeScript VS Code extension and webview |
| `schemas/` | Versioned JSON schemas shared across process boundaries |
| `tests/` | Python unit, contract, integration, and adversarial tests |
| `fixtures/` | Checked HydraDB responses, Graph IR examples, and evaluation repository |
| `evaluation/` | Isolated A/B/C evaluation runner, scoring, records, and agent manifests |
| `demo/` | Live preflight and timed demo runbook |
| `scripts/` | Repository-wide verification commands |
| `packaging/` | PyInstaller build, staging, signing, checksums, SBOM/license, and provenance helpers |
| `.github/workflows/` | Six-target release matrix |

## Python package

Important modules under `service/hydra_graph/`:

| Module | Responsibility |
|---|---|
| `discovery.py` | Finds supported files while honoring ignore rules and root containment |
| `analyzer.py` | Extracts deterministic Python nodes, relations, and evidence |
| `ids.py` | Creates stable node, edge, source, and view identifiers |
| `models.py` | Defines and validates Graph IR |
| `cards.py` | Converts Graph IR entities into HydraDB Knowledge source cards and BYOG relations |
| `projections.py` | Builds package, file, and symbol projections |
| `hydradb.py` | Owns the direct HydraDB API v2 transport contract |
| `managed.py` | Implements framed private credential/OAuth IPC |
| `security.py` | Signs window challenges and validates project-bound REST tokens |
| `mcp_oauth.py` | Implements dynamic registration, PKCE grants, rotation, and revocation |
| `sync.py` | Coordinates source ingestion, polling, deletion, manifests, and revision state |
| `query.py` | Normalizes raw HydraDB responses into the stable product envelope |
| `views.py` | Builds bounded six-mode product views |
| `events.py` | Stores bounded explicit Observe events and sessions |
| `checkpoints.py` | Stores the bounded before/after Graph IR checkpoint pair |
| `diff.py` | Computes deterministic graph deltas |
| `evolution.py` | Defines change-event, lens, and drift records |
| `evolution_service.py` | Publishes and retrieves change and lens Knowledge |
| `api.py` | Exposes the loopback HTTP API and mounted MCP application |
| `mcp_server.py` | Defines repository-specific MCP tools |
| `__main__.py` | Implements the `hydra-graph` CLI |

## Extension

Important paths under `extension/src/`:

| Path | Responsibility |
|---|---|
| `extension.ts` | Activates the extension and wires commands, views, sessions, and workflows |
| `serviceClient.ts` | Validates and calls the loopback service |
| `managedRuntime.ts` | Verifies, starts, attaches, restarts, and stops the bundled service |
| `managedProtocol.ts` | Defines versioned startup, credential, OAuth, and consent IPC |
| `credentials.ts` | Stores account, database binding, installation, and OAuth records in SecretStorage |
| `projectResolver.ts` / `projectIdentity.ts` | Selects the open project and derives persistent Git/local identity |
| `agentSetup.ts` | Detects Codex/Claude and runs confirmed URL-only registration commands |
| `graphPanel.ts` | Owns webview lifecycle and trusted message handling |
| `sidebar.ts` | Provides native Tree Views and status content |
| `editorFocus.ts` | Converts the active editor position into safe repository focus context |
| `sourceNavigation.ts` | Validates and opens source locations |
| `indexing.ts` | Implements preview, confirmation, indexing, and readiness checks |
| `evolution.ts` | Implements checkpoint, publish, lens save, and drift acceptance workflows |
| `observe.ts` | Normalizes events, enforces revision/cursor integrity, and tracks timeline state |
| `workspaceChanges.ts` | Restricts edit overlays to the proven repository root and visible paths |
| `viewAdapter.ts` | Converts product responses into webview graph data |
| `webview/` | Renders and interacts with the graph, inspector, controls, and textual paths |
| `test/` | TypeScript unit and DOM interaction tests |

## Shared schemas

| Schema | What crosses the boundary |
|---|---|
| `graph-ir.schema.json` | Deterministic repository nodes, edges, spans, evidence, and revisions |
| `query-response.schema.json` | Stable normalized HydraDB query envelope |
| `product-view.schema.json` | Bounded graph view consumed by the extension |
| `agent-event.schema.json` | Explicit observable event records |

## Runtime data

`.hydra-graph/` is runtime bookkeeping, not a local retrieval database. It can contain:

- the opaque persistent repository identity;
- the last verified synchronization manifest;
- a minimal interrupted-sync safety marker while a remote mutation may be incomplete;
- at most one `before` and one `after` checkpoint for deterministic comparison.

The application never searches those files to answer repository questions. Production retrieval comes from HydraDB.

Generated builds, evaluation artifacts, virtual environments, coverage output, and runtime state are ignored by Git.
The extension and sync service create `.hydra-graph/.gitignore` without
changing the project's root ignore rules, so runtime identity, manifests, and
checkpoints do not appear as untracked project files.
