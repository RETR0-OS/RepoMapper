import type { AgentRunTrace, AgentUsage, ContrastSide, ContrastState } from "../types.js";

/**
 * Presentation arithmetic for the Contrast panel. It lives outside main.ts so
 * the numbers on screen can be tested; main.ts is excluded from coverage.
 *
 * Nothing here estimates anything. Every figure comes from the agent's own
 * reported usage, or is a difference between two such figures.
 */

export function emptyContrastTrace(side: ContrastSide): AgentRunTrace {
  return { side, status: "starting", toolsAvailable: [], mcpServers: [], toolCalls: [], filesRead: [], turns: 0 };
}

export function emptyContrastState(): ContrastState {
  return {
    question: "",
    status: "idle",
    base: emptyContrastTrace("base"),
    argus: emptyContrastTrace("argus")
  };
}

/**
 * Every token the run charged for. Cache reads are included because they are
 * billed, and excluding them would flatter whichever side reads less.
 */
export function totalTokens(usage: AgentUsage | undefined): number {
  if (!usage) return 0;
  return usage.inputTokens + usage.outputTokens + usage.cacheReadTokens + usage.cacheCreationTokens;
}

export interface MetricRow {
  label: string;
  base: string;
  argus: string;
  /** Signed difference as a word plus a number. Never a colour alone. */
  delta: string;
  /** True when Argus used less. Used for emphasis, never as the only signal. */
  argusLower: boolean;
}

export function formatCount(value: number): string {
  return value.toLocaleString("en-US");
}

export function formatCost(value: number | undefined): string {
  return typeof value === "number" ? `$${value.toFixed(4)}` : "—";
}

export function formatDuration(ms: number | undefined): string {
  if (typeof ms !== "number" || ms <= 0) return "—";
  return ms < 1_000 ? `${ms} ms` : `${(ms / 1_000).toFixed(1)} s`;
}

function numericDelta(base: number, argus: number, format: (value: number) => string): string {
  const difference = argus - base;
  if (difference === 0) return "no change";
  const direction = difference < 0 ? "less" : "more";
  return `${format(Math.abs(difference))} ${direction}`;
}

function row(label: string, base: number, argus: number, format: (value: number) => string): MetricRow {
  return {
    label,
    base: format(base),
    argus: format(argus),
    delta: numericDelta(base, argus, format),
    argusLower: argus < base
  };
}

/**
 * The metrics strip. Only rows both sides can report are included, so a
 * half-finished run never shows an invented zero as if it were a measurement.
 */
export function contrastMetrics(state: ContrastState): MetricRow[] {
  const base = state.base;
  const argus = state.argus;
  const rows: MetricRow[] = [
    row("Total tokens", totalTokens(base.usage), totalTokens(argus.usage), formatCount),
    row("Output tokens", base.usage?.outputTokens ?? 0, argus.usage?.outputTokens ?? 0, formatCount),
    row("Cache read tokens", base.usage?.cacheReadTokens ?? 0, argus.usage?.cacheReadTokens ?? 0, formatCount),
    row("Tool calls", base.toolCalls.length, argus.toolCalls.length, formatCount),
    row("Files read", base.filesRead.length, argus.filesRead.length, formatCount),
    row("Turns", base.turns, argus.turns, formatCount)
  ];
  rows.push({
    label: "Cost",
    base: formatCost(base.costUsd),
    argus: formatCost(argus.costUsd),
    delta:
      typeof base.costUsd === "number" && typeof argus.costUsd === "number"
        ? `${formatCost(Math.abs(argus.costUsd - base.costUsd))} ${argus.costUsd < base.costUsd ? "less" : "more"}`
        : "—",
    argusLower: (argus.costUsd ?? 0) < (base.costUsd ?? 0)
  });
  rows.push({
    label: "Duration",
    base: formatDuration(base.durationMs),
    argus: formatDuration(argus.durationMs),
    delta: "—",
    argusLower: (argus.durationMs ?? 0) < (base.durationMs ?? 0)
  });
  return rows;
}

/** True once both sides have stopped, whatever the outcome. */
export function contrastFinished(state: ContrastState): boolean {
  const done = (trace: AgentRunTrace): boolean =>
    trace.status === "completed" || trace.status === "failed" || trace.status === "cancelled";
  return done(state.base) && done(state.argus);
}

/**
 * Both sides must have completed before any figure is a fair comparison. A
 * cancelled or failed side makes the strip meaningless, so the panel says so
 * instead of showing a difference nobody can defend.
 */
export function comparable(state: ContrastState): boolean {
  return state.base.status === "completed" && state.argus.status === "completed";
}

export function statusLabel(trace: AgentRunTrace): string {
  switch (trace.status) {
    case "starting": return "Starting";
    case "running": return "Running";
    case "completed": return "Completed";
    case "cancelled": return "Cancelled";
    case "failed": return trace.error ? `Failed: ${trace.error}` : "Failed";
  }
}

/** A short, content-free line for one tool call, safe to render as text. */
export function toolCallLabel(call: { name: string; detail: string }): string {
  return call.detail ? `${call.name} — ${call.detail}` : call.name;
}

/** The ordered text equivalent of the whole panel, for screen readers. */
export function contrastTextAlternative(state: ContrastState): string[] {
  const lines: string[] = [];
  for (const trace of [state.base, state.argus]) {
    const heading = trace.side === "base" ? "Base agent" : "With Argus";
    lines.push(`${heading}: ${statusLabel(trace)}, ${trace.toolCalls.length} tool calls, ${trace.turns} turns.`);
    trace.toolCalls.forEach((call, index) => lines.push(`${heading} step ${index + 1}: ${toolCallLabel(call)}`));
    if (trace.answer) lines.push(`${heading} answer: ${trace.answer}`);
  }
  return lines;
}
