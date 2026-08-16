# Accessibility and responsive behavior

Argus provides a keyboard-operable graph, a textual equivalent for visible relations, explicit state labels, reduced-motion behavior, and VS Code theme integration. This page describes the current controls and limits.

For the seven modes and common controls, see [Views](views.md). For task recipes, see [Workflows](workflows.md). Observe-specific event semantics are in [Observe](observe.md).

## Keyboard use

Use normal `Tab` and `Shift+Tab` navigation for mode tabs, the query form, primary action, relation filters, inferred toggle, zoom and reset controls, timeline events, evidence buttons, and the textual relation list.

When the graph has focus:

| Key | Action |
|---|---|
| `Arrow Right` or `Arrow Down` | Select the next visible node, wrapping at the end. |
| `Arrow Left` or `Arrow Up` | Select the previous visible node, wrapping at the start. |
| `Enter` | Open the selected node's source when it has a source range. |
| `0` | Reset node positions and the viewport. |

Individual graph nodes and edges use button semantics. `Enter` or `Space` selects the focused item and opens its source or first evidence record when available. Edges are also reachable through normal tab navigation.

Selecting a timeline entry selects its first visible referenced node or edge. A referenced node is also centered and keyboard-focused. The always-available **Accessible path and relation list** exposes each currently visible relation as a text button containing source, predicate, target, and quality.

If the graph canvas is difficult to use, the same source-focused entry points remain available through the editor context menu and `View repository graph` CodeLens. The evidence inspector and textual relation list do not require pointer dragging.

## Focus and accessible names

- Keyboard-focused buttons, mode tabs, timeline entries, zoom controls, and filter chips receive a visible two-pixel focus outline using the current VS Code accent color.
- Every mode tab has an accessible name containing both its label and purpose, even when surrounding header text is hidden at narrow widths.
- The graph is labeled as an interactive repository graph and includes its arrow-key and Enter instructions.
- Node accessible names contain the returned kind, full display name, and reason shown.
- Edge accessible names contain the predicate, exact/inferred quality, and explanation.
- Service toasts use a polite live status region. The zoom percentage is also a polite live output.

Visual node names may be shortened to 21 characters on the canvas. The accessible name and inspector retain the full returned display name.

## State is not color alone

Argus combines color with text and shape:

- inferred edges are dashed and include an `inferred` label;
- returned, selected, opened, and edited nodes have `RETURNED`, `SELECTED`, `OPENED`, and `EDITED` badges;
- added, removed, and modified Compare nodes have `+ ADDED`, `− REMOVED`, and `~ CHANGED` badges;
- removed nodes and edges use dashed outlines;
- the evidence quality badge says `exact`, `inferred`, `semantic`, or the returned quality;
- the timeline and textual relation list provide non-canvas equivalents.

Do not use color alone when reviewing a view. Confirm the badge, relation quality text, inspector explanation, and source evidence.

## The Contrast panel

Contrast is two columns of measured agent activity rather than a graph, so it has its own structure:

- Each run is a labeled section. One section is the base agent run and one is the Argus run, and the label names which run the column reports.
- The metrics strip and both tool-call lists are polite live regions, so counts and new tool calls are announced as the runs proceed.
- A text alternative lists both trajectories in order. The tool calls of each run can be read in sequence without comparing the two columns visually.
- No difference is stated by color alone. Every difference in the metrics strip is also written as text.

See [Contrast](views.md#contrast) for what each column reports.

## Reduced motion

Argus honors `prefers-reduced-motion: reduce`.

When reduced motion is enabled:

- arrival animations and transitions are reduced to effectively immediate changes;
- smooth scrolling is disabled; and
- Trace replay applies its node selections without the normal staggered delay.

The result and event order do not change. Reduced motion changes only presentation timing.

## Pointer and touchpad controls

- Drag a node with the primary pointer to move it. Connected edges remain attached.
- Drag empty background to pan.
- Use the wheel or touchpad scroll gesture over the graph for pointer-centered zoom.
- Use the **−** and **+** buttons when wheel zoom is inconvenient.
- Use **Reset view** to undo local display movement and zoom.

Node movement does not change graph facts, confidence, importance, architecture, or runtime order.

## Responsive behavior

The panel follows VS Code theme variables and adapts in two main steps:

- At 980 pixels and below, the evidence inspector moves below the graph, the query metadata is hidden, view actions stack, and the graph uses a fixed 470-pixel height.
- At 780 pixels and below, compact identity details and revision text are hidden, mode tabs and page padding tighten, and only the first four relation-filter chips remain visible.

The shell keeps a minimum width of 620 pixels. Below that size the webview may scroll horizontally instead of compressing the graph and controls into an unusable layout. Open the panel in a wider editor group for dense symbol views or evidence review.

The graph height otherwise scales between roughly 400 and 610 pixels. Timelines and relation toolbars scroll horizontally when their content exceeds the available width.

## Screen-reader-oriented review path

For a source-backed review without relying on canvas position:

1. Open a focused view from the source editor context menu.
2. Confirm the service and revision status.
3. Tab to **Accessible path and relation list** and expand it if needed.
4. Activate a relation to synchronize the evidence inspector and open its first evidence record.
5. Tab through the inspector's evidence cards to inspect alternate proof locations.
6. Use the normal VS Code editor and Explorer for the validated source location.

Spatial position is presentation only. The textual relationship and evidence remain the meaningful content.

## Accessible degraded states

- Degraded and preview states use a visible status banner with a title, explanation, and retry control.
- An interaction preview says it is not a repository result and that no HydraDB result is shown.
- Empty views display a text instruction to narrow the question or use a literal symbol search.
- Unavailable actions produce a toast or modal message instead of silently doing nothing.
- Observe pause, buffer count, stop, and restart states are written into the primary action label and announced through status messages.

## Current accessibility limits

- The graph uses an SVG `application` region with custom keyboard behavior. Users must enter the graph and use its documented keys; it is not exposed as a native tree widget.
- Arrow-key navigation covers nodes. Edges use Tab, the textual relation list, or pointer selection.
- Visual relation chips beyond the first four are hidden under 780 pixels. Use a wider panel when all predicate filters are needed.
- Timeline items show label and detail but do not currently render the event timestamp as visible text.
- Toasts disappear after about four seconds, although persistent status and degraded banners remain for important service state.
- There is no separate high-contrast layout mode. The UI relies on VS Code theme colors, outlines, labels, and native high-contrast variables where available.
