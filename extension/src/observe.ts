import type { GraphEdge, GraphNode, GraphView, TimelineEvent } from "./types.js";

export const AGENT_EVENT_TYPES = [
  "session_started",
  "query_started",
  "hydradb_result_returned",
  "path_replay_started",
  "path_hop_replayed",
  "context_selected",
  "evidence_opened",
  "user_context_pinned",
  "workspace_entity_changed",
  "hydradb_sync_started",
  "hydradb_revision_ready",
  "lens_drift_detected",
  "session_completed",
  "traversal_entered",
  "traversal_followed",
  "traversal_abandoned"
] as const;

export type AgentEventType = typeof AGENT_EVENT_TYPES[number];

export interface AgentEvent {
  eventId: string;
  sessionId: string;
  timestamp: string;
  type: AgentEventType;
  revisionId: string;
  viewId?: string;
  entityIds: string[];
  relationshipIds: string[];
  hydradbQueryMetadata?: Record<string, unknown>;
}

export interface ObserveSessionResponse {
  status: string;
  sessionId: string;
  revisionId: string;
  repositoryRootFingerprint: string;
  event?: AgentEvent;
}

export interface ObserveCompleteResponse {
  status: string;
  sessionId: string;
  event?: AgentEvent;
}

export interface ObserveRecordedResponse {
  status: string;
  event?: AgentEvent;
}

export type TraversalAction = "enter" | "follow" | "abandon";

export interface TraversalStep {
  eventId: string;
  action: TraversalAction;
  timestamp: string;
  nodeIds: string[];
  edgeIds: string[];
  trackIndex: number;
  stepIndex: number;
}

export interface TraversalState {
  tracks: TraversalStep[][];
  activeTrackIndex: number;
}

export class ObserveEventIntegrityError extends Error {
  public constructor() {
    super("Observe returned an event for a different repository revision; restart the session.");
    this.name = "ObserveEventIntegrityError";
  }
}

type UnknownRecord = Record<string, unknown>;

function record(value: unknown): UnknownRecord | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as UnknownRecord : undefined;
}

function boundedId(value: unknown, maximumLength = 1_024): string | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed && trimmed.length <= maximumLength && !/[\u0000-\u001f\u007f]/.test(trimmed) ? trimmed : undefined;
}

function boundedIds(value: unknown): string[] | undefined {
  if (!Array.isArray(value) || value.length > 100) return undefined;
  const values = value.map((item) => boundedId(item));
  if (values.some((item) => !item)) return undefined;
  return [...new Set(values as string[])];
}

export function normalizeAgentEvent(value: unknown): AgentEvent | undefined {
  const item = record(value);
  if (!item) return undefined;
  const eventId = boundedId(item.event_id ?? item.eventId, 256);
  const sessionId = boundedId(item.session_id ?? item.sessionId, 256);
  const revisionId = boundedId(item.revision_id ?? item.revisionId, 256);
  const viewValue = item.view_id ?? item.viewId;
  const viewId = viewValue === null || viewValue === undefined ? undefined : boundedId(viewValue, 256);
  const entityIds = boundedIds(item.entity_ids ?? item.entityIds);
  const relationshipIds = boundedIds(item.relationship_ids ?? item.relationshipIds);
  const timestamp = typeof item.timestamp === "string" && Number.isFinite(Date.parse(item.timestamp)) ? item.timestamp : undefined;
  const type = typeof item.type === "string" && (AGENT_EVENT_TYPES as readonly string[]).includes(item.type)
    ? item.type as AgentEventType
    : undefined;
  if (!eventId || !sessionId || !revisionId || !timestamp || !type || !entityIds || !relationshipIds || (viewValue != null && !viewId)) {
    return undefined;
  }
  const metadataValue = item.hydradb_query_metadata ?? item.hydradbQueryMetadata;
  const hydradbQueryMetadata = metadataValue == null ? undefined : record(metadataValue);
  if (metadataValue != null && !hydradbQueryMetadata) return undefined;
  if (hydradbQueryMetadata) {
    try {
      if (JSON.stringify(hydradbQueryMetadata).length > 16_000) return undefined;
    } catch {
      return undefined;
    }
  }
  return { eventId, sessionId, timestamp, type, revisionId, viewId, entityIds, relationshipIds, hydradbQueryMetadata };
}

