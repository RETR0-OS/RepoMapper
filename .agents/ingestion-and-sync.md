# Ingestion and Synchronization

## Goal

Turn a changing, multilingual repository into precise HydraDB Knowledge and deterministic BYOG relations while keeping the currently queryable revision internally consistent.

## Language coverage

Index every language for which a verified parser can emit reliable nodes and spans.

Breadth and depth are separate:

- Broad language coverage provides files, symbols, hierarchy, and syntax-level references.
- Deeper language-specific resolvers provide calls, implementations, type links, tests, and framework/configuration wiring.

Do not arbitrarily restrict the MVP to three languages if more verified parsers already work. Do not claim equal relation depth across all languages.

Publish a capability matrix:

| Language | Symbols | Imports | References | Resolved calls | Types | Tests | Config/runtime links |
|---|---:|---:|---:|---:|---:|---:|---:|
| Each verified parser | measured | measured | measured | measured | measured | measured | measured |

Populate this table from fixtures and tests, not optimism.

## Pipeline

```text
Discover
→ classify files
→ parse
→ normalize symbols
→ resolve deterministic relations
→ emit Graph IR
→ build package/file/symbol projection records
→ build source cards
→ build per-source BYOG payloads
→ calculate source lifecycle changes
→ upload/replace/delete in HydraDB
→ verify indexing
→ publish ready revision
```

## Discovery

- Respect `.gitignore` by default.
- Support a product-specific ignore file for generated, vendor, secret, or large paths.
- Never follow symlink loops.
- Detect binary and oversized files before reading.
- Record ignored counts for transparency.
- Let users preview the ingestion scope.

## Parser contract

Each parser emits:

- Normalized node records.
- Normalized edge records.
- Exact spans.
- Parser name and version.
- Diagnostics for incomplete parsing.
- A declared capability set.
- A stable source locator for every visible entity.
- A named derivation method for every edge.

Resolution stages should be separate:

1. Syntax extraction.
2. Within-file name resolution.
3. Cross-file/module resolution.
4. Framework or configuration adapters.
5. Explicit heuristics, labeled inferred.

Never silently promote a heuristic to exact.

The pipeline does not ask an LLM to create repository nodes or exact edges. Semantic enrichment, if later added, must be stored and displayed separately from deterministic structure.

## UI projection inputs

The analyzer and synchronization layer must provide enough grounded data for the settled Repository UI without becoming a second query engine.

### Package depth

- Emit real repository directories, language packages, or modules.
- Aggregate exact lower-level edges by predicate and group pair.
- Retain every contributing edge ID and evidence ID.

### File depth

- Emit real files with language, generated/test/config flags, and revision.
- Emit exact file-to-file relations derived from owned symbol relations or explicit file-level relations.

### Symbol depth

- Emit concrete declarations and source-anchored framework/configuration resources.
- Include exact declaration spans and resolver provenance.
- Apply node and edge budgets before returning a view.

Projection records are uploaded or represented through HydraDB-backed repository summary sources. The UI may cache only the bounded current view. Temporary Graph IR is not a production UI database.

Every item needed for source navigation carries a normalized workspace-relative path and range. Directory nodes carry a concrete directory path. Aggregated edges carry a list of contributing evidence records rather than a fabricated single location.

## HydraDB source generation

For each symbol or logical block:

1. Generate a deterministic source ID.
2. Generate a concise source card.
3. Add schema-backed metadata and display metadata.
4. Collect canonically owned relations.
5. Build a BYOG graph containing the focal entity plus referenced target entities.
6. Add plain relation context with path and line evidence.
7. Upload through the HydraDB v2 adapter.

Also generate file/module summary sources for containment and high-level repository maps.

## Incremental sync

On a file change:

1. Hash the changed file.
2. Reparse it.
3. Re-resolve direct dependents when the language resolver requires it.
4. Compare new and prior source manifests.
5. Replace changed HydraDB sources with full new BYOG payloads.
6. Add new sources.
7. Delete removed sources.
8. Wait until all operations reach a verified terminal state.
9. Publish the new revision.

BYOG replacement is per source, not per edge. A changed source must send its complete current relation set.

## Bookkeeping

A local sync manifest may contain:

- Source ID.
- Content hash.
- Path and symbol locator.
- Last attempted revision.
- Last verified HydraDB revision.
- HydraDB indexing ID/status.

It must not contain a separately searchable graph used to answer product queries.

If history comparison needs a prior exact Graph IR snapshot, prefer one of:

1. Fetching a prior HydraDB-stored snapshot/source before replacement.
2. Storing immutable checkpoint artifacts in a revision collection.
3. Keeping a bounded deterministic analysis artifact solely for diff calculation, never retrieval.

Choose after the capability spike.

## Deletion and rename handling

- Removed symbols require HydraDB source deletion.
- A rename normally appears as remove plus add unless deterministic rename matching proves continuity.
- Deleted targets may require replacement of sources whose BYOG payload referenced them.
- Do not leave stale edges in current Knowledge.
- Confirm deletion behavior through integration tests.

## Index readiness

HydraDB ingestion is asynchronous.

- Track every source ID returned by ingestion.
- Poll status during local development.
- Consider signed HydraDB webhooks for a hosted service.
- Deduplicate webhook deliveries by delivery ID.
- Keep the prior revision active until every required current source is ready.
- Show partial/failed counts in VS Code.

## Live editing behavior

- Debounce rapid file saves.
- Group related edits into one revision candidate.
- Do not upload on every keystroke.
- Allow explicit “Index now.”
- During an agent task, capture a before checkpoint and one after checkpoint rather than indexing every intermediate edit for the MVP.
- Later, optionally stream stable save points for a richer timeline.

## Secret and privacy controls

- Never ingest `.env` files by default.
- Detect common private-key and token formats before upload.
- Support explicit deny globs.
- Show the exact source list before first indexing.
- Redact only through explicit, testable rules.
- Keep original repository paths local unless the user authorizes ingestion metadata containing them.
- Never log the HydraDB API key.

## HydraDB failure behavior

- Queue only bounded sync intent locally.
- Keep the last verified revision visible.
- Show the failure clearly.
- Offer retry.
- Do not answer repository graph queries from temporary Graph IR as a hidden fallback.

## Required tests

- Stable IDs across unchanged parses.
- No duplicate canonical relation ownership.
- Exact/inferred separation.
- Added, modified, removed, and renamed symbols.
- Cross-file target deletion.
- BYOG payload limits.
- Metadata filter correctness.
- Re-ingest replace behavior.
- Index readiness and failure.
- Multilingual fixtures.
- Generated and ignored files.
- Secret exclusion.
