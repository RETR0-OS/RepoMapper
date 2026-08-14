# Repository Evolution and Living System Lenses

## Why this matters

The main problem is not merely finding code. It is preserving a programmer's mental model while humans and agents change the repository quickly.

Graph evolution is therefore a core product capability, not a decorative timeline.

## MVP unit of change

For the hackathon, the primary comparison is an agent task:

```text
verified graph before task
→ agent retrieval and edits
→ verified graph after task
→ structural delta
```

This is easier to explain and demonstrate than complete Git history.

## Change model

Track:

- Node added.
- Node removed.
- Node content/signature changed.
- Node deterministically matched as renamed.
- Relation added.
- Relation removed.
- Relation quality changed.
- Source evidence moved.
- Saved System Lens path changed.

Every change record includes:

- Before revision.
- After revision.
- Entity and relation IDs.
- Evidence.
- Deterministic explanation.
- Affected saved lenses.

## Where HydraDB is central

**HydraDB stores the repository states or graph-delta Knowledge and retrieves the relevant changes for both the human and the agent.**

The deterministic analyzer computes exact set differences because HydraDB BYOG does not provide per-triple mutation history. The result becomes HydraDB Knowledge with graph relations such as `CHANGED_IN`, `ADDED_IN`, `REMOVED_IN`, and `DRIFTS_FROM`.

The extension does not browse a separate local history graph. It asks HydraDB questions such as:

- “What changed in authentication during this agent task?”
- “Which saved flows include a removed relation?”
- “What new dependency was introduced in payments?”

## Revision strategies to test

### Strategy A: current plus immutable checkpoints

- Current sources live in a `current` collection.
- Important checkpoints live in `revision_<sha>` collections.
- A graph-delta source links the two revisions.

Advantages: simple demo and reproducible comparison.

Risks: storage growth and unproven cross-collection graph behavior.

### Strategy B: current graph plus immutable delta Knowledge

- Current sources are replaced in place.
- Each change produces an immutable delta source in HydraDB.
- Delta source contains before/after facts needed for explanation.

Advantages: smaller and does not require full history queries.

Risks: cannot reconstruct an arbitrary historical graph without more data.

### Working recommendation

Use Strategy A for one demo checkpoint pair and Strategy B as the longer-term default. Validate both before committing.

## Living System Lens

A System Lens is a saved, named understanding of an important flow.

Example:

```text
Name: Authentication
Purpose: Validate session, load policy, authorize action, and audit result.
Anchors: api.handle_request, auth.authorize_user, audit.audit_access
Saved revision: abc123
Owner: developer or team
```

A lens stores:

- Human name and purpose.
- Anchor entities.
- HydraDB path group IDs or grounded triplets from the saved revision.
- Optional user notes.
- Exact revision.
- Ownership: personal or shared.

Personal lenses belong in HydraDB Memory. Shared team lenses belong in HydraDB Knowledge. Structural graph facts stay in Knowledge and are never changed by a user's note.

## Lens refresh

When a new revision becomes ready:

1. Retrieve the lens definition.
2. Query current HydraDB Knowledge using its anchors and purpose.
3. Compare the returned grounded path with the saved path.
4. Classify drift.
5. Store or update a lens-drift record.
6. Notify the extension.

Drift classes:

- `unchanged`
- `path_extended`
- `path_shortened`
- `anchor_removed`
- `relation_changed`
- `test_coverage_relation_changed`
- `unresolved`

Do not call drift bad by default. Some change is intentional.

## Structural warnings

Useful deterministic warnings include:

- New dependency cycle.
- New cross-package edge.
- Public signature changed.
- Entrypoint moved or removed.
- Exact `TESTS` relation removed.
- Saved flow anchor removed.
- Structural centrality increased sharply.

Avoid unsupported warnings such as “security weakened” unless a specific rule or test proves it.

## Visual comparison

- Keep stable nodes in stable positions.
- Reuse the user's prior 2D layout where possible; layout remains presentation state rather than graph truth.
- Green for added, red for removed, amber for modified, with non-color labels.
- Let the user focus on one lens or path.
- Show a plain text summary beside the graph.
- Let the user open before and after evidence.
- Allow replay of the agent retrieval path before the edit and the updated HydraDB path after indexing.

The UI label for this experience is **Compare**. Its primary action advances through concrete changed nodes and edges while keeping the evidence inspector synchronized.

## Preserve interaction

The UI label for Living System Lenses is **Preserve**.

When drift is detected, the user can:

- Open the changed path and its source evidence.
- Compare the saved revision with the current verified revision.
- Accept the drift, which updates the grounded saved baseline to the current revision.
- Leave the drift unresolved for later review.

“Accept drift” does not declare the change good and does not alter repository graph facts. It records that the user has reviewed the current grounded path and chosen it as the lens's new baseline.

## Success condition

After an agent task, a programmer should be able to answer in under one minute:

- What important code changed?
- What new or removed relationships resulted?
- Which known system flows were affected?
- What evidence supports those claims?
- What does HydraDB return for the updated system now?
