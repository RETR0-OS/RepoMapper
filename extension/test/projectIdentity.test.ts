import { mkdtemp, readFile, realpath } from "node:fs/promises";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import {
  gitRepositoryIdentity,
  localRepositoryIdentity,
  normalizeGitOrigin,
  readProjectIdentity,
  writeProjectIdentity
} from "../src/projectIdentity.js";

describe("project identity", () => {
  it("normalizes HTTPS and SCP-style SSH origins to one identity", () => {
    const https = normalizeGitOrigin("https://user:secret@GitHub.com/Owner/Repo.git?token=nope#fragment");
    const ssh = normalizeGitOrigin("git@github.com:Owner/Repo.git");
    expect(https).toEqual({ canonical: "github.com/Owner/Repo", repositoryName: "Repo" });
    expect(ssh).toEqual(https);
    const first = gitRepositoryIdentity({ projectRoot: "/work/repo", gitRoot: "/work/repo", origin: "https://github.com/Owner/Repo.git" });
    const second = gitRepositoryIdentity({ projectRoot: "/work/repo", gitRoot: "/work/repo", origin: "git@github.com:Owner/Repo.git" });
    expect(first?.repository_id).toBe(second?.repository_id);
    expect(first?.repository_id).toMatch(/^git:Repo:[a-f0-9]{20}$/);
  });

  it("keeps forks and subprojects separate", () => {
    const upstream = gitRepositoryIdentity({ projectRoot: "/work/repo", gitRoot: "/work/repo", origin: "https://github.com/a/repo" });
    const fork = gitRepositoryIdentity({ projectRoot: "/work/repo", gitRoot: "/work/repo", origin: "https://github.com/b/repo" });
    const subproject = gitRepositoryIdentity({ projectRoot: "/work/repo/apps/api", gitRoot: "/work/repo", origin: "https://github.com/a/repo" });
    expect(upstream?.repository_id).not.toBe(fork?.repository_id);
    expect(subproject?.repository_id).toMatch(/^git:repo:[a-f0-9]{20}:[a-f0-9]{10}$/);
    expect(subproject?.repository_id.split(":").slice(0, 3)).toEqual(
      upstream?.repository_id.split(":").slice(0, 3)
    );
    expect(subproject?.repository_id).not.toBe(upstream?.repository_id);
  });

  it("rejects file remotes and malformed origins", () => {
    expect(normalizeGitOrigin("file:///tmp/repo.git")).toBeUndefined();
    expect(normalizeGitOrigin("not a remote")).toBeUndefined();
    expect(normalizeGitOrigin("https://example.test/../secret")).toBeUndefined();
  });

  it("generates and atomically persists a local identity", async () => {
    const root = await realpath(await mkdtemp(path.join(tmpdir(), "hydra-identity-")));
    const identity = localRepositoryIdentity("Customer Portal", "123e4567-e89b-42d3-a456-426614174000");
    expect(identity.repository_id).toBe("local:Customer-Portal:123e4567-e89b-42d3-a456-426614174000");
    await writeProjectIdentity(root, identity);
    expect(await readProjectIdentity(root)).toEqual(identity);
    const stored = await readFile(path.join(root, ".hydra-graph", "identity.json"), "utf8");
    expect(stored).not.toContain("database");
    expect(stored).not.toContain("api_key");
  });
});
