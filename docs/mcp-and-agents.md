# MCP and agents

The recommended agent connection is the Streamable HTTP MCP endpoint mounted in
the running service:

```text
http://127.0.0.1:8765/mcp
```

The mounted tools share the same bounded view store and event bus as the VS Code
extension. That shared process is required for agent tool activity to appear in
Observe.

## Start the shared service

Set the environment described in [Configuration](configuration.md), then run:

```powershell
python -m hydra_graph serve
```

Confirm the advertised endpoint:

```powershell
$health = Invoke-RestMethod http://127.0.0.1:8765/health
$health.mcp_endpoint
```

The result should be `/mcp`. Do not add a second `/mcp`; the client URL is not
`/mcp/mcp`.

## Codex

Add this to the user-level `~/.codex/config.toml` or a trusted project's
`.codex/config.toml`:

```toml
[mcp_servers.hydra-repository]
url = "http://127.0.0.1:8765/mcp"
```

Then verify the registration:

```powershell
codex mcp list
```

Restart or reload the Codex client if it was already running when the
configuration changed.

## Claude Code

From the trusted project:

```powershell
claude mcp add --scope project --transport http hydra-repository http://127.0.0.1:8765/mcp
claude mcp list
```

Project scope makes the repository-local choice visible and reviewable. Use a
different supported Claude Code scope only when that is intentional.

## Available tools

| Tool | Purpose | Important boundary |
| --- | --- | --- |
| `repository_query` | Ask a conceptual repository question with hybrid HydraDB graph retrieval. | Returns bounded ranked HydraDB context, not a full repository dump. |
| `focus_symbol` | Focus literal retrieval on a known symbol or path. | Does not promise exhaustive callers, callees, or neighbors. |
| `trace_flow` | Request bounded multi-hop paths in thinking mode. | Hop, path, relation, result, and context budgets are enforced. |
| `explain_relationship` | Explain a relationship already returned in a stored view. | Returns `not_found` when the relationship is outside that bounded result. |
| `compare_repository_graph` | Retrieve a published change event for two revisions. | Queries only the evolution collection; generic chunks cannot masquerade as change records. |
| `open_system_lens` | Retrieve a shared lens and a separately grounded current path. | Uses sequential single-collection queries, not cross-collection traversal. |
| `pin_context` | Record an explicit programmer selection and instruction. | Emits context telemetry; it does not modify structural graph facts. |

Tool results expose `hydradb.available`, explicit collection names, rank/path
identifiers, budgets, warnings, and a response schema. If HydraDB is unavailable,
the result is empty and says so. Agents must not replace it with a local search
and present that search as a HydraDB result.

## Observe correlation

Start Observe from the extension before an agent query. When an MCP tool omits
`session_id` and exactly one Observe session is active, the mounted server binds
the tool event to that session automatically. With no active session, the query
still works but is not attached to an Observe session. With multiple active
sessions, omission is ambiguous and the tool fails instead of guessing.

An explicit MCP `session_id` remains a valid independent agent correlation ID.
If it names a known completed Observe session, it is rejected. This differs from
the public `/api/query` route, where a supplied session ID must be a known active
Observe session with a compatible verified revision before any HydraDB request.

Observe shows domain events and returned paths. It does not expose or claim an
agent's hidden chain of thought. Event history is bounded; cursor polling reports
a history gap instead of silently resetting when retained events have overflowed.

## Standalone MCP

For simple tool use without shared Observe state:

```powershell
python -m hydra_graph mcp --transport stdio
```

The CLI also accepts `sse` and `streamable-http` transports:

```powershell
python -m hydra_graph mcp --transport streamable-http
```

These commands create another Python process. Its event bus and stored views are
not the ones used by a separately running FastAPI service, so it cannot feed that
service's Observe timeline. Prefer the mounted `/mcp` endpoint for the product
workflow.

## Local transport security

The service binds to `127.0.0.1`. The mounted MCP transport keeps DNS rebinding
protection enabled and allows only loopback host/origin forms for
`127.0.0.1`, `localhost`, and `[::1]`. HydraDB credentials remain in the Python
process and are not MCP arguments or webview data.

If setup fails, see [MCP troubleshooting](troubleshooting.md#mcp-client-cannot-connect).
The broader data and evidence boundaries are in
[Trust and safety](trust-and-safety.md).
