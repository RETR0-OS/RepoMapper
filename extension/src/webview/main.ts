import "./styles.css";
import { createPreviewView } from "../previewData.js";
import { deriveViewStatus } from "../statusState.js";
import type {
  GraphDepth,
  GraphEdge,
  GraphNode,
  GraphView,
  HostToWebviewMessage,
  ServiceHealth,
  SourceRange,
  ViewMode,
  WebviewToHostMessage
} from "../types.js";
import { DEFAULT_TRANSFORM, nextSelection, visibleEdges, zoomAtPoint, type Transform } from "./graphState.js";
import { computeLayout, edgePath, type NodePositions, type Point } from "./layout.js";

interface VsCodeApi {
  postMessage(message: WebviewToHostMessage): void;
  getState(): unknown;
  setState(state: unknown): void;
}

declare global {
  interface Window {
    __HYDRA_PREVIEW__?: boolean;
    acquireVsCodeApi?: () => VsCodeApi;
  }
}

const MODES: Array<{ id: ViewMode; label: string; hint: string }> = [
  { id: "repository", label: "Repository", hint: "Orient to concrete packages, files, and symbols" },
  { id: "explore", label: "Explore", hint: "Inspect a bounded neighborhood" },
  { id: "trace", label: "Trace", hint: "Follow a returned system path" },
  { id: "observe", label: "Observe", hint: "See explicit agent repository activity" },
  { id: "compare", label: "Compare", hint: "Review verified structural change" },
  { id: "preserve", label: "Preserve", hint: "Maintain grounded System Lenses" }
];

const PRIMARY_LABELS: Record<ViewMode, string> = {
  repository: "Open local graph",
  explore: "Expand graph",
  trace: "Replay path",
  observe: "Pause follow",
  compare: "Review changes",
  preserve: "Accept drift"
};

const app = document.querySelector<HTMLElement>("#app");
if (!app) {
  throw new Error("Repository Map requires an #app element.");
}

const vscode = window.acquireVsCodeApi?.() ?? createBrowserApi();
let view: GraphView = createPreviewView("repository", "file");
let health: ServiceHealth = { state: "unavailable", message: "Repository service has not been contacted." };
let positions: NodePositions = computeLayout(view.nodes, view.mode);
let transform: Transform = { ...DEFAULT_TRANSFORM };
let selectedId: string | undefined;
let selectedKind: "node" | "edge" = "node";
let relationKinds = new Set(view.edges.map((edge) => edge.predicate));
let showInferred = false;
let observePaused = false;
let observeBufferedCount = 0;
let observeActive = false;
let reviewIndex = -1;
let toastTimer: number | undefined;
let dragState:
  | { type: "node"; id: string; offset: Point; moved: boolean }
  | { type: "pan"; start: Point; origin: Point }
  | undefined;

app.innerHTML = `
  <main class="shell">
    <header class="topbar">
      <div class="identity">
        <span class="mark" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
        <div><strong>Repository Map</strong><span>See your code like your agent</span></div>
      </div>
      <div class="status-cluster">
        <span id="service-status" class="status-pill"></span>
        <span id="revision-status" class="meta-pill"></span>
      </div>
    </header>
    <nav id="mode-tabs" class="mode-tabs" aria-label="Repository Map modes"></nav>
    <section class="querybar" aria-label="Repository question and view controls">
      <form id="query-form" class="query-form">
        <label class="sr-only" for="query-input">Ask about the repository</label>
        <span class="query-icon" aria-hidden="true">⌕</span>
        <input id="query-input" autocomplete="off" placeholder="Ask how a concrete flow works…" />
        <button type="submit" class="button button-primary">Trace with HydraDB</button>
      </form>
      <div id="query-meta" class="query-meta"></div>
    </section>
    <section id="degraded-banner" class="degraded-banner" role="status" hidden>
        <div><strong id="degraded-title">Interactive preview</strong><span id="degraded-copy"></span></div>
      <button id="retry-button" type="button" class="button button-quiet">Retry service</button>
    </section>
    <section class="workspace">
      <section class="canvas-column" aria-label="Graph workspace">
        <div class="viewbar">
          <div>
            <span id="eyebrow" class="eyebrow"></span>
            <h1 id="view-title"></h1>
            <p id="view-summary"></p>
          </div>
          <div class="view-actions">
            <div id="depth-control" class="segmented" aria-label="Repository depth"></div>
            <button id="primary-action" type="button" class="button button-primary"></button>
          </div>
        </div>
        <div class="graph-card">
          <div class="graph-toolbar">
            <div id="relation-filters" class="relation-filters" aria-label="Relation filters"></div>
            <label class="switch-control"><input id="inferred-toggle" type="checkbox" /> <span>Show inferred</span></label>
            <span class="toolbar-spacer"></span>
            <button id="zoom-out" type="button" class="icon-button" aria-label="Zoom out">−</button>
            <output id="zoom-level" aria-live="polite">100%</output>
            <button id="zoom-in" type="button" class="icon-button" aria-label="Zoom in">+</button>
            <button id="reset-layout" type="button" class="button button-quiet">Reset view</button>
          </div>
          <div id="graph-wrap" class="graph-wrap">
            <svg id="graph" viewBox="0 0 1000 590" tabindex="0" role="application" aria-label="Interactive repository graph. Use arrow keys to move between nodes and Enter to open source evidence.">
              <defs>
                <marker id="arrow-exact" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z"></path></marker>
                <marker id="arrow-inferred" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z"></path></marker>
              </defs>
              <rect class="canvas-background" x="-3000" y="-3000" width="7000" height="7000"></rect>
              <g id="viewport"><g id="edge-layer"></g><g id="node-layer"></g></g>
            </svg>
            <div class="canvas-note">Layout is presentation only. Source evidence is authoritative.</div>
            <div id="empty-state" class="empty-state" hidden></div>
          </div>
        </div>
        <section class="timeline-panel" aria-labelledby="timeline-title">
          <div class="section-heading"><h2 id="timeline-title">Path timeline</h2><span>Observable events only</span></div>
          <ol id="timeline" class="timeline"></ol>
        </section>
        <details class="text-alternative" open>
          <summary>Accessible path and relation list</summary>
          <ol id="path-list"></ol>
        </details>
      </section>
      <aside class="inspector" aria-labelledby="inspector-title">
        <div class="section-heading"><h2 id="inspector-title">Evidence</h2><span id="quality-badge" class="quality-badge"></span></div>
        <div id="inspector-content"></div>
      </aside>
    </section>
    <div id="toast" class="toast" role="status" aria-live="polite" hidden></div>
  </main>`;

