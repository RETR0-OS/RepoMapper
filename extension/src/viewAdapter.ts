import type {
  GraphEdge,
  GraphEvidence,
  GraphNode,
  GraphView,
  HydraMetadata,
  RelationQuality,
  ServiceHealth,
  SourceRange,
  TimelineEvent,
  ViewDiagnostics,
  ViewMode
} from "./types.js";

type UnknownRecord = Record<string, unknown>;

function record(value: unknown): UnknownRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as UnknownRecord : {};
}

function textValue(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function numberValue(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function normalizeSpan(pathValue: unknown, spanValue: unknown): SourceRange | undefined {
  const span = record(spanValue);
  const sourcePath = textValue(pathValue);
  if (!sourcePath) {
    return undefined;
  }
  return {
    path: sourcePath,
    startLine: numberValue(span.start_line ?? span.startLine, 1),
    startColumn: numberValue(span.start_column ?? span.startColumn, 0),
    endLine: numberValue(span.end_line ?? span.endLine, 1),
    endColumn: numberValue(span.end_column ?? span.endColumn, 0)
  };
}

function normalizeNode(value: unknown, revision: string): GraphNode {
  const node = record(value);
  const attributes = record(node.attributes);
  return {
    id: textValue(node.id, "unknown-node"),
    kind: textValue(node.kind, "ENTITY"),
    displayName: textValue(node.display_name ?? node.displayName, "Unnamed entity"),
    qualifiedName: textValue(node.qualified_name ?? node.qualifiedName) || undefined,
    language: textValue(node.language) || undefined,
    source: normalizeSpan(node.path, node.span ?? node.source),
    parser: textValue(node.parser, "Unknown extractor"),
    parserVersion: textValue(node.parser_version ?? node.parserVersion) || undefined,
    revision: textValue(node.revision_id ?? node.revision, revision),
    reason: textValue(attributes.reason ?? node.reason, "Included in this bounded repository view."),
    hydradbOrigin: textValue(attributes.hydradb_origin ?? node.hydradbOrigin) || undefined,
    state: textValue(attributes.state ?? node.state) as GraphNode["state"] || undefined
  };
}

function normalizeEvidence(value: unknown): GraphEvidence {
  const evidence = record(value);
  const source = normalizeSpan(evidence.path, evidence.span ?? evidence) ?? {
    path: textValue(evidence.path), startLine: 1, startColumn: 0, endLine: 1, endColumn: 0
  };
  return {
    id: textValue(evidence.id, "unknown-evidence"),
    ...source,
    explanation: textValue(evidence.explanation, "Source evidence for this relation."),
    excerpt: textValue(evidence.excerpt) || undefined
  };
}

function normalizeEdge(value: unknown, revision: string): GraphEdge {
  const edge = record(value);
  const attributes = record(edge.attributes);
  const quality = textValue(edge.quality, "unknown") as RelationQuality;
  return {
    id: textValue(edge.id, "unknown-edge"),
    sourceId: textValue(edge.source_id ?? edge.sourceId),
    targetId: textValue(edge.target_id ?? edge.targetId),
    predicate: textValue(edge.predicate, "RELATED_TO"),
    quality: ["exact", "inferred", "semantic", "unknown"].includes(quality) ? quality : "unknown",
    extractor: textValue(edge.extractor, "Unknown extractor"),
    extractorVersion: textValue(edge.extractor_version ?? edge.extractorVersion) || undefined,
    revision: textValue(edge.revision_id ?? edge.revision, revision),
    evidence: Array.isArray(edge.evidence) ? edge.evidence.map(normalizeEvidence) : [],
    explanation: textValue(attributes.explanation ?? edge.explanation, `${textValue(edge.predicate, "Relation")} is present in the verified graph.`),
    hydradbOrigin: textValue(attributes.hydradb_origin ?? edge.hydradbOrigin) || undefined,
    relevancy: typeof attributes.relevancy === "number" ? attributes.relevancy : undefined,
    state: textValue(attributes.state ?? edge.state) as GraphEdge["state"] || undefined,
    aggregateCount: typeof edge.exact_relation_count === "number" ? edge.exact_relation_count : undefined,
    contributingEdgeIds: stringArray(edge.contributing_edge_ids)
  };
}

function normalizeTimeline(value: unknown): TimelineEvent[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item, index) => {
    const event = record(item);
    return {
      id: textValue(event.id ?? event.event_id, `event-${index}`),
      label: textValue(event.label ?? event.type, "Repository event").replaceAll("_", " "),
      detail: textValue(event.detail, "Observable repository activity."),
      timestamp: textValue(event.timestamp) || undefined,
      nodeIds: stringArray(event.node_ids ?? event.nodeIds),
      edgeIds: stringArray(event.edge_ids ?? event.edgeIds),
      state: textValue(event.state) || undefined
    };
  });
}

