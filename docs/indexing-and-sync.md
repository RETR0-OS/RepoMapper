# Indexing and sync

Indexing is an explicit two-step operation: preview the configured repository,
then confirm the HydraDB write. There is no background watcher that silently
uploads file changes.

## Preview before writing

Choose a concrete revision label, preferably a commit SHA:

```powershell
$revision = (git rev-parse HEAD).Trim()
python -m hydra_graph index --revision $revision --preview
```

If the working tree does not represent that commit exactly, use a truthful
workspace-snapshot label instead. The revision is an identity and consistency
boundary, not a free-form description.

Preview performs these local operations:

1. Resolve and inspect only `HYDRA_REPOSITORY_ROOT`.
2. Discover supported source files.
3. Build deterministic Graph IR.
4. Build source cards and exact BYOG relations.
5. Report the files, source counts, content size, and exact relation counts.

Preview performs no HydraDB request. It is not a retrieval path.

## Run the write

After reviewing the preview:

```powershell
python -m hydra_graph index --revision $revision
```

The service compares deterministic complete-card hashes with the persisted
manifest. It uploads added and changed sources in bounded batches, waits for
HydraDB graph creation in bounded status batches, deletes removed sources only
after candidate sources are ready, and persists the verified manifest last.

The direct HydraDB protocol stays behind the adapter. Ingest uses HydraDB v2
multipart requests, query uses one explicit collection, and status/delete calls
are not exposed as general public service endpoints.

## Read the result

The command returns a preview and a `sync` object. Important fields are:

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

Check health from PowerShell:

```powershell
$health = Invoke-RestMethod http://127.0.0.1:8765/health
$health | ConvertTo-Json -Depth 5
```

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

## Index from VS Code

Run `Repository Map: Index Workspace with HydraDB`. The extension requests a
revision, calls the local preview endpoint, shows the upload scope in a modal,
and writes only after confirmation. API bodies contain only the revision ID;
callers cannot supply an arbitrary repository path.

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
