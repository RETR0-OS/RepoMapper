import { describe, expect, it, vi } from "vitest";
import {
  checkpointWasCaptured,
  lensPreviewMatches,
  lensWriteIsReady,
  previewThenConfirm,
  publishPreviewMatches,
  publishIsReady,
  type LensResponse
} from "../src/evolution.js";
import { RepositoryServiceClient, requireLoopbackServiceUrl } from "../src/serviceClient.js";

function responseFor(url: string, body: Record<string, unknown>): Record<string, unknown> {
  if (url.includes("checkpoints")) {
    const slot = url.includes("/after") ? "after" : "before";
    return {
      status: "captured", operation: "capture_checkpoint", slot, repository_id: "repo",
      revision_id: body.revision_id, checkpoint_id: `checkpoint-${slot}`, node_count: 10,
      edge_count: 12, writes_performed: true, warnings: []
    };
  }
  if (url.endsWith("/api/evolution/publish")) {
    return {
      status: body.confirm ? "ready" : "preview", operation: "publish_delta", repository_id: "repo",
      before_revision_id: body.before_revision_id, after_revision_id: body.after_revision_id,
      source_ids: ["delta-1"], source_count: 1, writes_performed: body.confirm,
      hydradb: { available: true, write_attempted: body.confirm }, warnings: []
    };
  }
  const accept = url.includes("/accept");
  return {
    status: body.confirm ? "ready" : "preview",
    operation: accept ? "accept_lens" : "save_lens",
    lens_id: accept ? "lens / one" : "lens-1",
    source_id: "lens-source",
    name: body.name ?? "Authentication",
    saved_revision_id: "rev-after",
    previous_revision_id: accept ? "rev-before" : null,
    anchor_node_ids: ["node-1"], edge_ids: ["edge-1"], ownership: "shared",
    writes_performed: body.confirm,
    hydradb: { available: true, write_attempted: body.confirm }, warnings: []
  };
}