const elements = {
  serviceStatus: required("service-status"),
  revisionStatus: required("revision-status"),
  modeTabs: required("mode-tabs"),
  queryForm: required<HTMLFormElement>("query-form"),
  queryInput: required<HTMLInputElement>("query-input"),
  queryMeta: required("query-meta"),
  degradedBanner: required("degraded-banner"),
  degradedTitle: required("degraded-title"),
  degradedCopy: required("degraded-copy"),
  retryButton: required<HTMLButtonElement>("retry-button"),
  eyebrow: required("eyebrow"),
  viewTitle: required("view-title"),
  viewSummary: required("view-summary"),
  depthControl: required("depth-control"),
  primaryAction: required<HTMLButtonElement>("primary-action"),
  relationFilters: required("relation-filters"),
  inferredToggle: required<HTMLInputElement>("inferred-toggle"),
  zoomLevel: required<HTMLOutputElement>("zoom-level"),
  graph: required<SVGSVGElement>("graph"),
  viewport: required<SVGGElement>("viewport"),
  edgeLayer: required<SVGGElement>("edge-layer"),
  nodeLayer: required<SVGGElement>("node-layer"),
  emptyState: required("empty-state"),
  timelinePanel: document.querySelector<HTMLElement>(".timeline-panel")!,
  timeline: required<HTMLOListElement>("timeline"),
  pathList: required<HTMLOListElement>("path-list"),
  inspector: required("inspector-content"),
  qualityBadge: required("quality-badge"),
  toast: required("toast")
};

bindEvents();
renderAll();
vscode.postMessage({ type: "ready" });

window.addEventListener("message", (event: MessageEvent<HostToWebviewMessage>) => {
  const message = event.data;
  if (!message || typeof message.type !== "string") {
    return;
  }
  if (message.type === "view") {
    applyView(message.view, message.health);
  } else if (message.type === "loading") {
    elements.serviceStatus.textContent = message.message;
    elements.serviceStatus.className = "status-pill is-loading";
  } else if (message.type === "error") {
    showToast(message.message, "error");
  } else if (message.type === "sourceOpened") {
    markOpened(message.itemId);
    showToast("Opened exact source evidence in the editor.");
  } else if (message.type === "observeStatus") {
    observeActive = message.active;
    observePaused = message.paused;
    observeBufferedCount = message.bufferedCount;
    renderHeader();
    if (message.message) showToast(message.message);
  } else if (message.type === "actionResult") {
    showToast(message.message);
    if (message.view) {
      applyView(message.view, health);
    }
  }
});

function required<T extends HTMLElement | SVGElement = HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) {
    throw new Error(`Missing element #${id}`);
  }
  return element as T;
}

