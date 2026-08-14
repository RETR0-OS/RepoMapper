# Architecture

[Documentation index](README.md) · [Core concepts](concepts.md) ·
[Graph and evidence](graph-and-evidence.md) ·
[Compare and Preserve](compare-and-preserve.md)

Hydra Repository Map has one production knowledge and retrieval substrate:
HydraDB. Local analysis creates upload material and deterministic diff inputs;
it does not become a second repository query engine.

## Component map

```text
VS Code extension (root selection, SecretStorage, process owner)
      |
      | authenticated REST + private credential/OAuth IPC
      v
Bundled managed Python service
      |
      v
Repository files
      |
      v
Python discovery and analyzer
      |
      v
Graph IR -> source cards + exact BYOG payloads
      |
      v
HydraDB current Knowledge
      |
      v
Python query/view service ---- OAuth repository MCP tools
      |
      v
TypeScript graph webview

Before/after Graph IR checkpoints
      |
      v
Deterministic delta -> HydraDB evolution Knowledge
      |
      v
Compare and Preserve queries
```

## Local analysis

The Python discovery layer walks one validated repository scope at a time. It respects
`.gitignore`, `.hydraignore`, explicit deny globs, common secret filenames and
content signatures, binary detection, file-size limits, and symlink exclusion.
It returns both eligible files and reasons for ignored paths.

The analyzer currently parses eligible Python files. It creates versioned Graph
IR with stable IDs, source hashes, parser versions, diagnostics, and exact
relations whose targets resolve to discovered declarations. Dynamic or external
calls that cannot be resolved are left absent rather than guessed.

The analyzer does not rank context and has no repository-search API.

## Source cards and HydraDB BYOG

The card builder creates one deterministic HydraDB source per concrete Graph IR
entity. A card contains readable identity and source information plus metadata
used to bind repository and revision queries.

Each relation has one canonical owning source. Only exact owned relations enter
the source's BYOG graph. Inferred relations can remain in Graph IR for an
explicit opt-in view, but they are not uploaded as exact BYOG facts.

If an entity owns no exact relation, its BYOG graph is empty. The implementation
does not invent a self-edge merely to keep an entity connected, and the empty
payload prevents automatic extraction from manufacturing repository structure
for that source.

The sync service batches additions and full-source replacements, waits for
indexing status, and confirms deletions before publishing a revision as ready.
Its durable manifest stores source IDs and card hashes only. It contains no
searchable graph content.

## Query and view flow

```text
Human question or MCP tool call
      |
      v
Bounded product query request
      |
      v
HydraDB query with repository/revision filters
      |
      v
Normalized chunks, sources, paths, relations, and warnings
      |
      +----> bounded agent context
      |
      `----> bounded human graph view
```

The query service assigns session and view IDs, applies budgets, and normalizes
HydraDB's response into the versioned product response. It may reject unsafe or
mixed-revision data, deduplicate it, and truncate it to an explicit budget. It
does not rerank HydraDB results or substitute local results.

The view service turns only that normalized HydraDB result into Repository,
Explore, Trace, Observe, Compare, or Preserve view data. Its in-process view
store is a small bounded cache of recently displayed results, not a graph
database.

The extension host, written in TypeScript, owns project selection, SecretStorage,
the bundled process, authenticated project attachment, credential brokering,
native consent, source navigation, and file opening. The webview receives
structured display data; it receives no HydraDB credentials and does not call
HydraDB directly.

## Human and agent access

The VS Code extension and repository MCP server call the same managed service
and see the same HydraDB-backed repository model. REST uses short project-bound
tokens. MCP uses OAuth with an explicit repository subject. The MCP server
exposes bounded repository-aware operations rather than raw database access.

For Observe to correlate MCP calls with the extension timeline, the MCP endpoint
must be mounted in the same service process at `/mcp`. A separate stdio MCP
process can use the tools but does not share the service's event bus or view
store.

Only observable events are recorded: queries, returned paths, selected context,
opened evidence, and workspace changes. These events are not chain-of-thought.

## Current and evolution collections

Current repository sources live in the configured current collection. Change
events and the one shared System Lens live in a separate evolution collection.
The service queries these collections independently.

The implementation does not depend on cross-collection graph traversal or
HydraDB Memory. Shared lenses are stored as Knowledge. The product does not
merge separate collection results into a fabricated structural traversal.

See [Compare and Preserve](compare-and-preserve.md) for the evolution flow.

## Local state that is allowed

The workspace may contain:

- source code and configuration;
- an opaque repository identity and a source-ID/card-hash sync manifest;
- exactly two bounded Graph IR checkpoint files used as diff inputs; and
- a bounded in-process cache of current HydraDB views and Observe events.

The checkpoints expose capture and pair loading, not search. Compare and
Preserve retrieval never reads them. After a confirmed change event is ready in
HydraDB, the service attempts to clear both checkpoint slots.

## Failure behavior

When HydraDB is unavailable, repository queries return `unavailable` with empty
paths, chunks, and relations. When the current collection may be mixed after a
partial sync, queries return an empty `degraded` response. There is no local
Graph IR or TF-IDF fallback in the product service.

Writes can be `unavailable`, `failed`, or `indeterminate`. An indeterminate
write means HydraDB may have accepted only part of the operation; the service
does not claim success and retains local diff checkpoints where possible.

## Security boundaries

- API keys and project database names are stored in VS Code SecretStorage.
  Python receives a fresh short-lived lease through private IPC for each
  HydraDB operation. Neither value is sent to the webview.
- The bundled service is hash-verified, version-matched, loopback-only, and
  started without HydraDB values in argv or environment.
- REST uses short-lived canonical-root/repository tokens. MCP uses PKCE OAuth,
  rotating tokens, revocation, and native project/scope consent.
- The service analyzes only the selected, resolved repository root. Extension
  scope comes from the extension host, never from the webview.
- Repository paths in Graph IR are normalized, relative paths. Absolute paths
  and parent traversal are rejected.
- Discovery excludes symlinks and common secret material before analysis.
- Checkpoint paths are fixed beneath the workspace, size-bounded, hash-checked,
  and rejected if a slot is a symlink.

Secret detection is deliberately conservative, not a proof that a repository
contains no sensitive data. Users should review the indexing preview before a
confirmed upload.

## Important limits

- Repository analysis is Python-only today.
- HydraDB source replacement is per source, not per edge, and current-collection
  updates are not transactional.
- Exact live relation inspection, Memory behavior, and cross-collection
  traversal remain provisional until credentialed integration tests prove the
  required semantics.
- Views are budgeted slices. They are not complete whole-repository diagrams.
- Offline HydraDB fixtures test adapters and failure rules; they are not live
  performance evidence.

For the records that cross these boundaries, read
[Graph and evidence](graph-and-evidence.md).
