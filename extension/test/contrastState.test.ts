import { describe, expect, it } from "vitest";
import {
  comparable,
  contrastFinished,
  contrastMetrics,
  contrastTextAlternative,
  emptyContrastState,
  emptyContrastTrace,
  formatCost,
  formatDuration,
  statusLabel,
  toolCallLabel,
  totalTokens
} from "../src/webview/contrastState.js";
import type { AgentRunTrace, ContrastState } from "../src/types.js";

function trace(side: "base" | "argus", overrides: Partial<AgentRunTrace> = {}): AgentRunTrace {
  return { ...emptyContrastTrace(side), status: "completed", ...overrides };
}

function state(overrides: Partial<ContrastState> = {}): ContrastState {
  return {
    ...emptyContrastState(),
    status: "done",
    base: trace("base", {
      turns: 17,
      toolCalls: [{ name: "Grep", detail: "authorize" }, { name: "Read", detail: "api.py" }],
      filesRead: ["api.py"],
      usage: { inputTokens: 20, outputTokens: 4506, cacheReadTokens: 370213, cacheCreationTokens: 51286, thinkingTokens: 1217 },
      costUsd: 0.8113,
      durationMs: 72084
    }),
    argus: trace("argus", {
      turns: 2,
      toolCalls: [{ name: "mcp__argus__trace_flow", detail: "how does auth work" }],
      filesRead: [],
      usage: { inputTokens: 18, outputTokens: 612, cacheReadTokens: 24180, cacheCreationTokens: 9840, thinkingTokens: 190 },
      costUsd: 0.0721,
      durationMs: 9120
    }),
    ...overrides
  };
}

describe("token totals", () => {
  it("counts cache tokens, because they are billed", () => {
    expect(totalTokens({ inputTokens: 1, outputTokens: 2, cacheReadTokens: 4, cacheCreationTokens: 8, thinkingTokens: 99 }))
      .toBe(15);
  });

  it("reports zero when the agent gave no usage", () => {
    expect(totalTokens(undefined)).toBe(0);
  });
});

describe("metrics strip", () => {
  it("states the difference as a word and a number, never as colour alone", () => {
    const rows = contrastMetrics(state());
    const tokens = rows.find((row) => row.label === "Total tokens");
    expect(tokens?.base).toBe("426,025");
    expect(tokens?.argus).toBe("34,650");
    expect(tokens?.delta).toBe("391,375 less");
    expect(tokens?.argusLower).toBe(true);
  });

  it("says 'no change' rather than showing a bare zero", () => {
    const flat = state({ argus: trace("argus", { turns: 17 }), base: trace("base", { turns: 17 }) });
    expect(contrastMetrics(flat).find((row) => row.label === "Turns")?.delta).toBe("no change");
  });

  it("reports more when Argus used more", () => {
    const worse = state({
      base: trace("base", { toolCalls: [{ name: "Read", detail: "a" }] }),
      argus: trace("argus", { toolCalls: [{ name: "a", detail: "" }, { name: "b", detail: "" }, { name: "c", detail: "" }] })
    });
    const row = contrastMetrics(worse).find((item) => item.label === "Tool calls");
    expect(row?.delta).toBe("2 more");
    expect(row?.argusLower).toBe(false);
  });

  it("shows a dash for a cost that was never reported", () => {
    const partial = state({ argus: trace("argus", { costUsd: undefined }) });
    expect(contrastMetrics(partial).find((row) => row.label === "Cost")?.delta).toBe("—");
  });
});

describe("comparison honesty", () => {
  it("is comparable only when both sides completed", () => {
    expect(comparable(state())).toBe(true);
    expect(comparable(state({ argus: trace("argus", { status: "cancelled" }) }))).toBe(false);
    expect(comparable(state({ base: trace("base", { status: "failed" }) }))).toBe(false);
  });

  it("treats a cancelled or failed side as finished", () => {
    expect(contrastFinished(state({ argus: trace("argus", { status: "cancelled" }) }))).toBe(true);
    expect(contrastFinished(state({ argus: trace("argus", { status: "running" }) }))).toBe(false);
  });

  it("names the reason a run failed", () => {
    expect(statusLabel(trace("base", { status: "failed", error: "timed out" }))).toBe("Failed: timed out");
    expect(statusLabel(trace("base", { status: "running" }))).toBe("Running");
  });
});

describe("formatting", () => {
  it("keeps cost precise enough to be checked", () => {
    expect(formatCost(0.8113375)).toBe("$0.8113");
    expect(formatCost(undefined)).toBe("—");
  });

  it("reads durations in the right unit", () => {
    expect(formatDuration(840)).toBe("840 ms");
    expect(formatDuration(72084)).toBe("72.1 s");
    expect(formatDuration(undefined)).toBe("—");
  });

  it("omits an empty tool detail rather than printing a dangling dash", () => {
    expect(toolCallLabel({ name: "Bash", detail: "" })).toBe("Bash");
    expect(toolCallLabel({ name: "Read", detail: "api.py" })).toBe("Read — api.py");
  });
});

describe("text alternative", () => {
  it("lists both trajectories in order for a screen reader", () => {
    const lines = contrastTextAlternative(state());
    expect(lines[0]).toContain("Base agent: Completed, 2 tool calls");
    expect(lines).toContain("Base agent step 1: Grep — authorize");
    expect(lines.some((line) => line.startsWith("With Argus:"))).toBe(true);
  });

  it("includes each side's final answer, so quality can be checked without color", () => {
    const lines = contrastTextAlternative(state({
      base: trace("base", { answer: "The request enters through api.py." }),
      argus: trace("argus", { answer: "The request enters through the router." })
    }));
    expect(lines).toContain("Base agent answer: The request enters through api.py.");
    expect(lines).toContain("With Argus answer: The request enters through the router.");
  });

  it("omits the answer line when the agent reported none", () => {
    const lines = contrastTextAlternative(state());
    expect(lines.some((line) => line.includes(" answer: "))).toBe(false);
  });
});