function bindEvents(): void {
  elements.queryForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const question = elements.queryInput.value.trim();
    if (question) {
      vscode.postMessage({ type: "query", question });
    } else {
      showToast("Enter a concrete repository question.", "error");
      elements.queryInput.focus();
    }
  });
  elements.retryButton.addEventListener("click", () => vscode.postMessage({ type: "retry" }));
  elements.inferredToggle.addEventListener("change", () => {
    showInferred = elements.inferredToggle.checked;
    renderGraph();
    renderPathList();
  });
  required("zoom-in").addEventListener("click", () => setZoom(transform.scale * 1.15));
  required("zoom-out").addEventListener("click", () => setZoom(transform.scale / 1.15));
  required("reset-layout").addEventListener("click", resetLayout);
  elements.primaryAction.addEventListener("click", runPrimaryAction);
  elements.graph.addEventListener("wheel", onWheel, { passive: false });
  elements.graph.addEventListener("pointerdown", onPointerDown);
  elements.graph.addEventListener("pointermove", onPointerMove);
  elements.graph.addEventListener("pointerup", onPointerUp);
  elements.graph.addEventListener("pointercancel", onPointerUp);
  elements.graph.addEventListener("keydown", onGraphKeydown);
}

function applyView(nextView: GraphView, nextHealth: ServiceHealth): void {
  view = nextView;
  health = nextHealth;
  positions = computeLayout(view.nodes, view.mode);
  transform = { ...DEFAULT_TRANSFORM };
  const latestEvent = view.mode === "observe" ? view.timeline[view.timeline.length - 1] : undefined;
  const followedNode = latestEvent?.nodeIds?.find((id) => view.nodes.some((node) => node.id === id));
  const followedEdge = latestEvent?.edgeIds?.find((id) => view.edges.some((edge) => edge.id === id));
  selectedId = followedNode ?? followedEdge ?? view.nodes[0]?.id;
  selectedKind = followedNode || !followedEdge ? "node" : "edge";
  relationKinds = new Set(view.edges.map((edge) => edge.predicate));
  showInferred = false;
  reviewIndex = -1;
  if (nextView.mode !== "observe") {
    observePaused = false;
    observeBufferedCount = 0;
    observeActive = false;
  } else if (nextView.preview) {
    observeActive = true;
  }
  renderAll();
  persistDisplayState();
}

function renderAll(): void {
  renderModes();
  renderStatus();
  renderHeader();
  renderDepth();
  renderFilters();
  renderGraph();
  renderTimeline();
  renderPathList();
  renderInspector();
}

function renderModes(): void {
  elements.modeTabs.replaceChildren(...MODES.map((mode) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `mode-tab${view.mode === mode.id ? " is-active" : ""}`;
    button.setAttribute("aria-label", `${mode.label}: ${mode.hint}`);
    button.setAttribute("aria-current", view.mode === mode.id ? "page" : "false");
    button.textContent = mode.label;
    button.addEventListener("click", () => {
      if (mode.id !== view.mode) {
        vscode.postMessage({ type: "changeMode", mode: mode.id });
      }
    });
    return button;
  }));
}

function renderStatus(): void {
  const status = deriveViewStatus(view, health);
  health = status.health;
  elements.serviceStatus.className = `status-pill ${status.tone === "ready" ? "is-ready" : status.tone === "loading" ? "is-loading" : "is-degraded"}`;
  elements.serviceStatus.textContent = status.label;
  elements.revisionStatus.textContent = status.revisionLabel;
  elements.degradedBanner.hidden = status.bannerHidden;
  elements.degradedTitle.textContent = status.bannerTitle;
  elements.degradedCopy.textContent = ` ${status.bannerMessage}`;
  elements.queryMeta.replaceChildren();
  if (view.hydradb?.available === true) {
    const labels = [
      "HydraDB",
      view.hydradb.queryBy,
      view.hydradb.mode,
      view.hydradb.graphContext ? "graph context" : undefined
    ].filter(Boolean);
    elements.queryMeta.textContent = labels.join(" · ");
  } else {
    elements.queryMeta.textContent = "Queries require the local repository service";
  }
}

function renderHeader(): void {
  const mode = MODES.find((item) => item.id === view.mode)!;
  elements.eyebrow.textContent = view.preview ? `${mode.label} · interaction preview` : `${mode.label} · bounded repository view`;
  elements.viewTitle.textContent = mode.hint;
  elements.viewSummary.textContent = view.summary ?? `${view.nodes.length} concrete entities and ${view.edges.length} relations are visible.`;
  elements.primaryAction.textContent = view.mode === "observe" && !observeActive
    ? "Restart follow"
    : view.mode === "observe" && observePaused
      ? `Resume follow${observeBufferedCount ? ` (${observeBufferedCount})` : ""}`
      : PRIMARY_LABELS[view.mode];
}

