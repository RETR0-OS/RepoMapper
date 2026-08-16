# Troubleshooting

This guide starts with the packaged extension. Developer-only problems are at the end.

## Diagnose the managed service without VS Code

Do not install the package to find a service fault. This command drives the same
path the extension drives, and shows each step:

```bash
node scripts/diagnose_managed.mjs
```

It starts the bundled service, completes the private IPC handshake, serves
credentials the way the VS Code vault does, attaches with a signed challenge, and
calls `/health` and `/api/setup/test`. Each stage reports PASS or FAIL. The exit
code is 1 if any stage fails. Without `--index` every call is read-only; nothing
is written to HydraDB.

| Option | Effect |
| --- | --- |
| `--http` | Also trace each HydraDB request the service makes. |
| `--no-credentials` | Refuse each credential request, as an unconfigured project does. |
| `--index` | Also run the real indexing path. **This writes to HydraDB.** See below. |
| `--cancel-after <seconds>` | With `--index` only: cancel the job after this many seconds and check that it reaches `cancelled`. |
| `--root <path>` | Attach a different repository root. |
| `--bundle <path>` | Test a different service bundle, such as one extracted from a package. |
| `--env <path>` | Read `HYDRA_DB_API_KEY` and `HYDRA_DB_DATABASE` from a different file. |
| `--port <number>` | Use a different loopback port. |
| `--quiet` | Show stage results only. |

The transcript shows each IPC frame, each service log line, and each HTTP request
with its status and body. Secrets are never printed: a key appears only as a
length and a short fingerprint.

### Test the indexing path

```bash
node scripts/diagnose_managed.mjs --index
node scripts/diagnose_managed.mjs --index --cancel-after 20
```

`--index` uploads the repository for real. It never runs unless you pass the
flag, and it prints a one-line warning that names the target database before it
starts. Do not point it at a database whose content matters.

It calls `POST /api/index/preview`, prints the source and batch counts, calls
`POST /api/index`, then polls `GET /api/index/jobs/{job_id}` about once a second
and shows one progress line — phase, uploaded batches out of total, verified
sources out of total. It adds three stages:

| Stage | Passes when |
| --- | --- |
| Index preview reports a revision | The preview returns a revision and a preview token. |
| Index job starts | Confirmation returns HTTP `202` and a job ID. |
| Index job reaches a verified revision | The job ends `completed`, its `result.sync` is `ready`, `ready_revision` equals `candidate_revision`, and nothing is pending or failed. |

With `--cancel-after`, the last stage becomes **Index job reaches the cancelled
state** instead: the script calls `POST /api/index/jobs/{job_id}/cancel` at that
time and then checks the job ends `cancelled`. That is the only way to exercise
the cancellation path without VS Code. Remember that cancelling does not remove
the batches already uploaded.

Keep the service running for the whole run. The job lives in the service process
only; killing the service loses the job record, and the script then fails the
stage instead of waiting.

To trace HydraDB requests inside VS Code instead, start VS Code with
`HYDRA_DEBUG_HTTP=1` and open **Output: Argus Service**. That variable adds
the local failure text of each attempt. The method, address, attempt, duration, and
outcome are always recorded, with or without it.

## Read the query funnel

Every query writes one line to **Output: Argus Service**. The line names
the time of each stage and the count at each stage. It holds no repository content
and no credential.

```
hydra.query session=session_… view=view_… status=ready outcome=all_groups_ungrounded
  ms.verified_revision=2.1 ms.hydradb_query=31840.2 ms.normalize=12.4 ms.total=31861.0
  n.raw_chunks=8 n.raw_paths=3 n.dropped_paths=3 n.kept_paths=0 n.hops=0
```

Read `ms.` to find where the time went, and `n.` to find where the graph was lost:

