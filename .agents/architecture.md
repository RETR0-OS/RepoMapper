# Architecture

## Architectural thesis

The project has one shared repository model in HydraDB and two clients:

- A VS Code extension for the programmer.
- An MCP interface for coding agents.

Both receive graph-backed results from the same HydraDB database.

```text
Repository files
      │
      ▼
Deterministic analyzer
      │ Graph IR + symbol evidence
      ▼
HydraDB synchronization service
      │
      ▼
**HydraDB Knowledge, BYOG graph, and Memory**
      │                              │
      ▼                              ▼
VS Code extension              Repository MCP tools
Human graph views              Agent context and path events
      │                              │
      └──────── shared view/session ─┘
```

## Components

### 1. Deterministic analyzer

Responsibilities:

- Discover repository files using explicit ignore rules.
- Parse every language supported by a verified parser.
- Extract symbols, spans, signatures, imports, types, calls, tests, and configuration links.
- Resolve only relations it can justify.
- Emit versioned Graph IR.
- Produce source cards for HydraDB ingestion.
- Compare two Graph IR snapshots and produce graph-delta records.

It must not:

- Perform semantic retrieval.
- Rank context for agents.
- Become a permanent graph database.
- Label inferred relations as exact.

### 2. HydraDB synchronization service

Recommended language: Python.

Responsibilities:

- Convert Graph IR nodes and edges to source cards and BYOG payloads.
- Create or validate the HydraDB database and metadata schema.
- Batch uploads and replacements.
- Delete removed sources.
- Poll status or process signed webhooks.
- Expose indexing health and revision readiness.
- Keep the HydraDB SDK behind an internal adapter.

### 3. Repository query service

Recommended language: Python, in the same service process as synchronization for the MVP.

Responsibilities:

- Turn user and agent questions into explicit HydraDB query modes.
- Apply repository, revision, entity-kind, and confidence filters.
- Preserve HydraDB ranking order.
- Convert `query_paths`, `chunk_relations`, chunks, sources, and additional context into a stable product response.
- Assign `view_id` and `session_id` values.
- Emit observable path events to the extension.
- Enforce token and node budgets.
- Build deterministic package, file, and symbol projections from HydraDB-backed repository sources for the Repository mode.
- Return contributing relation IDs when several exact relations are aggregated into a higher-level edge.

It must not reimplement HydraDB ranking or graph retrieval.

### 4. MCP server

Responsibilities:

- Present repository-specific tools to Codex and Claude Code.
- Call the repository query service, which calls HydraDB.
- Return concise structured context with source spans and path evidence.
- Emit query, path-returned, context-selected, and evidence-opened events.
- Correlate all events with an agent session.

The generic HydraDB MCP server is useful reference plumbing, but the product needs its own repository-aware MCP layer to support graph views, revisions, evidence, budgets, and path-event correlation.

### 5. VS Code extension host

Recommended language: TypeScript.

Responsibilities:

- Register commands, Tree Views, CodeLens, status items, and webview panels.
- Track the active repository, file, selection, and visible revision.
- Talk to the local service.
- Relay structured messages to the graph webview.
- Open exact source ranges in normal VS Code editors.
- Open directory/package selections in the native Explorer.
- Validate webview source-navigation requests against the active workspace before opening them.
- Subscribe to agent-session and indexing events.

### 6. Graph webview

Responsibilities:

- Render only bounded graph slices or progressively aggregated repository projections.
- Support a deterministic 2D repository map at package, file, and symbol depth.
- Support node dragging, canvas panning, pointer-centered zoom, layout reset, focus, expansion, path animation, and graph diffs.
- Keep edges attached while a node is moved.
- Send node and edge selections to the extension host for source navigation.
- Show why an item is visible, its resolver, stable ID, evidence, quality, HydraDB origin, revision, and retrieval mode.
- Maintain accessible alternatives to color-only encoding.

The webview must not create structural facts. Node positions, pan, zoom, collapsed groups, and relation filters are presentation state only.

The webview receives data from the extension host. It does not hold HydraDB credentials or call HydraDB directly.

## Product view contracts

The service-to-extension response should separate graph truth from display state.

```text
view_id
revision_id
mode                    repository | explore | trace | observe | compare | preserve
depth                   package | file | symbol, when applicable
nodes[]                 concrete entities with stable IDs and source locations
edges[]                 predicates with quality, resolver, and evidence IDs
aggregates[]            counts plus contributing exact node/edge IDs
hydradb                  database, collection, query mode, path IDs, origin
warnings[]              gaps, truncation, unresolved targets, degraded state
budget                   requested and returned node/edge counts
```

Display state is maintained separately:

```text
view_id
node_positions
pan
zoom
hidden_relation_kinds
inferred_visible
selected_item_id
```

