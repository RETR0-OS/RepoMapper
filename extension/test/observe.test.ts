import { afterEach, describe, expect, it, vi } from "vitest";
import {
  applyObserveEvents,
  BoundedPoller,
  eventToTimeline,
  latestObserveViewReference,
  normalizeAgentEvent,
  ObserveEventLog,
  verifiedObserveView
} from "../src/observe.js";
import type { GraphView } from "../src/types.js";

function rawEvent(id: string, timestamp: string, overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    event_id: id,
    session_id: "session-1",
    timestamp,
    type: "hydradb_result_returned",
    revision_id: "rev-1",
    view_id: "view-1",
    entity_ids: ["node-1"],
    relationship_ids: ["edge-1"],
    hydradb_query_metadata: null,
    ...overrides
  };
}

const baseView: GraphView = {
  viewId: "view-1",
  revision: "rev-1",
  mode: "observe",
  depth: "symbol",
  nodes: [{ id: "node-1", kind: "FUNCTION", displayName: "authorize", parser: "tree-sitter", revision: "rev-1", reason: "Returned by HydraDB." }],
  edges: [{ id: "edge-1", sourceId: "node-1", targetId: "node-1", predicate: "CALLS", quality: "exact", extractor: "tree-sitter", revision: "rev-1", evidence: [], explanation: "Exact call." }],
  timeline: [],
  warnings: [],
  hydradb: { available: true },
  budget: { requestedNodes: 10, returnedNodes: 1, requestedEdges: 10, returnedEdges: 1 },
  preview: false
};

