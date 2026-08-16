import { describe, expect, it } from "vitest";
import { createPreviewView } from "../src/previewData.js";
import { normalizeGraphView, normalizeHealth } from "../src/viewAdapter.js";

describe("product view normalization", () => {
  it("adapts the shared snake_case schema and preserves explicit HydraDB unavailability", () => {
    const result = normalizeGraphView({
      view_id: "view-1", revision_id: "rev-8", mode: "repository", depth: "file",
      nodes: [{
        id: "n1", kind: "FUNCTION", display_name: "work", qualified_name: "mod.work", language: "python",
        path: "src/mod.py", span: { start_line: 5, start_column: 0, end_line: 6, end_column: 9 },
        revision_id: "rev-8", parser: "tree-sitter", parser_version: "1", attributes: { reason: "Focused result" }
      }],
      edges: [], warnings: ["bounded"],
      hydradb: { available: false, database: null, collections: [], graph_context: false },
      budget: { requested_nodes: 10, returned_nodes: 1, requested_edges: 10, returned_edges: 0, truncated: true }
    }, "trace");

    expect(result.mode).toBe("repository");
    expect(result.nodes[0]?.source).toMatchObject({ startLine: 5, startColumn: 0, endColumn: 9 });
    expect(result.nodes[0]?.reason).toBe("Focused result");
    expect(result.hydradb).toMatchObject({ available: false, graphContext: false });
    expect(result.hydradb).not.toHaveProperty("database");
    expect(result.budget).toMatchObject({ returnedNodes: 1, truncated: true });
  });

  it("accepts one legacy view release, rejects unknown schemas, and drops database fields", () => {
    const legacy = {
      view_schema: "hack-hydra.product-view.v1",
      view_id: "legacy", revision_id: "rev-1", mode: "trace",
      nodes: [], edges: [], warnings: [],
      hydradb: { available: true, database: "must-discard", collections: ["current"], graph_context: true },
      budget: {}
    };
    expect(normalizeGraphView(legacy, "trace").hydradb).not.toHaveProperty("database");
    expect(() => normalizeGraphView({ ...legacy, view_schema: "unknown.v9" }, "trace")).toThrow(/schema/i);
  });

  it("does not treat a configured but generic current marker as a verified revision", () => {
    expect(normalizeHealth({ state: "ready", revision_id: "current", message: "Configured" })).toMatchObject({
      state: "unverified",
      revision: "current"
    });
    expect(normalizeHealth({ state: "ready", revision_id: "rev-a1" })).toMatchObject({
      state: "ready",
      revision: "rev-a1"
    });
  });

  it("carries service diagnostics without inventing counters", () => {
    const view = normalizeGraphView({
      view_id: "view-1",
      revision_id: "rev-a1",
      mode: "trace",
      nodes: [],
      edges: [],
      warnings: [],
      diagnostics: {
        outcome: "all_groups_ungrounded",
        reason: "returned revisions: rev-a1",
        stage_ms: { hydradb_query: 1_204.5, total: 1_260.2 },
        funnel: { raw_chunks: 3, kept_paths: 0, broken: "not a number" }
      }
    }, "trace");

    expect(view.diagnostics?.outcome).toBe("all_groups_ungrounded");
    expect(view.diagnostics?.stageMs).toEqual({ hydradb_query: 1_204.5, total: 1_260.2 });
    // A non-numeric counter is dropped rather than shown as a false measurement.
    expect(view.diagnostics?.funnel).toEqual({ raw_chunks: 3, kept_paths: 0 });

    // An older service sends no diagnostics, and none may be invented for it.
    const legacy = normalizeGraphView({
      view_id: "view-2", revision_id: "rev-a1", mode: "trace", nodes: [], edges: [], warnings: []
    }, "trace");
    expect(legacy.diagnostics).toBeUndefined();
  });

  it("keeps preview data explicitly separate from HydraDB result metadata", () => {
    const preview = createPreviewView("trace");

    expect(preview.preview).toBe(true);
    expect(preview.hydradb).toBeUndefined();
    expect(preview.warnings.join(" ")).toContain("no HydraDB result");
    expect(preview.nodes.every((node) => node.parser === "Preview fixture")).toBe(true);
  });
});
