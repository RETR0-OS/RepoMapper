# Indexing and sync

Indexing is an explicit two-step operation: preview the selected repository,
then confirm the HydraDB write. There is no background watcher that silently
uploads file changes.

The complete path is: **preview → confirm → background job → verified
revision.** Confirmation only starts the job. The upload itself runs in the
service and is followed by polling, because a large repository needs far more
time than one HTTP request should hold.

## Preview before writing

The managed service chooses the revision. A clean Git project uses the complete
commit SHA. A dirty or non-Git project uses a deterministic digest of analyzed
content. Users do not type revision labels.

Preview performs these local operations:

1. Resolve and inspect only the selected repository root. The extension selects
   its open workspace; direct CLI use falls back to `HYDRA_REPOSITORY_ROOT` or
   the process working directory.
2. Discover supported source files.
3. Build deterministic Graph IR.
4. Build source cards and exact BYOG relations.
5. Report the files, source counts, content size, and exact relation counts.

Preview performs no HydraDB request. It is not a retrieval path.

## Start the write

After reviewing the preview, the extension sends its single-use confirmation
token. The service still refuses the write if the root, identity, revision,
files, or source-card scope changed.

It does not analyze the repository twice. The preview keeps its analyzed
snapshot, and confirmation reuses it when no analyzed file changed in the
meantime. Only a changed file forces a fresh analysis, and a changed scope is
refused instead of uploaded.

Confirmation returns HTTP `202` and a job record straight away. The job then
does the work: it compares deterministic complete-card hashes with the persisted
manifest, uploads added and changed sources in bounded batches, waits for
HydraDB graph creation in bounded status batches, deletes removed sources only
after candidate sources are ready, and persists the verified manifest last.

The direct HydraDB protocol stays behind the adapter. Ingest uses HydraDB v2
multipart requests, query uses one explicit collection, and status/delete calls
are not exposed as general public service endpoints.

## Follow the background job

