import { describe, expect, it, vi } from "vitest";
import {
  formatIndexPreview,
  runSafeIndexing,
  type IndexPreview,
  type IndexResult,
  type IndexingClient
} from "../src/indexing.js";
import { RepositoryServiceClient } from "../src/serviceClient.js";

const preview: IndexPreview = {
  previewToken: "p".repeat(43),
  repositoryRoot: "C:\\configured\\repository",
  repositoryId: "repo-1",
  revisionId: "rev-42",
  revisionSource: "content-digest",
  discoveredFileCount: 12,
  ignoredCount: 4,
  nodeCount: 31,
  edgeCount: 47,
  sourceCount: 18,
  sources: [{
    sourceId: "source-1",
    nodeId: "node-1",
    path: "src/api.py",
    displayName: "api.py",
    entityKind: "FILE",
    contentChars: 420,
    exactRelationCount: 6
  }],
  diagnostics: ["One dynamic call target was unresolved."],
  uploadsPerformed: false
};

const readyResult: IndexResult = {
  preview,
  sync: {
    status: "ready",
    candidateRevision: "rev-42",
    readyRevision: "rev-42",
    added: ["source-1"],
    replaced: [],
    deleted: [],
    pending: [],
    failed: {},
    currentStateIndeterminate: false
  }
};

describe("safe repository indexing", () => {
  it("sends an empty preview body and only the server token on confirmation", async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      const body = url.endsWith("/preview") ? {
        preview_token: preview.previewToken,
        repository_root: preview.repositoryRoot,
        repository_id: preview.repositoryId,
        revision_id: "rev-42",
        revision_source: "content-digest",
        discovered_file_count: 12,
        ignored_count: 4,
        node_count: 31,
        edge_count: 47,
        source_count: 18,
        sources: [],
        diagnostics: [],
        uploads_performed: false
      } : {
        preview: { revision_id: "rev-42", uploads_performed: false },
        sync: {
          status: "ready", candidate_revision: "rev-42", ready_revision: "rev-42",
          added: [], replaced: [], deleted: [], pending: [], failed: {}, current_state_indeterminate: false
        }
      };
      return { ok: true, status: 200, json: async () => body } as Response;
    });
    const client = new RepositoryServiceClient({
      baseUrl: "http://127.0.0.1:8765/",
      timeoutMs: 1000,
      repositoryScope: {
        repositoryRoot: "C:\\Workspaces\\Hydra Repo",
        repositoryId: "hydra-repo-a1b2c3d4e5f6"
      },
      fetchImpl: fetchMock as typeof fetch
    });

    await client.previewIndex();
    await client.indexRepository(preview.previewToken);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("http://127.0.0.1:8765/api/index/preview");
    expect(String(fetchMock.mock.calls[1]?.[0])).toBe("http://127.0.0.1:8765/api/index");
    for (const call of fetchMock.mock.calls) {
      const init = call[1];
      expect(init?.method).toBe("POST");
      const headers = new Headers(init?.headers);
      expect(headers.get("content-type")).toBe("application/json");
      expect(headers.get("x-hydra-repository-root")).toBe("C%3A%5CWorkspaces%5CHydra%20Repo");
      expect(headers.get("x-hydra-repository-id")).toBe("hydra-repo-a1b2c3d4e5f6");
      expect(JSON.parse(String(init?.body))).not.toHaveProperty("repository_root");
    }
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({});
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({ preview_token: preview.previewToken });
  });

  it("does not call the upload endpoint when modal confirmation is cancelled", async () => {
    const client: IndexingClient = {
      previewIndex: vi.fn(async () => preview),
      indexRepository: vi.fn(async () => readyResult)
    };
    const confirm = vi.fn(async () => false);

    const outcome = await runSafeIndexing(client, confirm);

    expect(outcome.status).toBe("cancelled");
    expect(client.previewIndex).toHaveBeenCalledOnce();
    expect(confirm).toHaveBeenCalledWith(preview);
    expect(client.indexRepository).not.toHaveBeenCalled();
  });

  it("uploads exactly once after confirmation and keeps the revision unchanged", async () => {
    const client: IndexingClient = {
      previewIndex: vi.fn(async () => preview),
      indexRepository: vi.fn(async () => readyResult)
    };

    const outcome = await runSafeIndexing(client, async () => true);

    expect(outcome.status).toBe("completed");
    expect(client.indexRepository).toHaveBeenCalledOnce();
    expect(client.indexRepository).toHaveBeenCalledWith(preview.previewToken);
  });

  it("stops if the preview ever claims an upload was already performed", async () => {
    const client: IndexingClient = {
      previewIndex: vi.fn(async () => ({ ...preview, uploadsPerformed: true })),
      indexRepository: vi.fn(async () => readyResult)
    };
    const confirm = vi.fn(async () => true);

    await expect(runSafeIndexing(client, confirm)).rejects.toThrow("unexpectedly reported an upload");
    expect(confirm).not.toHaveBeenCalled();
    expect(client.indexRepository).not.toHaveBeenCalled();
  });

  it("stops before confirmation when the server omits its preview token", async () => {
    const client: IndexingClient = {
      previewIndex: vi.fn(async () => ({ ...preview, previewToken: "" })),
      indexRepository: vi.fn(async () => readyResult)
    };
    const confirm = vi.fn(async () => true);

    await expect(runSafeIndexing(client, confirm)).rejects.toThrow("confirmation token");
    expect(confirm).not.toHaveBeenCalled();
    expect(client.indexRepository).not.toHaveBeenCalled();
  });

  it("formats the server-owned root and file, source, and relation scope for confirmation", () => {
    const detail = formatIndexPreview(preview);

    expect(detail).toContain("Workspace root: C:\\configured\\repository");
    expect(detail).toContain("Discovered files: 12");
    expect(detail).toContain("Generated source cards: 18");
    expect(detail).toContain("Graph relations: 47");
    expect(detail).toContain("src/api.py · FILE · 6 exact relations");
    expect(detail).toContain("One dynamic call target was unresolved.");
  });

});
