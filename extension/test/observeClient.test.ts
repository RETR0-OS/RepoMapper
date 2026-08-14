import { describe, expect, it, vi } from "vitest";
import { observeRecordMatches, observeSessionIsActive, observeSessionWasCompleted } from "../src/observe.js";
import { RepositoryServiceClient } from "../src/serviceClient.js";

function event(type: string, overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    event_schema: "1.0",
    event_id: `event-${type}`,
    session_id: "session / one",
    timestamp: "2026-08-14T10:00:00.000Z",
    type,
    revision_id: "rev-1",
    view_id: type === "session_started" || type === "session_completed" ? null : "view / one",
    entity_ids: type === "workspace_entity_changed" ? ["node-1"] : [],
    relationship_ids: type === "context_selected" ? ["edge-1"] : [],
    hydradb_query_metadata: null,
    repository_id: "repo",
    agent: "extension",
    evidence_ids: [],
    metadata: {},
    ...overrides
  };
}

describe("Observe service client contract", () => {
  it("uses exact bounded-polling, session, view, interaction, and workspace request shapes", async () => {
    const calls: Array<{ url: string; method?: string; body?: unknown }> = [];
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, method: init?.method, body: init?.body === undefined ? undefined : JSON.parse(String(init.body)) });
      let response: unknown;
      if (url.endsWith("/api/observe/sessions")) {
        response = { status: "active", session_id: "session / one", revision_id: "rev-1", event: event("session_started") };
      } else if (url.endsWith("/complete")) {
        response = { status: "completed", session_id: "session / one", event: event("session_completed") };
      } else if (url.includes("/api/events?")) {
        response = [event("hydradb_result_returned")];
      } else if (url.includes("/api/views/by-id/")) {
        response = {
          view_id: "view / one", revision_id: "rev-1", mode: "observe", depth: "symbol",
          nodes: [], edges: [], warnings: [], hydradb: { available: true },
          budget: { requested_nodes: 10, returned_nodes: 0, requested_edges: 10, returned_edges: 0 }
        };
      } else if (url.endsWith("/selection")) {
        response = { status: "recorded", event: event("context_selected", { relationship_ids: ["edge-1"] }) };
      } else if (url.endsWith("/evidence-opened")) {
        response = { status: "recorded", event: event("evidence_opened", { entity_ids: ["node-1"] }) };
      } else {
        response = { status: "recorded", event: event("workspace_entity_changed") };
      }
      return { ok: true, status: 200, json: async () => response } as Response;
    });
    const client = new RepositoryServiceClient({
      baseUrl: "http://127.0.0.1:8765", timeoutMs: 1000, fetchImpl: fetchMock as typeof fetch
    });

    const started = await client.startObserveSession();
    const events = await client.observeEvents("session / one");
    await client.getViewById("view / one");
    const selection = await client.recordObserveInteraction("selection", "view / one", "edge-1", "edge");
    const evidence = await client.recordObserveInteraction("evidence-opened", "view / one", "node-1", "node");
    const changed = await client.recordWorkspaceChange("view / one", "src/api route.py");
    const completed = await client.completeObserveSession("session / one");

    expect(observeSessionIsActive(started)).toBe(true);
    expect(Array.isArray(events)).toBe(true);
    expect(observeRecordMatches(selection, "context_selected", "session / one", "view / one", "edge-1", "edge")).toBe(true);
    expect(observeRecordMatches(evidence, "evidence_opened", "session / one", "view / one", "node-1", "node")).toBe(true);
    expect(observeRecordMatches(changed, "workspace_entity_changed", "session / one", "view / one")).toBe(true);
    expect(observeSessionWasCompleted(completed, "session / one")).toBe(true);
    expect(calls.map((call) => ({ path: new URL(call.url).pathname, method: call.method, body: call.body }))).toEqual([
      { path: "/api/observe/sessions", method: "POST", body: {} },
      { path: "/api/events", method: "GET", body: undefined },
      { path: "/api/views/by-id/view%20%2F%20one", method: "GET", body: undefined },
      { path: "/api/views/view%20%2F%20one/selection", method: "POST", body: { item_id: "edge-1", item_kind: "edge" } },
      { path: "/api/views/view%20%2F%20one/evidence-opened", method: "POST", body: { item_id: "node-1", item_kind: "node" } },
      { path: "/api/views/view%20%2F%20one/workspace-change", method: "POST", body: { path: "src/api route.py" } },
      { path: "/api/observe/sessions/session%20%2F%20one/complete", method: "POST", body: {} }
    ]);
    expect(new URL(calls[1]!.url).searchParams.get("session_id")).toBe("session / one");
    expect(calls[1]!.url).toContain("session_id=session+%2F+one");
  });

  it("fails closed when session or recorded event IDs are substituted", () => {
    const active = {
      status: "active", sessionId: "session-1", revisionId: "rev-1",
      event: {
        eventId: "event-1", sessionId: "other", timestamp: "2026-08-14T10:00:00Z", type: "session_started" as const,
        revisionId: "rev-1", entityIds: [], relationshipIds: []
      }
    };
    const recorded = {
      status: "recorded",
      event: {
        eventId: "event-2", sessionId: "session-1", timestamp: "2026-08-14T10:00:00Z", type: "context_selected" as const,
        revisionId: "rev-1", viewId: "other-view", entityIds: ["node-1"], relationshipIds: []
      }
    };

    expect(observeSessionIsActive(active)).toBe(false);
    expect(observeRecordMatches(recorded, "context_selected", "session-1", "view-1", "node-1", "node")).toBe(false);
  });

  it("rejects a selected item returned in the wrong event ID category", () => {
    const swapped = {
      status: "recorded",
      event: {
        eventId: "event-2", sessionId: "session-1", timestamp: "2026-08-14T10:00:00Z", type: "context_selected" as const,
        revisionId: "rev-1", viewId: "view-1", entityIds: [], relationshipIds: ["node-1"]
      }
    };

    expect(observeRecordMatches(swapped, "context_selected", "session-1", "view-1", "node-1", "node")).toBe(false);
    expect(observeRecordMatches(swapped, "context_selected", "session-1", "view-1", "node-1", "edge")).toBe(true);
  });
});