function renderDepth(): void {
  const depths: Array<{ id: GraphDepth; label: string }> = [
    { id: "package", label: "Packages" }, { id: "file", label: "Files" }, { id: "symbol", label: "Symbols" }
  ];
  elements.depthControl.hidden = view.mode !== "repository";
  elements.depthControl.replaceChildren(...depths.map((depth) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = depth.label;
    button.className = view.depth === depth.id ? "is-active" : "";
    button.setAttribute("aria-pressed", String(view.depth === depth.id));
    button.addEventListener("click", () => vscode.postMessage({ type: "changeDepth", depth: depth.id }));
    return button;
  }));
}

function renderFilters(): void {
  const predicates = [...new Set(view.edges.map((edge) => edge.predicate))].sort();
  elements.relationFilters.replaceChildren(...predicates.map((predicate) => {
    const label = document.createElement("label");
    label.className = "filter-chip";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = relationKinds.has(predicate);
    input.addEventListener("change", () => {
      input.checked ? relationKinds.add(predicate) : relationKinds.delete(predicate);
      renderGraph();
      renderPathList();
    });
    const text = document.createElement("span");
    text.textContent = predicate.replaceAll("_", " ").toLowerCase();
    label.append(input, text);
    return label;
  }));
  elements.inferredToggle.checked = showInferred;
  elements.inferredToggle.disabled = !view.edges.some((edge) => edge.quality === "inferred");
}

function renderGraph(): void {
  elements.viewport.setAttribute("transform", `translate(${transform.x} ${transform.y}) scale(${transform.scale})`);
  elements.zoomLevel.textContent = `${Math.round(transform.scale * 100)}%`;
  const edges = visibleEdges(view, relationKinds, showInferred);
  elements.edgeLayer.replaceChildren(...edges.map(renderEdge));
  elements.nodeLayer.replaceChildren(...view.nodes.map(renderNode));
  elements.emptyState.hidden = view.nodes.length > 0;
  elements.emptyState.textContent = view.nodes.length === 0
    ? "No bounded graph slice was returned. Try a narrower question or literal symbol search."
    : "";
}

function renderEdge(edge: GraphEdge): SVGGElement {
  const source = positions[edge.sourceId];
  const target = positions[edge.targetId];
  const group = svg("g");
  group.classList.add("graph-edge", `quality-${edge.quality}`, `state-${edge.state ?? "default"}`);
  group.dataset.edgeId = edge.id;
  group.setAttribute("role", "button");
  group.setAttribute("tabindex", "0");
  group.setAttribute("aria-label", `${edge.predicate} relation, ${edge.quality}. ${edge.explanation}`);
  if (!source || !target) {
    return group;
  }
  const path = svg("path");
  path.classList.add("edge-line");
  path.dataset.edgeId = edge.id;
  path.setAttribute("d", edgePath(source, target));
  path.setAttribute("marker-end", `url(#arrow-${edge.quality === "inferred" ? "inferred" : "exact"})`);
  const hit = svg("path");
  hit.classList.add("edge-hit");
  hit.setAttribute("d", edgePath(source, target));
  const label = svg("text");
  label.classList.add("edge-label");
  label.dataset.edgeLabel = edge.id;
  label.setAttribute("x", String((source.x + target.x) / 2));
  label.setAttribute("y", String((source.y + target.y) / 2 + 18));
  label.textContent = `${edge.predicate.replaceAll("_", " ")}${edge.quality === "inferred" ? " · inferred" : ""}`;
  if (selectedKind === "edge" && selectedId === edge.id) {
    group.classList.add("is-selected");
  }
  group.append(path, hit, label);
  const select = () => selectEdge(edge, true);
  group.addEventListener("click", select);
  group.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      select();
    }
  });
  return group;
}

function renderNode(node: GraphNode): SVGGElement {
  const point = positions[node.id] ?? { x: 0, y: 0 };
  const group = svg("g");
  group.classList.add("graph-node", `state-${node.state ?? "default"}`);
  group.dataset.nodeId = node.id;
  group.setAttribute("transform", `translate(${point.x} ${point.y})`);
  group.setAttribute("role", "button");
  group.setAttribute("tabindex", selectedId === node.id && selectedKind === "node" ? "0" : "-1");
  group.setAttribute("aria-label", `${node.kind.toLowerCase()} ${node.displayName}. ${node.reason}`);
  if (selectedKind === "node" && selectedId === node.id) {
    group.classList.add("is-selected");
  }
  const rect = svg("rect");
  rect.setAttribute("x", "-80"); rect.setAttribute("y", "0"); rect.setAttribute("width", "160"); rect.setAttribute("height", "58"); rect.setAttribute("rx", "12");
  const kind = svg("text");
  kind.classList.add("node-kind"); kind.setAttribute("x", "-65"); kind.setAttribute("y", "20"); kind.textContent = node.kind;
  const name = svg("text");
  name.classList.add("node-name"); name.setAttribute("x", "-65"); name.setAttribute("y", "42"); name.textContent = truncate(node.displayName, 21);
  const badge = svg("text");
  badge.classList.add("node-badge"); badge.setAttribute("x", "65"); badge.setAttribute("y", "20"); badge.setAttribute("text-anchor", "end");
  badge.textContent = stateBadge(node.state);
  group.append(rect, kind, name, badge);
  group.addEventListener("pointerdown", (event) => beginNodeDrag(event, node.id));
  group.addEventListener("click", () => {
    if (dragState?.type !== "node" || !dragState.moved) {
      selectNode(node, true);
    }
  });
  group.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      selectNode(node, true);
    }
  });
  return group;
}