describe("Observe event transport", () => {
  afterEach(() => vi.useRealTimers());

  it("normalizes the schema's entity_ids and relationship_ids without swapping them", () => {
    const event = normalizeAgentEvent(rawEvent("event-1", "2026-08-14T10:00:00.000Z", {
      entity_ids: ["entity-a"], relationship_ids: ["relationship-b"]
    }));

    expect(event?.entityIds).toEqual(["entity-a"]);
    expect(event?.relationshipIds).toEqual(["relationship-b"]);
    expect(eventToTimeline(event!).nodeIds).toEqual(["entity-a"]);
    expect(eventToTimeline(event!).edgeIds).toEqual(["relationship-b"]);
  });

  it("orders by timestamp, dedupes event IDs, and ignores another session", () => {
    const log = new ObserveEventLog("session-1", "rev-1");
    log.ingestPolledBatch([
      rawEvent("event-late", "2026-08-14T10:00:02.000Z"),
      rawEvent("event-early", "2026-08-14T10:00:01.000Z"),
      rawEvent("event-late", "2026-08-14T10:00:03.000Z"),
      rawEvent("event-other", "2026-08-14T10:00:00.000Z", { session_id: "other-session" })
    ]);

    expect(log.visibleEvents().map((event) => event.eventId)).toEqual(["event-early", "event-late"]);
    expect(log.lastAcceptedCursor()).toBe("event-late");
  });

  it("buffers while paused and releases a bounded chronological batch on resume", () => {
    const log = new ObserveEventLog("session-1", "rev-1", 5, 2, 10);
    log.ingestPolledBatch([rawEvent("event-initial", "2026-08-14T10:00:00.000Z")]);
    log.setPaused(true);
    expect(log.ingestPolledBatch([
      rawEvent("event-3", "2026-08-14T10:00:03.000Z"),
      rawEvent("event-1", "2026-08-14T10:00:01.000Z"),
      rawEvent("event-2", "2026-08-14T10:00:02.000Z")
    ])).toEqual([]);
    expect(log.visibleEvents().map((event) => event.eventId)).toEqual(["event-initial"]);
    expect(log.bufferedCount()).toBe(2);
    expect(log.bufferedOverflowCount()).toBe(1);

    expect(log.setPaused(false).map((event) => event.eventId)).toEqual(["event-2", "event-3"]);
    expect(log.visibleEvents().map((event) => event.eventId)).toEqual(["event-initial", "event-2", "event-3"]);
  });

  it("does not let a direct response skip an earlier polled event and advances through its duplicate tail", () => {
    const log = new ObserveEventLog("session-1", "rev-1");
    log.ingestPolledBatch([rawEvent("event-start", "2026-08-14T10:00:00.000Z", { type: "session_started", view_id: null, entity_ids: [], relationship_ids: [] })]);

    log.ingestDirect([rawEvent("event-direct", "2026-08-14T10:00:02.000Z", { type: "context_selected" })]);
    expect(log.lastAcceptedCursor()).toBe("event-start");

    const accepted = log.ingestPolledBatch([
      rawEvent("event-between", "2026-08-14T10:00:01.000Z", { type: "query_started", entity_ids: [], relationship_ids: [] }),
      rawEvent("event-direct", "2026-08-14T10:00:02.000Z", { type: "context_selected" })
    ]);

    expect(accepted.map((event) => event.eventId)).toEqual(["event-between"]);
    expect(log.visibleEvents().map((event) => event.eventId)).toEqual(["event-start", "event-between", "event-direct"]);
    expect(log.lastAcceptedCursor()).toBe("event-direct");
  });

  it("keeps exact view/revision references and rejects an unknown or substituted stored view", () => {
    const first = normalizeAgentEvent(rawEvent("event-1", "2026-08-14T10:00:00.000Z", { view_id: "view-old" }))!;
    const latest = normalizeAgentEvent(rawEvent("event-2", "2026-08-14T10:00:01.000Z", { view_id: "view-1" }))!;

    expect(latestObserveViewReference([first, latest])).toEqual({ viewId: "view-1", revisionId: "rev-1" });
    expect(verifiedObserveView(baseView, "view-1", "rev-1")).toBe(baseView);
    expect(verifiedObserveView(baseView, "view-unknown", "rev-1")).toBeUndefined();
    expect(verifiedObserveView({ ...baseView, viewId: "view-unknown" }, "view-1", "rev-1")).toBeUndefined();
    expect(verifiedObserveView({ ...baseView, preview: true }, "view-1", "rev-1")).toBeUndefined();
    expect(verifiedObserveView({ ...baseView, hydradb: { available: false } }, "view-1", "rev-1")).toBeUndefined();
  });

  it("applies states only to exact IDs in the event's stored view", () => {
    const selected = normalizeAgentEvent(rawEvent("event-selected", "2026-08-14T10:00:00.000Z", { type: "context_selected" }))!;
    const unknownView = normalizeAgentEvent(rawEvent("event-unknown", "2026-08-14T10:00:01.000Z", {
      type: "evidence_opened", view_id: "view-unknown"
    }))!;
    const changed = applyObserveEvents(baseView, [selected, unknownView]);

    expect(changed.nodes[0]?.state).toBe("selected");
    expect(changed.edges[0]?.state).toBe("selected");
    expect(changed.timeline.map((item) => item.id)).toEqual(["event-selected", "event-unknown"]);
    expect(baseView.nodes[0]?.state).toBeUndefined();
  });

  it("keeps edited > opened > selected > returned when weaker events arrive later", () => {
    const edited = normalizeAgentEvent(rawEvent("event-edited", "2026-08-14T10:00:00.000Z", {
      type: "workspace_entity_changed", relationship_ids: []
    }))!;
    const opened = normalizeAgentEvent(rawEvent("event-opened", "2026-08-14T10:00:01.000Z", { type: "evidence_opened" }))!;
    const selected = normalizeAgentEvent(rawEvent("event-selected", "2026-08-14T10:00:02.000Z", { type: "context_selected" }))!;
    const returned = normalizeAgentEvent(rawEvent("event-returned", "2026-08-14T10:00:03.000Z"))!;

    const changed = applyObserveEvents(baseView, [edited, opened, selected, returned]);

    expect(changed.nodes[0]?.state).toBe("edited");
    expect(changed.edges[0]?.state).toBe("opened");
    expect(changed.timeline.map((item) => item.id)).toEqual(["event-edited", "event-opened", "event-selected", "event-returned"]);
  });

  it("rejects wrong-revision events before cursor, timeline, or graph state", () => {
    const log = new ObserveEventLog("session-1", "rev-1");
    log.ingestPolledBatch([rawEvent("event-wrong-revision", "2026-08-14T10:00:00.000Z", {
      type: "workspace_entity_changed", revision_id: "rev-other", relationship_ids: []
    })]);

    const changed = applyObserveEvents(baseView, log.visibleEvents());

    expect(changed.nodes[0]?.state).toBeUndefined();
    expect(changed.timeline).toEqual([]);
    expect(log.visibleEvents()).toEqual([]);
    expect(log.lastAcceptedCursor()).toBeUndefined();
  });

  it("rejects malformed, oversized, and unknown events", () => {
    expect(normalizeAgentEvent(rawEvent("event-1", "not-a-date"))).toBeUndefined();
    expect(normalizeAgentEvent(rawEvent("event-1", "2026-08-14T10:00:00.000Z", { type: "agent_thought" }))).toBeUndefined();
    expect(normalizeAgentEvent(rawEvent("event-1", "2026-08-14T10:00:00.000Z", { entity_ids: new Array(101).fill("node") }))).toBeUndefined();
    expect(normalizeAgentEvent(rawEvent("event-1", "2026-08-14T10:00:00.000Z", { view_id: "x".repeat(257) }))).toBeUndefined();
    expect(normalizeAgentEvent(rawEvent("event-1", "2026-08-14T10:00:00.000Z", { hydradb_query_metadata: { query: "x".repeat(16_001) } }))).toBeUndefined();
  });

  it("polls without overlap and stops cleanly even when a request completes late", async () => {
    vi.useFakeTimers();
    let releaseFirst: (() => void) | undefined;
    const first = new Promise<void>((resolve) => { releaseFirst = resolve; });
    const task = vi.fn().mockImplementationOnce(async () => first).mockResolvedValue(undefined);
    const poller = new BoundedPoller(250);

    poller.start(task);
    expect(task).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(task).toHaveBeenCalledTimes(1);
    releaseFirst?.();
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(250);
    expect(task).toHaveBeenCalledTimes(2);
    poller.stop();
    await vi.advanceTimersByTimeAsync(1_000);
    expect(task).toHaveBeenCalledTimes(2);
    expect(poller.isActive()).toBe(false);
  });
});
