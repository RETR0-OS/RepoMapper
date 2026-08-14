import { createHash, randomUUID } from "node:crypto";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { promises as fs } from "node:fs";
import type { FileHandle } from "node:fs/promises";
import * as net from "node:net";
import * as path from "node:path";
import * as vscode from "vscode";
import { CredentialVault } from "./credentials.js";
import {
  createProjectAttachment,
  credentialErrorResponse,
  credentialResponse,
  managedErrorResponse,
  managedResponse,
  MANAGED_SERVICE_PROTOCOL,
  parseManagedServiceLine,
  serviceStartMessage,
  type CredentialRequest,
  type ManagedServiceMessage
} from "./managedProtocol.js";
import type { ResolvedProject } from "./projectIdentity.js";
import { RepositoryServiceClient } from "./serviceClient.js";

const PORT_STATE_KEY = "hydra.runtime.port.v1";
const DEFAULT_PORT = 8_765;
const START_TIMEOUT_MS = 15_000;
const ATTACH_TIMEOUT_MS = 2_000;

interface ManagedSession {
  baseUrl: string;
  accessToken: string;
  expiresAt: number;
}

interface RuntimeManifest {
  protocol: string;
  targets: Record<string, { path: string; sha256: string }>;
}

export class ManagedRuntime implements vscode.Disposable, vscode.UriHandler {
  private session: ManagedSession | undefined;
  private child: ChildProcessWithoutNullStreams | undefined;
  private ownerHandle: FileHandle | undefined;
  private ownerLockPath: string | undefined;
  private starting: Promise<ManagedSession> | undefined;
  private disposed = false;
  private stdoutBuffer = "";
  private readonly pendingConsents = new Map<string, {
    message: Extract<ManagedServiceMessage, { type: "oauth_consent" }>;
    resolve: (repositoryId?: string) => void;
    timer: NodeJS.Timeout;
  }>();
  private readonly output = vscode.window.createOutputChannel("Repository Map Service", { log: true });