export function normalizeObserveSession(value: unknown): ObserveSessionResponse {
  const item = record(value) ?? {};
  return {
    status: typeof item.status === "string" ? item.status : "",
    sessionId: boundedId(item.session_id ?? item.sessionId, 256) ?? "",
    revisionId: boundedId(item.revision_id ?? item.revisionId, 256) ?? "",
    repositoryRootFingerprint: typeof (item.repository_root_fingerprint ?? item.repositoryRootFingerprint) === "string"
      ? String(item.repository_root_fingerprint ?? item.repositoryRootFingerprint)
      : "",
    event: normalizeAgentEvent(item.event)
  };
}

export function normalizeObserveComplete(value: unknown): ObserveCompleteResponse {
  const item = record(value) ?? {};
  return {
    status: typeof item.status === "string" ? item.status : "",
    sessionId: boundedId(item.session_id ?? item.sessionId, 256) ?? "",
    event: normalizeAgentEvent(item.event)
  };
}

export function normalizeObserveRecorded(value: unknown): ObserveRecordedResponse {
  const item = record(value) ?? {};
  return {
    status: typeof item.status === "string" ? item.status : "",
    event: normalizeAgentEvent(item.event)
  };
}

export function observeSessionIsActive(response: ObserveSessionResponse): boolean {
  return response.status === "active"
    && Boolean(response.sessionId)
    && Boolean(response.revisionId)
    && /^[a-f0-9]{64}$/.test(response.repositoryRootFingerprint)
    && response.event?.type === "session_started"
    && response.event.sessionId === response.sessionId
    && response.event.revisionId === response.revisionId;
}

export function observeSessionWasCompleted(response: ObserveCompleteResponse, sessionId: string): boolean {
  return response.status === "completed"
    && response.sessionId === sessionId
    && response.event?.type === "session_completed"
    && response.event.sessionId === sessionId;
}

export function observeRecordMatches(
  response: ObserveRecordedResponse,
  expectedType: "context_selected" | "evidence_opened" | "workspace_entity_changed",
  sessionId: string,
  revisionId: string,
  viewId: string,
  selectedItemId?: string,
  selectedItemKind?: "node" | "edge"
): boolean {
  const event = response.event;
  const itemMatches = selectedItemId === undefined
    || selectedItemKind === "node" && event !== undefined && event.entityIds.includes(selectedItemId) && !event.relationshipIds.includes(selectedItemId)
    || selectedItemKind === "edge" && event !== undefined && event.relationshipIds.includes(selectedItemId) && !event.entityIds.includes(selectedItemId);
  return response.status === "recorded"
    && event?.type === expectedType
    && event.sessionId === sessionId
    && event.revisionId === revisionId
    && event.viewId === viewId
    && itemMatches;
}

interface SequencedEvent {
  event: AgentEvent;
  sequence: number;
}

function chronological(items: SequencedEvent[]): SequencedEvent[] {
  return items.sort((left, right) => {
    const time = Date.parse(left.event.timestamp) - Date.parse(right.event.timestamp);
    return time || left.sequence - right.sequence;
  });
}

export class ObserveEventLog {
  private readonly seen = new Map<string, number>();
  private visible: SequencedEvent[] = [];
  private buffered: SequencedEvent[] = [];
  private sequence = 0;
  private paused = false;
  private bufferedOverflow = 0;
  private lastCursor: string | undefined;

  public constructor(
    private readonly sessionId: string,
    private readonly revisionId: string,
    private readonly historyLimit = 500,
    private readonly bufferLimit = 200,
    private readonly seenLimit = 1_000
  ) {
    if (!boundedId(sessionId, 256) || !boundedId(revisionId, 256) || historyLimit < 1 || bufferLimit < 1 || seenLimit < historyLimit) {
      throw new Error("Observe event bounds must be positive and the session and revision IDs must be concrete.");
    }
  }

