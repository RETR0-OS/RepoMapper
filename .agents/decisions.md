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

Run the Python HTTP service on loopback and mount the repository MCP server in that same process at `/mcp`. The TypeScript VS Code extension talks only to the loopback service. HydraDB credentials stay in the Python process and are never sent to the webview. Standalone stdio MCP remains available when shared Observe events are not required.

The deterministic analyzer may build upload payloads and bounded diff artifacts, but product retrieval remains HydraDB-only. When credentials, indexing, or a query are unavailable, the service returns an explicit empty degraded result. The interactive UI fixture is labeled as a preview and is never returned as repository truth.

## D-025 — Exact relation evidence envelope

Status: accepted.

Serialize every deterministic BYOG relation context as the bounded, versioned `hack-hydra.relation-evidence.v1` JSON envelope. It carries the readable summary, stable edge ID, extractor identity, and original exact evidence record. A returned relation is exact only when its BYOG origin and evidence envelope both validate. Missing, malformed, or automatically extracted relation context must be downgraded or omitted without inventing a source range.

## D-026 — Confirmed manual indexing

Status: accepted for the MVP.

Index only the request-selected repository scope. Require an explicit revision ID, show the discovered files and complete source-card upload scope, and require confirmation before contacting HydraDB. A manual `Index now` flow is the MVP editing loop; automatic file watching remains future work.

Stable source replacement in the `current` collection is not transactional. If an upsert or deletion fails after HydraDB accepts part of a candidate, report the current collection as indeterminate. The prior revision is only the last verified marker, not a promise that every prior source is still queryable. Immutable revision collections remain provisional until live collection semantics are proven.

## D-027 — Knowledge-backed evolution records

Status: accepted for the MVP.

Store current repository cards in the explicit `current` Knowledge collection and published change events and one shared System Lens in the explicit `evolution` Knowledge collection. Query the collections separately; do not claim cross-collection traversal or HydraDB Memory behavior.

Keep exactly one bounded before checkpoint and one bounded after checkpoint on local disk only long enough to build a deterministic delta. Checkpoints are not a retrieval store and are removed only after HydraDB confirms the published evolution records.

## D-028 — Shared-process Observe

Status: accepted for the MVP.

Mount Streamable HTTP MCP at `/mcp` inside the loopback FastAPI service so MCP queries, stored views, and explicit Observe events share one process. Observe shows only explicit session, query, returned-context, selection, evidence-open, and visible workspace-change events. It never claims hidden model reasoning.

Bind every Observe session to one verified revision and an opaque fingerprint of the configured canonical repository root. Poll with a bounded event cursor. A mismatched revision, root, expired view, or pruned cursor fails closed instead of silently recoloring another repository or omitting timeline history.

Standalone stdio MCP remains available, but it cannot populate a different service process's Observe timeline.

## D-029 — Evaluation baseline isolation

Status: accepted for the MVP.

Keep the deterministic TF-IDF baseline inside the evaluation-only package. Product service code must never import or use it as retrieval fallback.

Evaluation conditions are A: local TF-IDF, B: HydraDB with `graph_context=false`, and C: the same HydraDB request with `graph_context=true`. Score returned stable IDs, complete relation facts, and exact evidence against a checked gold Graph IR. Keep exact and inferred denominators separate. Offline fixtures may rehearse the pipeline but may not support comparative claims; those require one complete live run for every question and condition.

## D-030 — Extension-owned repository scope

Status: accepted for the MVP.

VS Code users do not configure `HYDRA_REPOSITORY_ROOT` or
`HYDRA_REPOSITORY_ID`. The extension selects the first open local workspace
folder and derives an ASCII-safe repository ID from its name and a short hash
of its canonical path. Every extension request sends the paired scope to the
loopback service.

The service validates the pair and keeps independent sync, query, view,
evolution, checkpoint, and Observe state for each workspace. Direct CLI and
standalone MCP workflows may still use the process environment because they do
not have VS Code workspace context. Index preview and explicit confirmation
remain required before an extension-triggered HydraDB upload.

## D-031 — Canonical project identity

Status: accepted. Supersedes the path-derived identity in D-030.

Treat the active editor's workspace folder as the current project, followed by
the sole folder and then a native multi-root picker. Resolve that folder through
`realpath` and never broaden analysis to a higher Git root.

For a new Git project, normalize the credential-free `origin` remote and use
`git:<name>:<20-character-origin-hash>`. A separately opened Git subproject adds
a stable Git-relative path hash. Persist only the repository ID and origin
fingerprint, never the raw remote. A project without a usable origin gets a
random persistent local identity.

Existing identities win. Offer a Git migration preview after later Git setup,
but migrate automatically only when no indexed current or evolution source can
be orphaned. Otherwise preserve the existing identity.

## D-032 — SecretStorage and per-operation leases

Status: accepted. Supersedes the credential boundary in D-024.

TypeScript owns HydraDB account profiles and project database bindings in VS
Code SecretStorage. Normal state stores only labels and opaque IDs. The managed
Python process starts without HydraDB environment credentials and requests a
fresh key/database lease over framed private IPC for every HydraDB operation.

