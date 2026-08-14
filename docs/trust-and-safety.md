# Trust and safety

Hydra Repository Map is designed to say where its data came from, what was
verified, and when it cannot answer. The central rule is simple: production
retrieval comes from HydraDB.

## Data path

The local analyzer reads the configured repository and builds deterministic
Graph IR, source cards, and exact BYOG relations. It is an ingestion producer.
After upload, repository queries, paths, Compare records, and Preserve records
must come back through HydraDB.

The service does not use these as a hidden query fallback:

- repository files;
- analyzer Graph IR;
- the sync manifest;
- before/after checkpoints;
- checked JSON response fixtures; or
- a local graph database.

When credentials are absent, HydraDB is unavailable, a revision conflicts, a
specialized record is malformed, or current state is indeterminate, the service
returns an empty/degraded response with warnings or refuses the operation. It
does not fill the result with plausible local data.

Automated fixtures exercise transport and response normalization. They are not
loaded by the running service and are not evidence of live HydraDB performance.

## Credentials and network boundary

- `HYDRA_DB_API_KEY` stays in the Python service process.
- The key is sent to HydraDB as a bearer credential; it is not sent to the VS
  Code webview, stored in a ProductView, or accepted as an MCP tool argument.
- The FastAPI service binds to `127.0.0.1` and does not offer an arbitrary host
  option.
- The mounted MCP endpoint keeps DNS rebinding protection enabled and accepts
  loopback hosts and origins only.
- Raw HydraDB ingest, delete, and status operations are not public service
  routes. Indexing is exposed through the configured-root preview and confirmed
  index workflow.

Treat any process that can read the service environment as able to read the API
key. Use normal operating-system account and secret-management boundaries.

## Repository boundary

`HYDRA_REPOSITORY_ROOT` is resolved once when the service container is created.
Public requests cannot provide a replacement root. Discovery, analysis, index
preview, checkpoint capture, and workspace-change validation stay within that
root.

The service checks resolved manifest and checkpoint locations for containment,
including symlink escapes. It exposes only a deterministic SHA-256 root
fingerprint in health and session responses, never the absolute root. The
extension compares this fingerprint with its canonical workspace root before it
reports a workspace change.

Paths submitted to interaction routes must be normalized, inside the configured
root, and already represented by visible source-backed nodes. A workspace-change
event marks matching visible entities only. It does not infer that a relation
changed and does not silently re-index the file.

## Evidence and relation quality

Exact repository relations originate in uploaded BYOG data and carry validated
source evidence. Evidence includes a repository-relative normalized path, a
complete ordered source range, and a valid excerpt hash. Malformed evidence,
non-BYOG origin, unsupported predicates, or ungrounded entities cannot be
promoted to exact.

Inferred relations remain labeled inferred. The product does not fabricate an
evidence range from a chunk declaration or a readable sentence. If a returned
entity or relation cannot satisfy the shared graph model, it is omitted with an
honest warning or omitted count.

Views are bounded projections of ranked HydraDB results. They are not exhaustive
whole-repository graphs. Rank, path IDs, relation origin, collection, budgets,
and truncation are preserved so the UI and agents can describe what was actually
returned.

## Revision and sync truth

`unverified` means configuration exists but the process has not verified a
concrete current revision. `ready` means an index completed and its deterministic
source-hash manifest was persisted. Queries for `current` are gated while an
index is in progress or the current collection is indeterminate.

Current-collection replacement is not transactional. Stable source IDs are
upserted before every status check and deletion can complete. If a later step
fails, candidate content may already be visible. The prior `ready_revision`
remains the last verified marker, not a promise that HydraDB has rolled back to
that content.

The safe recovery is an explicit complete reindex after the underlying problem
is resolved. The service never claims a rollback it did not perform. More detail
is in [Indexing and sync](indexing-and-sync.md).

## Evolution boundary

The current and evolution collections must be distinct. Change events and
shared lenses are written and queried only in evolution. Current repository
paths are queried only in current. Preserve uses two sequential, explicit
single-collection queries and joins their validated product meaning in the
service.

This is not a HydraDB cross-collection traversal claim. The product also makes no
HydraDB Memory claim. Local before/after checkpoints are write inputs used to
build deterministic delta cards; Compare never reads them as a retrieval
fallback.

## Agent and Observe boundary

The mounted `/mcp` endpoint shares events and stored bounded views with the
extension. Tool calls record query and view events; they do not reveal or claim
hidden agent reasoning. `pin_context` records an explicit human selection and
instruction without changing structural graph facts.

Observe sessions are revision-bound and bounded. The server derives event IDs,
revision IDs, view IDs, entity IDs, and relationship IDs from validated server
state. Clients cannot post arbitrary event envelopes. Unknown or completed
sessions, expired views, unshown items, and path escapes are rejected before a
HydraDB request or event emission where applicable.

Event history is bounded. Cursor polling returns a conflict when the requested
cursor is no longer retained, rather than silently presenting an incomplete
timeline as complete.

## What has not been proved live

The checked-out project does not contain HydraDB credentials. The adapter and
service have extensive mocked transport, schema, anti-gaming, and failure-path
tests, but those tests do not establish a credentialed production result.

Until a credentialed integration run records the exact requests and raw
responses, treat these areas as provisional:

- exact live relation-inspection response semantics;
- stable-source replacement behavior beyond the explicit indeterminate model;
- HydraDB Memory behavior, which the product does not use or claim; and
- cross-collection revision traversal, which the product does not perform or
  claim.

Offline evaluation output is a rehearsal, not evidence that graph-backed
HydraDB retrieval improved an agent outcome. Comparative claims require a
complete credentialed A/B/C run against the exact gold repository revision and
must pass the demo preflight. See the [project README](../README.md#verify) and
[evaluation design](../.agents/evaluation.md).

For setup, begin with [Getting started](getting-started.md). For operational
failures, use [Troubleshooting](troubleshooting.md).