Read `GET /api/index/jobs/{job_id}` about once a second. The record reports the
`state` (`running`, `completed`, `failed`, `cancelled`), the `phase`
(`analyzing`, `clearing_stale_graphs`, `uploading`, `verifying`, `deleting`,
`done`), uploaded batches out of total batches, and verified sources out of
total sources. The full field list is in the
[service API](service-api.md#get-apiindexjobsjob_id).

Status polling asks HydraDB only about the sources that have not finished
indexing yet. Every source that reports a finished state leaves the question
set, so each cycle is smaller than the one before it. Progress therefore slows
down in source count but not in request size, and a repository with thousands of
sources does not repeat one huge status request until it times out.

The job exists only inside the running service process. It is not written to
disk, and `durable` is always `false`. If the service stops, the job record and
its progress are lost, while the batches already accepted by HydraDB remain.
Preview and index again after that happens. A small
`.hydra-graph/sync-in-progress.json` safety marker is written before the first
HydraDB mutation. It contains no progress or credentials and cannot resume a
job. On restart it only forces the current collection into an indeterminate,
query-gated state until a complete sync succeeds.

A job ends verified when `state` is `completed` **and** `result.sync.status` is
`ready` with `ready_revision` equal to `candidate_revision`, nothing `pending`,
and nothing `failed`.

Any terminal sync result other than `ready` makes the job `failed` and keeps the
full `{preview, sync}` result plus HydraDB's bounded reason for diagnosis.

## Cancel a running job

`POST /api/index/jobs/{job_id}/cancel` requests a stop. The record moves to
`state: cancelled` when the worker observes that request. If the revision became
ready first, the job correctly remains `completed`.

Cancellation is not a rollback and not an undo:

- The batches that were already uploaded stay in the current collection, so part
  of the candidate revision can already be visible to queries.
- The prior `ready_revision` stays the last verified marker. It does not promise
  that every prior source is still exactly what HydraDB returns.
- The candidate revision is not published, and the local manifest is not
  updated.

Recover the same way as from a failure: run a fresh preview of the complete
repository snapshot and index it again, then confirm `ready`.

## Read the result

When the job ends, its `result` holds the preview and a `sync` object.
Important `sync` fields are:

| Field | Meaning |
| --- | --- |
| `status` | `ready`, `indexing`, `failed`, or `unavailable`. |
| `candidate_revision` | Revision the operation attempted to publish. |
| `ready_revision` | Last revision whose complete operation and local manifest were verified. |
| `added`, `replaced`, `deleted` | Source IDs confirmed in those categories. |
| `pending` | Source IDs whose final state was not confirmed. |
| `failed` | Per-source or manifest failures. |
| `current_state_indeterminate` | Whether the current collection may contain a mixed or partially replaced state. |
| `warning` | Human-readable consequence, including whether candidate content may already be visible. |

The `/health` endpoint summarizes service state:

| Health state | Meaning |
| --- | --- |
| `unavailable` | Credentials are missing or the latest operation could not reach HydraDB. No local fallback is used. |
| `unverified` | Credentials are configured, but this process has no concrete verified revision. |
| `indexing` | A candidate revision is being written and checked. Current queries are gated. |
| `ready` | A concrete revision and its persisted manifest were verified by this process. |
| `failed` | The latest attempt failed. Read the message and sync result; current content may be indeterminate. |

`revision_verified: true` and `verification_status: verified` mean the process
has a verified revision marker. They do not turn HydraDB replacement into a
transaction.

## Why replacement can become indeterminate

The current collection uses stable source IDs and upsert. HydraDB can expose a
candidate source before every source, relation, deletion, and local manifest
write has completed. If a later step fails, the prior `ready_revision` remains
the last verified marker, but it does not guarantee that all prior content is
still what HydraDB returns.

For this reason the service:

- marks changed or deletion failures as `current_state_indeterminate: true`;
- refuses to publish the candidate as ready;
- gates current queries while indexing or indeterminate;
- reports confirmed and pending deletions separately; and
- never silently substitutes the analyzer, manifest, checkpoint, or fixtures as
  query data.

There is no transactional rollback claim. Resolve the HydraDB/API problem, run
a fresh preview of the complete repository snapshot, and explicitly index it
again. Confirm `ready` before relying on current queries.

Each source's HydraDB `additional_metadata` is capped at 1,024 serialized bytes.
Argus removes duplicated display/evidence bookkeeping before upload
and drops an optional long signature only when needed. Required path, identity,
span, parser, and content-hash fields are never silently truncated. An
unavoidable overflow fails locally before any batch is sent.

## Index from VS Code

Run **Argus: Index Workspace with HydraDB**. The extension calls the
authenticated preview endpoint, shows the selected root, automatic revision,
and upload scope, then writes only after confirmation. The preview body is
empty; confirmation contains only the opaque preview token. Confirmation starts
the background job, and the extension follows that job record until it reaches a
terminal state. Cancelling the progress notification cancels the job; read
[Cancel a running job](#cancel-a-running-job) before you do that. Project scope
comes from the short-lived managed token, never the webview or
caller-controlled headers.

To drive the same path without VS Code, run
`node scripts/diagnose_managed.mjs --index`. See
[Troubleshooting](troubleshooting.md#diagnose-the-managed-service-without-vs-code).

## Change history and lenses

Evolution data uses the separate configured evolution collection. A typical
command-line flow is:

```powershell
python -m hydra_graph checkpoint before --revision "before-revision"
# Make and index the intended repository change.
python -m hydra_graph checkpoint after --revision "after-revision"

# Preview; this does not write evolution cards.
python -m hydra_graph evolution-publish --before "before-revision" --after "after-revision"

# Confirm the HydraDB evolution write.
python -m hydra_graph evolution-publish --before "before-revision" --after "after-revision" --confirm

python -m hydra_graph compare --before "before-revision" --after "after-revision"
```

A checkpoint is accepted only when the analyzed cards exactly match the current
verified manifest and revision. It is local input for building a change event,
not a fallback comparison database. Checkpoints are cleared only after every
delta card is confirmed ready.

Compare queries only the evolution collection. Preserve first queries the saved
lens in evolution, then separately queries the current collection for a grounded
path. It does not issue a cross-collection traversal and does not claim HydraDB
Memory behavior.

See [Troubleshooting](troubleshooting.md) for recovery guidance and
[Trust and safety](trust-and-safety.md) for the exact/inferred evidence rules.
