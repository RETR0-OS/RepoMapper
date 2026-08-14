# Configuration

The Python service reads environment variables when the process starts. The
repository includes [`.env.example`](../.env.example) as a reference, but the
service does not load it automatically.

## HydraDB settings

| Variable | Required | Default | Meaning |
| --- | --- | --- | --- |
| `HYDRA_DB_API_KEY` | Yes for live use | none | HydraDB bearer credential. Missing credentials produce an explicit unavailable state. |
| `HYDRA_DB_DATABASE` | Yes for live use | empty | HydraDB database used by all requests. |
| `HYDRA_DB_COLLECTION` | No | `current` | Current repository collection. Must be nonblank and different from the evolution collection. |
| `HYDRA_DB_EVOLUTION_COLLECTION` | No | `evolution` | Change-event and shared-lens collection. Must be nonblank and different from the current collection. |
| `HYDRA_DB_API_URL` | No | `https://api.hydradb.com` | HydraDB API base URL. A trailing slash is removed. |
| `HYDRA_DB_TIMEOUT_SECONDS` | No | `20` | Timeout for one HydraDB HTTP request. Must be greater than zero. |
| `HYDRA_DB_MAX_RETRIES` | No | `2` | Additional attempts for network failures and retryable responses. Must be zero or greater. |
| `HYDRA_DB_RETRY_BACKOFF_SECONDS` | No | `0.25` | Base retry backoff. Must be zero or greater. |
| `HYDRA_DB_POLL_INTERVAL_SECONDS` | No | `1` | Delay between bounded index-status polls. Must be greater than zero. |
| `HYDRA_DB_POLL_TIMEOUT_SECONDS` | No | `120` | Maximum status-poll time for an index operation. Must be greater than zero. |

The adapter retries network failures and HTTP `429`, `500`, `502`, and `503`.
It does not retry request/authentication errors such as `400`, `401`, `403`,
`404`, `409`, or `413`.

## Repository settings

| Variable | Required | Default | Meaning |
| --- | --- | --- | --- |
| `HYDRA_REPOSITORY_ID` | Recommended | database name, or `unconfigured-repository` without one | Stable logical repository identity stored in cards, manifests, checkpoints, and views. The example file suggests `hack-hydra`; that is not a hard-coded runtime default. |
| `HYDRA_REPOSITORY_ROOT` | Recommended | process working directory | The only directory the analyzer and indexing API may inspect. Prefer an absolute path. |

Set an absolute root before starting the service from another directory:

```powershell
$repositoryRoot = (Resolve-Path "C:\src\my-repository").Path
$env:HYDRA_REPOSITORY_ROOT = $repositoryRoot
$env:HYDRA_REPOSITORY_ID = "my-repository"
python -m hydra_graph serve
```

The service resolves the root before use. `/health` exposes the repository ID
and a deterministic SHA-256 `repository_root_fingerprint`, never the absolute
path. The extension uses the fingerprint to prove that its workspace and the
service refer to the same canonical root before reporting workspace-change
events.

Sync bookkeeping is saved at `.hydra-graph/manifest.json` inside the configured
root. Manifest and checkpoint paths are containment-checked after path
resolution, including symlinks. `.hydra-graph/` is ignored by Git.

## PowerShell example

Environment variables apply to the current process and child processes:

```powershell
$env:HYDRA_DB_API_KEY = "your-key"
$env:HYDRA_DB_DATABASE = "your-database"
$env:HYDRA_DB_COLLECTION = "current"
$env:HYDRA_DB_EVOLUTION_COLLECTION = "evolution"
$env:HYDRA_REPOSITORY_ID = "my-repository"
$env:HYDRA_REPOSITORY_ROOT = (Resolve-Path ".").Path
$env:HYDRA_DB_TIMEOUT_SECONDS = "20"
$env:HYDRA_DB_POLL_TIMEOUT_SECONDS = "120"

python -m hydra_graph serve
```

Do not commit a real API key. Do not put it in VS Code webview settings or MCP
tool arguments. It belongs in the Python service process.

## VS Code settings

| Setting | Default | Allowed range | Meaning |
| --- | --- | --- | --- |
| `hydra.serviceUrl` | `http://127.0.0.1:8765` | loopback HTTP URL | Local Python service URL. |
| `hydra.requestTimeoutMs` | `5000` | 500–30000 | Timeout for ordinary local service requests. |
| `hydra.indexTimeoutMs` | `120000` | 5000–600000 | Timeout for analysis and indexing requests. |

Use VS Code Settings and search for `Repository Map` to change these values.
Keep the URL on loopback. The Python service itself binds only to `127.0.0.1`.

## Configuration is not verification

The service is allowed to start without credentials so it can report an honest
`unavailable` state. With credentials but no verified manifest, `/health`
reports `unverified`, not `ready`. See [Indexing and sync](indexing-and-sync.md)
for the full state table and [Trust and safety](trust-and-safety.md) for the
security boundaries.
