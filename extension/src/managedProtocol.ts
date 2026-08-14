import { createHmac, randomBytes } from "node:crypto";
import * as path from "node:path";
import type { AcquiredCredentials } from "./credentials.js";
import type { RepositoryScope } from "./workspaceScope.js";

export const MANAGED_IPC_PROTOCOL = "hack-hydra.managed-ipc.v1";
export const MANAGED_SERVICE_PROTOCOL = "hack-hydra.managed-service.v1";
export const MAX_IPC_LINE = 32_768;

export interface ServiceHello {
  protocol: typeof MANAGED_IPC_PROTOCOL;
  type: "service_hello";
  pid: number;
}

export interface ServiceReady {
  protocol: typeof MANAGED_IPC_PROTOCOL;
  type: "service_ready";
  port: number;
  repository_id: string;
}

export interface CredentialRequest {
  protocol: typeof MANAGED_IPC_PROTOCOL;
  type: "credential_request" | "credential_status";
  request_id: string;
  repository_id: string;
}

export type ManagedServiceMessage = ServiceHello | ServiceReady | CredentialRequest;

export interface ProjectAttachment {
  repository_root: string;
  repository_id: string;
  timestamp: number;
  nonce: string;
  signature: string;
}

export function parseManagedServiceLine(line: string): ManagedServiceMessage {
  if (Buffer.byteLength(line, "utf8") > MAX_IPC_LINE) throw new Error("Managed service message is too large.");
  let parsed: unknown;
  try {
    parsed = JSON.parse(line);
  } catch {
    throw new Error("Managed service returned invalid JSON.");
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Managed service returned an invalid message.");
  }
  const value = parsed as Record<string, unknown>;
  if (value.protocol !== MANAGED_IPC_PROTOCOL || typeof value.type !== "string") {
    throw new Error("Managed service protocol does not match this extension.");
  }
  if (value.type === "service_hello" && Number.isSafeInteger(value.pid) && Number(value.pid) > 0) {
    return value as unknown as ServiceHello;
  }
  if (value.type === "service_ready" && validPort(value.port) && typeof value.repository_id === "string") {
    return value as unknown as ServiceReady;
  }
  if ((value.type === "credential_request" || value.type === "credential_status")
    && validRequestId(value.request_id) && typeof value.repository_id === "string") {
    return value as unknown as CredentialRequest;
  }
  throw new Error("Managed service returned an unsupported message.");
}

export function serviceStartMessage(
  scope: RepositoryScope,
  controlKey: string,
  options: { apiUrl?: string; collection?: string; evolutionCollection?: string } = {}
): string {
  return frame({
    protocol: MANAGED_IPC_PROTOCOL,
    type: "service_start",
    repository_root: scope.repositoryRoot,
    repository_id: scope.repositoryId,
    control_key: controlKey,
    api_url: options.apiUrl ?? "https://api.hydradb.com/v2",
    collection: options.collection ?? "current",
    evolution_collection: options.evolutionCollection ?? "evolution"
  });
}

export function credentialResponse(
  request: CredentialRequest,
  credentials?: AcquiredCredentials,
  configured?: boolean
): string {
  if (request.type === "credential_status") {
    return frame({
      protocol: MANAGED_IPC_PROTOCOL,
      type: "response",
      request_id: request.request_id,
      ok: true,
      configured: configured === true
    });
  }
  return credentials
    ? frame({
      protocol: MANAGED_IPC_PROTOCOL,
      type: "response",
      request_id: request.request_id,
      ok: true,
      api_key: credentials.apiKey,
      database: credentials.database
    })
    : credentialErrorResponse(request);
}

export function credentialErrorResponse(request: CredentialRequest): string {
  return frame({
    protocol: MANAGED_IPC_PROTOCOL,
    type: "response",
    request_id: request.request_id,
    ok: false
  });
}

export function createProjectAttachment(
  controlKey: string,
  scope: RepositoryScope,
  timestamp = Math.floor(Date.now() / 1_000),
  nonce = randomBytes(24).toString("base64url")
): ProjectAttachment {
  if (controlKey.length < 32) throw new Error("Installation control key is invalid.");
  const canonicalRoot = canonicalChallengeRoot(scope.repositoryRoot);
  const message = [MANAGED_SERVICE_PROTOCOL, timestamp, nonce, canonicalRoot, scope.repositoryId].join("\n");
  return {
    repository_root: scope.repositoryRoot,
    repository_id: scope.repositoryId,
    timestamp,
    nonce,
    signature: createHmac("sha256", controlKey).update(message).digest("base64url")
  };
}

export function canonicalChallengeRoot(value: string): string {
  let canonical = path.resolve(value).replace(/\\/g, "/").replace(/\/+$/, "") || "/";
  if (process.platform === "win32") canonical = canonical.toLowerCase();
  return canonical;
}

function frame(payload: Record<string, unknown>): string {
  const value = `${JSON.stringify(payload)}\n`;
  if (Buffer.byteLength(value, "utf8") > MAX_IPC_LINE) throw new Error("Managed IPC message is too large.");
  return value;
}

function validPort(value: unknown): boolean {
  return Number.isInteger(value) && Number(value) >= 1 && Number(value) <= 65_535;
}

function validRequestId(value: unknown): boolean {
  return typeof value === "string" && /^[0-9a-f]{32}$/i.test(value);
}
