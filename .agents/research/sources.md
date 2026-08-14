# Research Sources

Verified 2026-08-13. Prefer these official HydraDB documents over secondary summaries.

## HydraDB

### Introduction

https://docs.hydradb.com/

HydraDB describes itself as graph-first state infrastructure for AI and combines semantic, keyword, graph, and metadata signals.

### Bring Your Own Graph

https://docs.hydradb.com/essentials/v2/bring-your-own-graph

Key facts used by this project:

- `graph_payload` supplies deterministic entities and relations.
- BYOG replaces automatic graph extraction for a source.
- Sources remain chunked, embedded, and vector searchable.
- BYOG relations appear in `graph_context` with `origin: "byog"`.
- BYOG payloads are per source and replace the stored source graph on update.
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
