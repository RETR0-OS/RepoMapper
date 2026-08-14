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
    expect(result.budget).toMatchObject({ returnedNodes: 1, truncated: true });
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

  it("keeps preview data explicitly separate from HydraDB result metadata", () => {
    const preview = createPreviewView("trace");

    expect(preview.preview).toBe(true);
    expect(preview.hydradb).toBeUndefined();
    expect(preview.warnings.join(" ")).toContain("no HydraDB result");
    expect(preview.nodes.every((node) => node.parser === "Preview fixture")).toBe(true);
  });
});