| Reading | Meaning | Correction |
| --- | --- | --- |
| `ms.hydradb_query` holds nearly all of `ms.total` | HydraDB itself is slow | Compare it with the `HYDRA_DB_TIMEOUT_SECONDS` budget. A `hydra.hydradb` line with `outcome=timeout` proves the budget expired first. |
| `hydra.ipc` lines are slow, or many appear for one query | The VS Code credential channel is the cost, not HydraDB | The extension host is busy. Report the count and the `ms` values. |
| `hydra.hydradb.retry` lines appear | One answer became several waits | The caller waits the retry delay plus a further full timeout for each line. |
| `ms.total` is small but the panel showed a timeout | The runtime handshake is the cost | The timeout message names that time separately, because the handshake runs outside the request budget. |
| `n.raw_chunks=0` | HydraDB matched no source | Narrow the question, or use a literal file or symbol name. |
| `n.raw_paths=0` and `n.raw_relations=0` | Sources matched, but no relation came back | Index the project again, and confirm the graph payload was uploaded. |
| `n.dropped_paths` equals `n.raw_paths` | The relation groups cite sources outside this result, so their revision could not be proven | Index the project again. |
| `n.relation_pairs` is 0 while `n.raw_chunks` is not | The stored graph read returned nothing for the returned sources | Confirm the sources carry a BYOG graph with `scripts/diagnose_byog.py`. |
| `n.relation_failures` is above 0 | Some stored-graph reads failed | Look for `hydra.relations.failed` lines beside it. |
| `ms.repository_relations` is large | The stored-graph reads are the cost | Lower `HYDRA_DB_RELATION_SOURCES`, or raise `HYDRA_DB_RELATION_WORKERS`. |
| `n.hops` is above zero, but the view has no node | No source card proved the entities the hops name | Index the project again. |
| `n.raw_test_chunks` is most of `n.raw_chunks` | Little implementation code matched, so the test tail dominates | Name a real symbol or file. The tail is capped at a quarter of the budget, so a large share means the first query found little. |
| `n.completion_chunks=0` while `n.relation_outside_window` is high | The records that join the matched code were not fetched, so the graph stays a set of unlinked pairs | Confirm `HYDRA_DB_COMPLETION_SOURCES` is not `0`, and read `n.completion_candidates`. |
| `n.completion_dropped_revision` is above 0 | Connecting records came back from another revision and were refused | Index the project again so one revision holds every source. |
| `n.assembled_paths=0` while `n.hops` is above zero | Relations were proven, but no ordered path runs from an entry point to the matched code | Confirm entry points exist. An index written before entry-point detection has none until the project is indexed again. |

The panel shows the same outcome in place of the empty-graph message, so the cause
is visible without the log.

## Read the logs while you use the extension

VS Code writes a file for each output channel. Follow them in a terminal:

```bash
scripts/logs.sh            # service and extension host together
scripts/logs.sh service    # bundled Python service only
scripts/logs.sh client     # extension host only
```

The script finds the newest VS Code window, so no log path must be typed. Stop
with Ctrl+C. Set `CODE_LOG_ROOT` for VS Code Insiders or a portable install.

## Setup did not appear

Run **Argus: Set Up Argus**. Make sure a local folder is open. Remote workspaces, WSL extension hosts, Codespaces, and web VS Code are not supported in this release.

In a multi-root workspace, open a file in the intended folder or select it from the native picker.

## Read access test failed

Argus does not show the stored key or database. Check the values outside the extension, then:

- run **Replace HydraDB API Key** to enter a replacement key;
- run **Remove Project Database Binding**, then setup, to enter the database again;
- confirm normal HTTPS access to HydraDB is allowed by the machine/network.

The test is read-only. Failure does not upload repository data.

The failure message names one of two causes:

- `HydraDB credentials are not available for this project.` — the stored key or
  database is missing, or the extension refused the credential lease.
- `HydraDB refused the read request.` — HydraDB received the request and rejected it.

Run `node scripts/diagnose_managed.mjs --http` to see the exact request address,
duration, and outcome.

## Managed service is unavailable

Try **Argus: Refresh Argus**. An expired or invalid project
grant is reattached automatically after HTTP 401. A timeout or dropped
connection keeps the managed session intact, so the next request can retry
without killing a healthy service or an active index job.

Open **Output: Argus Service** for bounded diagnostics. The service sends
each log line, including the HTTP access log, to that channel. Do not paste secrets
into issue reports.

Run `node scripts/diagnose_managed.mjs` to find which stage fails.

If the bundled service hash or protocol is wrong, reinstall the exact platform package. The extension intentionally refuses an unknown or modified binary.

## Port 8765 is occupied

The extension chooses a stable alternate loopback port automatically. Run **Configure Agents** again if an existing Codex or Claude Code registration still points to an old port. Argus never edits agent configuration silently.