  public constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly vault: CredentialVault,
    private readonly project: ResolvedProject
  ) {}

  public client(timeoutMs: number): RepositoryServiceClient {
    const developerUrl = this.developerServiceUrl();
    if (developerUrl) {
      return new RepositoryServiceClient({
        baseUrl: developerUrl,
        repositoryScope: this.project,
        timeoutMs
      });
    }
    return new RepositoryServiceClient({
      baseUrl: `http://127.0.0.1:${this.preferredPort()}`,
      baseUrlProvider: async () => (await this.ensureReady()).baseUrl,
      authorizationProvider: async () => `Bearer ${(await this.ensureReady()).accessToken}`,
      sessionInvalidator: () => {
        this.session = undefined;
      },
      timeoutMs
    });
  }

  public async mcpUrl(): Promise<string> {
    if (this.developerServiceUrl()) {
      throw new Error("Automatic agent setup is unavailable in developer service mode.");
    }
    return `${(await this.ensureReady()).baseUrl}/mcp`;
  }

  public async handleUri(uri: vscode.Uri): Promise<void> {
    if (uri.authority !== "hack-hydra.hydra-repository-observability" || uri.path !== "/oauth-consent") return;
    const requestId = new URLSearchParams(uri.query).get("request");
    if (!requestId || !/^[0-9a-f-]{36}$/i.test(requestId)) return;
    const pending = this.pendingConsents.get(requestId);
    if (!pending) return;
    this.pendingConsents.delete(requestId);
    clearTimeout(pending.timer);
    const message = pending.message;
    const selected = message.projects.length === 1
      ? message.projects[0]
      : await vscode.window.showQuickPick(
        message.projects.map((project) => ({
          label: project.project_name,
          description: project.repository_id,
          detail: `Canonical root fingerprint ${project.root_fingerprint.slice(0, 16)}…`,
          project
        })),
        {
          title: `${message.client_name} Repository Map access`,
          placeHolder: "Select the project this agent may read",
          ignoreFocusOut: true
        }
      ).then((item) => item?.project);
    if (!selected) {
      pending.resolve(undefined);
      return;
    }
    const approved = await vscode.window.showInformationMessage(
      `${message.client_name} wants read-only Repository Map access to ${selected.project_name}.`,
      {
        modal: true,
        detail: `Requested scopes: ${message.scopes.join(", ")}. This does not reveal HydraDB credentials or allow indexing writes.`
      },
      "Allow read-only access"
    ) === "Allow read-only access";
    pending.resolve(approved ? selected.repository_id : undefined);
  }

  public async ensureReady(): Promise<ManagedSession> {
    if (this.disposed) throw new Error("Repository Map service runtime is closed.");
    const now = Math.floor(Date.now() / 1_000);
    if (this.session && this.session.expiresAt > now + 30) return this.session;
    if (!this.starting) {
      this.starting = this.connectOrStart().finally(() => {
        this.starting = undefined;
      });
    }
    this.session = await this.starting;
    return this.session;
  }

  public dispose(): void {
    this.disposed = true;
    this.session = undefined;
    if (this.child && !this.child.killed) {
      this.child.kill();
    }
    this.child = undefined;
    for (const pending of this.pendingConsents.values()) {
      clearTimeout(pending.timer);
      pending.resolve(undefined);
    }
    this.pendingConsents.clear();
    void this.releaseOwnerLock();
    this.output.dispose();
  }

  private async connectOrStart(): Promise<ManagedSession> {
    const secrets = await this.vault.installationSecrets();
    const preferred = this.preferredPort();
    const attached = await this.tryAttach(preferred, secrets.control_key);
    if (attached) return attached;

    const ownsLock = await this.acquireOwnerLock(preferred);
    if (!ownsLock) {
      for (let attempt = 0; attempt < 20; attempt += 1) {
        await delay(250);
        const candidate = await this.tryAttach(this.preferredPort(), secrets.control_key);
        if (candidate) return candidate;
      }
      if (!await this.acquireOwnerLock(preferred, true)) {
        throw new Error("Another VS Code window owns the Repository Map service but it did not become ready.");
      }
    }

    const port = await this.choosePort(preferred, secrets.control_key);
    await this.context.globalState.update(PORT_STATE_KEY, port);
    await this.writeOwnerRecord(port);
    await this.startOwnedService(port, secrets.control_key);
    const session = await this.tryAttach(port, secrets.control_key);
    if (!session) throw new Error("Managed Repository Map service started but authentication failed.");
    return session;
  }

  private async tryAttach(port: number, controlKey: string): Promise<ManagedSession | undefined> {
    const baseUrl = `http://127.0.0.1:${port}`;
    try {
      const version = await fetchJson(`${baseUrl}/version`, { method: "GET" }, ATTACH_TIMEOUT_MS);
      if (version.protocol !== MANAGED_SERVICE_PROTOCOL || version.service !== "repository-map") return undefined;
      const attachment = createProjectAttachment(controlKey, this.project);
      const result = await fetchJson(`${baseUrl}/managed/challenge`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(attachment)
      }, ATTACH_TIMEOUT_MS);
      const expiresAt = result.expires_at;
      if (result.protocol !== MANAGED_SERVICE_PROTOCOL
        || typeof result.access_token !== "string"
        || !/^[A-Za-z0-9_-]{40,128}$/.test(result.access_token)
        || typeof expiresAt !== "number"
        || !Number.isSafeInteger(expiresAt)
        || expiresAt <= Math.floor(Date.now() / 1_000)) return undefined;
      return { baseUrl, accessToken: result.access_token, expiresAt };
    } catch {
      return undefined;
    }
  }

  private async startOwnedService(port: number, controlKey: string): Promise<void> {
    const command = await this.resolveServiceCommand(port);
    const environment = managedEnvironment(command.environment);
    const child = spawn(command.executable, command.args, {
      cwd: command.cwd,
      env: environment,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true
    });
    this.child = child;
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk: string) => this.output.append(chunk.replace(/[^\r\n\t\x20-\x7e]/g, "")));
    child.on("exit", (code) => {
      this.session = undefined;
      this.child = undefined;
      this.output.warn(`Managed service stopped${code === null ? "." : ` with code ${code}.`}`);
      void this.releaseOwnerLock();
    });
    child.stdout.on("data", (chunk: string) => {
      this.stdoutBuffer += chunk;
      if (Buffer.byteLength(this.stdoutBuffer, "utf8") > 65_536) {
        child.kill();
        return;
      }
      let newline = this.stdoutBuffer.indexOf("\n");
      while (newline >= 0) {
        const line = this.stdoutBuffer.slice(0, newline).trim();
        this.stdoutBuffer = this.stdoutBuffer.slice(newline + 1);
        if (line) void this.handleServiceLine(line, controlKey);
        newline = this.stdoutBuffer.indexOf("\n");
      }
    });

    await waitFor(async () => {
      if (child.exitCode !== null) throw new Error("Managed service exited during startup.");
      return await this.probeVersion(port);
    }, START_TIMEOUT_MS);
  }

  private async handleServiceLine(line: string, controlKey: string): Promise<void> {
    let message: ManagedServiceMessage;
    try {
      message = parseManagedServiceLine(line);
    } catch (error) {
      this.output.error(error instanceof Error ? error.message : "Managed service IPC failed.");
      this.child?.kill();
      return;
    }
    if (message.type === "service_hello") {
      this.writeToService(serviceStartMessage(this.project, controlKey));
      return;
    }
    if (message.type === "credential_request" || message.type === "credential_status") {
      await this.handleCredentialRequest(message);
      return;
    }
    if (message.type === "oauth_get" || message.type === "oauth_put" || message.type === "oauth_delete") {
      try {
        if (message.type === "oauth_get") {
          const value = await this.vault.readOAuthRecord(message.key);
          this.writeToService(managedResponse(message.request_id, { value: value ?? null }));
        } else if (message.type === "oauth_put" && message.value !== undefined) {
          await this.vault.writeOAuthRecord(message.key, message.value);
          this.writeToService(managedResponse(message.request_id));
        } else {
          await this.vault.deleteOAuthRecord(message.key);
          this.writeToService(managedResponse(message.request_id));
        }
      } catch {
        this.writeToService(managedErrorResponse(message.request_id));
      }
      return;
    }
    if (message.type === "oauth_consent") {
      const repositoryId = await this.requestOAuthConsent(message);
      this.writeToService(managedResponse(message.request_id, {
        approved: repositoryId !== undefined,
        ...(repositoryId ? { repository_id: repositoryId } : {})
      }));
    }
  }

  private async requestOAuthConsent(
    message: Extract<ManagedServiceMessage, { type: "oauth_consent" }>
  ): Promise<string | undefined> {
    const requestId = randomUUID();
    return await new Promise<string | undefined>((resolve) => {
      const timer = setTimeout(() => {
        this.pendingConsents.delete(requestId);
        resolve(undefined);
      }, 120_000);
      this.pendingConsents.set(requestId, { message, resolve, timer });
      const uri = vscode.Uri.parse(
        `${vscode.env.uriScheme}://hack-hydra.hydra-repository-observability/oauth-consent?request=${requestId}`
      );
      void vscode.env.openExternal(uri).then((opened) => {
        if (opened) return;
        clearTimeout(timer);
        this.pendingConsents.delete(requestId);
        resolve(undefined);
      }, () => {
        clearTimeout(timer);
        this.pendingConsents.delete(requestId);
        resolve(undefined);
      });
    });
  }

  private async handleCredentialRequest(request: CredentialRequest): Promise<void> {
    if (request.type === "credential_status") {
      this.writeToService(credentialResponse(request, undefined, this.vault.hasProjectBinding(request.repository_id)));
      return;
    }
    try {
      const credentials = await this.vault.acquire(request.repository_id);
      this.writeToService(credentialResponse(request, credentials));
    } catch {
      this.writeToService(credentialErrorResponse(request));
    }
  }

  private writeToService(frame: string): void {
    if (!this.child?.stdin.writable) throw new Error("Managed service IPC channel is closed.");
    this.child.stdin.write(frame, "utf8");
  }

  private async probeVersion(port: number): Promise<boolean> {
    try {
      const response = await fetchJson(`http://127.0.0.1:${port}/version`, { method: "GET" }, 500);
      return response.protocol === MANAGED_SERVICE_PROTOCOL;
    } catch {
      return false;
    }
  }

  private preferredPort(): number {
    const stored = this.context.globalState.get<unknown>(PORT_STATE_KEY);
    return Number.isInteger(stored) && Number(stored) >= 1_024 && Number(stored) <= 65_535
      ? Number(stored)
      : DEFAULT_PORT;
  }

  private async choosePort(preferred: number, controlKey: string): Promise<number> {
    if (await portIsFree(preferred)) return preferred;
    const stableStart = 12_000 + (Number.parseInt(createHash("sha256").update(controlKey).digest("hex").slice(0, 6), 16) % 1_000);
    for (let offset = 0; offset < 64; offset += 1) {
      const candidate = stableStart + offset;
      if (await portIsFree(candidate)) return candidate;
    }
    throw new Error("Repository Map could not find an available loopback port.");
  }

  private async acquireOwnerLock(preferredPort: number, replaceStale = false): Promise<boolean> {
    const directory = this.context.globalStorageUri.fsPath;
    await fs.mkdir(directory, { recursive: true });
    const target = path.join(directory, "managed-service-owner.json");
    if (replaceStale) {
      const record = await readOwnerRecord(target);
      if (record && processIsAlive(record.pid)) return false;
      await fs.rm(target, { force: true });
    }
    try {
      const handle = await fs.open(target, "wx", 0o600);
      this.ownerHandle = handle;
      this.ownerLockPath = target;
      await handle.writeFile(JSON.stringify({ pid: process.pid, port: preferredPort }), "utf8");
      return true;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "EEXIST") return false;
      throw error;
    }
  }

  private async writeOwnerRecord(port: number): Promise<void> {
    if (!this.ownerHandle) return;
    const record = JSON.stringify({ pid: process.pid, port });
    await this.ownerHandle.write(record, 0, "utf8");
    await this.ownerHandle.truncate(Buffer.byteLength(record, "utf8"));
  }

  private async releaseOwnerLock(): Promise<void> {
    const handle = this.ownerHandle;
    const target = this.ownerLockPath;
    this.ownerHandle = undefined;
    this.ownerLockPath = undefined;
    await handle?.close().catch(() => undefined);
    if (target) await fs.rm(target, { force: true }).catch(() => undefined);
  }

  private async resolveServiceCommand(port: number): Promise<{
    executable: string;
    args: string[];
    cwd: string;
    environment?: NodeJS.ProcessEnv;
  }> {
    const manifestPath = this.context.asAbsolutePath(path.join("resources", "service", "manifest.json"));
    try {
      const manifest = JSON.parse(await fs.readFile(manifestPath, "utf8")) as RuntimeManifest;
      const target = manifest.targets?.[`${process.platform}-${process.arch}`];
      if (manifest.protocol !== MANAGED_SERVICE_PROTOCOL || !target) throw new Error("unsupported target");
      const executable = this.context.asAbsolutePath(target.path);
      const digest = createHash("sha256").update(await fs.readFile(executable)).digest("hex");
      if (!/^[a-f0-9]{64}$/.test(target.sha256) || digest !== target.sha256) {
        throw new Error("Bundled service integrity check failed.");
      }
      return { executable, args: ["serve", "--managed", "--port", String(port)], cwd: path.dirname(executable) };
    } catch (error) {
      if (this.context.extensionMode !== vscode.ExtensionMode.Development) {
        throw new Error(`Bundled Repository Map service is unavailable. ${error instanceof Error ? error.message : ""}`.trim());
      }
      const repositoryRoot = path.resolve(this.context.extensionPath, "..");
      return {
        executable: process.platform === "win32" ? "python" : "python3",
        args: ["-m", "hydra_graph", "serve", "--managed", "--port", String(port)],
        cwd: repositoryRoot,
        environment: { PYTHONPATH: path.join(repositoryRoot, "service") }
      };
    }
  }

  private developerServiceUrl(): string | undefined {
    const configuration = vscode.workspace.getConfiguration("hydra");
    if (!configuration.get<boolean>("developerMode", false)) return undefined;
    return configuration.get<string>("developerServiceUrl", "http://127.0.0.1:8765");
  }
}

