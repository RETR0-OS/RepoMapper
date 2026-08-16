import { describe, expect, it } from "vitest";
import { applyStreamEvent, buildAgentArgs, emptyTrace, StreamJsonParser } from "../src/agentRun.js";
import { agentEnvironment } from "../src/agentSetup.js";

/** The shape the Claude Code CLI actually emits, captured from a real run. */
const initEvent = {
  type: "system",
  subtype: "init",
  model: "claude-opus-5",
  tools: ["Bash", "Glob", "Grep", "Read", "WebSearch"],
  mcp_servers: [{ name: "argus", status: "connected" }]
};

const assistantEvent = {
  type: "assistant",
  message: {
    content: [
      { type: "text", text: "looking" },
      { type: "tool_use", name: "Grep", input: { pattern: "authorize" } },
      { type: "tool_use", name: "Read", input: { file_path: "eval_app/api.py" } }
    ]
  }
};

const resultEvent = {
  type: "result",
  subtype: "success",
  is_error: false,
  num_turns: 17,
  duration_ms: 72084,
  total_cost_usd: 0.8113375,
  result: "The request reaches the policy store through authorize().",
  usage: {
    input_tokens: 20,
    output_tokens: 4506,
    cache_read_input_tokens: 370213,
    cache_creation_input_tokens: 51286,
    output_tokens_details: { thinking_tokens: 1217 }
  }
};

function fold(events: unknown[]) {
  return events.reduce<ReturnType<typeof emptyTrace>>(
    (trace, event) => applyStreamEvent(trace, event),
    emptyTrace("base")
  );
}

describe("stream-json parsing", () => {
  it("holds a partial line until the rest of the chunk arrives", () => {
    const parser = new StreamJsonParser();
    const line = JSON.stringify(initEvent);
    expect(parser.push(line.slice(0, 20))).toEqual([]);
    expect(parser.push(`${line.slice(20)}\n`)).toEqual([initEvent]);
  });

  it("drops non-JSON noise instead of ending the run", () => {
    const parser = new StreamJsonParser();
    const events = parser.push(`warning: something\n${JSON.stringify(resultEvent)}\n`);
    expect(events).toHaveLength(1);
    expect(parser.truncated).toBe(false);
  });

  it("stops accepting output past the size bound", () => {
    const parser = new StreamJsonParser();
    parser.push("x".repeat(1_000_001));
    expect(parser.truncated).toBe(true);
    expect(parser.push(`${JSON.stringify(resultEvent)}\n`)).toEqual([]);
  });
});

describe("trace accumulation", () => {
  it("records the tools the agent was given", () => {
    const trace = fold([initEvent]);
    expect(trace.status).toBe("running");
    expect(trace.model).toBe("claude-opus-5");
    expect(trace.toolsAvailable).toEqual(["Bash", "Glob", "Grep", "Read", "WebSearch"]);
    expect(trace.mcpServers).toEqual(["argus"]);
  });

  it("counts tool calls and the files that were read", () => {
    const trace = fold([initEvent, assistantEvent]);
    expect(trace.toolCalls.map((call) => call.name)).toEqual(["Grep", "Read"]);
    expect(trace.toolCalls[0]?.detail).toBe("authorize");
    expect(trace.filesRead).toEqual(["eval_app/api.py"]);
  });

  it("takes usage from the agent's own report and does not estimate", () => {
    const trace = fold([initEvent, assistantEvent, resultEvent]);
    expect(trace.status).toBe("completed");
    expect(trace.turns).toBe(17);
    expect(trace.usage).toEqual({
      inputTokens: 20,
      outputTokens: 4506,
      cacheReadTokens: 370213,
      cacheCreationTokens: 51286,
      thinkingTokens: 1217
    });
    expect(trace.costUsd).toBeCloseTo(0.8113375, 6);
    expect(trace.durationMs).toBe(72084);
  });

  it("marks a reported error as a failure", () => {
    const trace = fold([initEvent, { ...resultEvent, is_error: true, subtype: "error_max_turns" }]);
    expect(trace.status).toBe("failed");
    expect(trace.error).toBe("error_max_turns");
  });

  it("ignores an event that is not a record", () => {
    expect(applyStreamEvent(emptyTrace("base"), "nonsense")).toEqual(emptyTrace("base"));
  });
});

