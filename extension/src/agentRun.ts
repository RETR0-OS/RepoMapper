import { spawn, type ChildProcess } from "node:child_process";
import { agentEnvironment, requireManagedMcpUrl } from "./agentSetup.js";
import type { AgentRunTrace, AgentUsage, ContrastSide } from "./types.js";

/**
 * Runs one coding agent twice over the same question: once with only its own
 * built-in tools, and once with only the Argus MCP endpoint. The agent reports
 * its own token usage, so the comparison is measured rather than estimated.
 *
 * Parsing is kept separate from spawning so the stream shape can be tested
 * against a recorded transcript without starting a process.
 */

// A single stream line is JSON for one event. A transcript that exceeds these
// bounds is a runaway, not a run, and is stopped instead of being buffered.
const MAX_LINE_BYTES = 1_000_000;
const MAX_EVENTS = 20_000;
const MAX_TOOL_CALLS = 500;
const MAX_DETAIL_CHARS = 120;
const MAX_ANSWER_CHARS = 4_000;

const DENIED_ON_BOTH_SIDES = ["Write", "Edit", "NotebookEdit"];

export function emptyTrace(side: ContrastSide): AgentRunTrace {
  return { side, status: "starting", toolsAvailable: [], mcpServers: [], toolCalls: [], filesRead: [], turns: 0 };
}

/**
 * Splits a `--output-format stream-json` byte stream into events. Chunk
 * boundaries fall anywhere, so a partial trailing line is held until the rest
 * of it arrives.
 */
export class StreamJsonParser {
  private buffer = "";
  private events = 0;
  private overflowed = false;

