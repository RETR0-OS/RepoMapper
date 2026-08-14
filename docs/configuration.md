# Configuration

Normal users configure Repository Map in VS Code. Marketplace use has no required environment variables or service URL.

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

| Setting | Default | Meaning |
| --- | ---: | --- |
| `hydra.requestTimeoutMs` | `5000` | Read/query timeout for the managed loopback service. |
| `hydra.indexTimeoutMs` | `120000` | Local analysis and indexing timeout. |
| `hydra.developerMode` | `false` | Use a separately started service. Development only. |
| `hydra.developerServiceUrl` | `http://127.0.0.1:8765` | Loopback URL used only when developer mode is enabled. |

The normal service URL is managed automatically. If port 8765 belongs to an unrelated process, Repository Map chooses a stable alternate loopback port and later agent registrations use that port.

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
