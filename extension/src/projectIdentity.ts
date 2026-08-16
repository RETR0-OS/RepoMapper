import { createHash, randomUUID } from "node:crypto";
import { promises as fs } from "node:fs";
import * as path from "node:path";
import type { RepositoryScope } from "./workspaceScope.js";

const IDENTITY_VERSION = 1;
const REPOSITORY_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const RUNTIME_IGNORE = "*\n";

export interface ProjectIdentityRecord {
  version: 1;
  repository_id: string;
  source: "git-origin" | "local" | "legacy";
  origin_fingerprint?: string;
}

export interface ResolvedProject extends RepositoryScope {
  projectName: string;
  identity: ProjectIdentityRecord;
  candidateIdentity?: ProjectIdentityRecord;
}

export interface GitIdentityInput {
  projectRoot: string;
  gitRoot: string;
  origin: string;
}

export function normalizeGitOrigin(value: string): { canonical: string; repositoryName: string } | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  if (/(?:^|[\\/])\.\.(?:[\\/?#]|$)/.test(trimmed)) return undefined;
  const scp = trimmed.includes("://") ? null : /^(?:[^@/\s]+@)?([^:/\s]+):(.+)$/.exec(trimmed);
  let candidate = trimmed;
  if (scp && !/^[A-Za-z]:[\\/]/.test(trimmed)) {
    candidate = `ssh://${scp[1]}/${scp[2]}`;
  }
  let parsed: URL;
  try {
    parsed = new URL(candidate);
  } catch {
    return undefined;
  }
  if (!parsed.hostname || !["https:", "http:", "ssh:", "git:"].includes(parsed.protocol)) {
    return undefined;
  }
  const host = parsed.hostname.toLowerCase();
  const defaultPort = (parsed.protocol === "https:" && parsed.port === "443")
    || (parsed.protocol === "http:" && parsed.port === "80")
    || (parsed.protocol === "ssh:" && parsed.port === "22");
  const authority = parsed.port && !defaultPort ? `${host}:${parsed.port}` : host;
  const pathname = decodeURIComponent(parsed.pathname)
    .replace(/\\/g, "/")
    .replace(/^\/+|\/+$/g, "")
    .replace(/\.git$/i, "");
  if (!pathname || pathname.split("/").some((part) => part === "." || part === "..")) return undefined;
  const repositoryName = sanitizeProjectName(pathname.split("/").at(-1) ?? "repository");
  return { canonical: `${authority}/${pathname}`, repositoryName };
}

export function gitRepositoryIdentity(input: GitIdentityInput): ProjectIdentityRecord | undefined {
  const remote = normalizeGitOrigin(input.origin);
  if (!remote) return undefined;
  const canonicalProject = canonicalPath(input.projectRoot);
  const canonicalGit = canonicalPath(input.gitRoot);
  let subproject = "";
  const relative = path.relative(canonicalGit, canonicalProject).replace(/\\/g, "/");
  if (relative && relative !== "." && !relative.startsWith("../") && relative !== "..") {
    subproject = `\n${relative}`;
  }
  const originFingerprint = sha256(remote.canonical);
  const identityHash = originFingerprint.slice(0, 20);
  const subprojectSuffix = subproject ? `:${sha256(relative).slice(0, 10)}` : "";
  return {
    version: IDENTITY_VERSION,
    repository_id: `git:${remote.repositoryName}:${identityHash}${subprojectSuffix}`,
    source: "git-origin",
    origin_fingerprint: originFingerprint
  };
}

export function localRepositoryIdentity(projectName: string, uuid = randomUUID()): ProjectIdentityRecord {
  const cleanUuid = uuid.toLowerCase();
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(cleanUuid)) {
    throw new Error("Generated project identity is not a valid UUID.");
  }
  return {
    version: IDENTITY_VERSION,
    repository_id: `local:${sanitizeProjectName(projectName)}:${cleanUuid}`,
    source: "local"
  };
}

export function sanitizeProjectName(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/[^A-Za-z0-9._-]+/g, "-")
    .replace(/^[^A-Za-z0-9]+|[-.]+$/g, "")
    .slice(0, 48) || "repository";
}

export async function readProjectIdentity(repositoryRoot: string): Promise<ProjectIdentityRecord | undefined> {
  const target = identityPath(repositoryRoot);
  try {
    const parsed = JSON.parse(await fs.readFile(target, "utf8")) as Partial<ProjectIdentityRecord>;
    if (parsed.version !== IDENTITY_VERSION || !isRepositoryId(parsed.repository_id)
      || !["git-origin", "local", "legacy"].includes(parsed.source ?? "")) return undefined;
    return {
      version: IDENTITY_VERSION,
      repository_id: parsed.repository_id,
      source: parsed.source,
      ...(typeof parsed.origin_fingerprint === "string" && /^[a-f0-9]{64}$/.test(parsed.origin_fingerprint)
        ? { origin_fingerprint: parsed.origin_fingerprint }
        : {})
    } as ProjectIdentityRecord;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined;
    return undefined;
  }
}

export async function writeProjectIdentity(repositoryRoot: string, record: ProjectIdentityRecord): Promise<void> {
  if (!isRepositoryId(record.repository_id)) throw new Error("Repository identity is invalid.");
  const root = await fs.realpath(repositoryRoot);
  const directory = path.join(root, ".hydra-graph");
  await fs.mkdir(directory, { recursive: true });
  try {
    await fs.writeFile(path.join(directory, ".gitignore"), RUNTIME_IGNORE, {
      encoding: "utf8",
      flag: "wx",
      mode: 0o600
    });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
  }
  const target = path.join(directory, "identity.json");
  const temporary = `${target}.${process.pid}.${randomUUID()}.tmp`;
  await fs.writeFile(temporary, `${JSON.stringify(record, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
  await fs.rename(temporary, target);
}

function identityPath(repositoryRoot: string): string {
  return path.join(repositoryRoot, ".hydra-graph", "identity.json");
}

export function canonicalPath(value: string): string {
  let result = path.resolve(value).replace(/\\/g, "/").replace(/\/+$/, "");
  if (process.platform === "win32") result = result.toLowerCase();
  return result || "/";
}

function sha256(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function isRepositoryId(value: unknown): value is string {
  return typeof value === "string" && REPOSITORY_ID.test(value);
}
