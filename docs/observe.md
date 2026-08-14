# Observe explicit repository activity

Observe follows repository activity that the product can prove happened. It shows explicit tool events, HydraDB-returned views and paths, selections, source evidence opened through Repository Map, and matching workspace edits. It does not expose an agent's private reasoning or HydraDB's internal search process.

For general graph controls, see [Views](views.md). For a short end-to-end recipe, see [Workflows](workflows.md#follow-explicit-agent-activity). Keyboard and motion behavior are in [Accessibility](accessibility.md).

## Start and stop following

Open Observe from the mode tabs, the **Agent Activity** sidebar section, or **Follow Agent**.

The extension starts only when the local service has one concrete verified revision. The service returns an exact session ID, revision ID, repository-root fingerprint, and `session_started` event. The extension rejects a substituted session, revision, event, or root fingerprint.

While Observe is active, the extension performs bounded JSON polling. It does not use server-sent events. Leaving Observe, closing the panel, or disposing the extension stops polling, waits for pending interaction reports, and asks the service to complete the exact session.

Before the first HydraDB result is returned, the view says that following is active but no stored result view exists yet. It does not fill the canvas with a guessed graph.

## What the event timeline can show

The bounded event model recognizes:

| Event | What it means in the UI |
|---|---|
| Session started/completed | The explicit follow boundary. |
| Repository query started | A product query was issued. |
| HydraDB result returned | A stored, bounded HydraDB view or path became available. |
| Path replay started / hop replayed | An explicit replay action and its returned relationship hops. |
| Context selected | Returned node or edge context was explicitly selected. |
| Evidence opened | Source evidence was explicitly opened through the product. |
| User context pinned | Returned context was explicitly pinned. |
| Workspace entity changed | A visible source-backed entity matched a workspace file change. |
| HydraDB sync started / revision ready | An explicit index transition. |
| System Lens drift detected | A grounded lens comparison returned drift. |

The timeline uses the server timestamps for chronological display. Selecting an event selects the first visible node or edge named by that event; a node is also centered and keyboard-focused. Timeline selection does not open source by itself and does not create a new service event.

Only events for the exact active session and revision enter the visible log. Unknown event types, malformed IDs, invalid timestamps, oversized ID lists, and oversized query metadata are rejected. Entity IDs map only to nodes; relationship IDs map only to edges.

## Returned views and exact IDs

A `hydradb_result_returned` event may name a view ID. The extension fetches that stored view by the exact ID and accepts it only when:

- it is not a preview;
- its view ID matches the event;
- its revision matches the event and session; and
- it reports HydraDB as available.

An unknown or substituted view is reported as unavailable. Fetch retries are bounded; the extension does not silently replace it with another view.

## Visual state and precedence

Observe uses labels, badges, stroke styles, and the textual timeline as well as color.

| State | Meaning |
|---|---|
| `RETURNED` | The exact node or edge appeared in a HydraDB result or replayed path hop. |
| `SELECTED` | Returned context was explicitly selected or pinned. |
| `OPENED` | Exact evidence for the item was opened. |
| `EDITED` | A matching visible source-backed node's workspace file changed. |

State precedence is `EDITED` over `OPENED`, `OPENED` over `SELECTED`, and `SELECTED` over `RETURNED`. A later lower-information event cannot erase a stronger observed fact. The full bounded timeline remains chronological.

Selecting a visible node or edge reports its exact stable ID and kind. Opening source reports `evidence_opened` only after VS Code successfully opens or reveals the validated workspace evidence. A malformed service response that swaps a node into relationship IDs, changes the session, revision, view, or item ID, or names an unshown item is rejected.

## Pause and resume

**Pause follow** pauses visual application, not collection. Polling continues and accepted events enter a bounded UI buffer.

- The button changes to **Resume follow (count)** while events are buffered.
- Resuming releases buffered events in chronological order and loads the latest exact stored view when needed.
- The paused buffer retains at most 200 events. If it overflows, the status message tells you how many oldest buffered events were omitted from the display.
- The visible event history retains at most 500 events.

Pause does not pause the agent, the service, HydraDB, file watching, or other repository work.

## Replay semantics

Observe can display explicit `path_replay_started` and `path_hop_replayed` events emitted by the product. These are observable replay actions, not reconstructed thought steps.

Observe's primary control is pause/resume. The separate Trace **Replay path** action locally steps through an already returned path. It does not create private-reasoning telemetry. See [Trace](views.md#trace).

## Workspace edit overlay

The workspace edit overlay is deliberately strict:

1. The service sends only a SHA-256 fingerprint of its canonical repository root, never the raw path.
2. The extension resolves each VS Code workspace root, applies the shared slash, case, and trailing-slash normalization, and computes its fingerprint.
3. Edit reporting is enabled only when exactly one workspace root matches the service fingerprint.
4. A changed file must remain inside that root.
5. Its workspace-relative path must exactly match the normalized source path of at least one currently visible node.
6. The service response may name only those visible, path-matched node IDs and no relationship IDs.

If no root or more than one root matches, following still works but the edit overlay is disabled with an honest status. This prevents an identically named relative file in another repository from coloring the current graph.

Create, change, and delete notifications use the same checks. No raw workspace root is sent in the event request.

## Cursor and history safety

The `session_started` event seeds the first polling cursor. Every later poll asks for events strictly after the last accepted server-stream event.

Direct selection, evidence, and workspace-change responses can appear immediately in the UI, but they do not advance the polling cursor. When the same event later arrives in the poll stream it is deduplicated for display and still advances the cursor. This avoids skipping an earlier concurrent event.

If the service reports an unknown, wrong-session, or evicted cursor, it returns a history-gap error. The extension stops and completes the session, changes the primary action to **Restart follow**, and explains that the history is incomplete. It never retries from an empty cursor.

A same-session event for a different revision is also an integrity failure. The extension stops rather than appearing to follow across a revision boundary. Other-session or malformed entries are ignored because they cannot be attached to this session.

## Practical Observe recipe

1. Index and verify revision `A`.
2. Open Observe and confirm the session status says it is following explicit events.
3. Run a repository query through the product.
4. Wait for `HydraDB result returned`; the exact stored view should appear.
5. Select a returned node and open its evidence. Confirm the timeline records selection and evidence opening.
6. Pause visual following.
7. Perform another explicit repository action. Confirm the button reports a buffer count.
8. Resume and select timeline entries to review what arrived.
9. Edit a visible node's exact source file. If the workspace root identity matches, confirm the node receives an `EDITED` badge.
10. Leave Observe to complete the follow session.

## Empty, degraded, and stopped states

- **No verified revision:** Observe cannot start. Index or restore one verified revision.
- **Waiting for stored result:** the event timeline may grow, but no graph is shown until a valid `hydradb_result_returned` view exists.
- **Service unavailable:** an explicitly labeled interaction preview may demonstrate pause controls; it is not live telemetry.
- **Stored view unavailable:** the exact ID is reported; another view is not substituted.
- **Workspace overlay disabled:** repository events still follow, but local edits are not mapped without an exact root identity match.
- **History gap or revision drift:** following stops and requires restart.

## Observe limits

- Polling is bounded and periodic, not instantaneous streaming.
- The timeline is a bounded record, not an audit archive.
- Pause buffering is UI-only and bounded to 200 events.
- Event metadata is display-safe and bounded; it is not a channel for hidden chain-of-thought.
- Only source opened through Repository Map is recorded as evidence opened.
- Only currently visible source-backed nodes can receive the workspace edit overlay.
- Observe reports explicit product events. Activity outside the instrumented product surface may not appear.
