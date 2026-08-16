# MCP and coding agents

Argus exposes one Streamable HTTP MCP endpoint inside the managed service. It is not a second process and it is available only while VS Code is running.

## Configure an agent

Run **Argus: Configure Agents**. The extension:

1. starts or attaches to the managed service;
2. detects `codex` and `claude` without changing configuration;
3. shows the exact commands for the installed clients;
4. lets you select one or both;
5. asks for confirmation;
6. runs each client's supported command with an argument array, not a shell;
7. removes `HYDRA_DB_*` values from the child environment.

The current command shapes are:

```text
codex mcp add repository-map --url http://127.0.0.1:<port>/mcp
claude mcp add --transport http --scope local repository-map http://127.0.0.1:<port>/mcp
```

The port is discovered at runtime. No HydraDB key, database, static bearer token, project root, or repository remote is written to agent configuration.

## First authorization

Codex and Claude Code discover the OAuth server from the MCP endpoint. Authorization uses:

- dynamic client registration;
- PKCE S256;
- 60-second single-use authorization codes;
- five-minute access tokens;
- rotating one-day refresh tokens;
- token-family revocation;
- read-only scopes by default.

The service asks VS Code for consent through private IPC. VS Code creates a random, one-time URI containing only an in-memory request ID, routes it through the extension URI handler, and opens native project/scope consent. Client details and grant material do not appear in that URI.

If more than one project has attached to the service, choose the project explicitly. The issued token subject is that repository ID and each tool resolves the matching service container. A missing, ambiguous, or closed project fails closed.

## Scopes

The available scopes are:

- `repository:read` — bounded repository queries and views;
- `evidence:read` — source-backed relation explanation;
- `observe:read` — explicit Observe correlation and view events.

There is no MCP indexing, deletion, credential, or identity-migration scope in this release.

## Tools

- `repository_query` — hybrid HydraDB repository question.
- `focus_symbol` — bounded literal retrieval around a known entity.
- `trace_flow` — bounded multi-hop HydraDB path.
- `explain_relationship` — evidence for an edge already present in a stored view.
- `compare_repository_graph` — evolution Knowledge for two revisions.
- `open_system_lens` — a shared lens record and its current grounded path.
- `pin_context` — explicit programmer-selected context in an active Observe session.

Every tool is HydraDB-backed. Missing credentials or unavailable retrieval returns an explicit empty result, not local search.

## Observe correlation

MCP and VS Code share the same event bus and bounded view store because they share one process. With one active Observe session, an omitted session ID is correlated automatically. Multiple active sessions are ambiguous and rejected before HydraDB I/O.

Observe records explicit queries, returned context, selections, evidence opens, and visible file edits. It does not expose chain of thought or hidden agent reasoning.

## Revocation and availability

OAuth client and grant records are brokered into VS Code SecretStorage. Python keeps no process-lifetime grant cache. Revocation removes the token family. Closing the final VS Code window stops the service, so MCP becomes unavailable even if an agent still has an unexpired token.

Developer mode may run standalone stdio MCP for testing. It cannot feed the managed service's Observe timeline and is not part of the Marketplace setup.
