# Research Sources

Verified 2026-08-14. Prefer these official HydraDB documents over secondary summaries.

## HydraDB

### Introduction

https://docs.hydradb.com/

HydraDB describes itself as graph-first state infrastructure for AI and combines semantic, keyword, graph, and metadata signals.

### Bring Your Own Graph

https://docs.hydradb.com/essentials/v2/bring-your-own-graph

Key facts used by this project:

- `graph_payload` supplies deterministic entities and relations.
- BYOG replaces automatic graph extraction for each source keyed in `graph_payload`.
- Sources remain chunked, embedded, and vector searchable.
- BYOG relations appear in `graph_context` with `origin: "byog"`.
- BYOG payloads are per source and replace the stored source graph on update.
- A mixed ingest may omit relation-free `app_knowledge` sources from
  `graph_payload`; their automatically extracted relations must not be treated
  as exact repository structure.
- Per-triple mutation is not currently available.
- Documented per-source limits include 5,000 entities, 10,000 relations, degree 500, relation context 2,000 characters, and names/predicates 256 characters.

### Query

https://docs.hydradb.com/essentials/v2/query

Key facts:

- `POST /query` can query Knowledge, Memory, or both.
- Relevance combines dense-vector similarity, BM25, and graph traversal.
- `graph_context: true` includes graph paths.
- Thinking mode provides richer multi-hop traversal than fast mode.
- `query_forceful_relations` hydrates linked sources only in thinking mode.
- Metadata filters narrow candidates before ranking.
- API v2 uses `database` and `collection`; old tenant names are deprecated aliases.
- Auto mode may override explicit graph-context behavior, so explicit modes are preferred for deterministic product paths.

### Context Graphs

https://docs.hydradb.com/essentials/context-graphs

Key facts:

- Relations use directional source–relation–target triplets.
- Graph context augments retrieval rather than replacing it.
- Responses may contain multi-hop `query_paths`, `chunk_relations`, and `chunk_id_to_group_ids`.
- Empty graph fields are valid when no useful relations are found.

### Knowledge and forceful relations

https://docs.hydradb.com/essentials/v2/knowledge

Key facts:

- Knowledge is shared repository-wide context.
- Ingestion is asynchronous.
- Forceful relations link whole sources and return them in query `additional_context` in thinking mode.
- Knowledge is versioned through explicit replacement or deletion.

### Metadata

https://docs.hydradb.com/essentials/metadata

Key facts:

- Metadata defines deterministic query scope before hybrid and graph ranking.
- Stable, frequently queried fields should be schema-backed.
- Flexible source-level data belongs in additional metadata.

### API result structure

https://docs.hydradb.com/essentials/api-results

Key facts:

- Preserve HydraDB chunk ranking.
- Query paths should be presented before ranked chunks when preparing agent context.
- `chunk_id_to_group_ids` associates retrieved chunks with relation path groups.
- Relation evidence includes predicate, context, confidence, relationship ID, and chunk links when available.

### Memories

https://docs.hydradb.com/essentials/memories

Key facts:

- Memories are user-scoped, dynamic context.
- They can represent preferences, prior interactions, tasks, and outcomes.
- They are retrieved with semantic, metadata, graph, and personalized signals.

### Webhooks

https://docs.hydradb.com/essentials/webhooks

Key facts:

- Indexing status changes can be delivered by webhook.
- Deliveries should be signature-verified and deduplicated by delivery ID.
- Polling remains simpler for the local MVP.

### HydraDB MCP

https://docs.hydradb.com/plugins/mcp

Key facts:

- HydraDB already supports graph-enriched context through MCP.
- The product still needs a repository-specific MCP interface for evidence, revisions, budgets, view IDs, and Agent View events.

### API reference

https://docs.hydradb.com/api-reference

Use for current endpoint and SDK shapes. Keep all direct calls behind the HydraDB adapter because documentation and SDK surfaces include both current and legacy naming.

Implementation verification on 2026-08-14:

- The official API v2 documentation lists `POST /context/ingest`, `GET /context/status`, `POST /query`, `DELETE /context`, and `GET /context/relations`.
- API v2 requests use `Authorization: Bearer ...` and `API-Version: 2`.
- BYOG ingestion sends `graph_payload` as a JSON string in the multipart request, keyed by the exact source IDs in the same request.
- Current query documentation supports explicit `database`, `collection`/`collections`, `query_by`, `mode`, `graph_context`, `max_results`, and `metadata_filters` fields.
- A live credentialed capability run was not possible in this workspace on 2026-08-14 because `HYDRA_DB_API_KEY` and `HYDRA_DB_DATABASE` were not set. Adapter behavior and response shaping are fixture-tested; live replacement, deletion, collection, Memory, and relation-inspection semantics remain unverified.