  public ingestPolledBatch(values: unknown): AgentEvent[] {
    return this.ingest(values, true);
  }

  public ingestDirect(values: unknown): AgentEvent[] {
    return this.ingest(values, false);
  }

  private ingest(values: unknown, advanceCursor: boolean): AgentEvent[] {
    if (!Array.isArray(values)) return [];
    const events = values.slice(-this.historyLimit)
      .map(normalizeAgentEvent)
      .filter((event): event is AgentEvent => event !== undefined);
    if (advanceCursor && events.some((event) => event.sessionId === this.sessionId && event.revisionId !== this.revisionId)) {
      throw new ObserveEventIntegrityError();
    }
    const accepted: SequencedEvent[] = [];
    for (const event of events) {
      if (event.sessionId !== this.sessionId || event.revisionId !== this.revisionId) continue;
      // The polling cursor follows server-list order, including already-rendered
      // direct events. A POST response may be rendered immediately, but it must
      // never skip older events that have not arrived through the poll stream.
      if (advanceCursor) this.lastCursor = event.eventId;
      if (this.seen.has(event.eventId)) continue;
      const sequenced = { event, sequence: this.sequence++ };
      this.seen.set(event.eventId, sequenced.sequence);
      accepted.push(sequenced);
    }
    this.pruneSeen();
    if (this.paused) {
      const combined = chronological([...this.buffered, ...accepted]);
      this.bufferedOverflow += Math.max(0, combined.length - this.bufferLimit);
      this.buffered = combined.slice(-this.bufferLimit);
      return [];
    }
    this.visible = chronological([...this.visible, ...accepted]).slice(-this.historyLimit);
    return chronological(accepted).map((item) => item.event);
  }

  public setPaused(paused: boolean): AgentEvent[] {
    if (paused === this.paused) return [];
    this.paused = paused;
    if (paused) {
      this.bufferedOverflow = 0;
      return [];
    }
    const released = chronological(this.buffered).map((item) => item.event);
    this.visible = chronological([...this.visible, ...this.buffered]).slice(-this.historyLimit);
    this.buffered = [];
    return released;
  }

  public isPaused(): boolean {
    return this.paused;
  }

  public bufferedCount(): number {
    return this.buffered.length;
  }

  public bufferedOverflowCount(): number {
    return this.bufferedOverflow;
  }

  public visibleEvents(): AgentEvent[] {
    return this.visible.map((item) => item.event);
  }

  public lastAcceptedCursor(): string | undefined {
    return this.lastCursor;
  }

  private pruneSeen(): void {
    if (this.seen.size <= this.seenLimit) return;
    const ordered = [...this.seen.entries()].sort((left, right) => left[1] - right[1]);
    for (const [eventId] of ordered.slice(0, this.seen.size - this.seenLimit)) this.seen.delete(eventId);
  }
}

export function latestObserveViewReference(events: readonly AgentEvent[]): { viewId: string; revisionId: string } | undefined {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event?.type === "hydradb_result_returned" && event.viewId) {
      return { viewId: event.viewId, revisionId: event.revisionId };
    }
  }
  return undefined;
}

export function verifiedObserveView(
  view: GraphView,
  expectedViewId: string,
  expectedRevisionId: string
): GraphView | undefined {
  return !view.preview
    && view.viewId === expectedViewId
    && view.revision === expectedRevisionId
    && view.hydradb?.available === true
    ? view
    : undefined;
}

export class BoundedPoller {
  private active = false;
  private generation = 0;
  private timer: ReturnType<typeof setTimeout> | undefined;

  public constructor(private readonly intervalMs = 1_250) {
    if (!Number.isInteger(intervalMs) || intervalMs < 250 || intervalMs > 30_000) {
      throw new Error("Observe polling interval must be between 250 and 30000 ms.");
    }
  }

  public start(task: () => Promise<void>): void {
    this.stop();
    this.active = true;
    const generation = this.generation;
    void this.tick(task, generation);
  }

  public stop(): void {
    this.active = false;
    this.generation += 1;
    if (this.timer) clearTimeout(this.timer);
    this.timer = undefined;
  }