describe("Compare and Preserve service contract", () => {
  it("sends exact request bodies and encodes the lens ID path segment", async () => {
    const calls: Array<{ url: string; body: Record<string, unknown> }> = [];
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      calls.push({ url, body });
      return { ok: true, status: 200, json: async () => responseFor(url, body) } as Response;
    });
    const client = new RepositoryServiceClient({
      baseUrl: "http://[::1]:8765",
      timeoutMs: 1000,
      fetchImpl: fetchMock as typeof fetch
    });

    await client.checkpoint("before", "rev-before");
    await client.publishEvolution("rev-before", "rev-after", false);
    await client.publishEvolution("rev-before", "rev-after", true);
    await client.saveLens({ name: "Authentication", purpose: "Preserve auth flow", viewId: "view-1" }, false);
    await client.saveLens({ name: "Authentication", purpose: "Preserve auth flow", viewId: "view-1" }, true);
    await client.acceptLens("lens / one", "view-2", false);
    await client.acceptLens("lens / one", "view-2", true);

    expect(calls.map((call) => call.body)).toEqual([
      { revision_id: "rev-before" },
      { before_revision_id: "rev-before", after_revision_id: "rev-after", confirm: false },
      { before_revision_id: "rev-before", after_revision_id: "rev-after", confirm: true },
      { name: "Authentication", purpose: "Preserve auth flow", view_id: "view-1", notes: null, confirm: false },
      { name: "Authentication", purpose: "Preserve auth flow", view_id: "view-1", notes: null, confirm: true },
      { view_id: "view-2", confirm: false },
      { view_id: "view-2", confirm: true }
    ]);
    expect(calls[0]?.body).not.toHaveProperty("confirm");
    expect(calls[5]?.url).toContain("/api/lenses/lens%20%2F%20one/accept");
  });

  it("does not call a confirmed write after preview cancellation", async () => {
    const confirmed = vi.fn(async () => ({ status: "ready", writesPerformed: true }));
    const confirm = vi.fn(async () => false);
    const outcome = await previewThenConfirm(
      async () => ({ status: "preview", writesPerformed: false, scope: "delta" }),
      confirm,
      confirmed
    );

    expect(outcome.status).toBe("cancelled");
    expect(confirm).toHaveBeenCalledOnce();
    expect(confirmed).not.toHaveBeenCalled();
  });

  it.each([
    { status: "preview", writesPerformed: true },
    { status: "ready", writesPerformed: false },
    { status: "unavailable", writesPerformed: false }
  ])("fails closed when the preview response is not a no-write preview: %j", async (unsafePreview) => {
    const confirm = vi.fn(async () => true);
    const confirmed = vi.fn(async () => ({ status: "ready" }));

    await expect(previewThenConfirm(async () => unsafePreview, confirm, confirmed)).rejects.toThrow("safe no-write preview");
    expect(confirm).not.toHaveBeenCalled();
    expect(confirmed).not.toHaveBeenCalled();
  });

  it("requires committed IDs, matching revisions, and complete source counts before reporting ready", () => {
    const checkpoint = {
      status: "captured", operation: "capture_checkpoint", slot: "before" as const, repositoryId: "repo",
      revisionId: "rev-before", checkpointId: "cp-1", nodeCount: 2, edgeCount: 1,
      writesPerformed: true, warnings: []
    };
    const publish = {
      status: "ready", operation: "publish_delta", repositoryId: "repo", beforeRevisionId: "rev-before",
      afterRevisionId: "rev-after", sourceIds: ["delta-1"], sourceCount: 1,
      writesPerformed: true, hydradb: { available: true, write_attempted: true }, warnings: []
    };
    const lens: LensResponse = {
      status: "ready", operation: "save_lens", lensId: "lens-1", sourceId: "source-1", name: "Auth",
      savedRevisionId: "rev-after", anchorNodeIds: ["n"], edgeIds: ["e"], ownership: "shared",
      writesPerformed: true, hydradb: { available: true, write_attempted: true }, warnings: []
    };

    expect(checkpointWasCaptured(checkpoint, "before", "rev-before")).toBe(true);
    expect(checkpointWasCaptured({ ...checkpoint, checkpointId: undefined }, "before", "rev-before")).toBe(false);
    expect(publishIsReady(publish, "rev-before", "rev-after")).toBe(true);
    expect(publishIsReady({ ...publish, sourceCount: 2 }, "rev-before", "rev-after")).toBe(false);
    expect(lensWriteIsReady(lens, "rev-after")).toBe(true);
    expect(lensWriteIsReady({ ...lens, writesPerformed: false }, "rev-after")).toBe(false);
  });

  it("rejects normalized success shells with no concrete graph scope or HydraDB write proof", () => {
    const checkpoint = {
      status: "captured", operation: "capture_checkpoint", slot: "before" as const, repositoryId: "repo",
      revisionId: "rev-before", checkpointId: "cp-1", nodeCount: 0, edgeCount: 0,
      writesPerformed: true, warnings: []
    };
    const publish = {
      status: "ready", operation: "publish_delta", repositoryId: "repo", beforeRevisionId: "rev-before",
      afterRevisionId: "rev-after", sourceIds: [], sourceCount: 0,
      writesPerformed: true, hydradb: { available: true, write_attempted: true }, warnings: []
    };
    const lens: LensResponse = {
      status: "ready", operation: "save_lens", lensId: "lens-1", sourceId: "source-1", name: "Auth",
      savedRevisionId: "rev-after", anchorNodeIds: [], edgeIds: [], ownership: "shared",
      writesPerformed: true, hydradb: { available: true, write_attempted: true }, warnings: []
    };

    expect(checkpointWasCaptured(checkpoint, "before", "rev-before")).toBe(false);
    expect(publishIsReady(publish, "rev-before", "rev-after")).toBe(false);
    expect(publishIsReady({ ...publish, sourceIds: ["delta"], sourceCount: 1, hydradb: { available: false, write_attempted: true } }, "rev-before", "rev-after")).toBe(false);
    expect(publishIsReady({ ...publish, sourceIds: ["delta"], sourceCount: 1, hydradb: { available: true } }, "rev-before", "rev-after")).toBe(false);
    expect(lensWriteIsReady(lens, "rev-after")).toBe(false);
    expect(lensWriteIsReady({ ...lens, anchorNodeIds: ["node"], edgeIds: ["edge"], hydradb: { available: false, write_attempted: true } }, "rev-after")).toBe(false);
    expect(lensWriteIsReady({ ...lens, anchorNodeIds: ["node"], edgeIds: ["edge"], ownership: "private" }, "rev-after")).toBe(false);
  });

  it("rejects write previews with empty scope or evidence of an attempted write", () => {
    const publish = {
      status: "preview", operation: "publish_delta", repositoryId: "repo", beforeRevisionId: "before",
      afterRevisionId: "after", sourceIds: ["delta"], sourceCount: 1,
      writesPerformed: false, hydradb: { available: true, write_attempted: false }, warnings: []
    };
    const lens: LensResponse = {
      status: "preview", operation: "save_lens", lensId: "lens", sourceId: "source", name: "Auth",
      savedRevisionId: "after", anchorNodeIds: ["node"], edgeIds: ["edge"], ownership: "shared",
      writesPerformed: false, hydradb: { available: true, write_attempted: false }, warnings: []
    };

    expect(publishPreviewMatches(publish, "before", "after")).toBe(true);
    expect(publishPreviewMatches({ ...publish, sourceIds: [], sourceCount: 0 }, "before", "after")).toBe(false);
    expect(publishPreviewMatches({ ...publish, hydradb: { available: true, write_attempted: true } }, "before", "after")).toBe(false);
    expect(lensPreviewMatches(lens, "save_lens", "after")).toBe(true);
    expect(lensPreviewMatches({ ...lens, edgeIds: [] }, "save_lens", "after")).toBe(false);
    expect(lensPreviewMatches({ ...lens, hydradb: {} }, "save_lens", "after")).toBe(false);
    expect(lensPreviewMatches({ ...lens, operation: "accept_lens" }, "accept_lens", "after", "other-lens")).toBe(false);
  });

  it("encodes exact Compare and Preserve GET context without substituting preview IDs", async () => {
    const urls: string[] = [];
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      urls.push(String(input));
      return {
        ok: true,
        status: 200,
        json: async () => ({
          view_id: "view-1", revision_id: "rev-after", mode: "compare", depth: "symbol",
          nodes: [], edges: [], warnings: [], hydradb: { available: true },
          budget: { requested_nodes: 20, returned_nodes: 0, requested_edges: 30, returned_edges: 0 }
        })
      } as Response;
    });
    const client = new RepositoryServiceClient({
      baseUrl: "http://127.0.0.1:8765",
      timeoutMs: 1000,
      fetchImpl: fetchMock as typeof fetch
    });

    await client.getView("compare", "symbol", { beforeRevision: "rev/before", afterRevision: "rev after" });
    await client.getView("preserve", "file", { lens: "lens / one" });

    const compare = new URL(urls[0] ?? "");
    const preserve = new URL(urls[1] ?? "");
    expect([...compare.searchParams.entries()]).toEqual([
      ["depth", "symbol"], ["before_revision", "rev/before"], ["after_revision", "rev after"]
    ]);
    expect([...preserve.searchParams.entries()]).toEqual([["depth", "file"], ["lens", "lens / one"]]);
    expect(urls[0]).toContain("before_revision=rev%2Fbefore");
    expect(urls[1]).toContain("lens=lens+%2F+one");
    expect(urls.join(" ")).not.toContain("preview");
  });
});

describe("loopback service enforcement", () => {
  it.each([
    "https://example.com:8765",
    "http://localhost.evil:8765",
    "file:///tmp/service",
    "http://user:secret@localhost:8765",
    "http://localhost:8765?target=external"
  ])("rejects a non-loopback or ambiguous configured URL: %s", (url) => {
    expect(() => requireLoopbackServiceUrl(url)).toThrow();
  });

  it.each([
    "http://localhost:8765/",
    "http://127.0.0.1:8765",
    "https://[::1]:8765/"
  ])("accepts an explicit loopback URL: %s", (url) => {
    expect(requireLoopbackServiceUrl(url)).toMatch(/^https?:\/\//);
  });
});
