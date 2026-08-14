import { describe, expect, it, vi } from "vitest";
import { RepositoryServiceClient } from "../src/serviceClient.js";

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
});
