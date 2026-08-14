import * as path from "node:path";
import type { ViewMode } from "./types.js";

export type FocusAction = "show" | "callers" | "trace" | "tests";

export interface EditorSnapshot {
  scheme: string;
  absolutePath: string;
  activeLine: number;
}

export interface EditorFocus {
  relativePath: string;
  line: number;
}

export interface FocusedViewRequest {
  mode: ViewMode;
  question: string;
}

function comparisonPath(value: string): string {
  const resolved = path.resolve(value);
  return process.platform === "win32" ? resolved.toLowerCase() : resolved;
}

export function captureEditorFocus(
  editor: EditorSnapshot | undefined,
  workspaceRoots: readonly string[]
): EditorFocus | undefined {
  if (!editor || editor.scheme !== "file" || !Number.isInteger(editor.activeLine) || editor.activeLine < 0) {
    return undefined;
  }
  const resolvedAbsolute = path.resolve(editor.absolutePath);
  const absolute = comparisonPath(resolvedAbsolute);
  const roots = [...workspaceRoots].sort((left, right) => right.length - left.length);
  for (const root of roots) {
    const resolvedRoot = path.resolve(root);
    const normalizedRoot = comparisonPath(resolvedRoot);
    const relative = path.relative(normalizedRoot, absolute);
    if (relative && relative !== ".." && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative)) {
      return {
        relativePath: path.relative(resolvedRoot, resolvedAbsolute).split(path.sep).join("/"),
        line: editor.activeLine + 1
      };
    }
  }
  return undefined;
}

export function focusedViewRequest(action: FocusAction, focus: EditorFocus): FocusedViewRequest {
  const location = `workspace file ${JSON.stringify(focus.relativePath)} at one-based line ${focus.line}`;
  if (action === "show") {
    return {
      mode: "repository",
      question: `Focus the bounded repository structure view on ${location}. Show concrete source-backed entities only. Do not infer an exact symbol from the cursor line.`
    };
  }
  if (action === "callers") {
    return {
      mode: "explore",
      question: `Show a bounded caller and callee neighborhood for code at ${location}. Resolve a concrete symbol only when returned source evidence identifies it; otherwise focus the file.`
    };
  }
  if (action === "trace") {
    return {
      mode: "trace",
      question: `Trace the HydraDB-backed repository flow starting from source at ${location}. Do not invent an exact symbol or a missing path hop.`
    };
  }
  return {
    mode: "explore",
    question: `Find exact test relations grounded in source evidence for code at ${location}. If no concrete symbol is resolved, report file-level test relations without guessing.`
  };
}
