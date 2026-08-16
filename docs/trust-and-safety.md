# Trust and safety

Argus handles repository source, a HydraDB API key, a project database binding, and coding-agent authorization. Its security model separates ordinary extension state, OS-backed secret storage, private local IPC, authenticated loopback APIs, and HydraDB HTTPS.

## SecretStorage boundary

VS Code SecretStorage contains:

- account profile API keys;
- project database bindings;
- installation control material;
- OAuth client, code, access, and refresh records.

Ordinary workspace/global state contains only opaque IDs, profile labels, and non-sensitive preferences. Project state contains only a repository ID and fingerprints. Secrets are not synchronized between machines.

Stored key and database values are never revealed. Rotation means entering a replacement.

## Credentials during a request

For each HydraDB operation:

1. Python requests the binding for one normalized repository ID over private IPC.
2. TypeScript reads the project binding and selected profile from SecretStorage.
3. TypeScript sends the key and database in one framed IPC response.
4. Python performs one HTTPS HydraDB operation.
5. Both sides release their references.

There is no process-lifetime credential cache. JavaScript and Python cannot guarantee physical zeroization of immutable strings, so credentials do briefly exist in process memory. The supported guarantee is no unsafe persistence and no long-lived cache.

Managed service children receive no HydraDB key or database in argv, environment variables, files, HTTP setup bodies, or webview messages. The managed binary ignores inherited `HYDRA_DB_*` values.

## Database disclosure controls

Database names do not appear in health, query responses, ProductViews, events, MCP results, sidebars, status bars, sync manifests, or evolution records. The sync manifest uses a keyed fingerprint to detect the wrong binding.

Legacy manifests containing a plaintext `database` field are rewritten atomically without that field. If the current secret binding cannot produce a matching fingerprint, the state is not trusted as verified.

Public HydraDB errors are generic. A remote response that echoes a credential or database cannot be copied into a warning, API response, MCP result, or service log.

## Project boundary

The selected VS Code folder is resolved with `realpath` and remains the scan boundary. A higher Git root may contribute origin/subpath identity, but it never broadens discovery. Deleted roots, non-file URI schemes, paths outside the opened folder, secret-like filenames, binary/oversized files, and symlink escapes are rejected or ignored.

Git remote credentials, queries, and fragments are removed before hashing. The raw remote is not persisted or returned.

## Local service authentication

Only `/version` is unauthenticated discovery. Managed REST requests use short-lived random bearer tokens issued after an HMAC-signed challenge. Each grant is bound to one canonical root and repository ID.

The server rejects:

- remote bind/host values and DNS rebinding;
- missing, expired, replayed, or wrong-project tokens;
- root substitutions;
- oversized bodies;
- excessive per-token request rates;
- version mismatches;
- write confirmations with stale snapshots.

Developer mode is a separate explicit path and must not be treated as the Marketplace security boundary.

## MCP OAuth

MCP does not reuse REST project tokens. It uses OAuth 2.1 dynamic registration, PKCE S256, short codes, short access tokens, rotating refresh tokens, and revocation. Redirect URIs must be loopback HTTP. Only read scopes are supported.

First authorization passes through a nonce-only VS Code URI. The native consent UI shows the client, selected project, and scopes. Multiple open projects require explicit selection. Token subjects resolve an exact registered repository service; ambiguity fails closed.

Agent configuration contains only the loopback `/mcp` URL. HydraDB secrets and static bearer tokens never appear there.

## Write safety

Index, evolution publication, System Lens save, and drift acceptance use preview-before-confirmation. Index previews are single-use, expire, and bind the canonical project, repository ID, revision, file snapshot, and source-card scope. A changed file invalidates confirmation.

HydraDB source replacement is not transactional. Partial ingest, status, or deletion marks current state indeterminate. The previous revision remains only the last verified marker, not a promise that the old state is fully queryable.

## Evidence and retrieval truth

- HydraDB is the production retrieval substrate.
- No unavailable query is replaced by local search.
- Exact edges require BYOG origin plus a valid deterministic evidence envelope.
- Malformed or automatic relations are downgraded or omitted.
- Views are bounded; they are not presented as exhaustive architecture.
- Observe records explicit events only, never hidden model reasoning.

## Known proof boundary

Automated tests and offline fixtures prove contracts but not the live HydraDB service. Release acceptance still requires credentialed staging on every supported platform plus current Codex and Claude Code OAuth tests. See [Known limits](limitations.md) and [Packaging and distribution](distribution.md).
