import type { GraphDepth, SourceRange, ViewMode, WebviewToHostMessage } from "./types.js";
import { safeDisplayStateKey } from "./webview/graphState.js";

type UnknownRecord = Record<string, unknown>;
const modes = new Set<ViewMode>(["repository", "explore", "trace", "observe", "compare", "preserve"]);
const depths = new Set<GraphDepth>(["package", "file", "symbol"]);

function isRecord(value: unknown): value is UnknownRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function parseSource(value: unknown): SourceRange | undefined {
  if (!isRecord(value) || typeof value.path !== "string" || value.path.length === 0 || value.path.length > 4096) {
    return undefined;
  }
  const numbers = [value.startLine, value.startColumn, value.endLine, value.endColumn];
  if (!numbers.every((item) => Number.isInteger(item))) {
    return undefined;
  }
  const startLine = value.startLine as number;
  const startColumn = value.startColumn as number;
  const endLine = value.endLine as number;
  const endColumn = value.endColumn as number;
  if (startLine < 1 || startColumn < 0 || endLine < startLine || endColumn < 0 || (startLine === endLine && endColumn < startColumn)) {
    return undefined;
  }
  return { path: value.path, startLine, startColumn, endLine, endColumn };
}

export function parseWebviewMessage(value: unknown): WebviewToHostMessage | undefined {
  if (!isRecord(value) || typeof value.type !== "string") {
    return undefined;
  }
  if (value.type === "ready" || value.type === "retry") {
    return { type: value.type };
  }
  if (value.type === "changeMode" && typeof value.mode === "string" && modes.has(value.mode as ViewMode)) {
    return { type: "changeMode", mode: value.mode as ViewMode };
  }
  if (value.type === "changeDepth" && typeof value.depth === "string" && depths.has(value.depth as GraphDepth)) {
    return { type: "changeDepth", depth: value.depth as GraphDepth };
  }
  if (value.type === "query" && typeof value.question === "string" && value.question.trim().length > 0 && value.question.length <= 4000) {
    return { type: "query", question: value.question };
  }
  if (value.type === "openSource" && typeof value.itemId === "string" && value.itemId.length <= 1000) {
    const source = parseSource(value.source);
    return source ? { type: "openSource", itemId: value.itemId, source } : undefined;
  }
  if (
    value.type === "selectItem"
    && typeof value.itemId === "string"
    && value.itemId.length > 0
    && value.itemId.length <= 1000
    && (value.itemKind === "node" || value.itemKind === "edge")
  ) {
    return { type: "selectItem", itemId: value.itemId, itemKind: value.itemKind };
  }
  if (value.type === "setObservePaused" && typeof value.paused === "boolean") {
    return { type: "setObservePaused", paused: value.paused };
  }
  if (value.type === "primaryAction" && typeof value.mode === "string" && modes.has(value.mode as ViewMode)) {
    return {
      type: "primaryAction",
      mode: value.mode as ViewMode,
      selectedId: typeof value.selectedId === "string" && value.selectedId.length <= 1000 ? value.selectedId : undefined
    };
  }
  if (value.type === "persistDisplayState" && typeof value.key === "string" && safeDisplayStateKey(value.key)) {
    try {
      if (JSON.stringify(value.value).length <= 50_000) {
        return { type: "persistDisplayState", key: value.key, value: value.value };
      }
    } catch {
      return undefined;
    }
  }
  return undefined;
}
