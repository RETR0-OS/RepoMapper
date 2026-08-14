import * as path from "node:path";
import type { SourceRange } from "./types.js";

export interface ValidatedSource {
  absolutePath: string;
  startLine: number;
  startColumn: number;
  endLine: number;
  endColumn: number;
}

function normalizeForComparison(value: string): string {
  const normalized = path.resolve(value);
  return process.platform === "win32" ? normalized.toLowerCase() : normalized;
}

export function validateSourceRange(source: SourceRange, workspaceRoots: readonly string[]): ValidatedSource | undefined {
  if (!source.path || path.isAbsolute(source.path) || workspaceRoots.length === 0) {
    return undefined;
  }
  if (![source.startLine, source.startColumn, source.endLine, source.endColumn].every(Number.isInteger)) {
    return undefined;
  }
  // Graph IR uses one-based lines and zero-based columns. Keep that convention
  // through the service and webview so only lines need conversion for VS Code.
  if (source.startLine < 1 || source.startColumn < 0 || source.endLine < source.startLine || source.endColumn < 0) {
    return undefined;
  }
  if (source.startLine === source.endLine && source.endColumn < source.startColumn) {
    return undefined;
  }

  for (const root of workspaceRoots) {
    const absolutePath = path.resolve(root, source.path);
    const normalizedRoot = normalizeForComparison(root);
    const normalizedPath = normalizeForComparison(absolutePath);
    const relative = path.relative(normalizedRoot, normalizedPath);
    if (relative && !relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative)) {
      return {
        absolutePath,
        startLine: source.startLine,
        startColumn: source.startColumn,
        endLine: source.endLine,
        endColumn: source.endColumn
      };
    }
  }
  return undefined;
}