  public isActive(): boolean {
    return this.active;
  }

  private async tick(task: () => Promise<void>, generation: number): Promise<void> {
    try {
      await task();
    } finally {
      if (!this.active || generation !== this.generation) return;
      this.timer = setTimeout(() => void this.tick(task, generation), this.intervalMs);
    }
  }
}

const labels: Record<AgentEventType, [string, string]> = {
  session_started: ["Follow session started", "Observable repository activity collection started."],
  query_started: ["Repository query started", "An explicit repository query was sent through the product."],
  hydradb_result_returned: ["HydraDB result returned", "HydraDB returned a bounded path or context view."],
  path_replay_started: ["Returned path replay started", "Replay started for a HydraDB-returned path."],
  path_hop_replayed: ["Returned path hop replayed", "One returned relationship hop was replayed."],
  context_selected: ["Context selected", "Explicit returned context was selected."],
  evidence_opened: ["Source evidence opened", "Line-addressable source evidence was opened."],
  user_context_pinned: ["User context pinned", "The user explicitly pinned returned context."],
  workspace_entity_changed: ["Workspace entity edited", "A visible source-backed entity matched an observed workspace change."],
  hydradb_sync_started: ["HydraDB sync started", "A repository revision sync was explicitly started."],
  hydradb_revision_ready: ["HydraDB revision ready", "HydraDB reported a verified repository revision ready."],
  lens_drift_detected: ["System Lens drift returned", "A grounded System Lens comparison returned drift."],
  session_completed: ["Follow session completed", "Observable repository activity collection completed."],
  traversal_entered: ["Traversal entered", "The agent entered a new graph point."],
  traversal_followed: ["Traversal followed", "The agent followed an edge to a new entity."],
  traversal_abandoned: ["Traversal abandoned", "The agent abandoned the current path."]
};

export function eventToTimeline(event: AgentEvent): TimelineEvent {
  const [label, baseDetail] = labels[event.type];
  const references = [
    event.entityIds.length ? `${event.entityIds.length} ${event.entityIds.length === 1 ? "entity" : "entities"}` : undefined,
    event.relationshipIds.length ? `${event.relationshipIds.length} ${event.relationshipIds.length === 1 ? "relationship" : "relationships"}` : undefined
  ].filter(Boolean).join(" and ");
  return {
    id: event.eventId,
    label,
    detail: references ? `${baseDetail} ${references} referenced.` : baseDetail,
    timestamp: event.timestamp,
    nodeIds: [...event.entityIds],
    edgeIds: [...event.relationshipIds],
    state: event.type
  };
}

type ObservableNodeState = "returned" | "selected" | "opened" | "edited";
type ObservableEdgeState = "returned" | "selected" | "opened";

function nodeState(event: AgentEvent): ObservableNodeState | undefined {
  if (event.type === "traversal_entered" || event.type === "traversal_followed") return "returned";
  if (event.type === "workspace_entity_changed") return "edited";
  if (event.type === "evidence_opened") return "opened";
  if (event.type === "context_selected" || event.type === "user_context_pinned") return "selected";
  if (event.type === "hydradb_result_returned" || event.type === "path_hop_replayed") return "returned";
  return undefined;
}

function edgeState(event: AgentEvent): ObservableEdgeState | undefined {
  if (event.type === "traversal_followed") return "returned";
  if (event.type === "evidence_opened") return "opened";
  if (event.type === "context_selected" || event.type === "user_context_pinned") return "selected";
  if (event.type === "hydradb_result_returned" || event.type === "path_hop_replayed") return "returned";
  return undefined;
}

const observableStatePriority = {
  returned: 1,
  selected: 2,
  opened: 3,
  edited: 4
} as const;

function keepStrongestState<T extends ObservableNodeState>(
  states: Map<string, T>,
  ids: readonly string[],
  next: T
): void {
  for (const id of ids) {
    const current = states.get(id);
    // Preserve the strongest observable fact: a later low-information event
    // must not erase that an item was explicitly opened or edited.
    if (!current || observableStatePriority[next] >= observableStatePriority[current]) states.set(id, next);
  }
}

