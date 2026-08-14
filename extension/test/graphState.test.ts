import { describe, expect, it } from "vitest";
import { createPreviewView } from "../src/previewData.js";
import { nextSelection, visibleEdges, zoomAtPoint } from "../src/webview/graphState.js";

describe("graph presentation state", () => {
  it("hides inferred relations by default without hiding selected exact predicates", () => {
    const view = createPreviewView("repository");
    const predicates = new Set(view.edges.map((edge) => edge.predicate));
    const exactOnly = visibleEdges(view, predicates, false);

    expect(view.edges.some((edge) => edge.quality === "inferred")).toBe(true);
    expect(exactOnly.length).toBeLessThan(view.edges.length);
    expect(exactOnly.every((edge) => edge.quality === "exact")).toBe(true);
    expect(visibleEdges(view, predicates, true).some((edge) => edge.quality === "inferred")).toBe(true);
  });

  it("applies relation filters to real predicates rather than only changing filter state", () => {
    const view = createPreviewView("repository");
    const calls = visibleEdges(view, new Set(["CALLS"]), true);
    const imports = visibleEdges(view, new Set(["IMPORTS"]), true);

    expect(calls).not.toEqual(imports);
    expect(calls).toHaveLength(1);
    expect(calls[0]?.predicate).toBe("CALLS");
    expect(imports[0]?.predicate).toBe("IMPORTS");
  });

  it("keeps the graph coordinate under the pointer fixed while zooming", () => {
    const before = { x: 20, y: -15, scale: 1.2 };
    const pointer = { x: 410, y: 250 };
    const graphPointBefore = {
      x: (pointer.x - before.x) / before.scale,
      y: (pointer.y - before.y) / before.scale
    };
    const after = zoomAtPoint(before, pointer, 1.8);
    const graphPointAfter = {
      x: (pointer.x - after.x) / after.scale,
      y: (pointer.y - after.y) / after.scale
    };

    expect(graphPointAfter.x).toBeCloseTo(graphPointBefore.x, 8);
    expect(graphPointAfter.y).toBeCloseTo(graphPointBefore.y, 8);
    expect(after.scale).toBe(1.8);
  });

  it("wraps keyboard selection in both directions", () => {
    const ids = ["a", "b", "c"];
    expect(nextSelection(ids, "c", 1)).toBe("a");
    expect(nextSelection(ids, "a", -1)).toBe("c");
    expect(nextSelection([], undefined, 1)).toBeUndefined();
  });

  it("keeps Compare change states separate from Observe retrieval states", () => {
    const compare = createPreviewView("compare");
    const changed = compare.nodes.filter((node) => ["added", "removed", "modified"].includes(node.state ?? ""));

    expect(changed.map((node) => node.id).sort()).toEqual(["preview:tests", "preview:webview"]);
    expect(compare.nodes.some((node) => node.state === "returned" || node.state === "selected")).toBe(false);
  });
});
