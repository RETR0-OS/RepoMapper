import { describe, expect, it } from "vitest";
import { createRepositoryScope } from "../src/workspaceScope.js";

describe("automatic workspace repository scope", () => {
  it("creates a valid repository ID without exposing the root path", () => {
    const scope = createRepositoryScope("C:\\Work\\Customer Portal", "Customer Portal", "win32");

    expect(scope.repositoryRoot).toMatch(/Customer Portal$/);
    expect(scope.repositoryId).toMatch(/^Customer-Portal-[a-f0-9]{12}$/);
    expect(scope.repositoryId).not.toContain("Work");
  });

  it("uses the canonical root to distinguish same-named workspaces", () => {
    const first = createRepositoryScope("C:\\Work\\api", "api", "win32");
    const second = createRepositoryScope("D:\\Work\\api", "api", "win32");

    expect(first.repositoryId).not.toBe(second.repositoryId);
  });

  it("falls back to an ASCII-safe name", () => {
    const scope = createRepositoryScope("C:\\Work\\repository", "---", "win32");

    expect(scope.repositoryId).toMatch(/^repository-[a-f0-9]{12}$/);
  });
});