function renderTimeline(): void {
  elements.timelinePanel.hidden = view.timeline.length === 0;
  elements.timeline.replaceChildren(...view.timeline.map((event, index) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "timeline-event";
    const step = document.createElement("span"); step.className = "timeline-step"; step.textContent = String(index + 1).padStart(2, "0");
    const copy = document.createElement("span");
    const label = document.createElement("strong"); label.textContent = event.label;
    const detail = document.createElement("small"); detail.textContent = event.detail;
    copy.append(label, detail); button.append(step, copy); item.append(button);
    button.addEventListener("click", () => {
      const node = view.nodes.find((candidate) => event.nodeIds?.includes(candidate.id));
      const edge = view.edges.find((candidate) => event.edgeIds?.includes(candidate.id));
      if (node) selectNode(node, false, true);
      else if (edge) selectEdge(edge, false, true);
      focusSelection();
    });
    return item;
  }));
}

function renderPathList(): void {
  const edges = visibleEdges(view, relationKinds, showInferred);
  elements.pathList.replaceChildren(...edges.map((edge) => {
    const source = view.nodes.find((node) => node.id === edge.sourceId)?.displayName ?? edge.sourceId;
    const target = view.nodes.find((node) => node.id === edge.targetId)?.displayName ?? edge.targetId;
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `${source} — ${edge.predicate.replaceAll("_", " ")} → ${target} (${edge.quality})`;
    button.addEventListener("click", () => selectEdge(edge, true));
    item.append(button);
    return item;
  }));
}

function renderInspector(): void {
  const selectedNode = selectedKind === "node" ? view.nodes.find((node) => node.id === selectedId) : undefined;
  const selectedEdge = selectedKind === "edge" ? view.edges.find((edge) => edge.id === selectedId) : undefined;
  elements.inspector.replaceChildren();
  if (selectedNode) {
    elements.qualityBadge.textContent = selectedNode.kind.toLowerCase();
    elements.qualityBadge.className = "quality-badge exact";
    elements.inspector.append(
      inspectorTitle(selectedNode.displayName, selectedNode.qualifiedName),
      inspectorRow("Why shown", selectedNode.reason),
      inspectorRow("Method", view.preview ? "Preview fixture · not a graph fact" : `${selectedNode.parser}${selectedNode.parserVersion ? ` ${selectedNode.parserVersion}` : ""} · deterministic · no LLM`),
      inspectorRow("Stable ID", selectedNode.id, true),
      inspectorRow("Revision", selectedNode.revision),
      inspectorRow("HydraDB", view.preview ? "Not shown — interaction preview" : selectedNode.hydradbOrigin ?? view.hydradb?.origin ?? "Repository source record"),
      sourceBlock(selectedNode.source, selectedNode.id)
    );
  } else if (selectedEdge) {
    const source = view.nodes.find((node) => node.id === selectedEdge.sourceId)?.displayName ?? selectedEdge.sourceId;
    const target = view.nodes.find((node) => node.id === selectedEdge.targetId)?.displayName ?? selectedEdge.targetId;
    elements.qualityBadge.textContent = selectedEdge.quality;
    elements.qualityBadge.className = `quality-badge ${selectedEdge.quality}`;
    elements.inspector.append(
      inspectorTitle(`${source} → ${target}`, selectedEdge.predicate.replaceAll("_", " ")),
      inspectorRow("Why shown", selectedEdge.explanation),
      inspectorRow("Method", view.preview ? "Preview fixture · not a graph fact" : `${selectedEdge.extractor}${selectedEdge.extractorVersion ? ` ${selectedEdge.extractorVersion}` : ""}${selectedEdge.quality === "exact" ? " · deterministic · no LLM" : " · heuristic"}`),
      inspectorRow("Stable ID", selectedEdge.id, true),
      inspectorRow("Revision", selectedEdge.revision),
      inspectorRow("HydraDB", view.preview ? "Not shown — interaction preview" : selectedEdge.hydradbOrigin ?? view.hydradb?.origin ?? "Deterministic BYOG relation"),
      evidenceList(selectedEdge)
    );
  } else {
    elements.qualityBadge.textContent = "none";
    elements.inspector.append(inspectorTitle("Select an item", "Open its source-backed explanation"));
  }
}

