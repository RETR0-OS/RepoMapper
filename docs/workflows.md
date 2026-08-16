# Argus workflows

These recipes cover the extension's write, query, editor, Compare, and Preserve flows. For individual controls, see [Views](views.md). For live event following, see [Observe](observe.md). For keyboard and responsive use, see [Accessibility](accessibility.md).

## Before you start

Argus bundles and manages a loopback service. The extension host keeps service access, SecretStorage, and filesystem selection out of the webview. The first window owns the process and other windows attach with project-bound tokens.

The active editor's workspace folder wins. A single folder is automatic; an ambiguous multi-root workspace uses a native picker. The canonical opened folder remains the scan boundary.

## Index a repository safely

1. Open the repository as a VS Code workspace.
2. Run **Argus: Index Workspace with HydraDB**, or select **Index this workspace** in the HydraDB Index Status sidebar.
3. Wait while the service derives a clean Git SHA or analyzed-content revision and builds the local preview. No upload occurs.
4. Review the modal. It shows the selected root, stable repository ID, revision, discovered and ignored files, graph node and relation counts, generated source cards, a bounded source list, and diagnostics.
5. Select **Upload to HydraDB** only if the root, revision, and scope are correct. Canceling performs no upload.
6. Wait for indexing and the automatic health/view refresh.

A success message is shown only when the candidate revision is the ready revision, no sources remain pending, no source failed, and current HydraDB state is not indeterminate. Otherwise the extension reports failed and pending counts, the last verified revision when known, and any uncertainty warning.

The validated workspace scope is authoritative. The extension never turns the previewed path into an upload path supplied by the webview.

## Orient to a repository

1. Open **Argus** from the Activity Bar or Command Palette.
2. Confirm that the header says `HydraDB · revision … ready` and names the expected revision.
3. Start at **Packages** or **Files** depth.
4. Use relation chips to keep only the predicates relevant to your question.
5. Select a node and read **Why shown**, **Method**, **Revision**, and **HydraDB** in the inspector.
6. Open the source evidence before drawing a conclusion.
7. Switch to **Symbols** only when you need declaration-level detail.

If the status says preview, unverified, or unavailable, treat the visible graph as a control demonstration or degraded state, not repository truth.

## Ask a repository question

1. Enter a concrete question in the panel, or run **Ask HydraDB About This Code**.
2. Prefer a bounded question: `How does authorize_user reach audit_access?` is better than `Explain the repository`.
3. Select **Trace with HydraDB**.
4. Inspect the returned left-to-right path, relation list, and evidence.
5. Use **Replay path** to step visually through the already returned nodes.

Replay is presentation only. It does not replay hidden model reasoning or HydraDB's internal search.

## Focus a view from the editor

The editor context menu provides:

| Command | Opens | Request semantics |
|---|---|---|
| **Show in Argus** | Repository | Focus bounded structure on the active workspace file and selected line. |
| **Show Callers and Callees** | Explore | Request a bounded caller/callee neighborhood. |
| **Trace Flow from Here** | Trace | Request a HydraDB-backed flow starting from this source location. |
| **Find Tests for This Symbol** | Explore | Request exact, evidence-backed test relations. |
| **Ask HydraDB About This Code** | Trace | Prompt for a separate concrete question. |

`View repository graph`, shown as a CodeLens at the top of a file, runs **Show in Argus**.

Focused commands send only a workspace-relative file path and the one-based selected line. They do not claim that a cursor line identifies an exact symbol. If returned evidence resolves a symbol, the result may focus it; otherwise the service should remain at file-level evidence.

The extension refuses the focused commands when there is no active editor, the document is not a file, or the file is outside every active workspace folder.

## Review callers, callees, or tests

1. Place the cursor on the relevant source line.
2. Run **Show Callers and Callees** or **Find Tests for This Symbol**.
3. In Explore, filter to useful predicates such as calls or test relations returned by the service.
4. Select each edge and open its exact evidence.
5. Use **Expand graph** only when the current bounded neighborhood is insufficient.