function normalizeHydra(value: unknown): HydraMetadata | undefined {
  const hydra = record(value);
  if (Object.keys(hydra).length === 0) {
    return undefined;
  }
  const collections = stringArray(hydra.collections);
  return {
    available: hydra.available === true,
    collection: textValue(hydra.collection) || collections[0],
    queryBy: textValue(hydra.query_by ?? hydra.queryBy) as HydraMetadata["queryBy"] || undefined,
    mode: textValue(hydra.mode) as HydraMetadata["mode"] || undefined,
    graphContext: Boolean(hydra.graph_context ?? hydra.graphContext),
    pathId: stringArray(hydra.path_ids)[0] ?? (textValue(hydra.pathId) || undefined),
    origin: textValue(hydra.origin) || undefined,
    status: textValue(hydra.status) || undefined
  };
}

function numberRecord(value: unknown): Record<string, number> | undefined {
  const source = record(value);
  const entries = Object.entries(source).filter(
    (entry): entry is [string, number] => typeof entry[1] === "number" && Number.isFinite(entry[1])
  );
  return entries.length > 0 ? Object.fromEntries(entries) : undefined;
}

function normalizeDiagnostics(value: unknown): ViewDiagnostics | undefined {
  const diagnostics = record(value);
  const outcome = textValue(diagnostics.outcome);
  if (!outcome) {
    return undefined;
  }
  return {
    outcome,
    reason: textValue(diagnostics.reason) || undefined,
    stageMs: numberRecord(diagnostics.stage_ms ?? diagnostics.stageMs),
    funnel: numberRecord(diagnostics.funnel)
  };
}

export function normalizeGraphView(value: unknown, fallbackMode: ViewMode): GraphView {
  const view = record(value);
  const schema = textValue(view.view_schema);
  if (schema && !["hack-hydra.product-view.v1", "hack-hydra.product-view.v2"].includes(schema)) {
    throw new Error("Repository Map view schema is not supported by this extension.");
  }
  const revision = textValue(view.revision_id ?? view.revision, "unknown");
  const rawNodes = Array.isArray(view.nodes) ? view.nodes : [];
  const rawEdges = Array.isArray(view.edges) ? view.edges : [];
  const rawBudget = record(view.budget);
  const mode = textValue(view.mode, fallbackMode) as ViewMode;
  return {
    viewId: textValue(view.view_id ?? view.viewId, `view-${fallbackMode}`),
    revision,
    mode: ["repository", "explore", "trace", "observe", "compare", "preserve"].includes(mode) ? mode : fallbackMode,
    depth: (textValue(view.depth) as GraphView["depth"]) || undefined,
    nodes: rawNodes.map((node) => normalizeNode(node, revision)),
    edges: rawEdges.map((edge) => normalizeEdge(edge, revision)),
    timeline: normalizeTimeline(view.timeline ?? view.events),
    warnings: stringArray(view.warnings),
    hydradb: normalizeHydra(view.hydradb),
    diagnostics: normalizeDiagnostics(view.diagnostics),
    budget: {
      requestedNodes: numberValue(rawBudget.requested_nodes ?? rawBudget.requestedNodes, rawNodes.length),
      returnedNodes: numberValue(rawBudget.returned_nodes ?? rawBudget.returnedNodes, rawNodes.length),
      requestedEdges: numberValue(rawBudget.requested_edges ?? rawBudget.requestedEdges, rawEdges.length),
      returnedEdges: numberValue(rawBudget.returned_edges ?? rawBudget.returnedEdges, rawEdges.length),
      truncated: Boolean(rawBudget.truncated)
    },
    preview: Boolean(view.preview),
    summary: textValue(view.summary) || undefined
  };
}

export function normalizeHealth(value: unknown): ServiceHealth {
  const health = record(value);
  const rawState = textValue(health.state ?? health.status, "unavailable");
  const reportedState = rawState === "ok" || rawState === "ready" ? "ready"
    : rawState === "indexing" ? "indexing"
      : rawState === "failed" || rawState === "error" ? "failed" : "unavailable";
  const revision = textValue(health.revision_id ?? health.revision) || undefined;
  const state = reportedState === "ready" && (!revision || revision === "current" || revision === "unknown")
    ? "unverified" : reportedState;
  return {
    state,
    revision,
    collection: textValue(health.collection) || stringArray(health.collections)[0],
    sourceCount: Number.isSafeInteger(health.source_count) && Number(health.source_count) >= 0
      ? Number(health.source_count) : undefined,
    repositoryId: textValue(health.repository_id) || undefined,
    repositoryRootFingerprint: /^[a-f0-9]{64}$/.test(textValue(health.repository_root_fingerprint))
      ? textValue(health.repository_root_fingerprint) : undefined,
    message: textValue(health.message) || undefined
  };
}