function inspectorTitle(title: string, subtitle?: string): HTMLElement {
  const element = document.createElement("div"); element.className = "inspector-title";
  const heading = document.createElement("h3"); heading.textContent = title;
  element.append(heading);
  if (subtitle) { const copy = document.createElement("p"); copy.textContent = subtitle; element.append(copy); }
  return element;
}

function inspectorRow(label: string, value: string, mono = false): HTMLElement {
  const row = document.createElement("dl"); row.className = "evidence-row";
  const term = document.createElement("dt"); term.textContent = label;
  const detail = document.createElement("dd"); detail.textContent = value; if (mono) detail.className = "mono";
  row.append(term, detail); return row;
}

function sourceBlock(source: SourceRange | undefined, itemId: string): HTMLElement {
  const block = document.createElement("div"); block.className = "source-block";
  if (!source) {
    block.textContent = "No line-addressable source range is available for this entity.";
    return block;
  }
  const path = document.createElement("code"); path.textContent = `${source.path}:${source.startLine}`;
  const button = document.createElement("button"); button.type = "button"; button.className = "button button-source"; button.textContent = "Open source";
  button.addEventListener("click", () => vscode.postMessage({ type: "openSource", itemId, source }));
  block.append(path, button); return block;
}

function evidenceList(edge: GraphEdge): HTMLElement {
  const wrapper = document.createElement("div"); wrapper.className = "evidence-list";
  const heading = document.createElement("h4"); heading.textContent = edge.aggregateCount
    ? `${edge.aggregateCount} contributing exact relations` : `${edge.evidence.length} source evidence ${edge.evidence.length === 1 ? "record" : "records"}`;
  wrapper.append(heading);
  edge.evidence.forEach((evidence) => {
    const item = document.createElement("button"); item.type = "button"; item.className = "evidence-card";
    const path = document.createElement("code"); path.textContent = `${evidence.path}:${evidence.startLine}`;
    const copy = document.createElement("span"); copy.textContent = evidence.explanation;
    item.append(path, copy);
    item.addEventListener("click", () => vscode.postMessage({ type: "openSource", itemId: edge.id, source: evidence }));
    wrapper.append(item);
  });
  if (edge.evidence.length === 0) {
    const missing = document.createElement("p"); missing.textContent = "No line-addressable evidence was returned."; wrapper.append(missing);
  }
  return wrapper;
}

function selectNode(node: GraphNode, openSource: boolean, reportSelection = openSource): void {
  selectedId = node.id; selectedKind = "node";
  renderGraph(); renderInspector();
  if (reportSelection) {
    vscode.postMessage({ type: "selectItem", itemId: node.id, itemKind: "node" });
  }
  if (openSource && node.source) {
    vscode.postMessage({ type: "openSource", itemId: node.id, source: node.source });
  }
}

function selectEdge(edge: GraphEdge, openSource: boolean, reportSelection = openSource): void {
  selectedId = edge.id; selectedKind = "edge";
  renderGraph(); renderInspector();
  if (reportSelection) {
    vscode.postMessage({ type: "selectItem", itemId: edge.id, itemKind: "edge" });
  }
  const evidence = edge.evidence[0];
  if (openSource && evidence) {
    vscode.postMessage({ type: "openSource", itemId: edge.id, source: evidence });
  }
}

function runPrimaryAction(): void {
  if (view.mode === "repository") {
    if (selectedKind === "node" && selectedId) {
      vscode.postMessage({ type: "changeMode", mode: "explore" });
    } else {
      showToast("Select a concrete entity first.", "error");
    }
    return;
  }
  if (view.mode === "trace") {
    replayPath();
    return;
  }
  if (view.mode === "observe") {
    vscode.postMessage(observeActive ? { type: "setObservePaused", paused: !observePaused } : { type: "retry" });
    return;
  }
  if (view.mode === "compare") {
    const changed = view.nodes.filter((node) => node.state === "added" || node.state === "removed" || node.state === "modified");
    if (changed.length === 0) {
      showToast("No verified structural changes were returned.");
      return;
    }
    reviewIndex = (reviewIndex + 1) % changed.length;
    const item = changed[reviewIndex];
    if (item) { selectNode(item, false); focusSelection(); showToast(`Reviewing ${reviewIndex + 1} of ${changed.length}: ${item.displayName}`); }
    return;
  }
  vscode.postMessage({ type: "primaryAction", mode: view.mode, selectedId });
}

