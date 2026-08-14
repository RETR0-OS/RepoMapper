import * as path from "node:path";
import { describe, expect, it } from "vitest";
import {
  matchingWorkspaceRoot,
  normalizeCanonicalRoot,
  repositoryRootFingerprint,
  visibleNodeIdsForWorkspaceChange,
  workspaceRelativePathForChange
} from "../src/workspaceChanges.js";
import type { GraphNode } from "../src/types.js";

const root = path.resolve("C:/work/repository");
const nodes: GraphNode[] = [
  { id: "visible-a", kind: "FUNCTION", displayName: "a", parser: "parser", revision: "rev", reason: "visible", source: { path: "src/api.py", startLine: 1, startColumn: 0, endLine: 2, endColumn: 0 } },
  { id: "visible-b", kind: "CLASS", displayName: "b", parser: "parser", revision: "rev", reason: "visible", source: { path: "src/api.py", startLine: 4, startColumn: 0, endLine: 8, endColumn: 0 } },
  { id: "other", kind: "FILE", displayName: "other", parser: "parser", revision: "rev", reason: "visible", source: { path: "src/other.py", startLine: 1, startColumn: 0, endLine: 1, endColumn: 0 } },
  { id: "unsafe", kind: "FILE", displayName: "unsafe", parser: "parser", revision: "rev", reason: "visible", source: { path: "../outside.py", startLine: 1, startColumn: 0, endLine: 1, endColumn: 0 } }
];

describe("Observe workspace change scope", () => {
  it("returns only currently visible nodes with an exact workspace-relative path match", () => {
    expect(visibleNodeIdsForWorkspaceChange(nodes, path.resolve(root, "src/api.py"), [root])).toEqual(["visible-a", "visible-b"]);
    expect(workspaceRelativePathForChange(path.resolve(root, "src/api.py"), [root])).toBe("src/api.py");
  });

  it("does not report outside, unmatched, or traversal paths", () => {
    expect(visibleNodeIdsForWorkspaceChange(nodes, path.resolve(root, "src/missing.py"), [root])).toEqual([]);
    expect(visibleNodeIdsForWorkspaceChange(nodes, path.resolve(root, "../outside.py"), [root])).toEqual([]);
    expect(visibleNodeIdsForWorkspaceChange([nodes[3]!], path.resolve(root, "../outside.py"), [root])).toEqual([]);
  });

  it("bounds the number of visible entity IDs sent for one file change", () => {
    const many = Array.from({ length: 120 }, (_, index): GraphNode => ({ ...nodes[0]!, id: `node-${index}` }));
    expect(visibleNodeIdsForWorkspaceChange(many, path.resolve(root, "src/api.py"), [root])).toHaveLength(100);
  });

  it("uses the shared canonical normalization before hashing root identity", () => {
    expect(normalizeCanonicalRoot("C:\\Work\\Repository\\", "win32")).toBe("c:/work/repository");
    expect(repositoryRootFingerprint("C:\\Work\\Repository\\", "win32")).toBe(
      repositoryRootFingerprint("c:/work/repository", "win32")
    );
  });

  it("enables edit reporting only for exactly one canonical root identity match", () => {
    const realRoot = path.resolve("C:/real/repository");
    const otherRoot = path.resolve("C:/real/other");
    const fingerprint = repositoryRootFingerprint(realRoot);
    const realpaths = new Map([[root, realRoot], [otherRoot, otherRoot]]);
    const resolve = (value: string): string => realpaths.get(value) ?? value;

    expect(matchingWorkspaceRoot([root], fingerprint, resolve)).toBe(root);
    expect(matchingWorkspaceRoot([otherRoot], fingerprint, resolve)).toBeUndefined();
    expect(matchingWorkspaceRoot([root, path.resolve("C:/alias")], fingerprint, () => realRoot)).toBeUndefined();
    expect(matchingWorkspaceRoot([root], "not-a-fingerprint", resolve)).toBeUndefined();
  });
});
