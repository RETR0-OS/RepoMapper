# VS Code Experience

## UX principle

The extension should help the programmer answer a question. It should not display a graph merely because a graph exists.

Index broadly. Render narrowly. Expand progressively.

The graph is an explanation and navigation surface. It is not a picture of hidden architecture. Source evidence remains authoritative.

## Settled UI shell

The current shell follows normal VS Code structure:

1. Activity Bar entry for Repository Map.
2. Native sidebar sections for repository and session summaries.
3. Editor tabs for Repository Map and opened source files.
4. A mode toolbar: **Repository, Explore, Trace, Observe, Compare, Preserve**.
5. A query/status bar showing the current question, HydraDB mode, revision, and result size.
6. A central 2D graph pane.
7. A right-side evidence inspector.
8. A path or revision timeline below the graph.
9. Normal VS Code status items for repository and HydraDB readiness.

The standalone mockup uses an in-panel source preview to demonstrate navigation. The real extension opens the actual document in a VS Code editor and selects the stored range.

## Main surfaces

### Activity Bar container

Working label: **Repository Map**.

Sidebar sections:

- Current Symbol
- Entrypoints
- Saved System Lenses
- Recent Graph Changes
- Agent Activity
- HydraDB Index Status

Use native Tree Views for these compact lists.

### Editor graph panel

Use a webview panel for the interactive graph canvas. It should support:

- A repository structure map at package, file, and symbol depth.
- Focused node neighborhoods.
- Left-to-right flow paths.
- Module/package maps.
- Before/after graph overlays.
- Progressive depth and semantic zoom.
- Node dragging, canvas panning, wheel zoom, and layout reset.
- Filtering by relation kind and quality.
- A path timeline.
- An evidence inspector.

The repository map is 2D. Its nodes are concrete repository entities. Spatial position is presentation state and must not be described as architecture, importance, confidence, or runtime order.

The webview should never receive the HydraDB API key. It communicates through the extension host.

### Editor integration

Commands:

- `Show in Repository Map`
- `Show Callers and Callees`
- `Trace Flow from Here`
- `Find Tests for This Symbol`
- `Ask HydraDB About This Code`
- `Compare Graph Before and After Change`
- `Save as System Lens`
- `Follow Agent`

Optional CodeLens example:

```text
4 callers · 3 tests · View HydraDB graph
```

Clicking a graph entity or edge opens the exact source range in a normal VS Code editor.

### Source navigation behavior

For a node selection:

1. The webview sends the stable entity ID and stored source range to the extension host.
2. The extension validates that the path is inside the active workspace.
3. VS Code opens the document and reveals the range.
4. The graph keeps the node selected and the evidence inspector stays synchronized.

For an edge selection, use the relation's evidence range rather than the target node's declaration range. If several evidence records prove the edge, show the list and open the first record by default.

Directory/package nodes open the corresponding Explorer location. A package-level aggregated edge opens a list of its contributing exact relations rather than pretending one line proves the whole aggregate.

## Views, not one graph

| UI mode | Default shape | Main use |
|---|---|---|
| Repository | Concrete packages, files, or symbols | Orientation and onboarding |
| Explore | Selected entity plus bounded neighbors | Local comprehension |
| Trace | Left-to-right path with branches | Explain system behavior |
| Observe | Animated returned and selected context | Observe agent repository access |
| Compare | Stable before/after overlay | Review structural evolution |
| Preserve | Grounded saved path plus drift state | Maintain living system knowledge |

Test and configuration maps are filters or focused projections inside Repository, Explore, or Trace. They are not separate top-level modes in the current shell.

### Primary action by mode

| Mode | Primary action | Behavior |
|---|---|---|
| Repository | Open local graph | Open Explore around the currently selected concrete entity. |
| Explore | Expand graph | Request the next bounded neighborhood depth until the render budget is reached. |
| Trace | Replay path | Replay the returned path; allow pause and restart. |
| Observe | Pause follow / Resume follow | Pause visual following while continuing to buffer observable events. |
| Compare | Review changes | Advance through changed nodes and edges with before/after evidence. |
| Preserve | Accept drift | After review, set the current grounded path as the lens's new baseline. |

Every action must expose a visible result, disabled state, or honest error. A clickable control must not exist only as decoration.

Default to roughly 10–30 visible nodes. Large paths should collapse intermediate clusters with explicit expansion controls.

The Repository mode is the exception only in scope, not density. It can represent the full repository at package or file depth, but must progressively reveal detail and must never render all symbol labels at once.

## Repository mode interaction contract

| Action | Result |
|---|---|
| Select Packages, Files, or Symbols | Rebuild the visible deterministic projection at that depth. |
| Drag a node | Change only its local display position; keep connected edges attached. |
| Drag the background | Pan the current view. |
| Use the wheel or zoom control | Zoom around the pointer or current focus. |
| Reset layout | Clear local position overrides and restore the deterministic default layout. |
| Click a node | Select it, update evidence, and open its source or Explorer location. |
| Click an edge | Select it, explain the predicate, and open proving source evidence. |
| Filter relations | Hide or show predicates without changing stored facts. |
| Enable inferred relations | Show them with dashed styling and explicit inferred labels. |