function replayPath(): void {
  const ids = view.nodes.map((node) => node.id);
  if (ids.length === 0) { showToast("No returned path is available to replay."); return; }
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  ids.forEach((id, index) => {
    window.setTimeout(() => {
      const node = view.nodes.find((candidate) => candidate.id === id);
      if (node) { selectNode(node, false); focusSelection(); }
    }, reduced ? 0 : index * 520);
  });
  showToast(view.preview ? "Replaying the interaction-preview path." : "Replaying the HydraDB returned path.");
}

function beginNodeDrag(event: PointerEvent, id: string): void {
  if (event.button !== 0) return;
  event.stopPropagation();
  const graphPoint = clientToGraph(event.clientX, event.clientY);
  const current = positions[id] ?? { x: 0, y: 0 };
  dragState = { type: "node", id, offset: { x: graphPoint.x - current.x, y: graphPoint.y - current.y }, moved: false };
  elements.graph.setPointerCapture(event.pointerId);
}

function onPointerDown(event: PointerEvent): void {
  if (event.button !== 0 || (event.target as Element).closest(".graph-node")) return;
  dragState = { type: "pan", start: { x: event.clientX, y: event.clientY }, origin: { x: transform.x, y: transform.y } };
  elements.graph.setPointerCapture(event.pointerId);
  elements.graph.classList.add("is-panning");
}

function onPointerMove(event: PointerEvent): void {
  if (!dragState) return;
  if (dragState.type === "pan") {
    transform.x = dragState.origin.x + event.clientX - dragState.start.x;
    transform.y = dragState.origin.y + event.clientY - dragState.start.y;
    updateViewport();
    return;
  }
  const graphPoint = clientToGraph(event.clientX, event.clientY);
  const next = { x: graphPoint.x - dragState.offset.x, y: graphPoint.y - dragState.offset.y };
  const previous = positions[dragState.id];
  if (previous && Math.hypot(next.x - previous.x, next.y - previous.y) > 1) dragState.moved = true;
  positions[dragState.id] = next;
  const node = elements.nodeLayer.querySelector<SVGGElement>(`[data-node-id="${CSS.escape(dragState.id)}"]`);
  node?.setAttribute("transform", `translate(${next.x} ${next.y})`);
  updateEdgeGeometry(dragState.id);
}

function onPointerUp(event: PointerEvent): void {
  if (!dragState) return;
  if (dragState.type === "node" && dragState.moved) {
    selectedId = dragState.id; selectedKind = "node"; renderInspector(); persistDisplayState();
  }
  dragState = undefined;
  elements.graph.classList.remove("is-panning");
  if (elements.graph.hasPointerCapture(event.pointerId)) elements.graph.releasePointerCapture(event.pointerId);
}

function updateEdgeGeometry(nodeId: string): void {
  view.edges.filter((edge) => edge.sourceId === nodeId || edge.targetId === nodeId).forEach((edge) => {
    const source = positions[edge.sourceId]; const target = positions[edge.targetId];
    if (!source || !target) return;
    const group = elements.edgeLayer.querySelector<SVGGElement>(`[data-edge-id="${CSS.escape(edge.id)}"]`);
    group?.querySelectorAll<SVGPathElement>("path").forEach((path) => path.setAttribute("d", edgePath(source, target)));
    const label = group?.querySelector<SVGTextElement>(".edge-label");
    label?.setAttribute("x", String((source.x + target.x) / 2)); label?.setAttribute("y", String((source.y + target.y) / 2 + 18));
  });
}

function onWheel(event: WheelEvent): void {
  event.preventDefault();
  const rect = elements.graph.getBoundingClientRect();
  const point = { x: ((event.clientX - rect.left) / rect.width) * 1000, y: ((event.clientY - rect.top) / rect.height) * 590 };
  transform = zoomAtPoint(transform, point, transform.scale * Math.exp(-event.deltaY * 0.0012));
  updateViewport(); persistDisplayState();
}

function setZoom(scale: number): void {
  transform = zoomAtPoint(transform, { x: 500, y: 295 }, scale); updateViewport(); persistDisplayState();
}

function updateViewport(): void {
  elements.viewport.setAttribute("transform", `translate(${transform.x} ${transform.y}) scale(${transform.scale})`);
  elements.zoomLevel.textContent = `${Math.round(transform.scale * 100)}%`;
}

function resetLayout(): void {
  positions = computeLayout(view.nodes, view.mode); transform = { ...DEFAULT_TRANSFORM }; renderGraph(); persistDisplayState(); showToast("Layout and viewport reset.");
}

function onGraphKeydown(event: KeyboardEvent): void {
  const direction = ["ArrowRight", "ArrowDown"].includes(event.key) ? 1 : ["ArrowLeft", "ArrowUp"].includes(event.key) ? -1 : undefined;
  if (direction) {
    event.preventDefault();
    const id = nextSelection(view.nodes.map((node) => node.id), selectedKind === "node" ? selectedId : undefined, direction);
    const node = view.nodes.find((candidate) => candidate.id === id);
    if (node) { selectNode(node, false, true); focusSelection(); }
  } else if (event.key === "Enter" && selectedKind === "node") {
    const node = view.nodes.find((candidate) => candidate.id === selectedId);
    if (node?.source) vscode.postMessage({ type: "openSource", itemId: node.id, source: node.source });
  } else if (event.key === "0") {
    resetLayout();
  }
}