Do not cache credentials for the process lifetime or expose database names in
health, ProductViews, query envelopes, events, MCP output, UI status, manifests,
or evolution records. Acknowledge that credentials briefly exist in JavaScript
and Python memory; do not claim physical zeroization.

## D-033 — Bundled authenticated runtime

Status: accepted. Supersedes the manually started service in D-024.

Ship a hash-verified PyInstaller one-directory service inside each desktop VSIX.
The extension owns startup, stable alternate port selection, multi-window owner
locking, attachment, stale-session invalidation, restart, and final shutdown.

Keep loopback binding. Use a SecretStorage installation key to sign window
challenges and issue short-lived REST tokens bound to one canonical project
root and repository ID. Authenticate all managed REST routes except version
discovery and the OAuth/MCP protocol routes, which have their own authorization
boundary. Reject host, root, token, body, rate, and protocol mismatches.

## D-034 — OAuth-only agent access

Status: accepted. Supersedes manual MCP configuration in D-028.

Keep one Streamable HTTP MCP endpoint at `/mcp` in the managed service. Codex
and Claude Code registration contains only the loopback URL and is performed by
their supported CLI after an exact preview and user confirmation.

Use dynamic client registration, PKCE S256, short authorization codes and
access tokens, rotating refresh tokens, explicit revocation, and read-only
repository scopes. Store server-side client/grant records through SecretStorage
IPC. Route first consent through a nonce-only VS Code URI and native client,
project, and scope approval. Resolve every token subject to exactly one
registered repository container.

## D-035 — Platform-specific desktop packages

Status: accepted.

Publish separate VSIX packages for Windows, macOS, and Linux on x64 and ARM64.
Bundle all runtime dependencies; never download a first-run binary or require
Python/Node on the user's machine. Sign Windows binaries, codesign/notarize
macOS binaries, and publish checksums, SBOMs, licenses, and provenance.

Local VS Code desktop is the first supported environment. Web, Codespaces,
Remote SSH, WSL-hosted extension processes, Alpine, and ARMHF remain outside the
release contract until separately designed and tested.

## D-036 — Automatic revisions and snapshot tokens

Status: accepted. Supersedes manual revision entry in D-026.

Use the complete commit SHA for a clean Git repository. Use a deterministic
analyzed-content digest for a dirty or non-Git project. Index preview issues a
short-lived single-use token bound to root, identity, revision, discovery, and
source-card scope. Confirmation re-analyzes and refuses changed snapshots.

Compare uses the verified before and after revisions automatically through
Start comparison and Finish comparison. All indexing and evolution writes keep
preview and explicit confirmation.

## D-037 — Cancellable background indexing jobs

Status: accepted.

Repository indexing runs as an in-process background job after preview and
confirmation. The service exposes bounded progress and cancellation endpoints,
keeps one active job per repository scope, and reports `completed` only when the
sync result is `ready`. Failed and unavailable sync results end the job as
`failed`; cancellation after a remote mutation remains indeterminate because
accepted HydraDB batches cannot be rolled back. Cancellation observed before
the first remote mutation preserves the prior verified state.

Job records are deliberately not durable. A service restart loses the record
and requires a new preview and index run, while any already accepted HydraDB
writes remain visible as an explicitly unverified state. A separate, minimal
`sync-in-progress.json` safety marker is durable: create it before the first
remote mutation and clear it only after the verified manifest is saved. It is
not resumable job progress. Its only purpose is to prevent a restart from
presenting the old manifest as proof that a partially replaced collection is
safe.

## D-038 — Relation-free sources stay outside BYOG

Status: accepted.

Every source keyed in a HydraDB BYOG payload contains at least one deterministic
entity and one exact relation. A code symbol or product record with no exact
relations remains in `app_knowledge` but is omitted from `graph_payload`. Do not
invent a self-relation, duplicate an exact relation under another owner, or
treat HydraDB's automatic extraction for an unkeyed source as exact repository
structure. Exact views still require proven BYOG ownership plus the valid
relation evidence envelope from D-027. Ownership may be HydraDB's returned
`origin: "byog"` marker or the verified current manifest's record that the
relation's source carried a BYOG payload.

## D-039 — Bound HydraDB wire metadata separately from local cards

Status: accepted.

Keep complete deterministic evidence and product records in local SourceCards,
but send a separate retrieval-critical `additional_metadata` projection that is
at most 1,024 serialized bytes. Omit display/evidence duplicates and the full
evolution `record_json`; the title, source content, and exact BYOG evidence
already carry that information. Evolution retrieval validates the canonical
record embedded after the card's `Record JSON:` marker.

Hash the actual app-knowledge and BYOG wire projection for synchronization so a
projection change triggers replacement even when the richer local card has not
changed. Refuse a source locally if required fields still cannot fit; do not
silently truncate paths, stable IDs, hashes, or product routing fields.

## D-040 — Keep graph grounding outside the text-content budget

Status: accepted.

