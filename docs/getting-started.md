# Getting started

Hydra Repository Map analyzes a Python repository, uploads source cards and exact
relations to HydraDB, and serves bounded HydraDB results to VS Code and MCP
clients. Production queries do not fall back to a local graph or the test
fixtures.

## Requirements

- Python 3.11 or newer
- Node.js 20 or newer
- VS Code 1.96 or newer
- A HydraDB API key and database for live indexing and retrieval

## Install

Open PowerShell in the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

Push-Location .\extension
npm install
npm run build
Pop-Location
```

If PowerShell blocks the activation script, see
[Troubleshooting](troubleshooting.md#powershell-blocks-virtual-environment-activation).

## Configure this PowerShell session

Replace the first two values and choose a stable repository ID:

```powershell
$env:HYDRA_DB_API_KEY = "your-key"
$env:HYDRA_DB_DATABASE = "your-database"
$env:HYDRA_DB_COLLECTION = "current"
$env:HYDRA_DB_EVOLUTION_COLLECTION = "evolution"
$env:HYDRA_REPOSITORY_ID = "your-repository"
$env:HYDRA_REPOSITORY_ROOT = (Get-Location).Path
```

The service reads its process environment. It does not load `.env` files
automatically. [`.env.example`](../.env.example) lists every supported setting;
[Configuration](configuration.md) explains the defaults and validation rules.

## Preview and index

Choose an explicit revision ID. A commit SHA is a good choice when one exists.
Preview performs local analysis and shows the upload scope. It does not contact
HydraDB.

```powershell
python -m hydra_graph index --revision "demo-before-change" --preview
```

Review the configured root, discovered files, source count, and exact relation
count. Then run the write:

```powershell
python -m hydra_graph index --revision "demo-before-change"
```

Do not treat a process exit by itself as proof of a ready index. Read the
returned `sync.status`, `sync.ready_revision`, and
`sync.current_state_indeterminate` fields. See
[Indexing and sync](indexing-and-sync.md) for their meaning.

## Start the service

```powershell
python -m hydra_graph serve
```

The service listens on `http://127.0.0.1:8765`. It deliberately has no public
bind option. In another PowerShell window, check it:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health | ConvertTo-Json -Depth 5
```

A newly configured process can report `unverified` until it has loaded a
persisted verified manifest or completed an index. `ready` means this process
has a concrete verified revision marker. It is not a general proof that every
live HydraDB behavior has been independently validated; see
[Trust and safety](trust-and-safety.md#what-has-not-been-proved-live).

## Open the extension

In a second PowerShell window at the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
code --extensionDevelopmentPath="$PWD\extension"
```

In the Extension Development Host, open the Repository Map activity item or run
`Repository Map: Open Repository Map`. The default service URL is
`http://127.0.0.1:8765`.

The command `Repository Map: Index Workspace with HydraDB` runs the same local
preview, asks for confirmation, and then indexes. The caller cannot choose a
different filesystem root; the service always uses `HYDRA_REPOSITORY_ROOT`.

## Connect an agent

The running service mounts MCP at `http://127.0.0.1:8765/mcp`. Use the mounted
endpoint when you want agent queries to appear in Observe. Setup examples are in
[MCP and agents](mcp-and-agents.md).

## Verify the checkout

```powershell
.\scripts\check.ps1
```

This runs Python lint and tests, TypeScript checks and tests, the extension
build, npm audit, and a package dry run. Automated HydraDB fixtures are transport
contract tests, not evidence of a credentialed live HydraDB run.

Next: [Configuration](configuration.md) ·
[Indexing and sync](indexing-and-sync.md) ·
[Troubleshooting](troubleshooting.md)
