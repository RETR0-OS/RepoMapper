import { describe, expect, it, vi } from "vitest";
import {
  cancelledIndexSummary,
  formatIndexJobProgress,
  formatIndexPreview,
  normalizeIndexJob,
  runSafeIndexing,
  type IndexJob,
  type IndexPreview,
  type IndexResult
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

const runningJob: IndexJob = {
  jobId: "job-1",
  repositoryId: "repo-1",
  revisionId: "rev-42",
  state: "running",
  phase: "uploading",
  totalBatches: 249,
  uploadedBatches: 12,
  totalSources: 6210,
  verifiedSources: 300,
  failed: {},
  startedAt: 1_786_723_200,
  updatedAt: 1_786_723_205,
  durable: false,
  message: ""
};

function job(overrides: Partial<IndexJob>): IndexJob {
  return { ...runningJob, ...overrides };
}

/** A client that hands out one job record per status call, so a poll loop is fully deterministic. */
function jobClient(records: IndexJob[], cancelled?: IndexJob) {
  const queue = [...records];
  const first = queue.shift() ?? runningJob;
  return {
    previewIndex: vi.fn(async () => preview),
    startIndexJob: vi.fn(async () => first),
    indexJobStatus: vi.fn(async () => queue.shift() ?? job({ state: "completed", phase: "done", result: readyResult })),
    cancelIndexJob: vi.fn(async () => cancelled ?? job({ state: "running", phase: "deleting" }))
  };
}

const noWait = async (): Promise<void> => undefined;

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
        job_id: "job-1",
        repository_id: "repo-1",
        revision_id: "rev-42",
        state: "running",
        phase: "analyzing",
        total_batches: 0,
        uploaded_batches: 0,
        total_sources: 0,
        verified_sources: 0,
        failed: {},
        durable: false,
        message: "Indexing started."
      };
      return { ok: true, status: url.endsWith("/preview") ? 200 : 202, json: async () => body } as Response;
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
    await client.startIndexJob(preview.previewToken);

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

  it("does not start a job when modal confirmation is cancelled", async () => {
    const client = jobClient([]);
    const confirm = vi.fn(async () => false);

    const outcome = await runSafeIndexing(client, confirm, { wait: noWait });

    expect(outcome.status).toBe("cancelled");
    expect(client.previewIndex).toHaveBeenCalledOnce();
    expect(confirm).toHaveBeenCalledWith(preview);
    expect(client.startIndexJob).not.toHaveBeenCalled();
  });

  it("starts exactly one job after confirmation and polls it to completion", async () => {
    const client = jobClient([
      job({ phase: "analyzing", totalBatches: 0, uploadedBatches: 0 }),
      job({ uploadedBatches: 120, verifiedSources: 3000 }),
      job({ state: "completed", phase: "done", uploadedBatches: 249, verifiedSources: 6210, result: readyResult })
    ]);
    const progress: string[] = [];

    const outcome = await runSafeIndexing(client, async () => true, {
      wait: noWait,
      onProgress: (update) => progress.push(`${update.state}:${update.phase}:${update.uploadedBatches}`)
    });

    expect(outcome.status).toBe("completed");
    if (outcome.status !== "completed") return;
    expect(outcome.result).toEqual(readyResult);
    expect(client.startIndexJob).toHaveBeenCalledOnce();
    expect(client.startIndexJob).toHaveBeenCalledWith(preview.previewToken);
    expect(client.indexJobStatus).toHaveBeenCalledTimes(2);
    expect(client.indexJobStatus).toHaveBeenCalledWith("job-1");
    expect(client.cancelIndexJob).not.toHaveBeenCalled();
    expect(progress).toEqual([
      "running:analyzing:0",
      "running:uploading:120",
      "completed:done:249"
    ]);
  });

  it("waits the configured interval between polls", async () => {
    const wait = vi.fn(async () => undefined);
    const client = jobClient([runningJob, job({ state: "completed", phase: "done", result: readyResult })]);

    await runSafeIndexing(client, async () => true, { wait, pollIntervalMs: 2500 });

    expect(wait).toHaveBeenCalledTimes(1);
    expect(wait).toHaveBeenCalledWith(2500);
  });

  it("asks the service to cancel once and reports the state the service settled on", async () => {
    const client = jobClient(
      [runningJob, job({ state: "cancelled", phase: "uploading", uploadedBatches: 40, verifiedSources: 900 })],
      job({ state: "running", phase: "deleting", uploadedBatches: 40 })
    );

    const outcome = await runSafeIndexing(client, async () => true, { wait: noWait, isCancelled: () => true });

    expect(outcome.status).toBe("cancelled-by-user");
    if (outcome.status !== "cancelled-by-user") return;
    expect(outcome.job.state).toBe("cancelled");
    expect(outcome.job.uploadedBatches).toBe(40);
    expect(client.cancelIndexJob).toHaveBeenCalledOnce();
    expect(client.cancelIndexJob).toHaveBeenCalledWith("job-1");
    // The cancel request never ends the poll loop by itself.
    expect(client.indexJobStatus).toHaveBeenCalledTimes(1);
    expect(cancelledIndexSummary(outcome.job)).toContain("may already be in HydraDB");
  });

  it("keeps polling when the service refuses to cancel and finishes the upload", async () => {
    const client = jobClient(
      [runningJob, job({ state: "completed", phase: "done", uploadedBatches: 249, verifiedSources: 6210, result: readyResult })],
      job({ state: "running", phase: "uploading", message: "Cancellation is not possible during verification." })
    );

    const outcome = await runSafeIndexing(client, async () => true, { wait: noWait, isCancelled: () => true });

    expect(outcome.status).toBe("completed");
    expect(client.cancelIndexJob).toHaveBeenCalledOnce();
  });

  it("does not warn about partial remote state when cancellation preceded every write", () => {
    const safeResult: IndexResult = {
      preview,
      sync: {
        ...readyResult.sync,
        status: "failed",
        failed: { __cancelled__: "Cancelled before upload" },
        currentStateIndeterminate: false
      }
    };

    const summary = cancelledIndexSummary(job({ state: "cancelled", phase: "done", result: safeResult }));

    expect(summary).toContain("before any HydraDB write");
    expect(summary).not.toContain("may already be in HydraDB");
  });

  it("surfaces the service's own reason when the job fails", async () => {
    const client = jobClient([
      runningJob,
      job({
        state: "failed",
        phase: "uploading",
        error: "HydraDB rejected batch 13.",
        failed: { "source-9": "payload too large" }
      })
    ]);

    await expect(runSafeIndexing(client, async () => true, { wait: noWait }))
      .rejects.toThrow(/HydraDB rejected batch 13\..*source-9 \(payload too large\)/s);
  });

  it("never reports success when a completed job carries no result", async () => {
    const client = jobClient([runningJob, job({ state: "completed", phase: "done", message: "Nothing was written." })]);

    await expect(runSafeIndexing(client, async () => true, { wait: noWait }))
      .rejects.toThrow(/completed without an indexing result.*Nothing was written\./s);
  });

  it("stops if the preview ever claims an upload was already performed", async () => {
    const client = { ...jobClient([]), previewIndex: vi.fn(async () => ({ ...preview, uploadsPerformed: true })) };
    const confirm = vi.fn(async () => true);

    await expect(runSafeIndexing(client, confirm, { wait: noWait })).rejects.toThrow("unexpectedly reported an upload");
    expect(confirm).not.toHaveBeenCalled();
    expect(client.startIndexJob).not.toHaveBeenCalled();
  });

  it("stops before confirmation when the server omits its preview token", async () => {
    const client = { ...jobClient([]), previewIndex: vi.fn(async () => ({ ...preview, previewToken: "" })) };
    const confirm = vi.fn(async () => true);

    await expect(runSafeIndexing(client, confirm, { wait: noWait })).rejects.toThrow("confirmation token");
    expect(confirm).not.toHaveBeenCalled();
    expect(client.startIndexJob).not.toHaveBeenCalled();
  });

  it("normalizes snake_case and camelCase job records without throwing on bad fields", () => {
    const normalized = normalizeIndexJob({
      job_id: "job-7",
      revisionId: "rev-9",
      state: "running",
      phase: "uploading",
      total_batches: 249,
      uploadedBatches: 12,
      total_sources: "not a number",
      verified_sources: -4,
      started_at: 1_786_723_200.25,
      updatedAt: "not a timestamp",
      failed: { "source-1": 42 },
      durable: false
    });

    expect(normalized.jobId).toBe("job-7");
    expect(normalized.revisionId).toBe("rev-9");
    expect(normalized.totalBatches).toBe(249);
    expect(normalized.uploadedBatches).toBe(12);
    expect(normalized.totalSources).toBe(0);
    expect(normalized.verifiedSources).toBe(0);
    expect(normalized.startedAt).toBe(1_786_723_200.25);
    expect(normalized.updatedAt).toBe(0);
    expect(normalized.failed).toEqual({ "source-1": "Unknown failure" });
    expect(normalized.result).toBeUndefined();
    expect(normalizeIndexJob(undefined).state).toBe("running");
  });

  it("reports upload progress with the service's own counts", () => {
    expect(formatIndexJobProgress(runningJob)).toBe("Uploading 12/249 batches · 300/6210 sources verified");
    expect(formatIndexJobProgress(job({ phase: "analyzing" }))).toContain("Analyzing");
    expect(formatIndexJobProgress(job({ phase: "clearing_stale_graphs" }))).toContain("Clearing stale exact relations");
    expect(formatIndexJobProgress(job({ phase: "verifying" }))).toBe("Verifying 300/6210 uploaded sources");
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
