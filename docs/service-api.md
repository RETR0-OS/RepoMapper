# Loopback service API

The managed Python service prefers `http://127.0.0.1:8765` and may choose a
stable alternate port. It is a local product boundary, not a public HydraDB
proxy. Request models reject unknown JSON fields.

`GET /version` is the only unauthenticated REST discovery route. Every other
managed REST request uses a short-lived bearer token issued by the signed
project challenge. MCP has a separate OAuth boundary. The commands below are
developer-runtime diagnostics; users should use VS Code commands rather than
copying tokens into a shell.

The examples below use PowerShell:

```powershell
$baseUrl = "http://127.0.0.1:8765"
```

## Health, query, and views

### `GET /health`

Returns configuration and verified-sync state without exposing the repository
path or API key.

```powershell
Invoke-RestMethod "$baseUrl/health" | ConvertTo-Json -Depth 5
```

```json
{
  "state": "ready",
  "revision_id": "abc123",
  "revision_verified": true,
  "verification_status": "verified",
  "collection": "current",
  "source_count": 42,
  "repository_id": "my-repository",
  "repository_root_fingerprint": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "mcp_endpoint": "/mcp",
  "message": "The reported HydraDB repository revision completed graph indexing."
}
```

`state` is one of `unavailable`, `unverified`, `indexing`, `ready`, or `failed`.
See [Indexing and sync](indexing-and-sync.md#read-the-result) for the exact
meaning. `ready` is a verified marker from this process; current HydraDB
replacement is not transactional.

### `POST /api/query`

Runs a bounded current-collection query and returns a `trace` ProductView.

```powershell
$body = @{
    question = "How does authorization work?"
    depth = "symbol"
    revision = "current"
    max_nodes = 50
    max_edges = 80
    max_context_chars = 7000
    query_by = "hybrid"
    mode = "thinking"
    graph_context = $true
} | ConvertTo-Json

Invoke-RestMethod "$baseUrl/api/query" `
    -Method Post -ContentType "application/json" -Body $body
```

Body fields and limits:

| Field | Default | Limit |
| --- | --- | --- |
| `question` | required | 1–4000 characters |
| `depth` | `symbol` | `package`, `file`, or `symbol` |
| `revision` | `current` | string |
| `max_nodes` | `50` | 1–500 |
| `max_edges` | `80` | 0–1000 |
| `max_context_chars` | `7000` | 1–100000 |
| `query_by` | `hybrid` | `hybrid` or `text` |
| `mode` | `thinking` | `fast` or `thinking` |
| `graph_context` | `true` | boolean |
| `session_id` | omitted | known active Observe session ID when supplied |

An Observe-bound `session_id` is checked for active state and revision
compatibility before HydraDB I/O.

The ProductView response has this stable top-level shape:

```json
{
  "view_schema": "hack-hydra.product-view.v2",
  "view_id": "view_opaque",
  "revision_id": "abc123",
  "mode": "trace",
  "depth": "symbol",
  "nodes": [],
  "edges": [],
  "aggregates": [],
  "hydradb": {
    "available": true,
    "collections": ["current"],
    "query_by": "hybrid",
    "mode": "thinking",
    "graph_context": true,
    "path_ids": [],
    "origin": null,
    "status": "ready"
  },
  "warnings": [],
  "budget": {
    "requested_nodes": 50,
    "returned_nodes": 0,
    "requested_edges": 80,
    "returned_edges": 0,
    "truncated": false
  }
}
```

Nodes, edges, and aggregates are populated only from normalized HydraDB data.
An unavailable query still returns HTTP `200`, but has
`hydradb.available: false`, empty graph arrays, and a warning. This makes a
retrieval failure explicit without inventing a local result.

### `GET /api/views/{mode}`

Loads one of `repository`, `explore`, `trace`, `observe`, `compare`, or
`preserve`.

Common query parameters:

| Parameter | Default | Limit |
| --- | --- | --- |
| `depth` | `file` | `package`, `file`, or `symbol` |
| `question` | omitted | at most 4000 characters |
| `revision` | `current` | string |
| `max_nodes` | `50` | 1–500 |
| `max_edges` | `80` | 0–1000 |

Compare additionally requires `before_revision` and `after_revision`, each at
most 256 characters. Preserve requires `lens`, at most 200 characters.

```powershell
Invoke-RestMethod `
    "$baseUrl/api/views/trace?depth=symbol&question=authorization&max_nodes=30&max_edges=40"

Invoke-RestMethod `
    "$baseUrl/api/views/compare?depth=symbol&before_revision=before&after_revision=after"

Invoke-RestMethod `
    "$baseUrl/api/views/preserve?depth=symbol&lens=lens_opaque"
```

Missing Compare or Preserve identifiers return an HTTP `200` degraded
ProductView with a warning. They do not fall through to a generic current query.
Compare queries the evolution collection only. Preserve performs separate
evolution and current queries; it does not request cross-collection traversal.

### Other view routes

| Route | Request | Response |
| --- | --- | --- |
| `POST /api/views/{mode}/action` | `{selected_id?, question?, depth?, revision?}` | Presentation message for Repository/Observe, otherwise a message and bounded ProductView. `selected_id` max 1024; `question` max 4000. |
| `GET /api/sidebar` | none | Current sidebar placeholders, the latest 20 activity events, and the health object. |
| `GET /api/views/by-id/{view_id}` | path ID | A stored, ready, HydraDB-derived ProductView only; never raw query chunks. Unknown, expired, unavailable, or non-HydraDB views return `404`. |

Stored views are bounded in-memory state and can expire.

## Safe indexing

Managed extension requests never send caller-controlled root headers. The
signed challenge resolves one canonical root and repository ID, and the bearer
token selects that registered service container. Root headers remain only in
the explicit developer runtime for compatibility testing.

### `POST /api/index/preview`

Body:

```json
{}
```

The server derives the revision: a clean Git commit SHA, otherwise a
deterministic analyzed-content digest.

```powershell
$body = @{} | ConvertTo-Json
$preview = Invoke-RestMethod "$baseUrl/api/index/preview" `
    -Method Post -ContentType "application/json" -Body $body
```

The response includes `repository_root`, `repository_id`, `revision_id`, file,
node, edge, and source counts, per-source upload details, diagnostics, and
`uploads_performed: false`. The absolute root is intentionally shown in this
local confirmation response so the user can verify scope. No HydraDB request is
made.

### `POST /api/index`

Uses the single-use preview token returned by the preview:

```powershell
$confirm = @{ preview_token = $preview.preview_token } | ConvertTo-Json
Invoke-RestMethod "$baseUrl/api/index" `
    -Method Post -ContentType "application/json" -Body $confirm
```

The response contains the same `preview` plus `sync`. Abridged example:

```json
{
  "preview": {"revision_id": "abc123", "uploads_performed": false},
  "sync": {
    "status": "ready",
    "candidate_revision": "abc123",
    "ready_revision": "abc123",
    "added": [],
    "replaced": [],
    "deleted": [],
    "pending": [],
    "failed": {},
    "current_state_indeterminate": false,
    "warning": null
  }
}
```

This endpoint does not have a `confirm` field. Safety comes from calling the
separate preview endpoint first. A non-ready sync can still be returned as HTTP
`200`; callers must inspect `sync.status`, `pending`, `failed`, and
`current_state_indeterminate`.

## Evolution and shared lenses

Evolution writes use the collection configured by
`HYDRA_DB_EVOLUTION_COLLECTION`, which must differ from the current collection.

### `POST /api/evolution/checkpoints/{slot}`

`slot` is `before` or `after`. The body is exactly:

```json
{"revision_id":"abc123"}
```

Checkpoint capture writes a verified local checkpoint immediately. It does not
write HydraDB and intentionally does not accept `confirm`.

```json
{
  "status": "captured",
  "operation": "capture_checkpoint",
  "slot": "before",
  "repository_id": "my-repository",
  "revision_id": "abc123",
  "checkpoint_id": "checkpoint_before_0123456789abcdef01234567",
  "node_count": 20,
  "edge_count": 12,
  "writes_performed": true,
  "local_writes_performed": true,
  "hydradb_writes_performed": false,
  "warnings": []
}
```

The analyzed snapshot must exactly match the verified current manifest and
revision.

### `POST /api/evolution/publish`

```json
{
  "before_revision_id": "before",
  "after_revision_id": "after",
  "confirm": false
}
```

With `confirm: false` or omitted, the service deterministically builds the delta
cards and returns `status: preview`, `source_ids`, `source_count`, change counts,
and `writes_performed: false`. With `confirm: true`, it uploads and verifies all
cards. Only a `ready` result clears the local checkpoints. `unavailable` means no
write began; `indeterminate` means some write may have occurred and checkpoints
were retained.

### `POST /api/lenses`

Saves one grounded exact path from a stored HydraDB ProductView:

```json
{
  "name": "Authorization path",
  "purpose": "Keep the request-to-policy path visible.",
  "view_id": "view_opaque",
  "notes": null,
  "confirm": false
}
```

Limits are 200 characters for `name`, 2000 for `purpose`, 256 for `view_id`, and
4000 for `notes`. The preview returns the stable `lens_id`, source ID, saved
revision, selected anchors and edges, and `writes_performed: false`. Repeat with
`confirm: true` to write the shared lens to evolution. The view must contain a
connected exact path with valid evidence.

### `POST /api/lenses/{lens_id}/accept`

Accepts an updated grounded path returned by Preserve:

```json
{"view_id":"opaque-preserve-refresh-view","confirm":false}
```

The body accepts only `view_id` and `confirm`. The view ID must be the opaque
server-stored refresh view tied to this lens; an arbitrary client view is
rejected. Preview returns `previous_revision_id`, `saved_revision_id`, and
`writes_performed: false`. Repeat with `confirm: true` to update the shared lens.

All evolution/lens write previews are deterministic and perform no HydraDB
write. A confirmed response is trustworthy only when `status` is `ready`.

## Observe interactions and events

Observe requires a ready, available, non-indeterminate current revision.

### Start and complete a session

Use `POST /api/observe/sessions` to start and
`POST /api/observe/sessions/{session_id}/complete` to finish.

Both request bodies must be exactly `{}`:

```powershell
$session = Invoke-RestMethod "$baseUrl/api/observe/sessions" `
    -Method Post -ContentType "application/json" -Body "{}"

$sessionId = $session.session_id

Invoke-RestMethod "$baseUrl/api/observe/sessions/$sessionId/complete" `
    -Method Post -ContentType "application/json" -Body "{}"
```

Start returns HTTP `201` with `status: active`, the opaque `session_id`, concrete
`revision_id`, opaque `repository_root_fingerprint`, and the emitted
`session_started` event. Complete returns `status: completed` and the emitted
`session_completed` event.

### Record interactions with a stored view

Selection and evidence-opened use the same exact body:

```json
{"item_id":"node-or-edge-id","item_kind":"node"}
```

`item_kind` is `node` or `edge`; `item_id` is limited to 1024 characters.

| Route | Validation and event |
| --- | --- |
| `POST /api/views/{view_id}/selection` | Item must be shown in the active session's stored view; emits `context_selected`. |
| `POST /api/views/{view_id}/evidence-opened` | Item must be shown and have grounded source evidence; emits `evidence_opened`. |
| `POST /api/views/{view_id}/workspace-change` | Exact body `{ "path": "relative/path.py" }`; path max 1024, inside the selected root, and shown by visible nodes; emits `workspace_entity_changed` for matching entities only. |

Success returns:

```json
{
  "status": "recorded",
  "event": {
    "event_id": "event_opaque",
    "session_id": "session_opaque",
    "timestamp": "2026-08-14T16:00:00+00:00",
    "type": "context_selected",
    "revision_id": "abc123",
    "view_id": "view_opaque",
    "entity_ids": ["node-id"],
    "relationship_ids": [],
    "hydradb_query_metadata": null
  }
}
```

The full event also contains `session_id`, ISO timestamp, `revision_id`, optional
`view_id`, `entity_ids`, `relationship_ids`, and optional bounded HydraDB query
metadata. The server derives these fields; clients cannot submit event IDs or
arbitrary event metadata. Interaction calls do not mutate the stored ProductView.

### Read events

JSON polling requires a session ID:

```powershell
$events = Invoke-RestMethod "$baseUrl/api/events?session_id=$sessionId"
$lastEventId = $events[-1].event_id
$later = Invoke-RestMethod `
    "$baseUrl/api/events?session_id=$sessionId&after_event_id=$lastEventId"
```

`session_id` and optional `after_event_id` are each limited to 256 characters.
With a cursor, only later events are returned. A cursor from another session or
one no longer retained in the bounded history returns `409`; clients must not
silently treat that as a complete timeline.

`GET /api/events/stream` is the server-sent event stream and emits heartbeat
comments while idle. The extension uses session-scoped JSON polling because it
supports cursors and explicit history-gap handling.

## Mounted MCP

`/mcp` is a Streamable HTTP MCP application, not a REST JSON endpoint. It shares
the service's EventBus and ViewStore, so mounted tool queries can appear in
Observe and their ProductViews can be read by ID. MCP DNS-rebinding protection
accepts loopback hosts/origins only.

Configure an MCP client with:

```text
http://127.0.0.1:8765/mcp
```

Do not append another `/mcp`. See [MCP and agents](mcp-and-agents.md) for Codex,
Claude Code, tools, and session correlation.

## Error meanings

| Status | Meaning |
| --- | --- |
| `404` | Observe session, stored HydraDB view, or shown item was not found or expired. Removed raw service routes also return `404`. |
| `405` | The path exists but the method is unsupported, such as `POST /api/events`. |
| `409` | Current state conflicts with the operation: unverified Observe start, inactive/mismatched session, event-history gap, or refused checkpoint/evolution/lens domain operation. |
| `422` | JSON has extra/missing fields, invalid enum values, violates a budget/string bound, or supplies an invalid/unshown workspace path or evidence action. |
| `429` | The bounded active Observe-session limit was reached. |
| `503` | The optional evolution service is not configured in the service container. |

HydraDB unavailability and specialized retrieval degradation commonly return
HTTP `200` with explicit status, availability, warnings, and empty data. Index
and evolution write results likewise require checking their domain `status`; an
HTTP success alone is not a readiness claim.

## Deliberately unsupported raw routes

The service does not expose general HydraDB administration or caller-authored
events:

- `POST /api/ingest` — removed; returns `404`.
- `DELETE /api/context` — removed; returns `404`.
- `GET /api/status` — removed; returns `404`.
- `POST /api/events` — no event-write handler; returns `405`.

Use authenticated indexing, server-derived Observe interactions, and the
adapter's internal status/delete operations instead. Managed project scope
comes only from the project token; indexing bodies cannot replace it. No route
accepts raw Graph IR ingestion, delete IDs, or event envelopes.

Related guides: [Getting started](getting-started.md) ·
[Configuration](configuration.md) · [Indexing and sync](indexing-and-sync.md) ·
[Observe](observe.md) · [Trust and safety](trust-and-safety.md)
