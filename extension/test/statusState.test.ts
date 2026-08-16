import { describe, expect, it } from "vitest";
import { deriveViewStatus, emptyGraphMessage, groundedViewContext, reconcileHealthWithView } from "../src/statusState.js";
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

describe("empty graph explanation", () => {
  function emptyView(diagnostics: unknown, warnings: string[] = []): GraphView {
    return normalizeGraphView({
      view_id: "view-empty",
      revision_id: "rev-1",
      mode: "trace",
      nodes: [],
      edges: [],
      warnings,
      diagnostics,
      hydradb: { available: true, collections: ["current"], graph_context: true, status: "ready" },
      budget: { requested_nodes: 20, returned_nodes: 0, requested_edges: 30, returned_edges: 0, truncated: false }
    }, "trace");
  }

  it("advises a narrower question only when HydraDB matched no source", () => {
    const message = emptyGraphMessage(emptyView({ outcome: "no_chunks", funnel: { raw_chunks: 0 } }));

    expect(message).toContain("matched no repository source");
    expect(message).toContain("narrower question");
  });

  it("names the dropped relation groups instead of blaming the question", () => {
    const message = emptyGraphMessage(emptyView({ outcome: "all_groups_ungrounded" }));

    expect(message).toContain("cite sources outside this result");
    expect(message).toContain("Index this project again");
    expect(message).not.toContain("narrower question");
  });

  it("reports the service reason when HydraDB never answered", () => {
    const message = emptyGraphMessage(emptyView(
      { outcome: "hydradb_unavailable", reason: "HydraDB did not answer inside the 90 s service budget." },
      ["HydraDB could not serve this repository query."]
    ));

    expect(message).toContain("did not answer this query");
    expect(message).toContain("90 s service budget");
    expect(message).not.toContain("narrower question");
  });

  it("falls back to the old advice when the service sends no diagnostics", () => {
    expect(emptyGraphMessage(emptyView(undefined))).toContain("narrower question");
  });

  it("never blames the question for an interaction preview", () => {
    const preview = { ...emptyView({ outcome: "no_chunks" }), preview: true };

    expect(emptyGraphMessage(preview)).toContain("interaction preview");
  });
});
