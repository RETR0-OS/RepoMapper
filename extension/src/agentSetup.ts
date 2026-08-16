import { execFile } from "node:child_process";

export type AgentKind = "codex" | "claude";

export interface AgentRegistration {
  kind: AgentKind;
  label: string;
  executable: string;
  arguments: string[];
}

export interface CommandResult {
  exitCode: number;
  output: string;
}

export type CommandRunner = (
  executable: string,
  args: string[],
  options: { cwd: string; timeoutMs: number }
) => Promise<CommandResult>;

export function agentRegistrations(mcpUrl: string): AgentRegistration[] {
  const url = requireManagedMcpUrl(mcpUrl);
  return [
    {
      kind: "codex",
      label: "Codex",
      executable: "codex",
      arguments: ["mcp", "add", "repository-map", "--url", url]
    },
    {
      kind: "claude",
      label: "Claude Code",
      executable: "claude",
      arguments: ["mcp", "add", "--transport", "http", "--scope", "local", "repository-map", url]
    }
  ];
}

export async function detectAgentRegistrations(
  registrations: AgentRegistration[],
  cwd: string,
  runner: CommandRunner = runCommand
): Promise<AgentRegistration[]> {
  const detected: AgentRegistration[] = [];
  for (const registration of registrations) {
    const result = await runner(registration.executable, ["--version"], { cwd, timeoutMs: 5_000 })
      .catch(() => ({ exitCode: -1, output: "" }));
    if (result.exitCode === 0) detected.push(registration);
  }
  return detected;
}

export async function registerAgent(
  registration: AgentRegistration,
  cwd: string,
  runner: CommandRunner = runCommand
): Promise<void> {
  const result = await runner(registration.executable, registration.arguments, { cwd, timeoutMs: 30_000 });
  if (result.exitCode !== 0) {
    throw new Error(`${registration.label} rejected the MCP registration. ${boundedOutput(result.output)}`.trim());
  }
}

export function formatRegistration(registration: AgentRegistration): string {
  return [registration.executable, ...registration.arguments].map(quoteArgument).join(" ");
}

export async function runCommand(
  executable: string,
  args: string[],
  options: { cwd: string; timeoutMs: number }
): Promise<CommandResult> {
  return await new Promise((resolve, reject) => {
    const child = execFile(executable, args, {
      cwd: options.cwd,
      windowsHide: true,
      timeout: options.timeoutMs,
      maxBuffer: 256 * 1_024,
      env: agentEnvironment()
    }, (error, stdout, stderr) => {
      if (error && typeof error.code !== "number") {
        reject(new Error(`Could not run ${executable}.`));
        return;
      }
      resolve({
        exitCode: typeof error?.code === "number" ? error.code : 0,
        output: `${stdout}\n${stderr}`.trim()
      });
    });
    child.stdin?.end();
  });
}

function requireManagedMcpUrl(value: string): string {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("Managed MCP URL is invalid.");
  }
  if (parsed.protocol !== "http:" || parsed.hostname !== "127.0.0.1" || !parsed.port
    || parsed.username || parsed.password || parsed.search || parsed.hash || parsed.pathname !== "/mcp") {
    throw new Error("Managed MCP URL must be the loopback Repository Map endpoint.");
  }
  return parsed.toString().replace(/\/$/, "");
}

function quoteArgument(value: string): string {
  return /^[A-Za-z0-9._:\/-]+$/.test(value) ? value : JSON.stringify(value);
}

function boundedOutput(value: string): string {
  return value.replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim().slice(0, 500);
}

function agentEnvironment(): NodeJS.ProcessEnv {
  const environment = { ...process.env };
  for (const key of Object.keys(environment)) {
    if (key.toUpperCase().startsWith("HYDRA_DB_")) delete environment[key];
  }
  return environment;
}

export async function hasConfiguredAgent(
  mcpUrl: string,
  cwd: string,
  runner: CommandRunner = runCommand
): Promise<boolean> {
  const registrations = agentRegistrations(mcpUrl);
  const detected = await detectAgentRegistrations(registrations, cwd, runner);
  return detected.length > 0;
}

export async function isAgentInstalled(
  cwd: string,
  runner: CommandRunner = runCommand
): Promise<boolean> {
  for (const executable of ["codex", "claude"]) {
    const result = await runner(executable, ["--version"], { cwd, timeoutMs: 5_000 })
      .catch(() => ({ exitCode: -1, output: "" }));
    if (result.exitCode === 0) return true;
  }
  return false;
}