export function managedEnvironment(overrides: NodeJS.ProcessEnv = {}): NodeJS.ProcessEnv {
  const environment = { ...process.env, ...overrides };
  for (const key of Object.keys(environment)) {
    if (key.toUpperCase().startsWith("HYDRA_DB_")) delete environment[key];
  }
  return environment;
}

async function fetchJson(url: string, init: RequestInit, timeoutMs: number): Promise<Record<string, unknown>> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { ...init, signal: controller.signal });
    if (!response.ok) throw new Error(`Service returned ${response.status}.`);
    const value = await response.json() as unknown;
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Service returned invalid JSON.");
    return value as Record<string, unknown>;
  } finally {
    clearTimeout(timeout);
  }
}

async function portIsFree(port: number): Promise<boolean> {
  return await new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.listen(port, "127.0.0.1", () => server.close(() => resolve(true)));
  });
}

async function waitFor(probe: () => Promise<boolean>, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await probe()) return;
    await delay(100);
  }
  throw new Error("Managed Repository Map service did not become ready in time.");
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function readOwnerRecord(target: string): Promise<{ pid: number; port: number } | undefined> {
  try {
    const value = JSON.parse(await fs.readFile(target, "utf8")) as Record<string, unknown>;
    return Number.isSafeInteger(value.pid) && Number.isSafeInteger(value.port)
      ? { pid: Number(value.pid), port: Number(value.port) }
      : undefined;
  } catch {
    return undefined;
  }
}

function processIsAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}
