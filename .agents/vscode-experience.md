# VS Code Experience

## UX principle

The extension should help the programmer answer a question. It should not display a graph merely because a graph exists.

Index broadly. Render narrowly. Expand progressively.

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

- Focused node neighborhoods.
- Left-to-right flow paths.
- Module/package maps.
- Before/after graph overlays.
- Semantic zoom.
- Filtering by relation kind and quality.
- A path timeline.
- An evidence inspector.

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

## Views, not one graph

| View | Default shape | Main use |
|---|---|---|
| Repository Map | Grouped modules/packages | Orientation and onboarding |
| Symbol Focus | Selected node plus bounded neighbors | Local comprehension |
| Flow Trace | Left-to-right path with branches | Explain system behavior |
| Test Map | Code path with linked tests | Change confidence |
| Configuration Map | Config/infra to runtime path | Explain wiring |
| Agent View | Animated returned and selected context | Observe agent repository access |
| Change Map | Stable before/after layout | Review structural evolution |

Default to roughly 10–30 visible nodes. Large paths should collapse intermediate clusters with explicit expansion controls.

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

This is where the product earns trust. A line without evidence is decoration.

## Change Map

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

## Accessibility

- Provide keyboard navigation between nodes and edges.
- Provide a textual path list equivalent to every visual path.
- Do not encode state only through color or animation.
- Respect reduced-motion settings.
- Use VS Code theme variables.
- Provide accessible labels containing node kind, name, relation, and state.
- Keep source navigation available without the graph canvas.

## Empty and degraded states

Good empty states explain the next action:

- No repository indexed: `Index this workspace with HydraDB`.
- Indexing: show progress and the last verified revision.
- No path returned: offer a narrower query or a literal symbol search.
- Dynamic relation unknown: explain that static analysis could not prove it.
- HydraDB unavailable: show retry and configuration actions; do not silently switch engines.