function focusSelection(): void {
  if (selectedKind !== "node" || !selectedId) return;
  const point = positions[selectedId]; if (!point) return;
  transform.x = 500 - (point.x * transform.scale); transform.y = 265 - (point.y * transform.scale); updateViewport();
  elements.nodeLayer.querySelector<SVGGElement>(`[data-node-id="${CSS.escape(selectedId)}"]`)?.focus();
}

function clientToGraph(clientX: number, clientY: number): Point {
  const rect = elements.graph.getBoundingClientRect();
  const svgPoint = { x: ((clientX - rect.left) / rect.width) * 1000, y: ((clientY - rect.top) / rect.height) * 590 };
  return { x: (svgPoint.x - transform.x) / transform.scale, y: (svgPoint.y - transform.y) / transform.scale };
}

function persistDisplayState(): void {
  const key = `${view.viewId}:${view.depth ?? "none"}`.replace(/[^a-z0-9:_-]/gi, "_").slice(0, 120);
  const value = { positions, transform, relationKinds: [...relationKinds], showInferred, selectedId, selectedKind };
  vscode.setState(value);
  vscode.postMessage({ type: "persistDisplayState", key, value });
}

function markOpened(itemId: string): void {
  const node = view.nodes.find((item) => item.id === itemId);
  const edge = view.edges.find((item) => item.id === itemId);
  if (node) node.state = "opened";
  if (edge) edge.state = "opened";
  renderGraph();
}

function showToast(message: string, kind: "info" | "error" = "info"): void {
  if (toastTimer) window.clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.className = `toast ${kind === "error" ? "is-error" : ""}`;
  elements.toast.hidden = false;
  toastTimer = window.setTimeout(() => { elements.toast.hidden = true; }, 4200);
}

function stateBadge(state: GraphNode["state"]): string {
  const labels: Record<NonNullable<GraphNode["state"]>, string> = {
    returned: "RETURNED", selected: "SELECTED", opened: "OPENED", edited: "EDITED",
    added: "+ ADDED", removed: "− REMOVED", modified: "~ CHANGED", unchanged: ""
  };
  return state ? labels[state] : "";
}

function truncate(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

function svg<K extends keyof SVGElementTagNameMap>(tag: K): SVGElementTagNameMap[K] {
  return document.createElementNS("http://www.w3.org/2000/svg", tag);
}

function createBrowserApi(): VsCodeApi {
  let state: unknown;
  return {
    postMessage(message) {
      if (!window.__HYDRA_PREVIEW__) return;
      if (message.type === "ready" || message.type === "retry") {
        window.setTimeout(() => window.dispatchEvent(new MessageEvent("message", { data: {
          type: "view", view: createPreviewView(view.mode, view.depth ?? "file"), health: { state: "unavailable", message: "Standalone preview has no repository service connection." }
        } satisfies HostToWebviewMessage })), 80);
      } else if (message.type === "changeMode") {
        window.dispatchEvent(new MessageEvent("message", { data: {
          type: "view", view: createPreviewView(message.mode, view.depth ?? "file"), health
        } satisfies HostToWebviewMessage }));
      } else if (message.type === "changeDepth") {
        window.dispatchEvent(new MessageEvent("message", { data: {
          type: "view", view: createPreviewView(view.mode, message.depth), health
        } satisfies HostToWebviewMessage }));
      } else if (message.type === "openSource") {
        window.dispatchEvent(new MessageEvent("message", { data: {
          type: "actionResult", action: "openSource", message: `VS Code would open ${message.source.path}:${message.source.startLine}. Standalone preview made no filesystem change.`
        } satisfies HostToWebviewMessage }));
      } else if (message.type === "setObservePaused") {
        window.dispatchEvent(new MessageEvent("message", { data: {
          type: "observeStatus", active: true, paused: message.paused, bufferedCount: 0,
          message: message.paused ? "Visual following paused. Observable events will remain buffered." : "Following observable preview events."
        } satisfies HostToWebviewMessage }));
      } else if (message.type === "query" || message.type === "primaryAction") {
        window.dispatchEvent(new MessageEvent("message", { data: {
          type: "actionResult", action: message.type, message: "This action needs the local repository service. Preview data was not used as a retrieval result."
        } satisfies HostToWebviewMessage }));
      }
    },
    getState: () => state,
    setState: (nextState) => { state = nextState; }
  };
}
