# HydraDB Design and Research

Research verified against official HydraDB documentation on 2026-08-13. See [research/sources.md](research/sources.md).

## Non-negotiable position

> **HydraDB is central and critical to this product.**

The deterministic analyzer knows how to extract code facts. HydraDB turns those facts and their source content into a queryable context system for humans and agents. The extension is a view over HydraDB-backed results. The MCP server is a repository-specific interface over HydraDB queries.

The product must not maintain a second production graph database, vector database, or independent retrieval index.

## Why HydraDB fits Track B

HydraDB is not only vector search. Its current query API combines:

- Dense-vector similarity.
- BM25 keyword matching.
- Deterministic metadata filtering.
- Context-graph traversal.
- Ranked source chunks.
- Multi-hop `query_paths`.
- Relations between returned chunks in `chunk_relations`.
- Forcefully linked additional context.
- Shared Knowledge and user-scoped Memory.

This is directly aligned with Track B: similarity is a weak proxy for code relevance, while calls, types, tests, imports, and configuration are explicit relations.

## Capability-to-product mapping

| HydraDB capability | Product use |
|---|---|
| Bring Your Own Graph | Store deterministic code entities and exact parser-proven relations. |
| Knowledge | Store shared repository symbols, evidence cards, file summaries, change events, and team lenses. |
| Memory | Store personal lenses and, later if proven useful, cross-device display preferences or user corrections that do not change structural facts. |
| Hybrid query | Resolve both literal symbol searches and conceptual questions. |
| Thinking mode | Retrieve richer multi-hop paths for system-flow questions. |
| `graph_context.query_paths` | Render the highlighted HydraDB path from a question to relevant code. |
| `graph_context.chunk_relations` | Explain how returned code chunks relate to one another. |
| `chunk_id_to_group_ids` | Associate graph paths with the exact retrieved chunks shown to the agent. |
| Forceful relations | Guarantee that explicitly linked companion sources are returned in `additional_context` in thinking mode. |
| Metadata filters | Scope by repository, revision, language, path, entity kind, and confidence class. |
| Collections | Isolate current repository state, checkpoints, users, or experiments. |
| Webhooks/status | Update the extension when asynchronous indexing completes or fails. |
| BYOG on Memory | Later support personal graph-backed learning state without mixing it with repository truth. |

## Required API baseline

Target HydraDB API v2 behind a small adapter.

- Ingest through `POST /context/ingest` with `API-Version: 2`.
- Query through `POST /query` with `API-Version: 2`.
- Use `database` and `collection`; treat `tenant_id` and `sub_tenant_id` as deprecated aliases only.
- Poll ingestion status or consume verified webhooks before declaring a revision ready.
- Set `graph_context: true` explicitly for graph experiences.
- Use `mode: "thinking"` for flow tracing and forceful relations.
- Use `mode: "fast"` for shallow focus where latency matters.
- Do not rely on `mode: "auto"` when deterministic graph behavior is required because auto-routing may override graph-context behavior.

All HydraDB calls must go through an owned adapter so SDK naming changes and API-version differences remain isolated.

## BYOG is the structural foundation

HydraDB BYOG lets the project submit an exact `graph_payload` for a source. HydraDB then:

- Skips LLM graph extraction for that source.
- Stores supplied `source → predicate → target` triplets.
- Continues to chunk and embed the source.
- Returns supplied relations in `graph_context`.
- Marks those relations with `origin: "byog"`.
- Persists the supplied graph across re-ingestion until it is explicitly replaced.

This is the correct boundary:

```text
Deterministic parser decides what is structurally true.
HydraDB stores, links, filters, ranks, traverses, and returns it.
```

Do not ask an LLM to infer relations already known by the parser. Use automatic extraction only for prose-like material where deterministic parsers do not know the relation.

## Boundary with the repository UI

HydraDB stores and returns repository knowledge; the webview renders a bounded 2D projection.

- Repository nodes remain concrete source-backed entities.
- Exact structural edges come from deterministic BYOG payloads.
- Package/file aggregate edges retain the exact contributing relations.
- HydraDB retrieval rank may choose which bounded slice is shown, but it does not turn semantic similarity into an exact code relation.
- Dragged positions, pan, zoom, filters, and collapsed state are UI state, not HydraDB graph facts.
- The UI may show semantic results around a user question, but it must not present LLM-created concepts as repository structure nodes.

## Source granularity

### Working choice: one source per symbol or logical block

Primary Knowledge sources should represent:

- A function or method.
- A class, interface, or type.
- A module/file summary.
- A test case or test suite.
- A configuration block.
- An infrastructure or build block.
- A generated change-event or system-lens record.

Each source contains a concise text card with the entity's qualified name, signature, path, source span, documentation, and enough surrounding code to answer questions.

Why this is preferred:

- HydraDB chunks align closely with symbols.
- Retrieved context has precise source evidence.
- Changed symbols can be replaced without re-uploading an entire repository.
- `chunk_relations` become easier to explain in the UI.
- Agent token budgets are easier to control.

Risks:

- Large repositories create many sources.
- Symbol additions, removals, and renames need explicit lifecycle handling.
- Cross-symbol relations need a stable global naming scheme.
- Upload batching and indexing latency must be measured.