describe("argument construction", () => {
  it("gives the base side no MCP server and keeps its own tools", () => {
    const args = buildAgentArgs({ side: "base", question: "Q", cwd: "." });
    expect(args).toContain("--strict-mcp-config");
    expect(args[args.indexOf("--mcp-config") + 1]).toBe('{"mcpServers":{}}');
    expect(args[args.indexOf("--disallowedTools") + 1]).toBe("Write Edit NotebookEdit");
  });

  it("points the Argus side at the loopback endpoint", () => {
    const args = buildAgentArgs({ side: "argus", question: "Q", cwd: ".", mcpUrl: "http://127.0.0.1:8765/mcp" });
    expect(args[args.indexOf("--mcp-config") + 1]).toContain("http://127.0.0.1:8765/mcp");
  });

  it("leaves the agent's own tools on both sides, so Argus only ever adds", () => {
    // The contrast is harness versus harness-with-Argus. Denying the agent's
    // own search tools would measure a crippled harness instead.
    for (const side of ["base", "argus"] as const) {
      const args = buildAgentArgs({ side, question: "Q", cwd: ".", mcpUrl: "http://127.0.0.1:8765/mcp" });
      expect(args[args.indexOf("--disallowedTools") + 1]).toBe("Write Edit NotebookEdit");
    }
  });

  it("uses a permission mode that lets the Argus tools actually run", () => {
    // Regression: "dontAsk" denies every MCP tool, so the Argus side could
    // never call the tools the whole comparison exists to measure.
    const args = buildAgentArgs({ side: "argus", question: "Q", cwd: ".", mcpUrl: "http://127.0.0.1:8765/mcp" });
    expect(args[args.indexOf("--permission-mode") + 1]).toBe("auto");
  });

  it("names the Argus MCP server to match the one-time OAuth registration", () => {
    // Regression: a name other than "repository-map" cannot reuse the login
    // completed by `claude mcp add ... repository-map <url>` (agentSetup.ts),
    // so the CLI drops the server with no error and the side runs with no
    // Argus tools at all.
    const args = buildAgentArgs({ side: "argus", question: "Q", cwd: ".", mcpUrl: "http://127.0.0.1:8765/mcp" });
    const config = JSON.parse(args[args.indexOf("--mcp-config") + 1] ?? "{}");
    expect(Object.keys(config.mcpServers)).toEqual(["repository-map"]);
  });

  it("never lets either side write to the repository", () => {
    for (const side of ["base", "argus"] as const) {
      const args = buildAgentArgs({ side, question: "Q", cwd: ".", mcpUrl: "http://127.0.0.1:8765/mcp" });
      const denied = args[args.indexOf("--disallowedTools") + 1] ?? "";
      expect(denied).toContain("Write");
      expect(denied).toContain("Edit");
    }
  });

  it("refuses an MCP URL that is not the loopback Argus endpoint", () => {
    expect(() => buildAgentArgs({ side: "argus", question: "Q", cwd: ".", mcpUrl: "https://example.com/mcp" }))
      .toThrow(/loopback/);
  });
});

describe("credential boundary", () => {
  it("strips every HydraDB variable before the agent starts", () => {
    process.env.HYDRA_DB_API_KEY = "secret-value";
    process.env.HYDRA_DB_DATABASE = "secret-database";
    try {
      const environment = agentEnvironment();
      expect(Object.keys(environment).some((key) => key.toUpperCase().startsWith("HYDRA_DB_"))).toBe(false);
    } finally {
      delete process.env.HYDRA_DB_API_KEY;
      delete process.env.HYDRA_DB_DATABASE;
    }
  });
});
