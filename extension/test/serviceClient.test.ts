import { describe, expect, it, vi } from "vitest";
import { RepositoryServiceClient, ServiceError } from "../src/serviceClient.js";

describe("managed service client", () => {
  it("retrieves a fresh project token and base URL for every request", async () => {
    const fetchMock = vi.fn(async (_input: string | URL | Request, _init?: RequestInit) => ({
      ok: true,
      status: 200,
      json: async () => ({
        state: "unverified",
        revision_id: "current",
        revision_verified: false,
        credentials_configured: true,
        collection: "current"
      })
    } as Response));
    const authorizationProvider = vi.fn()
      .mockResolvedValueOnce("Bearer token-one")
      .mockResolvedValueOnce("Bearer token-two");
    const baseUrlProvider = vi.fn()
      .mockResolvedValueOnce("http://127.0.0.1:12001")
      .mockResolvedValueOnce("http://127.0.0.1:12002");
    const client = new RepositoryServiceClient({
      baseUrl: "http://127.0.0.1:8765",
      baseUrlProvider,
      authorizationProvider,
      timeoutMs: 1_000,
      fetchImpl: fetchMock as typeof fetch
    });

    await client.health();
    await client.health();

    expect(authorizationProvider).toHaveBeenCalledTimes(2);
    expect(baseUrlProvider).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.map((call) => String(call[0]))).toEqual([
      "http://127.0.0.1:12001/health",
      "http://127.0.0.1:12002/health"
    ]);
    expect(new Headers(fetchMock.mock.calls[0]?.[1]?.headers).get("authorization")).toBe("Bearer token-one");
    expect(new Headers(fetchMock.mock.calls[1]?.[1]?.headers).get("authorization")).toBe("Bearer token-two");
    expect(new Headers(fetchMock.mock.calls[0]?.[1]?.headers).has("x-hydra-repository-root")).toBe(false);
  });

  it("keeps the service's own reason in the failure message", async () => {
    const client = new RepositoryServiceClient({
      baseUrl: "http://127.0.0.1:8765",
      timeoutMs: 1_000,
      fetchImpl: vi.fn(async () => ({
        ok: false,
        status: 503,
        text: async () => JSON.stringify({ detail: "HydraDB read access failed." })
      } as Response)) as typeof fetch
    });

    await expect(client.testConnection()).rejects.toThrow(/503\. HydraDB read access failed\./);
  });

  it("invalidates the managed session once and retries exactly once after a 401", async () => {
    const invalidator = vi.fn();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 401, text: async () => "" } as Response)
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ state: "ready", revision_id: "rev-1", revision_verified: true, credentials_configured: true })
      } as Response);
    const authorizationProvider = vi.fn()
      .mockResolvedValueOnce("Bearer stale")
      .mockResolvedValueOnce("Bearer fresh");
    const client = new RepositoryServiceClient({
      baseUrl: "http://127.0.0.1:8765",
      timeoutMs: 1_000,
      authorizationProvider,
      sessionInvalidator: invalidator,
      fetchImpl: fetchMock as unknown as typeof fetch
    });

    const health = await client.health();

    expect(health.state).toBe("ready");
    expect(invalidator).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(new Headers(fetchMock.mock.calls[1]?.[1]?.headers).get("authorization")).toBe("Bearer fresh");
  });

  it("stops after a second 401 and replays the confirmed body unchanged", async () => {
    const invalidator = vi.fn();
    const fetchMock = vi.fn(async (_input: string | URL | Request, _init?: RequestInit) => (
      { ok: false, status: 401, text: async () => "" } as Response
    ));
    const client = new RepositoryServiceClient({
      baseUrl: "http://127.0.0.1:8765",
      timeoutMs: 1_000,
      sessionInvalidator: invalidator,
      fetchImpl: fetchMock as typeof fetch
    });

    await expect(client.startIndexJob("token-1")).rejects.toThrow(/401/);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(invalidator).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls.map((call) => JSON.parse(String(call[1]?.body)))).toEqual([
      { preview_token: "token-1" },
      { preview_token: "token-1" }
    ]);
  });

  it("separates the runtime handshake from the request in a timeout message", async () => {
    // The handshake runs before the abort timer, so its cost is not inside the
    // budget. A message that reported only the budget made a slow handshake look
    // like a slow service, and raising the budget could never help.
    const client = new RepositoryServiceClient({
      baseUrl: "http://127.0.0.1:8765",
      timeoutMs: 1_000,
      authorizationProvider: async () => {
        await new Promise((resolve) => setTimeout(resolve, 25));
        return "Bearer token";
      },
      fetchImpl: vi.fn(async () => {
        const abort = new Error("aborted");
        abort.name = "AbortError";
        throw abort;
      }) as typeof fetch
    });

    const error = await client.query("anything", "symbol").catch((value: unknown) => value);

    expect(error).toBeInstanceOf(ServiceError);
    expect((error as ServiceError).message).toMatch(/of the 1000 ms budget for \/api\/query/);
    expect((error as ServiceError).message).toMatch(/plus \d+ ms to start the runtime/);
  });

  it("keeps the managed session after a timeout or a dropped connection", async () => {
    const invalidator = vi.fn();
    const timedOut = new RepositoryServiceClient({
      baseUrl: "http://127.0.0.1:8765",
      timeoutMs: 1_000,
      sessionInvalidator: invalidator,
      fetchImpl: vi.fn(async () => {
        const abort = new Error("aborted");
        abort.name = "AbortError";
        throw abort;
      }) as typeof fetch
    });
    await expect(timedOut.health()).rejects.toThrow(/timed out/i);

    const unavailable = new RepositoryServiceClient({
      baseUrl: "http://127.0.0.1:8765",
      timeoutMs: 1_000,
      sessionInvalidator: invalidator,
      fetchImpl: vi.fn(async () => { throw new Error("owner closed"); }) as typeof fetch
    });
    await expect(unavailable.health()).rejects.toThrow(/unavailable/i);

    const serviceFailure = new RepositoryServiceClient({
      baseUrl: "http://127.0.0.1:8765",
      timeoutMs: 1_000,
      sessionInvalidator: invalidator,
      fetchImpl: vi.fn(async () => ({ ok: false, status: 503, text: async () => "" } as Response)) as typeof fetch
    });
    await expect(serviceFailure.health()).rejects.toThrow(/503/);

    expect(invalidator).not.toHaveBeenCalled();
  });

  it("reports why the managed runtime could not start", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}) } as Response));
    const crashed = new RepositoryServiceClient({
      baseUrl: "http://127.0.0.1:8765",
      timeoutMs: 1_000,
      baseUrlProvider: async () => "http://127.0.0.1:8765",
      authorizationProvider: async () => {
        throw new Error("Managed service exited with code 1 during startup.");
      },
      fetchImpl: fetchMock as typeof fetch
    });

    await expect(crashed.health()).rejects.toThrow(/exited with code 1/);
    // A runtime that never started must not be described as a transport failure.
    await expect(crashed.health()).rejects.not.toThrow(/unavailable/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("addresses the job endpoints the service publishes", async () => {
    const fetchMock = vi.fn(async (_input: string | URL | Request, _init?: RequestInit) => ({
      ok: true,
      status: 200,
      json: async () => ({ job_id: "job-1", state: "running", phase: "uploading" })
    } as Response));
    const client = new RepositoryServiceClient({
      baseUrl: "http://127.0.0.1:8765",
      timeoutMs: 1_000,
      fetchImpl: fetchMock as typeof fetch
    });

    const status = await client.indexJobStatus("job 1");
    const cancelled = await client.cancelIndexJob("job 1");

    expect(status.jobId).toBe("job-1");
    expect(status.state).toBe("running");
    expect(cancelled.phase).toBe("uploading");
    expect(fetchMock.mock.calls.map((call) => String(call[0]))).toEqual([
      "http://127.0.0.1:8765/api/index/jobs/job%201",
      "http://127.0.0.1:8765/api/index/jobs/job%201/cancel"
    ]);
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe("GET");
    expect(fetchMock.mock.calls[1]?.[1]?.method).toBe("POST");
  });
});
