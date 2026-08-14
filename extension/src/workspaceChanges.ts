import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import type { GraphNode } from "./types.js";

function comparisonPath(value: string): string {
  const resolved = path.resolve(value);
  return process.platform === "win32" ? resolved.toLowerCase() : resolved;
}

export function normalizeCanonicalRoot(value: string, platform: NodeJS.Platform = process.platform): string {
  const slashes = value.replaceAll("\\", "/").replace(/\/+$/, "") || "/";
  return platform === "win32" ? slashes.toLowerCase() : slashes;
}

export function repositoryRootFingerprint(canonicalRealPath: string, platform: NodeJS.Platform = process.platform): string {
  return crypto.createHash("sha256").update(normalizeCanonicalRoot(canonicalRealPath, platform), "utf8").digest("hex");
}

export function matchingWorkspaceRoot(
  workspaceRoots: readonly string[],
  expectedFingerprint: string,
  realpath: (value: string) => string = fs.realpathSync.native
): string | undefined {
  if (!/^[a-f0-9]{64}$/.test(expectedFingerprint)) return undefined;
  const matches: string[] = [];
  for (const root of workspaceRoots) {
    try {
      if (repositoryRootFingerprint(realpath(root)) === expectedFingerprint) matches.push(root);
    } catch {
      // A root that cannot be resolved cannot prove identity with the service root.
    }
  }
  return matches.length === 1 ? matches[0] : undefined;
}

export function workspaceRelativePathForChange(absolutePath: string, workspaceRoots: readonly string[]): string | undefined {
  const resolvedAbsolute = path.resolve(absolutePath);
  const comparedAbsolute = comparisonPath(resolvedAbsolute);
  for (const root of [...workspaceRoots].sort((left, right) => right.length - left.length)) {
    const resolvedRoot = path.resolve(root);
    const relative = path.relative(comparisonPath(resolvedRoot), comparedAbsolute);
    if (relative && relative !== ".." && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative)) {
      return path.relative(resolvedRoot, resolvedAbsolute).split(path.sep).join("/");
    }
  }
  return undefined;
}

export function visibleNodeIdsForWorkspaceChange(
  nodes: readonly GraphNode[],
  changedAbsolutePath: string,
  workspaceRoots: readonly string[]
): string[] {
  const relative = workspaceRelativePathForChange(changedAbsolutePath, workspaceRoots);
  if (!relative) return [];
  const compared = process.platform === "win32" ? relative.toLowerCase() : relative;
  return [...new Set(nodes
    .filter((node) => {
      const sourcePath = node.source?.path;
      if (!sourcePath || path.isAbsolute(sourcePath)) return false;
      const normalized = path.posix.normalize(sourcePath.replaceAll("\\", "/"));
      if (normalized === ".." || normalized.startsWith("../")) return false;
      return (process.platform === "win32" ? normalized.toLowerCase() : normalized) === compared;
    })
    .map((node) => node.id))].slice(0, 100);
}
