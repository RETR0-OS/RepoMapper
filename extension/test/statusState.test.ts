import { describe, expect, it } from "vitest";
import { deriveViewStatus, groundedViewContext, reconcileHealthWithView } from "../src/statusState.js";
import { normalizeGraphView } from "../src/viewAdapter.js";
import type { GraphView, ServiceHealth } from "../src/types.js";

function serviceView(available: boolean, revision = "rev-1"): GraphView {
  return normalizeGraphView({
    view_id: "view-status",
    revision_id: revision,
    mode: "repository",
    depth: "file",
    nodes: [],
    edges: [],
    warnings: available ? [] : ["HydraDB query failed; no local fallback was used."],
    hydradb: {
      available,
      database: available ? "repo-db" : null,
      collections: available ? ["current"] : [],
      graph_context: available,
      status: available ? "ready" : "unavailable"
    },
    budget: { requested_nodes: 20, returned_nodes: 0, requested_edges: 30, returned_edges: 0, truncated: false }
  }, "repository");
}

describe("view status truthfulness", () => {
  it("never lets configured health make an unavailable HydraDB view look ready", () => {
    const configuredHealth: ServiceHealth = {
      state: "ready",
      revision: "rev-1",
      database: "repo-db",
      message: "HydraDB repository retrieval is configured."
    };
    const view = serviceView(false);
    const status = deriveViewStatus(view, configuredHealth);

    // These assertions exercise the rendered state, not just the input flag.
    expect(view.preview).toBe(false);
    expect(view.hydradb?.available).toBe(false);
    expect(status.verified).toBe(false);
    expect(status.health.state).toBe("unavailable");
    expect(status.label.toLowerCase()).toContain("unavailable");
    expect(status.label.toLowerCase()).not.toContain("ready");
    expect(status.bannerHidden).toBe(false);
    expect(status.bannerMessage).toContain("no local fallback");
  });

  it("requires HydraDB availability and an exact verified revision match for readiness", () => {
    const available = serviceView(true, "rev-1");
    const matching = deriveViewStatus(available, { state: "ready", revision: "rev-1" });
    const mismatched = deriveViewStatus(available, { state: "ready", revision: "rev-2" });

    expect(matching.verified).toBe(true);
    expect(matching.label).toBe("HydraDB · revision rev-1 ready");
    expect(matching.bannerHidden).toBe(true);
    expect(mismatched.verified).toBe(false);
    expect(mismatched.health.state).toBe("unverified");
    expect(mismatched.label).not.toContain("ready");
  });

  it("reconciles an unavailable view before native status consumers receive health", () => {
    const reconciled = reconcileHealthWithView(
      { state: "ready", revision: "rev-1", message: "Configured" },
      serviceView(false, "rev-1")
    );

    expect(reconciled).toMatchObject({
      state: "unavailable",
      message: "HydraDB query failed; no local fallback was used."
    });
  });

  it("exposes a view ID for writes only when the exact revision is grounded and ready", () => {
    const view = serviceView(true, "rev-1");

    expect(groundedViewContext(view, { state: "ready", revision: "rev-1" })).toEqual({
      viewId: "view-status",
      revision: "rev-1"
    });
    expect(groundedViewContext(view, { state: "ready", revision: "rev-2" })).toBeUndefined();
    expect(groundedViewContext({ ...view, preview: true }, { state: "ready", revision: "rev-1" })).toBeUndefined();
    expect(groundedViewContext({ ...view, hydradb: { ...view.hydradb!, available: false } }, { state: "ready", revision: "rev-1" })).toBeUndefined();
  });
});
