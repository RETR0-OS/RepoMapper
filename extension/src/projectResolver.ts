import { execFile } from "node:child_process";
import { promises as fs } from "node:fs";
import * as path from "node:path";
import { promisify } from "node:util";
import * as vscode from "vscode";
import {
  canonicalPath,
  gitRepositoryIdentity,
  localRepositoryIdentity,
  readProjectIdentity,
  writeProjectIdentity,
  type ResolvedProject
} from "./projectIdentity.js";

const execFileAsync = promisify(execFile);

interface GitRemote {
  readonly name: string;
  readonly fetchUrl?: string;
  readonly pushUrl?: string;
}

interface GitRepository {
  readonly rootUri: vscode.Uri;
  readonly state: { readonly remotes: readonly GitRemote[] };
}

interface GitApi {
  readonly repositories: readonly GitRepository[];
}

interface GitExtension {
  getAPI(version: 1): GitApi;
}

export async function selectCurrentProjectFolder(): Promise<vscode.WorkspaceFolder | undefined> {
  const editorUri = vscode.window.activeTextEditor?.document.uri;
  if (editorUri?.scheme === "file") {
    const activeFolder = vscode.workspace.getWorkspaceFolder(editorUri);
    if (activeFolder?.uri.scheme === "file") return activeFolder;
  }
  const folders = (vscode.workspace.workspaceFolders ?? []).filter((folder) => folder.uri.scheme === "file");
  if (folders.length === 1) return folders[0];
  if (folders.length === 0) return undefined;
  return vscode.window.showWorkspaceFolderPick({ placeHolder: "Select the project Repository Map should use" });
}

export async function resolveCurrentProject(): Promise<ResolvedProject | undefined> {
  const folder = await selectCurrentProjectFolder();
  if (!folder) return undefined;
  const repositoryRoot = await fs.realpath(folder.uri.fsPath);
  const stats = await fs.stat(repositoryRoot);
  if (!stats.isDirectory()) throw new Error("The selected project root is not a directory.");
  const existing = await readProjectIdentity(repositoryRoot);
  const git = await detectGit(repositoryRoot);
  const candidate = git?.origin
    ? gitRepositoryIdentity({ projectRoot: repositoryRoot, gitRoot: git.root, origin: git.origin })
    : undefined;
  const chosen = existing ?? candidate ?? localRepositoryIdentity(folder.name);
  if (!existing) await writeProjectIdentity(repositoryRoot, chosen);
  return {
    repositoryRoot,
    repositoryId: chosen.repository_id,
    projectName: folder.name,
    identity: chosen,
    candidateIdentity: existing && candidate && existing.repository_id !== candidate.repository_id
      ? candidate
      : undefined
  };
}

async function detectGit(projectRoot: string): Promise<{ root: string; origin?: string } | undefined> {
  const fromExtension = await detectGitFromExtension(projectRoot);
  if (fromExtension) return fromExtension;
  try {
    const rootResult = await execFileAsync("git", ["-C", projectRoot, "rev-parse", "--show-toplevel"], {
      encoding: "utf8", windowsHide: true, timeout: 5_000
    });
    const root = await fs.realpath(rootResult.stdout.trim());
    let origin: string | undefined;
    try {
      const remoteResult = await execFileAsync("git", ["-C", projectRoot, "remote", "get-url", "origin"], {
        encoding: "utf8", windowsHide: true, timeout: 5_000
      });
      origin = remoteResult.stdout.trim() || undefined;
    } catch { /* A local Git repository may have no origin. */ }
    return { root, origin };
  } catch {
    return undefined;
  }
}

async function detectGitFromExtension(projectRoot: string): Promise<{ root: string; origin?: string } | undefined> {
  const extension = vscode.extensions.getExtension<GitExtension>("vscode.git");
  if (!extension) return undefined;
  try {
    const exports = extension.isActive ? extension.exports : await extension.activate();
    const repositories = exports.getAPI(1).repositories;
    const canonicalProject = canonicalPath(projectRoot);
    const candidates = repositories.filter((repository) => {
      const relative = path.relative(canonicalPath(repository.rootUri.fsPath), canonicalProject);
      return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
    }).sort((left, right) => right.rootUri.fsPath.length - left.rootUri.fsPath.length);
    const repository = candidates[0];
    if (!repository) return undefined;
    const remote = repository.state.remotes.find((item) => item.name === "origin");
    return {
      root: await fs.realpath(repository.rootUri.fsPath),
      origin: remote?.fetchUrl ?? remote?.pushUrl
    };
  } catch {
    return undefined;
  }
}