export function applyObserveEvents(baseView: GraphView, events: readonly AgentEvent[]): GraphView {
  const nodeStates = new Map<string, ObservableNodeState>();
  const edgeStates = new Map<string, ObservableEdgeState>();
  for (const event of events) {
    if (event.viewId !== baseView.viewId || event.revisionId !== baseView.revision) continue;
    const nextNodeState = nodeState(event);
    const nextEdgeState = edgeState(event);
    if (nextNodeState) keepStrongestState(nodeStates, event.entityIds, nextNodeState);
    if (nextEdgeState) keepStrongestState(edgeStates, event.relationshipIds, nextEdgeState);
  }
  return {
    ...baseView,
    mode: "observe",
    nodes: baseView.nodes.map((node) => ({ ...node, state: nodeStates.get(node.id) ?? node.state })),
    edges: baseView.edges.map((edge) => ({ ...edge, state: edgeStates.get(edge.id) ?? edge.state })),
    timeline: events.slice(-200).map(eventToTimeline),
    summary: "Shows only explicit queries, returned HydraDB context, selections, opened evidence, and matching workspace edits."
  };
}

export function deriveTraversalState(events: readonly AgentEvent[]): TraversalState {
  const tracks: TraversalStep[][] = [];
  let currentTrack: TraversalStep[] = [];
  let trackIndex = 0;

  for (const event of events) {
    if (event.type === "traversal_entered") {
      if (currentTrack.length > 0) {
        tracks.push(currentTrack);
        trackIndex += 1;
        currentTrack = [];
      }
      currentTrack.push({
        eventId: event.eventId,
        action: "enter",
        timestamp: event.timestamp,
        nodeIds: [...event.entityIds],
        edgeIds: [...event.relationshipIds],
        trackIndex,
        stepIndex: currentTrack.length
      });
    } else if (event.type === "traversal_followed") {
      currentTrack.push({
        eventId: event.eventId,
        action: "follow",
        timestamp: event.timestamp,
        nodeIds: [...event.entityIds],
        edgeIds: [...event.relationshipIds],
        trackIndex,
        stepIndex: currentTrack.length
      });
    } else if (event.type === "traversal_abandoned") {
      currentTrack.push({
        eventId: event.eventId,
        action: "abandon",
        timestamp: event.timestamp,
        nodeIds: [...event.entityIds],
        edgeIds: [...event.relationshipIds],
        trackIndex,
        stepIndex: currentTrack.length
      });
      tracks.push(currentTrack);
      trackIndex += 1;
      currentTrack = [];
    }
  }

  if (currentTrack.length > 0) {
    tracks.push(currentTrack);
  }

  return {
    tracks,
    activeTrackIndex: tracks.length > 0 ? tracks.length - 1 : 0
  };
}

export function createObserveWaitingView(sessionId: string, revisionId: string): GraphView {
  return {
    viewId: "",
    revision: revisionId,
    mode: "observe",
    depth: "symbol",
    nodes: [],
    edges: [],
    timeline: [],
    warnings: ["Following explicit repository activity. No stored HydraDB result view has been returned for this session yet."],
    hydradb: { available: true, graphContext: true, origin: `observe session ${sessionId}` },
    budget: { requestedNodes: 0, returnedNodes: 0, requestedEdges: 0, returnedEdges: 0, truncated: false },
    preview: false,
    summary: "Following explicit repository events. Waiting for a stored HydraDB result view."
  };
}

export function createTraversalWaitingView(sessionId: string, revisionId: string): GraphView {
  return {
    viewId: "",
    revision: revisionId,
    mode: "observe",
    depth: "symbol",
    nodes: [],
    edges: [],
    timeline: [],
    warnings: ["Waiting for agent traversal. The canvas will populate as the agent navigates the graph."],
    hydradb: { available: true, graphContext: true, origin: `traversal session ${sessionId}` },
    budget: { requestedNodes: 0, returnedNodes: 0, requestedEdges: 0, returnedEdges: 0, truncated: false },
    preview: false,
    summary: "Waiting for agent traversal."
  };
}
