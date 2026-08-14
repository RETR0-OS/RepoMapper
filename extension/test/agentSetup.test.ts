import { describe, expect, it, vi } from "vitest";
import {
  agentRegistrations,
  detectAgentRegistrations,
  formatRegistration,
  registerAgent,
  type CommandRunner
} from "../src/agentSetup.js";

const url = "http://127.0.0.1:8765/mcp";

describe("agent MCP setup", () => {
  it("builds supported URL-only registration commands", () => {
    const [codex, claude] = agentRegistrations(url);
    expect(codex?.arguments).toEqual(["mcp", "add", "repository-map", "--url", url]);
    expect(claude?.arguments).toEqual([
      "mcp", "add", "--transport", "http", "--scope", "local", "repository-map", url
    ]);
    expect(formatRegistration(codex!)).toBe(`codex mcp add repository-map --url ${url}`);
    expect(JSON.stringify([codex, claude])).not.toMatch(/api.?key|database|bearer|token/i);
  });

  it("rejects remote, credentialed, and ambiguous MCP URLs", () => {
    for (const candidate of [
      "https://127.0.0.1:8765/mcp",
      "http://localhost:8765/mcp",
      "http://user:secret@127.0.0.1:8765/mcp",
      "http://127.0.0.1:8765/mcp?project=x",
      "http://127.0.0.1:8765/"
    ]) {
      expect(() => agentRegistrations(candidate)).toThrow(/loopback/i);
    }
  });

  it("detects clients without modifying their configuration", async () => {
    const runner = vi.fn<CommandRunner>(async (executable) => ({
      exitCode: executable === "codex" ? 0 : 1,
      output: ""
    }));
    const result = await detectAgentRegistrations(agentRegistrations(url), "C:\\work", runner);
    expect(result.map((item) => item.kind)).toEqual(["codex"]);
    expect(runner).toHaveBeenCalledTimes(2);
    expect(runner.mock.calls.every((call) => call[1][0] === "--version")).toBe(true);
  });

  it("uses argument arrays and reports a bounded failure", async () => {
    const registration = agentRegistrations(url)[0]!;
    const runner = vi.fn<CommandRunner>(async () => ({ exitCode: 2, output: `bad\n${"x".repeat(1_000)}` }));
    await expect(registerAgent(registration, "C:\\work", runner)).rejects.toThrow(/rejected.*bad/i);
    expect(runner).toHaveBeenCalledWith(
      "codex",
      ["mcp", "add", "repository-map", "--url", url],
      { cwd: "C:\\work", timeoutMs: 30_000 }
    );
  });
});
