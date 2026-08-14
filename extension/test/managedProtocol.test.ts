import { createHmac } from "node:crypto";
import { describe, expect, it } from "vitest";
import {
  canonicalChallengeRoot,
  createProjectAttachment,
  credentialErrorResponse,
  credentialResponse,
  MANAGED_IPC_PROTOCOL,
  MANAGED_SERVICE_PROTOCOL,
  parseManagedServiceLine,
  serviceStartMessage
} from "../src/managedProtocol.js";

const scope = {
  repositoryRoot: "C:\\Workspaces\\Example Project",
  repositoryId: "git:example:0123456789abcdefabcd"
};

describe("managed private protocol", () => {
  it("builds a non-secret startup frame and validates service messages", () => {
    const frame = serviceStartMessage(scope, "x".repeat(43));
    const parsed = JSON.parse(frame) as Record<string, unknown>;

    expect(parsed).toMatchObject({
      protocol: MANAGED_IPC_PROTOCOL,
      type: "service_start",
      repository_root: scope.repositoryRoot,
      repository_id: scope.repositoryId,
      control_key: "x".repeat(43)
    });
    expect(frame).not.toContain("api_key");
    expect(frame).not.toContain("database");
    expect(parseManagedServiceLine(JSON.stringify({
      protocol: MANAGED_IPC_PROTOCOL,
      type: "service_hello",
      pid: 42
    })).type).toBe("service_hello");
  });

  it("rejects malformed, oversized, and wrong-version service messages", () => {
    expect(() => parseManagedServiceLine("not-json")).toThrow(/invalid JSON/i);
    expect(() => parseManagedServiceLine(JSON.stringify({ protocol: "old", type: "service_hello", pid: 1 }))).toThrow(/protocol/i);
    expect(() => parseManagedServiceLine("x".repeat(32_769))).toThrow(/too large/i);
  });

  it("accepts only bounded project choices for native OAuth consent", () => {
    const message = {
      protocol: MANAGED_IPC_PROTOCOL,
      type: "oauth_consent",
      request_id: "b".repeat(32),
      client_name: "Codex",
      scopes: ["repository:read"],
      projects: [{
        repository_id: scope.repositoryId,
        project_name: "Example Project",
        root_fingerprint: "c".repeat(64)
      }]
    };
    expect(parseManagedServiceLine(JSON.stringify(message))).toEqual(message);
    expect(() => parseManagedServiceLine(JSON.stringify({
      ...message,
      projects: [{ ...message.projects[0], repository_id: "../outside" }]
    }))).toThrow(/unsupported/i);
  });

  it("returns credentials only for the matching private request", () => {
    const request = parseManagedServiceLine(JSON.stringify({
      protocol: MANAGED_IPC_PROTOCOL,
      type: "credential_request",
      request_id: "a".repeat(32),
      repository_id: scope.repositoryId
    }));
    if (request.type !== "credential_request") throw new Error("wrong test message");

    expect(JSON.parse(credentialResponse(request, {
      apiKey: "secret-key",
      database: "secret-db",
      profileId: "00000000-0000-4000-8000-000000000000"
    }))).toEqual({
      protocol: MANAGED_IPC_PROTOCOL,
      type: "response",
      request_id: "a".repeat(32),
      ok: true,
      api_key: "secret-key",
      database: "secret-db"
    });
    expect(JSON.parse(credentialErrorResponse(request))).not.toHaveProperty("error");
  });

  it("signs the canonical project attachment without exposing the control key", () => {
    const controlKey = "installation-control-key-that-stays-secret";
    const attachment = createProjectAttachment(controlKey, scope, 1_800_000_000, "0123456789abcdef0123456789abcdef");
    const message = [
      MANAGED_SERVICE_PROTOCOL,
      attachment.timestamp,
      attachment.nonce,
      canonicalChallengeRoot(scope.repositoryRoot),
      scope.repositoryId
    ].join("\n");

    expect(attachment.signature).toBe(createHmac("sha256", controlKey).update(message).digest("base64url"));
    expect(JSON.stringify(attachment)).not.toContain(controlKey);
  });
});