  push(chunk: string): unknown[] {
    if (this.overflowed) return [];
    this.buffer += chunk;
    if (this.buffer.length > MAX_LINE_BYTES) {
      this.overflowed = true;
      this.buffer = "";
      return [];
    }
    const lines = this.buffer.split("\n");
    this.buffer = lines.pop() ?? "";
    const parsed: unknown[] = [];
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      if (this.events >= MAX_EVENTS) {
        this.overflowed = true;
        break;
      }
      this.events += 1;
      try {
        parsed.push(JSON.parse(trimmed));
      } catch {
        // A non-JSON line is CLI noise, not an event. Dropping it keeps one
        // stray warning from ending an otherwise good run.
      }
    }
    return parsed;
  }

  get truncated(): boolean {
    return this.overflowed;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function text(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function count(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : 0;
}

function names(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function bounded(value: unknown): string {
  if (typeof value !== "string") return "";
  const printable = Array.from(value, (ch) => ((ch.codePointAt(0) ?? 0) < 32 || ch.codePointAt(0) === 127 ? " " : ch)).join("");
  return printable.replace(/\s+/g, " ").trim().slice(0, MAX_DETAIL_CHARS);
}

/**
 * Names what a tool call was pointed at, without carrying file content. Each
 * tool puts that somewhere different, so the fields are tried in order.
 */
function toolDetail(input: unknown): string {
  if (!isRecord(input)) return "";
  for (const key of ["file_path", "pattern", "question", "symbol", "query", "command", "path"]) {
    const found = bounded(input[key]);
    if (found) return found;
  }
  return "";
}

function readUsage(value: unknown): AgentUsage | undefined {
  if (!isRecord(value)) return undefined;
  const details = isRecord(value.output_tokens_details) ? value.output_tokens_details : {};
  return {
    inputTokens: count(value.input_tokens),
    outputTokens: count(value.output_tokens),
    cacheReadTokens: count(value.cache_read_input_tokens),
    cacheCreationTokens: count(value.cache_creation_input_tokens),
    thinkingTokens: count(details.thinking_tokens)
  };
}

/**
 * Folds one stream event into the running trace. Returns a new trace, so the
 * webview can be posted an immutable snapshot on every update.
 */
export function applyStreamEvent(trace: AgentRunTrace, event: unknown): AgentRunTrace {
  if (!isRecord(event)) return trace;
  const next: AgentRunTrace = {
    ...trace,
    toolsAvailable: [...trace.toolsAvailable],
    mcpServers: [...trace.mcpServers],
    toolCalls: [...trace.toolCalls],
    filesRead: [...trace.filesRead]
  };

  if (event.type === "system" && event.subtype === "init") {
    next.status = "running";
    next.model = text(event.model) ?? next.model;
    next.toolsAvailable = names(event.tools);
    next.mcpServers = Array.isArray(event.mcp_servers)
      ? event.mcp_servers.map((server) => (isRecord(server) ? text(server.name) ?? "" : "")).filter(Boolean)
      : [];
    return next;
  }

  if (event.type === "assistant" && isRecord(event.message)) {
    next.status = "running";
    const content = Array.isArray(event.message.content) ? event.message.content : [];
    for (const block of content) {
      if (!isRecord(block) || block.type !== "tool_use") continue;
      const name = text(block.name);
      if (!name || next.toolCalls.length >= MAX_TOOL_CALLS) continue;
      const detail = toolDetail(block.input);
      next.toolCalls.push({ name, detail });
      if (name === "Read" && detail && !next.filesRead.includes(detail)) next.filesRead.push(detail);
    }
    return next;
  }

  if (event.type === "result") {
    next.status = event.is_error === true ? "failed" : "completed";
    next.turns = count(event.num_turns);
    next.usage = readUsage(event.usage) ?? next.usage;
    next.costUsd = typeof event.total_cost_usd === "number" ? event.total_cost_usd : next.costUsd;
    next.durationMs = count(event.duration_ms) || next.durationMs;
    const answer = text(event.result);
    if (answer) next.answer = answer.slice(0, MAX_ANSWER_CHARS);
    if (next.status === "failed") next.error = text(event.subtype) ?? "The agent reported an error.";
    return next;
  }

  return next;
}

export interface AgentRunOptions {
  side: ContrastSide;
  question: string;
  cwd: string;
  /** The loopback `/mcp` endpoint. Required for the Argus side only. */
  mcpUrl?: string;
  model?: string;
  timeoutMs?: number;
}

/**
 * Builds the exact argument list. Kept pure so a test can assert what is sent
 * without spawning anything.
 */
export function buildAgentArgs(options: AgentRunOptions): string[] {
  // The name must match the "repository-map" name used by the one-time OAuth
  // registration in agentSetup.ts (`claude mcp add ... repository-map <url>`).
  // The CLI caches its OAuth login by server name; a run cannot complete a
  // fresh login on its own, so a name it has not logged in under is dropped
  // with no error, leaving this side with no Argus tools at all.
  const servers = options.side === "argus"
    ? { "repository-map": { type: "http", url: requireManagedMcpUrl(options.mcpUrl ?? "") } }
    : {};
  // Both sides keep every tool the harness normally gives them. The Argus side
  // differs by addition only: it also has the Argus tools. Taking the agent's
  // own search tools away would measure a crippled harness, not an augmented
  // one. Writes stay denied on both sides so neither run can change the repo.
  const denied = [...DENIED_ON_BOTH_SIDES];
  const args = [
    "-p", options.question,
    "--output-format", "stream-json",
    "--verbose",
    "--strict-mcp-config",
    "--mcp-config", JSON.stringify({ mcpServers: servers }),
    // "dontAsk" denies every MCP tool outright, which leaves the Argus side
    // unable to call the very tools being measured. "auto" runs the same
    // read-only tools without a prompt no headless run could answer.
    "--permission-mode", "auto",
    "--disallowedTools", denied.join(" ")
  ];
  if (options.model) args.push("--model", options.model);
  return args;
}

export interface AgentRunHandle {
  /** Resolves with the final trace. It never rejects; failure is a status. */
  completed: Promise<AgentRunTrace>;
  cancel(): void;
}

/**
 * Starts one side of a contrast. `onUpdate` fires on every stream event so the
 * panel can show the run as it happens.
 */
export function startAgentRun(
  options: AgentRunOptions,
  onUpdate: (trace: AgentRunTrace) => void,
  spawnImpl: typeof spawn = spawn
): AgentRunHandle {
  let trace = emptyTrace(options.side);
  const parser = new StreamJsonParser();
  let child: ChildProcess | undefined;
  let cancelled = false;
  let settled = false;
  let requestCancel = (): void => {
    // Cancelling before the child exists still has to stop the run, so the
    // flag is set now and the close handler reports it.
    cancelled = true;
  };

  const publish = (): void => onUpdate(trace);

  const completed = new Promise<AgentRunTrace>((resolve) => {
    const settle = (final: AgentRunTrace): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      trace = final;
      publish();
      resolve(final);
    };

    const timer = setTimeout(() => {
      kill();
      settle({ ...trace, status: "failed", error: "The agent run passed its time limit and was stopped." });
    }, options.timeoutMs ?? 180_000);

    const kill = (): void => {
      // A killed shell can leave the agent running, so the whole tree goes.
      if (child?.pid === undefined) return;
      try {
        if (process.platform === "win32") {
          spawnImpl("taskkill", ["/pid", String(child.pid), "/t", "/f"], { windowsHide: true });
        } else {
          process.kill(-child.pid, "SIGKILL");
        }
      } catch {
        child.kill("SIGKILL");
      }
    };

    try {
      child = spawnImpl("claude", buildAgentArgs(options), {
        cwd: options.cwd,
        windowsHide: true,
        env: agentEnvironment(),
        detached: process.platform !== "win32"
      });
    } catch {
      settle({ ...trace, status: "failed", error: "Claude Code could not be started." });
      return;
    }

    child.stdin?.end();
    child.stdout?.setEncoding("utf8");
    child.stdout?.on("data", (chunk: string) => {
      for (const event of parser.push(chunk)) {
        trace = applyStreamEvent(trace, event);
      }
      if (parser.truncated) {
        kill();
        settle({ ...trace, status: "failed", error: "The agent produced more output than the panel accepts." });
        return;
      }
      publish();
    });

    child.on("error", () => {
      settle({ ...trace, status: "failed", error: "Claude Code could not be started." });
    });

    child.on("close", (code) => {
      if (cancelled) {
        settle({ ...trace, status: "cancelled" });
        return;
      }
      if (trace.status === "completed" || trace.status === "failed") {
        settle(trace);
        return;
      }
      settle({ ...trace, status: "failed", error: `Claude Code exited with code ${code ?? "unknown"}.` });
    });

    requestCancel = (): void => {
      cancelled = true;
      kill();
    };
  });

  return { completed, cancel: () => requestCancel() };
}
