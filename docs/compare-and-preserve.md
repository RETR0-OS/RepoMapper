# Compare and Preserve

[Documentation index](README.md) · [Core concepts](concepts.md) ·
[Architecture](architecture.md) ·
[Graph and evidence](graph-and-evidence.md)

Compare explains structural change between two verified repository revisions.
Preserve saves one important exact path and reports deterministic drift when a
later HydraDB query returns a different grounded path.

Neither feature judges whether a change is good. Both keep the claim tied to
source evidence and concrete revisions.

## Before and after checkpoints

The service owns two local checkpoint slots: `before` and `after`. Each contains
a complete versioned Graph IR plus its canonical SHA-256 hash.

A checkpoint can be captured only when:

- the requested revision is the service's currently verified HydraDB revision;
- the current collection is not marked indeterminate; and
- freshly analyzed source cards exactly match the verified sync snapshot.

The store rejects oversized, corrupt, wrong-repository, wrong-revision, and
symlinked slot files. The default limit is 25 MB per checkpoint. Writes use a
temporary file and atomic replacement.

These files have no search or graph-query operation. They exist only to compute
and publish a deterministic delta. Compare and Preserve retrieval never falls
back to them.

## Deterministic graph delta

The comparer uses graph identities and deterministic record fields, not layout
or retrieval rank. Publication separately revalidates that those IDs match
their logical contents. The delta reports:

- added and removed nodes;
- modified nodes and the fields that changed;
- added and removed relations;
- evidence movement;
- relation-quality changes;
- inferred rename matches; and
- bounded structural warnings.

Current warnings cover removed `TESTS` relations and newly introduced exact
dependency cycles. A warning is a review signal, not a defect verdict.

### Rename honesty

A rename changes name-based identity, so it first appears as one exact removal
and one exact addition. The comparer may add an inferred rename hypothesis when
kind and language match and a weighted combination of body fingerprint, path,
signature shape, and owner reaches the configured threshold. Ambiguous tied
matches are left unmatched.

The change event keeps the exact add/remove facts even when it also records the
rename hypothesis. The hypothesis carries its score and matched signals; it is
never labeled exact.

## Change-event Knowledge

Before publication, the event builder verifies that:

- the delta, before graph, and after graph name the same repository and exact
  revisions;
- node, edge, and evidence IDs match their logical contents; and
- a fresh deterministic comparison equals the supplied delta.

This prevents a detached or edited delta from being published as evidence.

The resulting event is versioned and self-contained. Exact facts carry complete
before and/or after node, relation, revision, and evidence records. Relation
quality changes preserve both sides. Rename hypotheses remain inferred.

One summary card and one lossless card per fact are written to the HydraDB
evolution collection. The event is limited to 49 facts and each card to 12,000
characters. Bounds fail visibly; records are not sliced or silently truncated.
An empty delta still produces an explicit zero-change summary without a fake
self-relation.

The complete machine record is stored after the `Record JSON:` marker in each
card's content. It is not duplicated into HydraDB `additional_metadata`, which
has a 1,024-byte serialized limit. Retrieval accepts older cards that still
carry `record_json` in metadata and validates current cards from their content.

Publication is preview-only until explicitly confirmed. After HydraDB confirms
all source IDs and indexing completes, the service clears the local checkpoints.
Partial acknowledgement, failure, or timeout produces an unavailable or
indeterminate result and retains the checkpoints where possible.

Compare later queries the stored `CHANGE_EVENT` Knowledge in HydraDB. It does
not recompute or answer from local checkpoints.

Change-event lens impact is currently marked `not_evaluated`. A blank affected
lens list does not claim that no lens changed; lens drift is evaluated
separately when the saved lens is opened.

## A shared System Lens

A System Lens is a named, user-reviewed baseline for an important path. The
current MVP supports one stable shared-workspace lens stored as HydraDB
Knowledge. It does not use HydraDB Memory.

A lens contains:

- a name, purpose, and optional note;
- a concrete saved revision and source view ID;
- grounded repository entities;
- one or more anchor node IDs; and
- the exact baseline hops and their evidence.

The name and purpose help retrieve and explain the lens. They do not create
repository facts or alter the saved structural hops.

### Saving a lens

The service accepts a lens only from a bounded view already stored by the
HydraDB-backed view service. It derives the anchors and hops from a complete,
connected exact path returned in that stored query; the client does not submit
its own graph facts. The builder requires:

- an available HydraDB result at one concrete revision;
- at least two grounded repository entities;
- at least one selected anchor and one connected hop;
- exact relations with evidence and `byog` origin;
- source-card-grounded node metadata; and
- matching repository, revision, logical identity, and stable IDs.

The current bounds are 25 entities, 24 hops, and 10 anchors. A disconnected,
mixed-revision, automatic, inferred, client-fabricated, or stale view fails
closed.

The stored lens card contains the structured baseline as Knowledge but is
omitted from `graph_payload`. Re-emitting the baseline relations from the lens
would create a second canonical owner, so the implementation deliberately does
not do that.

## Refresh and drift

Opening a lens performs two independent HydraDB queries:

1. retrieve the saved lens record from the evolution collection; and
2. retrieve the current exact repository path from the current collection.

The service does not claim cross-collection traversal. It validates the current
view and compares the two grounded records locally.

Drift uses this deterministic precedence:

1. `unresolved` when no complete grounded current path is available;
2. `anchor_removed` when a saved anchor is absent;
3. `test_coverage_relation_changed` when a changed hop is `TESTS`;
4. `unchanged` when edge IDs match;
5. `path_extended` when every saved hop remains and exact hops were added;
6. `path_shortened` when the current path is a strict subset; and
7. `relation_changed` for other replacements.

Drift is based on grounded exact hop identity. It does not diagnose behavior,
security, correctness, or intent. A query failure becomes `unresolved`, not an
invented path.

## Accepting drift

Accept drift means “I reviewed this current grounded path and want it to become
the new baseline.” It does not approve the code change, change repository graph
facts, or hide history.

The service requires the opaque current refresh view that it previously bound
to that lens. It retrieves the stored lens again, rebuilds the baseline from the
validated current view, preserves the human fields, and upserts the same stable
lens source only after explicit confirmation.

## Guarantees

- A delta is bound to complete before and after graphs and recomputed before
  publication.
- Rename continuity remains inferred while add/remove facts remain exact.
- Original relation evidence is preserved in structured change facts.
- Local checkpoints are bounded diff artifacts, never retrieval data.
- Compare and lens retrieval remain HydraDB-backed and fail visibly.
- A saved lens contains exact connected BYOG hops from one revision.
- Accept drift updates only the reviewed lens baseline.

## Limits

- Only one shared-workspace lens is implemented.
- Personal lenses and HydraDB Memory are not implemented in this workflow.
- Cross-collection graph traversal is neither required nor claimed.
- Change events are limited to 49 facts; larger deltas fail rather than publish
  an incomplete event.
- Rename detection is a deterministic heuristic and can remain unresolved.
- Drift compares the set of saved exact edge IDs. Evidence span or hash movement
  under an otherwise unchanged relation is handled by graph deltas, not as a
  distinct lens-drift class.
- Structural warnings are intentionally narrow and do not claim that a change
  is unsafe or wrong.

For the repository facts used by both workflows, return to
[Graph and evidence](graph-and-evidence.md).
