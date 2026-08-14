export type ViewMode = "repository" | "explore" | "trace" | "observe" | "compare" | "preserve";
export type GraphDepth = "package" | "file" | "symbol";
export type RelationQuality = "exact" | "inferred" | "semantic" | "unknown";
export type ServiceState = "ready" | "indexing" | "unverified" | "unavailable" | "failed";

export interface SourceRange {
  path: string;
  startLine: number;
  startColumn: number;
  endLine: number;
  endColumn: number;
}

export interface GraphEvidence extends SourceRange {
  id: string;
  explanation: string;
  excerpt?: string;
}

export interface GraphNode {
  id: string;
  kind: string;
  displayName: string;
  qualifiedName?: string;
  language?: string;
  source?: SourceRange;
  parser: string;
  parserVersion?: string;
  revision: string;
  reason: string;
  hydradbOrigin?: string;
  state?: "returned" | "selected" | "opened" | "edited" | "added" | "removed" | "modified" | "unchanged";
}

export interface GraphEdge {
  id: string;
  sourceId: string;
  targetId: string;
  predicate: string;
  quality: RelationQuality;
  extractor: string;
  extractorVersion?: string;
  revision: string;
  evidence: GraphEvidence[];
  explanation: string;
  hydradbOrigin?: string;
  relevancy?: number;
  state?: "returned" | "selected" | "opened" | "added" | "removed" | "modified" | "unchanged";
  aggregateCount?: number;
  contributingEdgeIds?: string[];
}

export interface TimelineEvent {
  id: string;
  label: string;
  detail: string;
  timestamp?: string;
  nodeIds?: string[];
  edgeIds?: string[];
  state?: string;
}

export interface HydraMetadata {
  available: boolean;
  collection?: string;
  queryBy?: "hybrid" | "text";
  mode?: "fast" | "thinking";
  graphContext?: boolean;
  pathId?: string;
  origin?: string;
  status?: string;
}

export interface GraphView {
  viewId: string;
  revision: string;
  mode: ViewMode;
  depth?: GraphDepth;
  nodes: GraphNode[];
  edges: GraphEdge[];
  timeline: TimelineEvent[];
  warnings: string[];
  hydradb?: HydraMetadata;
  budget: {
    requestedNodes: number;
    returnedNodes: number;
    requestedEdges: number;
    returnedEdges: number;
    truncated?: boolean;
  };
  preview: boolean;
  summary?: string;
}

export interface ServiceHealth {
  state: ServiceState;
  revision?: string;
  collection?: string;
  sourceCount?: number;
  repositoryId?: string;
  repositoryRootFingerprint?: string;
  message?: string;
}

export interface ViewRequestContext {
  question?: string;
  beforeRevision?: string;
  afterRevision?: string;
  lens?: string;
}

export interface SidebarSnapshot {
  currentSymbol?: Pick<GraphNode, "id" | "displayName" | "kind" | "source">;
  entrypoints: Array<Pick<GraphNode, "id" | "displayName" | "kind" | "source">>;
  lenses: Array<{ id: string; label: string; detail: string }>;
  changes: Array<{ id: string; label: string; detail: string }>;
  activity: Array<{ id: string; label: string; detail: string }>;
  health: ServiceHealth;
}

export type HostToWebviewMessage =
  | { type: "view"; view: GraphView; health: ServiceHealth }
  | { type: "loading"; mode: ViewMode; message: string }
  | { type: "error"; message: string; recoverable: boolean }
  | { type: "sourceOpened"; itemId: string }
  | { type: "observeStatus"; active: boolean; paused: boolean; bufferedCount: number; sessionId?: string; message?: string }
  | { type: "actionResult"; action: string; message: string; view?: GraphView };

export type WebviewToHostMessage =
  | { type: "ready" }
  | { type: "changeMode"; mode: ViewMode }
  | { type: "changeDepth"; depth: GraphDepth }
  | { type: "query"; question: string }
  | { type: "openSource"; itemId: string; source: SourceRange }
  | { type: "selectItem"; itemId: string; itemKind: "node" | "edge" }
  | { type: "setObservePaused"; paused: boolean }
  | { type: "primaryAction"; mode: ViewMode; selectedId?: string }
  | { type: "retry" }
  | { type: "persistDisplayState"; key: string; value: unknown };