The capability spike must compare symbol-level and file-level ingestion on the demo repository. Keep this decision reversible until measurements exist.

## HydraDB entity naming

BYOG entity map keys are only request-local handles. HydraDB normalizes entity names, and `identifier` is display-only. Therefore the stored entity `name` itself must be globally unambiguous within the repository database.

Recommended form:

```text
<qualified-symbol> [<kind>] @ <repository-relative-path>
```

Example:

```text
payments.auth.authorize_user [function] @ src/payments/auth.py
```

Keep names within HydraDB's 256-character limit. Put a deterministic full identifier in `identifier` and the short display label in source metadata for the extension.

## Suggested scoping model

For the hackathon:

- One HydraDB `database` per indexed repository.
- `current` collection for current shared repository Knowledge.
- Optional `revision_<sha>` collections for immutable demo checkpoints.
- `user_<stable-id>` collections for developer Memory.
- Separate benchmark collections for ablation experiments.

Before relying on graph paths across several collections, prove the behavior with a live API test. If cross-collection graph traversal is not supported as needed, query current Knowledge and user Memory separately and merge only presentation-level state. Do not invent unsupported graph semantics.

## Metadata design

Stable, frequently filtered fields belong in schema-backed `metadata`:

- `repository_id`
- `revision_id`
- `entity_kind`
- `language`
- `relation_quality`
- `is_generated`
- `is_test`

Flexible display and bookkeeping fields belong in `additional_metadata`:

- `path`
- `start_line`
- `end_line`
- `qualified_name`
- `display_name`
- `parser`
- `parser_version`
- `content_hash`
- `git_commit`
- `graph_ir_version`

HydraDB limits each source's serialized `additional_metadata` object to 1,024
bytes. Keep the richer local SourceCard, but project only retrieval-critical
fields onto the wire. The source title/content and exact relation evidence carry
duplicated display and evidence details. Evolution cards keep their complete
machine record after the `Record JSON:` marker in source content instead of
duplicating it into bounded wire metadata.

Declare hot metadata fields when creating the HydraDB database. Undeclared top-level filter keys may not behave as expected.

## Forceful relations

Use forceful relations sparingly for whole-source links that must travel together, for example:

- A symbol card and its exact implementation excerpt.
- A generated system-lens record and its user-authored explanation.
- A change record and the before/after evidence documents.

Do not use forceful relations as a substitute for the code graph. BYOG relations represent entity structure. Forceful relations guarantee companion source hydration in `additional_context`, and only work in thinking mode.

## Important documented limits

Per BYOG source:

- At most 5,000 entities.
- At most 10,000 relations.
- At most 500 relations touching one entity.
- Relation context at most 2,000 characters.
- Entity names and predicates at most 256 characters.

Other important behavior:

- BYOG replaces automatic graph extraction for that source; it does not augment it.
- BYOG is bulk and per-source. Per-triple add, update, and delete are not currently available.
- Every source keyed in `graph_payload` must contain at least one entity and one relation. A request may key only the relation-bearing subset of its `app_knowledge` sources.
- Relation-to-chunk linking is permissive and may link weakly related chunks.
- Re-ingesting a BYOG source with a new payload replaces its stored graph.
- Re-ingesting an existing BYOG source without a new payload entry reapplies the stored graph; delete before a relation-bearing to relation-free transition.
- Serialized `additional_metadata` is limited to 1,024 bytes per source.
- Query graph fields may legitimately be empty.
- Context-graph traversal improves relational retrieval but adds payload and latency.

These limits support the symbol-level source strategy and require explicit replacement/deletion logic.

## What HydraDB does not currently promise

Do not claim any of the following without a successful capability test:

- Arbitrary Cypher-style graph queries.
- Streaming disclosure of HydraDB's private internal traversal steps.
- Per-edge mutation.
- Perfect exact-neighbor expansion by entity ID in API v2.
- Cross-collection traversal with the precise semantics this product needs.
- Stable entity identity across symbol renames without our own deterministic matching.

The extension may animate returned graph paths. It must not describe that animation as every internal search step taken inside HydraDB.

## Centrality tests for every feature

Before accepting a feature, answer:

1. What does HydraDB store for this feature?
2. What HydraDB query or graph output powers it?
3. Which HydraDB-specific signal makes it better than local text search?
4. What visible evidence shows the user that HydraDB provided value?
5. What is the degraded state when HydraDB is unavailable?

Reject features with weak answers.

## Required capability spike

Before broad implementation, prove all of the following against a live HydraDB database:

1. Ingest two symbol cards with deterministic BYOG relations.
2. Confirm `origin: "byog"` in returned graph context.
3. Confirm a conceptual query returns relevant chunks and a usable multi-hop path.
4. Confirm a literal symbol query works with hybrid and text modes.
5. Re-ingest one symbol source and verify replace behavior.
6. Delete a removed source and verify it no longer appears.
7. Measure indexing time for 100, 1,000, and 5,000 symbol sources if quota permits.
8. Confirm metadata filters for revision, language, path, and entity kind.
9. Test collection scoping and any cross-collection assumptions.
10. Test Knowledge plus Memory retrieval for a saved personal lens.
11. Determine whether a supported relation-inspection endpoint can power exact node expansion.
12. Record actual request and response fixtures for tests.

Until this spike passes, graph expansion and revision architecture remain provisional.