Keyboard users can move between visible nodes, open the selected source, close the source preview, and access a textual relation list.

## Agent traversal visualization

The centerpiece is a highlighted traversal path.

Suggested visual states:

| State | Visual treatment | Meaning |
|---|---|---|
| Current traversal hop | Pulsing blue plus motion marker | The currently replayed or explicitly observed step |
| HydraDB returned | Solid blue | Present in a HydraDB result |
| Agent context selected | Purple | Included in the bounded context returned to the agent |
| Evidence opened | Orange outline | The agent explicitly requested or opened the source evidence |
| Edited | Green fill plus edit badge | Workspace change observed for that entity |
| Removed | Red strike/outline | Removed in graph comparison |
| Inferred relation | Dashed edge plus label | Not deterministically proven |
| Unused context | Dimmed | Present for orientation but not returned or selected |

Do not rely on color alone. Use icons, labels, stroke styles, and an accessible event list.

## Truthful animation modes

### HydraDB path replay

After `/query` returns, animate its `graph_context.query_paths` and associated chunks. Label this clearly as a **HydraDB returned path**.

### Live agent tool traversal

As the agent calls repository MCP tools, animate each query and returned path event. This is genuinely live because the product observes each tool call.

### What must not be claimed

Do not say that the animation shows every internal HydraDB search step or the agent's private reasoning. The product shows:

- HydraDB-returned paths.
- HydraDB-returned chunks and relations.
- Explicit MCP tool calls.
- Source evidence explicitly opened through the product.
- File changes observed in the workspace.

## Path timeline

Each agent session should have a synchronized timeline:

```text
Asked repository question
→ HydraDB returned path p_0
→ Agent selected three chunks
→ Agent opened authorize_user
→ Agent edited policy.py
→ Re-index started
→ HydraDB revision became ready
→ Saved Authentication Lens drifted
```

Selecting a timeline event focuses the corresponding graph state.

## Evidence inspector

For a selected edge, show:

- Source and target display names.
- Predicate.
- Exact or inferred quality.
- Plain explanation.
- File and line evidence.
- Parser and version.
- Repository revision.
- HydraDB relation origin when returned.
- HydraDB path relevancy score where available.
- Associated retrieved chunk.

For a selected node, show:

- Concrete entity kind and display name.
- Stable entity ID.
- File and declaration range, or concrete repository location.
- Parser or adapter that created it.
- Plain reason it appears in the current view.
- Repository revision and HydraDB record origin.

Use the labels **Why shown**, **Method**, **Stable ID**, **Revision**, and **HydraDB** in the inspector. Include “no LLM” when a fact was derived deterministically so the user does not have to infer the provenance model.

This is where the product earns trust. A line without evidence is decoration.

## Compare

Requirements:

- Preserve node positions where possible between revisions.
- Show added, removed, modified, and renamed nodes.
- Show added and removed relations.
- Filter to “changes affecting this System Lens.”
- Provide a text summary beside the graph.
- Separate structural impact from test failures and runtime claims.

Example summary:

```text
Authentication changed:
- authorize_user now calls load_role_permissions.
- audit_access is no longer on the returned request path.
- one test relation was removed.
```

## HydraDB visibility

HydraDB should be unmistakable but accurate:

- Status: `HydraDB · current revision ready`.
- Query badge: `HydraDB · hybrid · thinking · graph context`.
- Path badge: `HydraDB Graph Path p_0`.
- Edge origin: `Deterministic BYOG relation`.
- Indexing state: `Uploading 12 changed symbols to HydraDB`.
- Failure state: `HydraDB unavailable; repository graph features paused`.

Do not hide these behind a generic “AI” label.

## Performance rules

- Never send the full repository graph to the webview by default.
- Apply node and edge budgets before rendering.
- Virtualize long event and result lists.
- Debounce active-editor changes.
- Reuse the current bounded HydraDB result while the user pans or selects.
- Ask the service for expansion only when the user requests it.
- Avoid expensive layout recomputation for simple style changes.
- Preserve positions during change comparison.
- Keep user layout overrides as bounded view state. Do not write them into structural Graph IR or BYOG relations.
- Recompute only the visible edge geometry while a node is dragged.

## Accessibility

- Provide keyboard navigation between nodes and edges.
- Provide a textual path list equivalent to every visual path.
- Do not encode state only through color or animation.
- Respect reduced-motion settings.
- Use VS Code theme variables.
- Provide accessible labels containing node kind, name, relation, and state.
- Keep source navigation available without the graph canvas.
- Give every mode button an accessible name even when its visible label is hidden at narrow widths.

## Empty and degraded states

Good empty states explain the next action:

- No repository indexed: `Index this workspace with HydraDB`.
- Indexing: show progress and the last verified revision.
- No path returned: offer a narrower query or a literal symbol search.
- Dynamic relation unknown: explain that static analysis could not prove it.
- HydraDB unavailable: show retry and configuration actions; do not silently switch engines.
