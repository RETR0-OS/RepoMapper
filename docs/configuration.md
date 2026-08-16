# Configuration

Normal users configure Argus in VS Code. Marketplace use has no required environment variables or service URL.

## Secret account profiles

An account profile contains:

- a visible, non-sensitive label;
- one HydraDB API key in VS Code SecretStorage.

The label may appear in normal extension state. The key may not. Profiles can be reused across projects.

## Secret project bindings

Each repository identity maps to:

- a selected account profile ID;
- one database name in SecretStorage.

Only opaque profile IDs and repository IDs appear in ordinary state. Database names are not shown after entry and are not synchronized between machines.

## Extension settings

| Setting | Default | Maximum | Meaning |
| --- | ---: | ---: | --- |
| `hydra.requestTimeoutMs` | `30000` | `120000` | Read/query timeout for the managed loopback service. |
| `hydra.indexTimeoutMs` | `300000` | `1800000` | Repository analysis timeout and the timeout of each index-job status request. |
| `hydra.developerMode` | `false` | — | Use a separately started service. Development only. |
| `hydra.developerServiceUrl` | `http://127.0.0.1:8765` | — | Loopback URL used only when developer mode is enabled. |

`hydra.requestTimeoutMs` was `5000` with a `30000` cap. A read makes the service
run a HydraDB `thinking`-mode query, and 5 seconds is below the real latency of
that query, so normal reads were cancelled before HydraDB answered.

`hydra.indexTimeoutMs` was `120000` with a `600000` cap. It no longer bounds the
whole upload, because the upload is now a background job in the service. It
bounds the two calls the extension actually waits for: local repository analysis
and each single job-status request.

The normal service URL is managed automatically. If port 8765 belongs to an unrelated process, Argus chooses a stable alternate loopback port and later agent registrations use that port.

## Service indexing limits

These are service-side values. The managed binary uses the defaults; only the
explicit developer runtime below can set them from the environment.

| Variable | Default | Meaning |
| --- | ---: | --- |
| `HYDRA_DB_POLL_TIMEOUT_SECONDS` | `1800` | How long the service waits for HydraDB to finish graph creation for one candidate revision. Raised from `120`: a large repository needs far longer than two minutes to finish indexing every source. |
| `HYDRA_DB_STATUS_BATCH_SIZE` | `100` | How many source IDs go in one `GET /context/status` call. Must be between 1 and 500. |
| `HYDRA_DB_RELATION_SOURCES` | `12` | How many of the returned sources have their stored graph read. A query returns a few relation groups and ranks HydraDB's own concept relations beside this repository's, so the graph is read per source instead. Each source costs one request. |
| `HYDRA_DB_RELATION_WORKERS` | `8` | How many stored-graph reads run at the same time. |
| `HYDRA_DB_COMPLETION_SOURCES` | `10` | How many connecting records one question may fetch. A relation is shown only when every chunk it cites came back in the same answer, and the code that joins two matched symbols is rarely a word match for the question. The stored graph names those endpoints, so they are fetched by name and the graph is grounded again. Costs one further query. Set `0` to disable it and accept a more disconnected graph. |
| `HYDRA_DB_MAX_RETRIES` | `2` | Additional attempts for rate limits and retryable server failures. |
| `HYDRA_DB_RETRY_BACKOFF_SECONDS` | `0.25` | Exponential retry delay when HydraDB does not provide a longer `Retry-After` delay. |

Ingest batches stay at 25 source cards. The status batch is separate and larger
because a status call only asks about state. Status polling asks about the
sources that have not finished yet, so the question set shrinks on every cycle.
An HTTP 429 honors HydraDB's bounded `Retry-After` delay (or the equivalent
"retry in N seconds" response message) before using another attempt.

## Repository identity state

`.hydra-graph/identity.json` stores only:

- the schema version;
- the public repository ID;
- whether it came from a Git origin, a generated local identity, or legacy state;
- an optional SHA-256 origin fingerprint.

It never stores the remote URL, API key, or database. The extension workspace binding contains the same opaque repository ID.

For Git projects, the public ID uses a sanitized repository name and the first 20 characters of the normalized origin SHA-256. HTTPS, SSH, and SCP-style forms normalize to the same identity. A separately opened subproject adds a stable hash of its Git-relative path.

For non-Git projects, a random UUID is generated once. Moving the folder preserves the identity because the checked project state wins over its path.

## Developer runtime only

Contributors may run the service separately and use environment-based credentials. This path is explicit and is not used by the packaged extension:

```powershell
$env:HYDRA_DB_API_KEY = "development-only"
$env:HYDRA_DB_DATABASE = "development-only"
python -m hydra_graph serve
```

The managed binary ignores all `HYDRA_DB_*` environment variables. Never tell end users to configure them.

## What cannot be configured

Users cannot disable preview/confirmation, broaden the project root, expose the service beyond loopback, place a bearer token in MCP configuration, or enable local fallback retrieval. These are security and truth boundaries, not preferences.