Live API v2 ingestion verification on 2026-08-14:

- A credentialed `POST /context/ingest` against `hack-hydra-db` rejected a
  source whose BYOG item had `entities: {}` and `relations: []` with HTTP 400,
  code `INVALID_INPUT`, and the message `graph_payload.entities must be
  non-empty`.
- The adapter must therefore reject empty BYOG entity maps before upload. A
  second live request showed that a non-empty entity map with `relations: []`
  is also rejected with `graph_payload.relations must be non-empty`.
- `graph_payload` may cover only a subset of the `app_knowledge` sources in the
  same ingest request. This was accepted live and lets relation-free source
  cards remain searchable without inventing an exact edge.
- `GET /context/status` and `DELETE /context` must include the same collection
  as ingestion. Omitting it returned not-found status for sources that existed
  in the configured collection. Live status and strict deletion both succeeded
  after the collection was included.
- Re-ingesting an existing BYOG source without a new `graph_payload` entry
  reapplies its stored BYOG graph. A transition from relation-bearing to
  relation-free therefore needs explicit stale-graph handling before re-ingest.
- A live large-repository run accepted 1,000 ingestion items, then returned HTTP
  429 `RATE_LIMITED` with a bounded "retry in 11 seconds" message. Retrying only
  with the adapter's sub-second exponential backoff exhausted every attempt.
  The adapter must honor HydraDB's `Retry-After` header or equivalent message.
- The same live run rejected a source whose serialized `additional_metadata`
  was 1,072 bytes with HTTP 400 `INVALID_INPUT`: `document_metadata is too
  large ... the maximum is 1024`. A compacted replay of the exact rejected
  25-source batch was accepted and all 25 sources reached `completed` on
  2026-08-14. The adapter now enforces the 1,024-byte boundary locally.
- The completed large-repository run accepted and verified all 6,210 source
  cards in 249 batches at revision
  `4c2ab87b8695636d2e0eb0c6f883b62585fea8ba`. The verified manifest contains
  3,628 sources with exact BYOG payloads. The run took about 109 minutes under
  HydraDB's rolling ingest quota, but batch and status progress was monotonic;
  it was not re-uploading completed batches or stuck in a retry loop.
- A live graph query returned 50 ranked chunks and 35–36 source summaries, plus
  context-graph relation groups. A 15,000-character product budget retained 8
  chunk texts. The source summaries still carried the stable path, span, node,
  parser, revision, and hash metadata needed to ground graph endpoints, so text
  truncation must not discard that metadata.
- Live API v2 relation objects did not include an `origin` field, including
  relations whose context was the exact `hack-hydra.relation-evidence.v1`
  envelope uploaded through BYOG. The returned `chunk_id` identifies the
  source, and the verified sync manifest records whether that source carried a
  BYOG graph. Those two facts can restore BYOG ownership locally without
  treating automatic relations as exact; full evidence-envelope validation is
  still required.
- After preserving metadata-only grounding and verified BYOG ownership, the
  same read-only managed-query shape returned a ready ProductView with 2
  grounded nodes and 1 exact BYOG edge. Relations whose endpoint source card
  HydraDB did not return remained explicitly omitted.

## VS Code

### Webview API

https://code.visualstudio.com/api/extension-guides/webview

Supports fully customizable editor panels and message passing between the extension and webview. Use for the graph canvas.

### Tree View API

https://code.visualstudio.com/api/extension-guides/tree-view

Supports native sidebar views. Use for Current Symbol, Entrypoints, System Lenses, changes, Agent Activity, and indexing status.

### Webview UX guidance

https://code.visualstudio.com/api/ux-guidelines/webviews

Webviews are appropriate for custom UI not supported by native APIs. They must respect VS Code themes, accessibility, and resource constraints.

### Language Server Extension Guide

https://code.visualstudio.com/api/language-extensions/language-server-extension-guide

VS Code language features can provide symbols, references, implementations, CodeLens, and other editor-native signals. Treat them as parser/resolver inputs where reliable, not as the product's persistent graph store.
