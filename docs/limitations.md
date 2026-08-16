# Known limits and honest claims

[Documentation home](README.md) · [Trust and safety](trust-and-safety.md) · [Evaluation](evaluation.md) · [Troubleshooting](troubleshooting.md)

This page states what the current application does not promise. These limits are part of the product contract, not hidden implementation details.

## Parser coverage

The deterministic repository analyzer currently parses Python source. The VS Code extension is written in TypeScript, but that does not mean TypeScript repositories are analyzed.

Unsupported files can exist in the workspace without becoming invented graph nodes. Add a verified parser before claiming another language.

## HydraDB live proof

The code implements and fixture-tests the direct HydraDB API v2 contracts. This checked-out environment has not supplied live credentials, so it does not contain evidence of a credentialed end-to-end run.

Until a live run is captured, these remain provisional:

- exact relation-inspection behavior beyond query results;
- Memory behavior;
- collection replacement and deletion semantics under real partial failures;
- performance and indexing latency;
- graph-enabled retrieval improvements.

The service reports unavailable or unverified instead of substituting a local retriever.

## Synchronization is not transactional

HydraDB source writes and deletions are separate remote operations. If a request is partially accepted or status cannot be confirmed, the service marks the current collection as indeterminate.

The previous verified revision remains a marker of the last confirmed state. It is not a guarantee that every previous source is still visible after a partial remote mutation.

## Retrieval is focused, not exhaustive

Repository, Explore, and Trace are bounded HydraDB-backed views. They do not claim to enumerate every transitive relation in the repository. Node expansion may issue another targeted retrieval query.

Truncation and budgets are visible. Layout position and distance are presentation choices, not measures of importance or confidence.

## Exact and inferred relations

An exact relation must have deterministic provenance and source evidence. Dynamic Python behavior that cannot be resolved honestly is omitted or labeled inferred/unknown.

An inferred edge is not upgraded because it looks plausible. Inferred relations remain structurally and visually separate and are hidden by default.

## Observe scope

Observe records explicit application events:

- session lifecycle;
- repository MCP or service queries;
- HydraDB results returned;
- graph selections;
- evidence opened;
- edits to visible source-backed files.

It cannot observe hidden model reasoning or every file read performed through unrelated tools. The timeline replays explicit states; it does not provide timed hop-by-hop animation of internal agent reasoning.

Observe is bound to one revision and one canonical repository root. Revision drift, history gaps, ambiguous sessions, or a different root stop the session and require restart.

## Compare history

The MVP stores one local `before` checkpoint and one local `after` checkpoint. It does not reconstruct arbitrary Git history or use local checkpoints for retrieval.

Published change records live in the HydraDB `evolution` Knowledge collection. Current code and evolution records are queried separately; the app does not claim cross-collection graph traversal.

## System Lenses

The MVP supports one shared Knowledge-backed System Lens workflow. It does not claim personal Memory-backed lenses, cross-device layout synchronization, or multiple-user conflict resolution.

Accepting drift updates the saved baseline only after an explicit review and confirmation.

## Evaluation claims

Offline fixtures test contracts and rehearse artifact generation. They are not performance evidence.

The checked Codex and Claude Code manifests are incomplete templates. The preflight intentionally fails until real live retrieval and observable agent-outcome files are attached.

Do not make a “better” or percentage claim unless all questions, all three conditions, the exact gold digest, the baseline corpus digest, the live service identity, and both agent runs pass preflight.

## Security boundary

The service binds to loopback only and still authenticates managed REST and MCP calls. It is not designed to be exposed directly to a network.

Indexed identity migration is deliberately conservative. HydraDB v2 does not currently give this product a proven exhaustive metadata-delete operation for both current and evolution sources. Argus therefore migrates an unindexed local identity, but preserves an indexed legacy identity rather than silently orphaning records.

The packaged release supports local VS Code desktop on Windows, macOS, and Linux x64/ARM64. Web, Codespaces, Remote SSH, WSL-hosted extension processes, Alpine, and ARMHF are not supported.

See [Trust and safety](trust-and-safety.md) before changing the bind address, authentication, or routes that mutate HydraDB.