Display state may be kept in VS Code workspace state or user state. It must not be written into Graph IR or treated as a HydraDB structural relation.

Repository projections still pass through HydraDB. If the capability spike shows that API v2 cannot enumerate the needed neighbors directly, ingest deterministic package/file projection summaries as HydraDB Knowledge and retrieve those bounded summaries. Do not bypass HydraDB by serving the temporary local Graph IR directly to the production UI.

## Source navigation flow

```text
User selects graph node or edge
        │
        ▼
Webview emits stable ID + evidence range
        │
        ▼
Extension validates workspace path and revision
        │
        ├── node: open declaration or concrete repository location
        └── edge: open the source range that proves the predicate
        │
        ▼
VS Code reveals and selects the exact range
```

The standalone UI mockup uses an embedded source drawer to demonstrate this flow. The production extension uses `openTextDocument` and `showTextDocument` through the extension host.

## Storage ownership

### HydraDB owns

- Shared repository Knowledge.
- Deterministic BYOG relations.
- Ranked chunks and graph-context retrieval.
- Current repository query scope.
- Personal Memory and saved personal lenses.
- Shared lens records when promoted to Knowledge.
- Immutable demo revision sources or graph-delta knowledge where used.

### Local workspace may hold

- Source code.
- Configuration.
- Temporary Graph IR during analysis and upload.
- A small, bounded cache of the currently displayed HydraDB result.
- Durable ingestion bookkeeping that contains IDs and hashes but not an alternate searchable graph, if needed for reliable sync.
- Test fixtures with synthetic HydraDB responses.

### Local workspace must not hold

- A production SQLite, Neo4j, or other graph store used for repository retrieval.
- A production vector index.
- A full persistent graph used as the primary UI/query backend.
- A silent fallback that makes HydraDB optional.

## Query flow

```text
Human question or MCP tool call
        │
        ▼
Product query planner
  - chooses fast/thinking
  - chooses hybrid/text
  - sets filters and budget
        │
        ▼
**HydraDB /query**
        │
        ▼
chunks + sources + query_paths + chunk_relations + additional_context
        │
        ├── compact context for agent
        └── graph view and path animation for human
```

The product query planner chooses parameters. It does not choose results after HydraDB returns them except for strict safety, deduplication, and response-budget enforcement. Preserve HydraDB ranking and expose any downstream filtering.

## Indexing flow

```text
File event or explicit index command
        │
        ▼
Parse changed files and dependents
        │
        ▼
Emit Graph IR and source ownership changes
        │
        ▼
Build symbol cards and per-source BYOG payloads
        │
        ▼
Upload/replace/delete through HydraDB adapter
        │
        ▼
Wait for verified indexing completion
        │
        ▼
Publish ready revision and refresh affected views
```

## Agent observation flow

```text
Agent calls repository MCP tool
        │
        ├── query_started
        ▼
HydraDB query
        │
        ├── path_returned
        ├── context_returned
        ▼
Agent receives bounded result
        │
        ├── evidence_opened, if requested
        └── file changes observed by workspace watcher
```

Only observable events are shown. The UI never claims access to private reasoning.

## Revision consistency

- Every source card and relation carries a revision identifier in metadata or evidence context.
- A graph view is pinned to one ready revision unless it explicitly compares two revisions.
- Do not merge partially indexed current state into a stable view.
- The extension shows “indexing” until all changed sources reach the required status.
- Agent results include the revision used so edits are not based on an ambiguous graph state.

## Failure behavior

When HydraDB is unavailable:

- Source editing still works because VS Code works normally.
- Repository graph search, graph path retrieval, saved lenses, and agent graph tools show an explicit unavailable state.
- The analyzer may queue a bounded pending sync manifest.
- Do not silently answer from a local graph or vector index.

When indexing fails:

- Preserve the last verified HydraDB revision.
- Mark the new revision as failed.
- Show failed source IDs and retry controls.
- Never label a partial revision as current.

## Security

- Keep `HYDRA_DB_API_KEY` outside source control.
- Never send credentials to the webview.
- Redact secrets from source cards before ingestion according to explicit rules.
- Respect `.gitignore` plus product-specific ignore configuration.
- Allow users to preview which files and spans will be sent to HydraDB.
- Record repository database and collection scope in the status UI.
- Verify webhook signatures and deduplicate delivery IDs if webhooks are used.

## Initial repository layout

The implementation may evolve, but a coherent first layout is:

```text
extension/          TypeScript VS Code extension and webview
service/            Python analysis, sync, query, events, and MCP
schemas/            Graph IR and product API schemas
fixtures/           Small multilingual repositories and HydraDB response fixtures
tests/              Unit, integration, retrieval, and UI tests
scripts/            Demo and benchmark commands
.agents/            Product and engineering context
```

Do not create the implementation layout until the first capability spike confirms SDK and API choices.