## Index preview changed or expired

Preview tokens are single-use and expire after ten minutes. They are also rejected when analyzed files change. Run **Index Workspace with HydraDB** again, review the new revision/scope, and reconfirm.

## An index job ended failed or cancelled

Confirmation starts a background job. Read its final record with
`GET /api/index/jobs/{job_id}`, or read the message the extension shows.

- **`failed`** — `error` names the reason and `result.sync` holds the usual
  fields. Fix the reported HydraDB or network problem, then run a new preview of
  the complete repository and index again. Do not index a partial selection to
  "finish" the previous attempt. HydraDB ingestion rate limits are retried
  automatically using the server's requested delay; a terminal HTTP 429 means
  all configured attempts were still refused.
- **`cancelled`** — the job stopped where it was. The batches already uploaded
  stay in the current collection, so part of the candidate revision can already
  be visible. The prior `ready_revision` stays the last verified marker but does
  not promise that all prior content is unchanged. Run a fresh preview and index
  again when you want a verified revision.
- **The job ID returns `404`** — the service restarted, or the record was
  evicted after several later jobs. Job records are in-process and are lost with
  the process. Treat a lost record exactly like a cancelled job.

In every one of these cases the candidate revision is not published and the
local manifest is not updated.

## Indexing is failed or indeterminate

Do not treat the last revision label as proof that all old content remains visible. Retry only after HydraDB is available and review the full new preview. A successful full sync restores a verified manifest.

If a legacy manifest had a database field, Argus removes it. A mismatched secure binding leaves the project unverified until a new confirmed index succeeds.

## Git identity changed

Run **Review Repository Identity**. Argus keeps the existing ID unless it can prove that migration will not orphan indexed current or evolution sources. An unindexed local identity can migrate with its SecretStorage binding. An indexed identity requires an explicit data reset/migration outside this release.

Raw remote URLs are never shown because they may contain credentials.

## Codex or Claude Code was not detected

Run the client from a normal terminal and confirm its executable is on the VS Code extension-host `PATH`. Restart VS Code after installing a client, then run **Configure Agents** again.

The command previews exactly what it will run. It does not overwrite client config files.

## OAuth did not complete

- Keep VS Code and the project open.
- Allow VS Code to handle its own `vscode://` URI.
- Check that the client uses a loopback HTTP redirect and PKCE S256.
- Restart agent setup if the 60-second code expired.
- Reauthorize after refresh-token revocation.

If several projects are open, select the intended project in the native consent UI. A closed or ambiguous project is rejected.

## MCP stops after closing VS Code

This is expected. MCP shares the managed service and is available only while VS Code runs. Reopen the project and retry the agent action.

## Observe stopped

Observe fails closed on revision drift, root mismatch, inactive session, malformed events, or an evicted history cursor. Use **Restart follow** after restoring one verified revision. It never skips a missing event range.

## Compare cannot finish

Index the before state, start the comparison, make the change, index the changed state, then finish. The before and after verified revisions must differ. Both checkpoints remain local until HydraDB confirms delta publication.

## Preserve has no grounded lens

Open a verified HydraDB view containing at least one exact connected edge. A System Lens cannot be created from preview data, automatic relations, empty views, or unverified revisions.

## Contrast shows the agent gate

Contrast needs the `claude` CLI to be installed and signed in. Without it the view shows the agent gate instead of a comparison.

Run `claude` from a normal terminal, sign in, and confirm its executable is on the VS Code extension-host `PATH`. Restart VS Code after installing it. Argus does not install the CLI and does not sign in for you.

## A contrast run did not finish

A contrast run starts two real agent processes, so it takes as long as the agent takes. When a run times out or stops:

- ask a narrower, more concrete question;
- confirm one revision is ready and the managed service is available, because the Argus run answers through the loopback MCP endpoint;
- start the run again.

A stopped run is not a result. Do not compare a finished column with a stopped one. Each attempt costs real money, so change the question before repeating a run that already failed.

## Developer mode

Only contributors should enable `hydra.developerMode`. In that mode, install the Python and Node dependencies from [Development](development.md), start the service separately, and use the developer loopback URL. Environment credentials belong only to that explicit process and do not test SecretStorage/managed IPC behavior.