Apply `max_context_chars` only to HydraDB-returned chunk and additional-context
text. Normalize the same response's source records into metadata-only graph
grounding, including stable node identity, path, span, parser, revision, and
content hash. This metadata does not add model context text and remains
available when lower-ranked chunk content is removed by the budget.

HydraDB API v2 does not currently echo a relation-origin field in live query
results. For the verified current revision, restore `origin: "byog"` only when
the relation chunk belongs to a source listed in the verified sync manifest's
`byog_sources` and its context carries the exact evidence-envelope marker. The
ProductView layer still performs full envelope and evidence validation. A
relation whose endpoint metadata was not returned remains omitted; do not
fabricate a repository node from an entity name.

## D-041 — Test code is retrieved separately and ordered last

Status: accepted.

HydraDB ranks one query and cannot be asked to rank a metadata value last. A
repository question therefore issues two filtered queries: `is_test = false` at
the full budget, then `is_test = true` in fast mode at a quarter budget. The
answers are concatenated, implementation first.

Ranking inside each half remains entirely HydraDB's. Only the join order is this
service's, and it is a fixed rule rather than a local relevance score, so the
result stays reproducible. This does not reintroduce local reranking under D-019.

A failed second query drops the test tail with a warning; it never fails the
answer. The `tests` policy accepts `last`, `mixed`, and `only`, so a question
about the tests can still reach them.

## D-042 — Entry points are proven by manifests, in any language

Status: accepted.

A graph that never names where execution starts cannot explain a system. Entry
points are detected at index time from evidence a manifest states: Python main
guards and `__main__.py`, `pyproject.toml` console scripts, `package.json`
`bin`/`main`/`scripts.start`, Dockerfile `ENTRYPOINT`/`CMD`, and `Procfile`
lines. A token that does not resolve to a discovered repository file proves
nothing and is dropped.

Detection sets `is_entry_point` and `entry_reasons` node attributes and one
filterable card metadata field. It never changes a node's kind or qualified
name, so stable IDs do not churn. `NodeKind.ENTRYPOINT` stays unused here
because it requires a source span that a file-level entry does not have.

A non-Python file becomes a `FILE` node only when a manifest proves it starts
the system, and it never enters the Python import-resolution map: `import
web.index` must not resolve onto `web/index.js` and claim an unproven exact edge.

## D-043 — Complete the answer window before grounding the graph

Status: accepted.

A relation is shown only when every chunk it cites came back in the same answer.
The code that connects two matched symbols is rarely a word match for the
question, so it stays outside the window and every relation through it is dropped
as ungrounded. That is why a correct graph arrives as disconnected pairs.

Two directions are missing and they need different seeds. A relation the answer
already holds names the code it reaches, so its endpoints find the callees. But
nothing in the answer names the callers, because a card's BYOG graph holds only
the relations that card owns. Every card does list its incoming relations by
name in its content, so searching for the matched qualified names finds the code
that calls them.

The completion read therefore seeds from both, interleaved so neither direction
starves the other, and it excludes test sources because a test that calls the
same symbol matches equally well while connecting nothing. It repeats for at most
`COMPLETION_ROUNDS` rounds and stops as soon as a round adds nothing: an entry
point usually sits several calls above the matched code, so a single round
reaches the caller and stops one step short of where execution starts.

Each round is bounded by `HYDRA_DB_COMPLETION_SOURCES` (0 disables completion). A
returned card that does not carry the requested revision is discarded rather than
mixed in. The cost is a small number of fast queries plus cached relation reads.

## D-044 — Ordered flow paths are presentation order over proven hops

Status: accepted.

Disconnected pairs do not explain a system; ordered steps do. After grounding,
the service assembles the already-returned, already-proven relations into paths
that run from an entry point to the code that matched the question, and places
them ahead of HydraDB's own path ranking.

Assembly may only order and select. It must never invent a hop, a node, or a
transitive edge that was not returned. Anchors prefer proven entry points, then
zero in-degree non-test entities; targets prefer top-ranked non-test chunks.
Preferring implementation code is never a refusal to answer, so an all-test
slice still yields a path. An entity with no returned chunk may be walked
through but can never be an anchor or a target, because nothing proves what it
is. A path shorter than two hops is not a flow and is not emitted.

An assembled path replaces the group it was built from, so one chain is never
shown or budgeted twice. This is the same category as D-023 aggregation:
presentation compression, not a new semantic claim.

## D-045 — Mode intent travels as filters, never as query prose

Status: accepted.

Sending "Return the concrete repository structure at file depth and its exact
relations." to semantic retrieval matches cards whose text resembles that
sentence, so it returns whatever code discusses structure rather than the
structure. Every mode was doing this, which is why every tab returned unusable
results.

Intent that a filter can carry travels as a filter: entity kinds, revision,
test policy, and entry-point selection. `query_by` and `mode` carry the rest.
The query text is reserved for the user's own words and for real symbol names.
The same rule binds MCP tools: `focus_symbol` searches for the symbol and path
only, and applies direction and relation choices by selecting among returned
proven hops, exactly as a predicate chip does in the panel.
