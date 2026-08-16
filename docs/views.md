# Argus views

Argus is a HydraDB-backed VS Code view for answering focused questions about a repository. It renders bounded graph results rather than a full-repository hairball. Source files remain authoritative; the graph is an explanation and navigation surface.

For task-based instructions, see [Workflows](workflows.md). Observe has its own [detailed guide](observe.md). Keyboard, motion, and narrow-panel behavior are covered in [Accessibility](accessibility.md).

## The VS Code shell

Open **Argus** from the Activity Bar, the Command Palette, the status bar, a source editor's context menu, or the `View repository graph` CodeLens at the top of a file.

The Activity Bar container has six native sidebar sections:

- **Current Symbol** shows the active source file and opens an Explore view.
- **Entrypoints** opens the Repository view when a verified revision is available.
- **Saved System Lenses** opens Preserve.
- **Recent Graph Changes** opens Compare.
- **Agent Activity** opens Observe.
- **HydraDB Index Status** reports readiness and exposes **Index this workspace**.

The editor panel contains:

1. service and revision status;
2. the seven mode tabs;
3. a repository question box;
4. the current view summary and primary action;
5. relation, inferred-edge, zoom, and layout controls;
6. the graph;
7. an optional path or event timeline;
8. a textual path and relation list; and
9. the evidence inspector.

The status-bar items open the map. The HydraDB status item distinguishes ready, indexing, unverified, and unavailable states.

## Status means evidence, not optimism

The panel shows a ready state only when all of these are true:

- the local service reports `ready`;
- both the service and the view name the same concrete revision;
- the returned view says HydraDB was available; and
- the view is not an interaction preview.

The main status labels mean:

| Label | Meaning |
|---|---|
| `HydraDB · revision … ready` | The visible result is pinned to the service's verified revision. |
| `HydraDB · indexing` | A candidate is being indexed. The last verified revision may remain active. |
| `HydraDB · revision unverified` | HydraDB answered, but the view is not proven to match the verified revision. |
| `HydraDB · indexing failed` | The candidate did not become current. A partial revision is not presented as ready. |
| `HydraDB · unavailable for this view` | No HydraDB-backed result is available for this view. There is no silent local retrieval fallback. |
| `Preview · service unavailable` | A bounded interaction fixture is shown only to demonstrate controls. It is not repository or HydraDB data. |

The revision badge repeats whether the current result is verified. A degraded banner provides **Retry service** and an explanation.

## Controls shared by all views

### Ask and trace

Enter a concrete question such as `How does an incoming request reach a database write?` and select **Trace with HydraDB**. A successful request opens Trace using hybrid retrieval, thinking mode, and graph context. An empty question is rejected. A failed query shows an explicitly labeled interaction preview, never a fabricated repository result.

### Relations and inferred edges

Each relation predicate returned in the current view becomes a filter chip. Clearing a chip removes that predicate from both the graph and the textual relation list; it does not delete or change a stored fact.

Inferred relations are hidden by default. **Show inferred** is enabled only when the view contains inferred edges. Inferred edges use a dashed line and an `inferred` text label. Exact relations remain separate.

### Pan, zoom, drag, and reset

- Drag empty graph background to pan.
- Use the wheel to zoom around the pointer.
- Use **−** and **+** to zoom around the graph center.
- Drag a node to change its display position; attached edge paths and labels move with it.
- Select **Reset view**, or press `0` while the graph has focus, to restore the deterministic layout and default viewport.

Layout, zoom, filters, inferred visibility, and selection are presentation state. They do not write graph facts.

### Selecting and opening evidence

Selecting a node updates the inspector and, when a source range exists, opens that range in a normal VS Code editor. Selecting an edge opens its first evidence record. Use the individual evidence buttons in the inspector to open a different record.

Before opening anything, the extension verifies that the workspace-relative path stays inside an active workspace folder. Files open at the stored line and column range. Directory evidence is revealed in Explorer. Outside-workspace, missing, and invalid ranges are blocked with a warning.

