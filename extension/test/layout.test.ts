import { describe, expect, it } from "vitest";
import { createPreviewView } from "../src/previewData.js";
import { computeLayout, edgePath } from "../src/webview/layout.js";

describe("graph layout", () => {
  it("assigns every concrete node one stable, distinct position", () => {
    const view = createPreviewView("repository");
    const first = computeLayout(view.nodes, "repository");
    const second = computeLayout(view.nodes, "repository");

    expect(first).toEqual(second);
    expect(Object.keys(first).sort()).toEqual(view.nodes.map((node) => node.id).sort());
    expect(new Set(Object.values(first).map((point) => `${point.x}:${point.y}`)).size).toBe(view.nodes.length);
  });

  it("lays trace nodes left to right so path order is readable", () => {
    const view = createPreviewView("trace");
    const positions = computeLayout(view.nodes, "trace");
    const xs = view.nodes.map((node) => positions[node.id]?.x ?? Number.NaN);

    expect(xs.every(Number.isFinite)).toBe(true);
    expect(xs.slice(1).every((value, index) => value > (xs[index] ?? value))).toBe(true);
  });

  it("changes edge geometry when either attached node moves", () => {
    const source = { x: 100, y: 100 };
    const target = { x: 400, y: 200 };
    const before = edgePath(source, target);
    const afterSourceMove = edgePath({ x: 160, y: 140 }, target);
    const afterTargetMove = edgePath(source, { x: 470, y: 260 });

    expect(afterSourceMove).not.toBe(before);
    expect(afterTargetMove).not.toBe(before);
    expect(afterSourceMove).toContain("240 168");
  });
});