An absent relation is not proof that runtime behavior is impossible. Dynamic relations may be unknown to static analysis; the UI should not convert an unknown into an inferred fact without an explicit inferred edge.

## Compare two revisions

The Compare command is intentionally a multi-step workflow.

### Capture before

1. Ensure the current repository state has a concrete revision ID.
2. Run **Compare Graph Before and After Change**.
3. Enter the before revision.
4. Review the modal and select **Capture before checkpoint**.

Checkpoint capture performs bounded local repository analysis. It does not publish a graph delta to HydraDB. The pending before revision is stored in workspace state so you can make the change and return later.

### Capture after and publish

1. Make the change.
2. Index the changed repository using a different explicit after revision and verify it becomes ready.
3. Run **Compare Graph Before and After Change** again.
4. Enter the after revision. It must differ from the before revision.
5. Review and capture the after checkpoint.
6. Review the no-write delta preview. It names the repository, both revisions, source-card count, HydraDB availability, and warnings.
7. Select **Publish graph delta** to perform the HydraDB write, or cancel to leave both checkpoints available.

The extension opens Compare and remembers the pair only after a concrete non-empty delta is published and HydraDB confirms both availability and a performed write. **Review changes** then advances through added, removed, and modified nodes.

## Save and maintain a System Lens

### Save the current grounded view

1. Open a non-preview HydraDB view whose revision exactly matches the verified service revision.
2. Run **Save as System Lens**.
3. Enter a concise name of at most 80 characters.
4. Enter a purpose of at most 240 characters describing the flow to preserve.
5. Review the no-write preview. It shows the saved revision, grounded anchor and exact-edge counts, shared ownership, HydraDB availability, and warnings.
6. Select **Save System Lens** to write it, or cancel to perform no HydraDB write.

The service derives anchors and exact edge IDs from the stored grounded view. The client does not submit graph facts from the webview. A successful save opens Preserve and remembers the exact lens ID.

### Review and accept drift

1. Open Preserve for the saved lens.
2. Read the saved revision and current verified revision separately.
3. Inspect the current grounded nodes, exact edges, lens metadata, and drift classification.
4. Open evidence for the changed path.
5. Select **Accept drift**.
6. Review the no-write acceptance preview.
7. Select **Accept reviewed drift** only when the current view should become the shared baseline.

Canceling leaves drift unresolved. Acceptance succeeds only when the service confirms the same lens, a concrete previous revision, a different saved revision, non-empty grounded anchors and edges, shared ownership, HydraDB availability, and a performed write.

## Follow explicit agent activity

1. Verify that one revision is ready.
2. Run **Follow Agent** or open Observe.
3. Wait for explicit repository events and a stored HydraDB result view.
4. Use the timeline to focus returned, selected, opened, or edited items.
5. Pause visual following when you need a stable view; polling continues into a bounded buffer.
6. Resume to release buffered events, or restart if the extension reports a history gap or revision mismatch.

See [Observe](observe.md) for the exact event and workspace-overlay rules.

## Recover from degraded states

- **Service unavailable:** verify the local process, configure a loopback URL, then retry.
- **Revision unverified:** index an explicit revision and wait for exact service/view revision agreement.
- **Index failed:** read failed and pending counts. Do not treat the candidate as current; the last verified revision is labeled when available.
- **Empty query result:** narrow the question or use a literal file or symbol name.
- **Compare or Preserve empty:** complete the workflow that creates its exact revision pair or lens ID.
- **Observe stopped:** restart the session. The extension intentionally does not skip an event-history gap or cross a revision boundary.

## Workflow limits

- Indexing, evolution publishing, lens saving, and drift acceptance are not undo buttons. Each HydraDB write requires a server preview and a separate modal confirmation.
- Checkpoints are local bounded analysis records; publishing the delta is the HydraDB write.
- Only one pending Compare workflow, last verified Compare pair, and last saved/opened lens are remembered per workspace.
- Focused editor requests identify a file and line, not a guaranteed symbol.
- Preview fixtures are useful for UI exploration only. They cannot be saved as lenses, used as grounded Compare results, or reported as ready.