The inspector uses explicit fields:

- **Why shown** explains why the item is in this bounded result.
- **Method** names the parser or extractor. Deterministic facts say `no LLM`; inferred facts say `heuristic`.
- **Stable ID** identifies the concrete node or edge.
- **Revision** identifies the graph revision.
- **HydraDB** identifies the returned record or relation origin.

For edges, the inspector also shows exact/inferred quality, source and target, predicate, and every returned evidence record. An aggregate relation is labeled with its number of contributing exact relations; it is not presented as if one line proves the whole aggregate.

## Repository

**Purpose:** orient to concrete packages, files, or symbols.

Repository is the only mode with the **Packages**, **Files**, and **Symbols** depth control. Changing depth asks the service to rebuild the bounded projection. Package or file depth is usually the clearest starting point; symbol depth is denser.

The primary action is **Open local graph**. It requires a selected concrete node and switches to Explore. The service still decides the bounded Explore result; selecting a node is not permission to invent missing relationships.

Use Repository for onboarding, locating entrypoints, and choosing a smaller region before exploring details.

## Explore

**Purpose:** inspect a bounded neighborhood around code or a focused editor location.

Explore normally shows a selected entity with nearby callers, callees, imports, tests, or other returned relations. The exact predicates depend on the service result.

The primary action is **Expand graph**. It asks the local service for the next bounded Explore action, using the selected stable ID when one is available. Expansion is not performed locally and remains subject to the service's node and edge budgets. In a preview or unavailable state, the action explains that repository truth was not changed.

