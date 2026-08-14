import { describe, expect, it } from "vitest";
import { previewIdentityMigration } from "../src/identityMigration.js";

const current = {
  version: 1 as const,
  repository_id: "local:portal:123e4567-e89b-42d3-a456-426614174000",
  source: "local" as const
};
const candidate = {
  version: 1 as const,
  repository_id: "git:portal:0123456789abcdefabcd",
  source: "git-origin" as const,
  origin_fingerprint: "a".repeat(64)
};

describe("repository identity migration", () => {
  it("allows only a provably empty project to adopt Git identity", () => {
    const preview = previewIdentityMigration(current, candidate, {
      state: "unverified",
      sourceCount: 0,
      repositoryId: current.repository_id
    });
    expect(preview.canMigrateWithoutOrphans).toBe(true);
    expect(JSON.stringify(preview)).not.toContain("github.com");
  });

  it("fails closed for indexed, unknown, mismatched, or active state", () => {
    expect(previewIdentityMigration(current, candidate, {
      state: "ready", sourceCount: 2, repositoryId: current.repository_id
    }).canMigrateWithoutOrphans).toBe(false);
    expect(previewIdentityMigration(current, candidate, {
      state: "unavailable", repositoryId: current.repository_id
    }).canMigrateWithoutOrphans).toBe(false);
    expect(previewIdentityMigration(current, candidate, {
      state: "indexing", sourceCount: 0, repositoryId: current.repository_id
    }).canMigrateWithoutOrphans).toBe(false);
    expect(() => previewIdentityMigration(current, candidate, {
      state: "unverified", sourceCount: 0, repositoryId: "local:other:id"
    })).toThrow(/different/i);
  });
});
