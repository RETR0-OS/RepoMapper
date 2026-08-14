import type { GraphDepth, GraphEdge, GraphNode, GraphView, TimelineEvent, ViewMode } from "./types.js";

const nodes: GraphNode[] = [
  {
    id: "preview:extension", kind: "PACKAGE", displayName: "extension", qualifiedName: "extension",
    source: { path: "extension/src/extension.ts", startLine: 1, startColumn: 0, endLine: 1, endColumn: 0 },
    parser: "Preview fixture", revision: "preview", reason: "Concrete package shown only to demonstrate repository orientation while the service is unavailable."
  },
  {
    id: "preview:host", kind: "FILE", displayName: "extension.ts", qualifiedName: "extension/src/extension.ts",
    source: { path: "extension/src/extension.ts", startLine: 1, startColumn: 0, endLine: 20, endColumn: 0 },
    parser: "Preview fixture", revision: "preview", reason: "Concrete file used to demonstrate source navigation in preview mode."
  },
  {
    id: "preview:client", kind: "FILE", displayName: "serviceClient.ts", qualifiedName: "extension/src/serviceClient.ts",
    source: { path: "extension/src/serviceClient.ts", startLine: 1, startColumn: 0, endLine: 20, endColumn: 0 },
    parser: "Preview fixture", revision: "preview", reason: "Concrete file used to demonstrate the service boundary in preview mode."
  },
  {
    id: "preview:panel", kind: "CLASS", displayName: "GraphPanel", qualifiedName: "GraphPanel",
    source: { path: "extension/src/graphPanel.ts", startLine: 1, startColumn: 0, endLine: 20, endColumn: 0 },
    parser: "Preview fixture", revision: "preview", reason: "Concrete class used to demonstrate a bounded symbol view.", state: "returned"
  },
  {
    id: "preview:navigate", kind: "FUNCTION", displayName: "validateSourceRange", qualifiedName: "validateSourceRange",
    source: { path: "extension/src/sourceNavigation.ts", startLine: 18, startColumn: 0, endLine: 50, endColumn: 0 },
    parser: "Preview fixture", revision: "preview", reason: "Concrete function used to demonstrate exact evidence selection.", state: "selected"
  },
  {
    id: "preview:webview", kind: "FILE", displayName: "main.ts", qualifiedName: "extension/src/webview/main.ts",
    source: { path: "extension/src/webview/main.ts", startLine: 1, startColumn: 0, endLine: 20, endColumn: 0 },
    parser: "Preview fixture", revision: "preview", reason: "Concrete UI file used to demonstrate a focused graph slice.", state: "edited"
  },
  {
    id: "preview:tests", kind: "TEST", displayName: "graphState.test.ts", qualifiedName: "extension/test/graphState.test.ts",
    source: { path: "extension/test/graphState.test.ts", startLine: 1, startColumn: 0, endLine: 20, endColumn: 0 },
    parser: "Preview fixture", revision: "preview", reason: "Concrete test file linked to the presentation-state logic.", state: "added"
  }
];

const evidence = (id: string, path: string, line: number, explanation: string) => ({
  id, path, startLine: line, startColumn: 0, endLine: line, endColumn: 80, explanation
});

const edges: GraphEdge[] = [
  {
    id: "preview:e1", sourceId: "preview:extension", targetId: "preview:host", predicate: "CONTAINS", quality: "exact",
    extractor: "Preview fixture", revision: "preview", evidence: [evidence("preview:ev1", "extension/src/extension.ts", 1, "The package contains this concrete file.")],
    explanation: "Package-to-file containment used for interaction preview."
  },
  {
    id: "preview:e2", sourceId: "preview:host", targetId: "preview:client", predicate: "IMPORTS", quality: "exact",
    extractor: "Preview fixture", revision: "preview", evidence: [evidence("preview:ev2", "extension/src/extension.ts", 5, "The extension host imports the service client.")],
    explanation: "A source import represented as an exact preview relation.", state: "returned"
  },
  {
    id: "preview:e3", sourceId: "preview:host", targetId: "preview:panel", predicate: "INSTANTIATES", quality: "exact",
    extractor: "Preview fixture", revision: "preview", evidence: [evidence("preview:ev3", "extension/src/extension.ts", 30, "The extension creates its graph panel.")],
    explanation: "A concrete construction relation for the interaction preview.", state: "returned"
  },
  {
    id: "preview:e4", sourceId: "preview:panel", targetId: "preview:navigate", predicate: "CALLS", quality: "exact",
    extractor: "Preview fixture", revision: "preview", evidence: [evidence("preview:ev4", "extension/src/graphPanel.ts", 120, "The panel validates every requested source range.")],
    explanation: "The host validates a path before source navigation.", state: "selected"
  },
  {
    id: "preview:e5", sourceId: "preview:panel", targetId: "preview:webview", predicate: "LOADS", quality: "exact",
    extractor: "Preview fixture", revision: "preview", evidence: [evidence("preview:ev5", "extension/src/graphPanel.ts", 190, "The panel loads the bundled webview script.")],
    explanation: "The extension host loads the sandboxed UI bundle.", state: "modified"
  },
  {
    id: "preview:e6", sourceId: "preview:tests", targetId: "preview:navigate", predicate: "TESTS", quality: "exact",
    extractor: "Preview fixture", revision: "preview", evidence: [evidence("preview:ev6", "extension/test/sourceNavigation.test.ts", 8, "Tests exercise workspace-boundary validation.")],
    explanation: "A test-to-production relation used for preview."
  },
  {
    id: "preview:e7", sourceId: "preview:client", targetId: "preview:webview", predicate: "MAY_CALL", quality: "inferred",
    extractor: "Preview heuristic", revision: "preview", evidence: [evidence("preview:ev7", "extension/src/serviceClient.ts", 15, "Preview-only heuristic relation.")],
    explanation: "An intentionally inferred relation to demonstrate the hidden-by-default treatment."
  }
];

