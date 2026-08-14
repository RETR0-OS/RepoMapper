import { createHash } from "node:crypto";
import * as path from "node:path";

export interface RepositoryScope {
  repositoryRoot: string;
  repositoryId: string;
}

export function createRepositoryScope(
  repositoryRoot: string,
  workspaceName: string,
  platform: NodeJS.Platform = process.platform
): RepositoryScope {
  const canonicalRoot = canonicalRepositoryRoot(repositoryRoot, platform);
  const slug = workspaceName
    .normalize("NFKD")
    .replace(/[^A-Za-z0-9._-]+/g, "-")
    .replace(/^[^A-Za-z0-9]+|[-.]+$/g, "")
    .slice(0, 96) || "repository";
  const rootHash = createHash("sha256").update(canonicalRoot).digest("hex").slice(0, 12);
  return {
    repositoryRoot: path.resolve(repositoryRoot),
    repositoryId: `${slug}-${rootHash}`
  };
}

function canonicalRepositoryRoot(repositoryRoot: string, platform: NodeJS.Platform): string {
  let canonical = path.resolve(repositoryRoot).replace(/\\/g, "/").replace(/\/+$/, "");
  if (platform === "win32") canonical = canonical.toLowerCase();
  return canonical || "/";
}