Use **Show Callers and Callees** or **Find Tests for This Symbol** from a source editor for an honest file-and-line-focused Explore request. See [Focused editor workflows](workflows.md#focus-a-view-from-the-editor).

## Trace

**Purpose:** explain a returned system path from left to right.

Trace is opened by the question bar, **Ask HydraDB About This Code**, **Trace Flow from Here**, or the Trace mode tab. A service query returns a bounded path and source evidence. The timeline lists returned path events when present.

The primary action is **Replay path**. Replay is a local presentation sequence over the nodes already returned by HydraDB; it does not reveal HydraDB's internal search or an agent's private reasoning. Reduced-motion users get the same selections without the timed sweep.

If the query returns no bounded nodes, the empty state recommends a narrower question or literal symbol search.

## Observe

**Purpose:** follow explicit repository activity for one verified revision.

Observe starts a bounded follow session, polls explicit events, and loads stored HydraDB views by their exact IDs. Node and edge states distinguish returned, selected, opened, and edited items. The primary action is **Pause follow**, **Resume follow (count)**, or **Restart follow** after a fail-closed stop.

Observe does not show private reasoning or every internal HydraDB search step. See [Observe](observe.md) for event types, timeline behavior, buffering, workspace edit matching, and restart conditions.

## Compare

**Purpose:** review a published structural delta between two explicit revisions.

Compare requires distinct before and after revisions. A successfully published pair is remembered in workspace state so the mode tab and refresh can reopen it. Without a verified pair, Compare shows the service's honest empty state.

Added, removed, and modified nodes use separate badges and stroke treatments. Added and removed edges also have distinct styles. Compare states are separate from Observe's returned/selected/opened states.

The primary action is **Review changes**. Each use advances to and centers the next changed node. It does not claim test or runtime effects unless those facts were returned separately.

Create a comparison through the two-stage [Compare workflow](workflows.md#compare-two-revisions).

## Preserve

**Purpose:** maintain a grounded, shared System Lens across revisions.

Preserve opens one saved lens by its exact lens ID. A successful save is remembered in workspace state, so the mode tab and refresh can reopen it. Without a saved lens context, the service returns an honest empty state.

The view separates the lens's saved revision from the current verified view. The `SYSTEM_LENS` node carries the saved lens metadata and drift classification; the remaining nodes and edges are the exact current grounded view.

The primary action is **Accept drift**. It is available only for a grounded current view and an exact shared lens. The extension first requests a no-write preview, then shows a modal review. Only **Accept reviewed drift** writes the new baseline. Cancellation leaves the baseline unchanged.

See [Save and maintain a System Lens](workflows.md#save-and-maintain-a-system-lens).

## Contrast

**Purpose:** answer one question twice with the same coding agent and the same model, once without Argus and once with it.

Contrast shows two runs side by side:

- **Base agent** — Claude Code answers using the tools its harness normally gives it: Grep, Glob, Read, Bash, and the rest. Argus is not used.
- **With Argus** — the same agent, with the same harness and the same tools, plus the Argus loopback MCP endpoint. It can also call `repository_query`, `trace_flow`, and `focus_symbol`.

The two sides differ by addition only. Argus is measured as an augmentation of the harness, never as a replacement for it.

Both runs are real and live. Neither column is a fixture or a recording.

Each column reports the agent's own measured usage: tools available, tool calls made, files read, turns, input, output, and cache tokens, thinking tokens, wall-clock duration, and cost in USD. A metrics strip above the two columns shows the difference. Token counts and cost come from the agent CLI's own usage report; they are not an Argus estimate.

### What is restricted

`Write`, `Edit`, and `NotebookEdit` are denied on both sides. Contrast is read-only.

Nothing else is taken away. Both sides keep every read-only tool the harness gives them, so the Argus side is never a weakened agent. The agent chooses when to use an Argus tool and when to use its own; that choice is part of what the run measures.

The spawned agent never receives HydraDB credentials. Every `HYDRA_DB_*` environment variable is stripped before the process starts.

### What a run proves

Agent runs are not deterministic. The same question can produce a different number of tool calls on a different run. The panel reports the run it actually made. It does not average runs and it does not claim a general result.

One observed run in this repository, for the question `How does a repository question become a HydraDB request body, and which test proves it?`, measured the base agent at 17 turns, 16 tool calls, 6 files read, 72 seconds, and $0.81. That is one run, not a benchmark.

### Requirements and cost

Contrast requires the `claude` CLI to be installed and signed in. If it is absent, the view shows the agent gate instead of a comparison.

Each contrast run costs real money, because it is two real agent runs. See [Contrast a question with and without Argus](workflows.md#contrast-a-question-with-and-without-argus) and [Contrast runs](limitations.md#contrast-runs).

## Empty and degraded states

- **No verified index:** use **Index this workspace** from the sidebar, view title, or Command Palette.
- **Empty graph:** the panel names the stage that emptied it. Narrow the question only when it reports that HydraDB matched no repository source. A dropped relation group or a hop without node grounding calls for indexing again, and a timeout or a refusal names the HydraDB reason instead. See [Read the query funnel](troubleshooting.md#read-the-query-funnel).
- **No Compare pair or Preserve lens:** run the corresponding workflow; the extension does not invent IDs.
- **Indexing:** wait for the candidate to become ready. The last verified revision is labeled separately.
- **Service unavailable:** configure or retry the loopback service. The interaction preview remains usable for learning the controls but is never labeled as HydraDB data.
- **Action unavailable:** the UI shows a toast or modal error. Controls do not silently mutate a preview.

## Current UI limits

- Views are bounded by service-provided node and edge budgets; the full repository graph is not sent to the webview by default.
- Node labels are shortened visually to fit cards. The accessible label and inspector keep the full returned name.
- Relation filtering and node layout are local display choices, not persisted repository knowledge.
- Repository depth applies only to Repository. Other modes use the depth returned by the service.
- The mode tabs can reopen only the last verified Compare pair and last saved/opened lens. Preview IDs are never persisted as workflow context.
- Contrast is not a bounded HydraDB view. It reports the two agent runs it made, and repeating the same question can produce different counts.
- At very narrow panel widths the view keeps a minimum usable canvas width and may require horizontal scrolling. See [Responsive behavior](accessibility.md#responsive-behavior).