const modeNodes: Record<ViewMode, string[]> = {
  repository: nodes.map((node) => node.id),
  explore: ["preview:host", "preview:client", "preview:panel", "preview:navigate", "preview:webview", "preview:tests"],
  trace: ["preview:client", "preview:host", "preview:panel", "preview:navigate"],
  observe: ["preview:client", "preview:host", "preview:panel", "preview:navigate", "preview:webview"],
  compare: ["preview:panel", "preview:navigate", "preview:webview", "preview:tests"],
  preserve: ["preview:host", "preview:panel", "preview:navigate", "preview:tests"]
};

const timeline: TimelineEvent[] = [
  { id: "preview:t1", label: "Question asked", detail: "How does the extension open exact source evidence?", nodeIds: ["preview:client"] },
  { id: "preview:t2", label: "Path returned", detail: "Preview path shown for interaction testing only.", nodeIds: ["preview:host", "preview:panel"], edgeIds: ["preview:e2", "preview:e3"] },
  { id: "preview:t3", label: "Evidence selected", detail: "Source validation was selected from the bounded context.", nodeIds: ["preview:navigate"], edgeIds: ["preview:e4"] },
  { id: "preview:t4", label: "Workspace edit observed", detail: "The graph UI file changed.", nodeIds: ["preview:webview"] }
];

export function createPreviewView(mode: ViewMode, depth: GraphDepth = "file"): GraphView {
  const ids = new Set(modeNodes[mode]);
  const visibleNodes = nodes.filter((node) => ids.has(node.id)).map((node) => ({ ...node, source: node.source ? { ...node.source } : undefined }));
  const visibleEdges = edges.filter((edge) => ids.has(edge.sourceId) && ids.has(edge.targetId)).map((edge) => ({
    ...edge,
    evidence: edge.evidence.map((item) => ({ ...item })),
    contributingEdgeIds: edge.contributingEdgeIds ? [...edge.contributingEdgeIds] : undefined
  }));
  if (mode === "trace") {
    visibleNodes.forEach((node) => { node.state = "returned"; });
    visibleEdges.forEach((edge) => { edge.state = "returned"; });
  } else if (mode === "compare") {
    visibleNodes.forEach((node) => { node.state = "unchanged"; });
    const changedUi = visibleNodes.find((node) => node.id === "preview:webview");
    const addedTest = visibleNodes.find((node) => node.id === "preview:tests");
    if (changedUi) changedUi.state = "modified";
    if (addedTest) addedTest.state = "added";
    visibleEdges.forEach((edge) => { edge.state = edge.id === "preview:e6" ? "added" : "unchanged"; });
  } else if (mode === "preserve") {
    visibleNodes.forEach((node) => { node.state = node.id === "preview:navigate" ? "modified" : "unchanged"; });
  }
  const summaries: Record<ViewMode, string> = {
    repository: "Orient to concrete repository entities, then move to a focused local graph.",
    explore: "A bounded neighborhood around the extension host.",
    trace: "A readable left-to-right path from service request to source evidence.",
    observe: "Only explicit returned, selected, opened, and edited events are shown.",
    compare: "One modified UI node and one added test are shown against stable positions.",
    preserve: "A grounded source-navigation lens with reviewable drift."
  };
  return {
    viewId: `preview-${mode}-${depth}`,
    revision: "preview",
    mode,
    depth,
    nodes: visibleNodes,
    edges: visibleEdges,
    timeline: mode === "repository" || mode === "explore" ? [] : timeline.map((event) => ({
      ...event,
      nodeIds: event.nodeIds ? [...event.nodeIds] : undefined,
      edgeIds: event.edgeIds ? [...event.edgeIds] : undefined
    })),
    warnings: ["Interactive preview only. The local repository service is unavailable; no HydraDB result is being shown."],
    budget: {
      requestedNodes: 30,
      returnedNodes: visibleNodes.length,
      requestedEdges: 50,
      returnedEdges: visibleEdges.length,
      truncated: false
    },
    preview: true,
    summary: summaries[mode]
  };
}
