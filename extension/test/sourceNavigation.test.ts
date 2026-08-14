import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { validateSourceRange } from "../src/sourceNavigation.js";

const root = path.resolve("C:/work/hydra-project");

describe("validateSourceRange", () => {
  it("resolves a relative source while preserving one-based lines and zero-based columns", () => {
    const result = validateSourceRange({
      path: "src/worker.ts", startLine: 4, startColumn: 0, endLine: 7, endColumn: 12
    }, [root]);

    expect(result).toEqual({
      absolutePath: path.resolve(root, "src/worker.ts"),
      startLine: 4, startColumn: 0, endLine: 7, endColumn: 12
    });
  });

  it.each([
    "../secrets.env",
    "src/../../secrets.env",
    path.resolve("C:/work/other/secrets.env")
  ])("rejects a path outside the workspace: %s", (unsafePath) => {
    expect(validateSourceRange({
      path: unsafePath, startLine: 1, startColumn: 0, endLine: 1, endColumn: 1
    }, [root])).toBeUndefined();
  });

  it("does not confuse a sibling with a matching path prefix for a child", () => {
    const siblingPath = path.relative(root, path.resolve(`${root}-backup`, "stolen.ts"));
    expect(validateSourceRange({
      path: siblingPath, startLine: 1, startColumn: 0, endLine: 1, endColumn: 1
    }, [root])).toBeUndefined();
  });

  it.each([
    { startLine: 0, startColumn: 0, endLine: 1, endColumn: 0 },
    { startLine: 2, startColumn: 0, endLine: 1, endColumn: 0 },
    { startLine: 2, startColumn: 5, endLine: 2, endColumn: 4 },
    { startLine: 1.5, startColumn: 0, endLine: 2, endColumn: 0 }
  ])("rejects a malformed range: %j", (range) => {
    expect(validateSourceRange({ path: "src/file.ts", ...range }, [root])).toBeUndefined();
  });
});
