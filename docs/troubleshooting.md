# Troubleshooting

Start with these checks from the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
python --version
python -m hydra_graph --help
python -m hydra_graph serve --help
python -m hydra_graph index --help
```

With the service running:

```powershell
$health = Invoke-RestMethod http://127.0.0.1:8765/health
$health | ConvertTo-Json -Depth 5
```

## `hydra-graph` is not recognized

Activate the virtual environment and install the project in editable mode:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m hydra_graph --help
```

All documented CLI operations work through `python -m hydra_graph`, even when
the `hydra-graph` console alias is not on `PATH`.

## PowerShell blocks virtual-environment activation

Use a process-only execution policy, which expires when the PowerShell process
closes:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Or call the virtual environment's Python directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m hydra_graph --help
```

## Health is `unavailable`

If the message names `HYDRA_DB_API_KEY` and `HYDRA_DB_DATABASE`, set both in the
same PowerShell session that starts the service:

```powershell
$env:HYDRA_DB_API_KEY = "your-key"
$env:HYDRA_DB_DATABASE = "your-database"
python -m hydra_graph serve
```

The service does not automatically load [`.env.example`](../.env.example) or a
local `.env` file. If credentials are set and a request still fails, check
network access, `HYDRA_DB_API_URL`, and the returned error. The adapter retries
network errors, `429`, `500`, `502`, and `503` within its configured budget. It
does not hide a final failure with local data.

## Health is `unverified`

Credentials are configured, but this process has not verified a concrete
current revision. Run a preview and complete an index:

```powershell
$revision = (git rev-parse HEAD).Trim()
python -m hydra_graph index --revision $revision --preview
python -m hydra_graph index --revision $revision
```

Then confirm `/health` reports `state: ready`, `revision_verified: true`, and the
expected revision. A missing `.hydra-graph/manifest.json` means a new process
cannot claim the prior verified state. An invalid manifest makes startup fail
closed; inspect the reported file problem, preserve the bad file for diagnosis,
and run a complete fresh index rather than editing it to force `ready`.

## Health is `indexing`

Wait for the bounded indexing operation to finish. Current queries are
deliberately gated while source upserts and status checks may expose a mixed
candidate/current state. If polling reaches
`HYDRA_DB_POLL_TIMEOUT_SECONDS`, the operation fails honestly rather than
returning local analyzer results.

## Health is `failed` or the collection is indeterminate

Read the index response fields `failed`, `pending`, `warning`, and
`current_state_indeterminate`. Do not assume `ready_revision` means its old
content is still fully visible: it is only the last verified marker.

Fix the credential, network, HydraDB response, deletion, or manifest-write
problem. Then preview and index one complete repository snapshot again:

```powershell
python -m hydra_graph index --revision "recovery-snapshot" --preview
python -m hydra_graph index --revision "recovery-snapshot"
```

There is no claimed transactional rollback. Do not manually edit the manifest
to force `ready`.

## Index preview points at the wrong repository

Stop the service, set an absolute root, and restart:

```powershell
$env:HYDRA_REPOSITORY_ROOT = (Resolve-Path "C:\src\expected-repository").Path
$env:HYDRA_REPOSITORY_ID = "expected-repository"
python -m hydra_graph serve
```

The indexing API cannot override this root. `/health` returns an opaque
`repository_root_fingerprint`, not the path. A fingerprint mismatch prevents
the extension from sending workspace-change events for a different checkout.

## Current and evolution collections conflict

They must be distinct and nonblank:

```powershell
$env:HYDRA_DB_COLLECTION = "current"
$env:HYDRA_DB_EVOLUTION_COLLECTION = "evolution"
python -m hydra_graph serve
```

Using one collection would blur current repository truth with change-event and
lens records, so startup fails instead of accepting it.

## The extension cannot reach the service

Confirm the service and its loopback URL:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health
```

In VS Code Settings, check `hydra.serviceUrl`. It must be a local loopback URL
and normally should be `http://127.0.0.1:8765`. If indexing is slow but healthy,
increase `hydra.indexTimeoutMs` within its allowed range rather than the ordinary
request timeout.

If the Python service cannot be reached, the extension may show a clearly
labeled interaction preview. That UI preview is not returned by the Python
service or MCP and is not HydraDB evidence.

## MCP client cannot connect

Use the mounted URL exactly:

```text
http://127.0.0.1:8765/mcp
```

Common mistakes are using `/mcp/mcp`, connecting before `python -m hydra_graph
serve` is running, or using a non-loopback hostname rejected by transport
security. Check the registration:

```powershell
codex mcp list
claude mcp list
```

For Observe, do not replace the mounted endpoint with a standalone stdio process;
the processes do not share events or views. See [MCP and agents](mcp-and-agents.md).

## Observe rejects a session, event cursor, or workspace change

- Unknown sessions return `404`.
- Completed sessions, revision conflicts, and missing event history return
  `409`.
- Too many active sessions return `429`.
- Unknown/expired views, unshown items, path traversal, paths outside the
  selected root, and workspace-root fingerprint mismatches are rejected.
- A history-gap response means the bounded event buffer no longer contains the
  supplied cursor. Start a new Observe session rather than silently treating a
  partial timeline as complete.

## Compare or Preserve returns no specialized data

Compare needs a complete, published change-event record for the exact before and
after revisions. Preserve needs a valid saved lens plus a separately retrieved
current exact path. Generic chunks, incomplete change pages, ignored filters,
malformed records, or missing exact evidence are omitted or degraded; they are
not relabeled to make the view look successful.

Check the response `warnings`, `hydradb.collections`, and availability. Local
checkpoints are never used as a Compare retrieval fallback.

## Run the local checks

```powershell
.\scripts\check.ps1
```

This proves the checked code and mocked transport contracts pass locally. It
does not prove live HydraDB behavior. See
[Trust and safety](trust-and-safety.md#what-has-not-been-proved-live).
