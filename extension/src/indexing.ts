export interface IndexSourceScope {
  sourceId: string;
  nodeId: string;
  path: string;
  displayName: string;
  entityKind: string;
  contentChars: number;
  exactRelationCount: number;
}

export interface IndexPreview {
  previewToken: string;
  repositoryRoot: string;
  repositoryId: string;
  revisionId: string;
  revisionSource: "git-clean" | "content-digest" | string;
  discoveredFileCount: number;
  ignoredCount: number;
  nodeCount: number;
  edgeCount: number;
  sourceCount: number;
  sources: IndexSourceScope[];
  diagnostics: string[];
  uploadsPerformed: boolean;
}

export interface IndexSyncResult {
  status: "ready" | "indexing" | "failed" | "unavailable" | string;
  candidateRevision: string;
  readyRevision?: string;
  added: string[];
  replaced: string[];
  deleted: string[];
  pending: string[];
  failed: Record<string, string>;
  currentStateIndeterminate: boolean;
  warning?: string;
}

export interface IndexResult {
  preview: IndexPreview;
  sync: IndexSyncResult;
}

export interface IndexJob {
  jobId: string;
  repositoryId: string;
  revisionId: string;
  state: "running" | "completed" | "failed" | "cancelled" | string;
  phase: "analyzing" | "clearing_stale_graphs" | "uploading" | "verifying" | "deleting" | "done" | string;
  totalBatches: number;
  uploadedBatches: number;
  totalSources: number;
  verifiedSources: number;
  failed: Record<string, string>;
  startedAt: number;
  updatedAt: number;
  error?: string;
  result?: IndexResult;
  durable: boolean;
  message: string;
}

export interface IndexingClient {
  previewIndex(): Promise<IndexPreview>;
  startIndexJob(previewToken: string): Promise<IndexJob>;
  indexJobStatus(jobId: string): Promise<IndexJob>;
  cancelIndexJob(jobId: string): Promise<IndexJob>;
}

export interface IndexRunOptions {
  onProgress?: (job: IndexJob) => void;
  isCancelled?: () => boolean;
  pollIntervalMs?: number;
  wait?: (ms: number) => Promise<void>;
}

export type SafeIndexOutcome =
  | { status: "cancelled"; preview: IndexPreview }
  | { status: "cancelled-by-user"; preview: IndexPreview; job: IndexJob }
  | { status: "completed"; preview: IndexPreview; result: IndexResult };

type UnknownRecord = Record<string, unknown>;

function record(value: unknown): UnknownRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as UnknownRecord : {};
}

function text(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function count(value: unknown): number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : 0;
}

function timestamp(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : 0;
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

export function normalizeIndexPreview(value: unknown): IndexPreview {
  const preview = record(value);
  return {
    previewToken: text(preview.preview_token ?? preview.previewToken),
    repositoryRoot: text(preview.repository_root ?? preview.repositoryRoot),
    repositoryId: text(preview.repository_id ?? preview.repositoryId),
    revisionId: text(preview.revision_id ?? preview.revisionId),
    revisionSource: text(preview.revision_source ?? preview.revisionSource),
    discoveredFileCount: count(preview.discovered_file_count ?? preview.discoveredFileCount),
    ignoredCount: count(preview.ignored_count ?? preview.ignoredCount),
    nodeCount: count(preview.node_count ?? preview.nodeCount),
    edgeCount: count(preview.edge_count ?? preview.edgeCount),
    sourceCount: count(preview.source_count ?? preview.sourceCount),
    sources: Array.isArray(preview.sources) ? preview.sources.map((value) => {
      const source = record(value);
      return {
        sourceId: text(source.source_id ?? source.sourceId),
        nodeId: text(source.node_id ?? source.nodeId),
        path: text(source.path),
        displayName: text(source.display_name ?? source.displayName),
        entityKind: text(source.entity_kind ?? source.entityKind),
        contentChars: count(source.content_chars ?? source.contentChars),
        exactRelationCount: count(source.exact_relation_count ?? source.exactRelationCount)
      };
    }) : [],
    diagnostics: strings(preview.diagnostics),
    uploadsPerformed: preview.uploads_performed === true || preview.uploadsPerformed === true
  };
}

export function validateRevisionId(value: string): string | undefined {
  const revision = value.trim();
  if (!revision) {
    return "Enter an explicit revision ID.";
  }
  if (revision.length > 256) {
    return "Revision IDs must be 256 characters or fewer.";
  }
  if (/[\u0000-\u001f\u007f]/.test(revision)) {
    return "Revision IDs cannot contain control characters.";
  }
  return undefined;
}

export function normalizeIndexResult(value: unknown): IndexResult {
  const result = record(value);
  const sync = record(result.sync);
  const failed = record(sync.failed);
  return {
    preview: normalizeIndexPreview(result.preview),
    sync: {
      status: text(sync.status, "failed"),
      candidateRevision: text(sync.candidate_revision ?? sync.candidateRevision),
      readyRevision: text(sync.ready_revision ?? sync.readyRevision) || undefined,
      added: strings(sync.added),
      replaced: strings(sync.replaced),
      deleted: strings(sync.deleted),
      pending: strings(sync.pending),
      failed: Object.fromEntries(Object.entries(failed).map(([key, reason]) => [key, text(reason, "Unknown failure")])),
      currentStateIndeterminate: sync.current_state_indeterminate === true || sync.currentStateIndeterminate === true,
      warning: text(sync.warning) || undefined
    }
  };
}

export function normalizeIndexJob(value: unknown): IndexJob {
  const job = record(value);
  const failed = record(job.failed);
  const result = job.result;
  return {
    jobId: text(job.job_id ?? job.jobId),
    repositoryId: text(job.repository_id ?? job.repositoryId),
    revisionId: text(job.revision_id ?? job.revisionId),
    // An unreadable state must never look finished, so polling continues instead of claiming an outcome.
    state: text(job.state, "running"),
    phase: text(job.phase, "analyzing"),
    totalBatches: count(job.total_batches ?? job.totalBatches),
    uploadedBatches: count(job.uploaded_batches ?? job.uploadedBatches),
    totalSources: count(job.total_sources ?? job.totalSources),
    verifiedSources: count(job.verified_sources ?? job.verifiedSources),
    failed: Object.fromEntries(Object.entries(failed).map(([key, reason]) => [key, text(reason, "Unknown failure")])),
    startedAt: timestamp(job.started_at ?? job.startedAt),
    updatedAt: timestamp(job.updated_at ?? job.updatedAt),
    error: text(job.error) || undefined,
    result: result !== null && typeof result === "object" ? normalizeIndexResult(result) : undefined,
    durable: job.durable === true,
    message: text(job.message)
  };
}

/** Only a running job may be polled again; every other state is what the service actually settled on. */
function jobIsRunning(job: IndexJob): boolean {
  return job.state === "running";
}

/** Repeat the service's own reasons, so the user never sees an invented explanation. */
function jobReportedReasons(job: IndexJob): string {
  const failed = Object.entries(job.failed);
  const listed = failed.slice(0, 5).map(([sourceId, reason]) => `${sourceId} (${reason})`);
  if (failed.length > listed.length) listed.push(`…and ${failed.length - listed.length} more`);
  return [
    job.error ?? "",
    job.message,
    listed.length ? `Failed sources: ${listed.join("; ")}` : ""
  ].filter((part) => part.trim()).join(" ");
}

function jobCounts(job: IndexJob): string {
  return `${job.uploadedBatches}/${job.totalBatches} batches uploaded, ${job.verifiedSources}/${job.totalSources} sources verified.`;
}

export async function runSafeIndexing(
  client: IndexingClient,
  confirm: (preview: IndexPreview) => Promise<boolean>,
  options: IndexRunOptions = {}
): Promise<SafeIndexOutcome> {
  const preview = await client.previewIndex();
  if (preview.uploadsPerformed) {
    throw new Error("The indexing preview unexpectedly reported an upload. Indexing was stopped.");
  }
  if (!preview.revisionId || !preview.previewToken) {
    throw new Error("The indexing preview did not include an automatic revision and confirmation token. Indexing was stopped.");
  }
  if (!preview.repositoryRoot) {
    throw new Error("The indexing preview did not report the selected workspace root. Indexing was stopped.");
  }
  if (!await confirm(preview)) {
    return { status: "cancelled", preview };
  }
  const pollIntervalMs = options.pollIntervalMs ?? 1000;
  const wait = options.wait ?? ((ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms)));
  let job = await client.startIndexJob(preview.previewToken);
  options.onProgress?.(job);
  let cancelRequested = false;
  while (jobIsRunning(job)) {
    if (!cancelRequested && options.isCancelled?.()) {
      cancelRequested = true;
      // Ask once, then keep polling: only the service can say whether the job really stopped.
      job = await client.cancelIndexJob(job.jobId);
      options.onProgress?.(job);
      continue;
    }
    await wait(pollIntervalMs);
    job = await client.indexJobStatus(job.jobId);
    options.onProgress?.(job);
  }
  if (job.state === "completed" && job.result) {
    return { status: "completed", preview, result: job.result };
  }
  if (job.state === "cancelled") {
    return { status: "cancelled-by-user", preview, job };
  }
  const reasons = jobReportedReasons(job);
  const ending = job.state === "completed"
    ? "completed without an indexing result"
    : `ended ${job.state} in phase ${job.phase}`;
  throw new Error(`The HydraDB indexing job ${ending}. ${jobCounts(job)}${reasons ? ` ${reasons}` : ""}`.trim());
}

export function formatIndexJobProgress(job: IndexJob): string {
  if (job.phase === "clearing_stale_graphs") {
    return "Clearing stale exact relations before upload";
  }
  if (job.phase === "uploading") {
    return `Uploading ${job.uploadedBatches}/${job.totalBatches} batches · ${job.verifiedSources}/${job.totalSources} sources verified`;
  }
  if (job.phase === "verifying") {
    return `Verifying ${job.verifiedSources}/${job.totalSources} uploaded sources`;
  }
  if (job.phase === "deleting") {
    return "Removing source cards that the new revision replaced";
  }
  if (job.phase === "done") {
    return "Finishing the revision";
  }
  return "Analyzing the selected project and deriving its revision…";
}

export function cancelledIndexSummary(job: IndexJob): string {
  const reasons = jobReportedReasons(job);
  const remoteState = job.result?.sync.currentStateIndeterminate === false
    ? "The service reports that cancellation happened before any HydraDB write."
    : `Part of revision ${job.revisionId || "the candidate revision"} may already be in HydraDB.`;
  return [
    `Indexing was cancelled in phase ${job.phase}.`,
    `The service reports ${jobCounts(job)}`,
    remoteState,
    reasons
  ].filter((part) => part.trim()).join(" ");
}

export function formatIndexPreview(preview: IndexPreview, visibleSourceLimit = 16): string {
  const visible = preview.sources.slice(0, visibleSourceLimit);
  const sourceLines = visible.map((source) => {
    const label = source.path || source.displayName || source.sourceId;
    return `• ${label} · ${source.entityKind || "entity"} · ${source.exactRelationCount} exact relations`;
  });
  if (preview.sources.length > visible.length) {
    sourceLines.push(`• …and ${preview.sources.length - visible.length} more source cards`);
  }
  return [
    `Workspace root: ${preview.repositoryRoot || "Not reported"}`,
    `Repository: ${preview.repositoryId || "Not reported"}`,
    `Revision: ${preview.revisionId} (${preview.revisionSource === "git-clean" ? "clean Git commit" : "analyzed content"})`,
    `Discovered files: ${preview.discoveredFileCount}`,
    `Generated source cards: ${preview.sourceCount}`,
    `Repository nodes: ${preview.nodeCount}`,
    `Graph relations: ${preview.edgeCount}`,
    `Ignored paths: ${preview.ignoredCount}`,
    "",
    "Source scope:",
    ...(sourceLines.length ? sourceLines : ["• No source cards were generated."]),
    ...(preview.diagnostics.length ? ["", "Diagnostics:", ...preview.diagnostics.map((item) => `• ${item}`)] : [])
  ].join("\n");
}

export function readyIndexSummary(result: IndexResult): string | undefined {
  const sync = result.sync;
  if (
    sync.status !== "ready"
    || !sync.readyRevision
    || sync.readyRevision !== sync.candidateRevision
    || sync.currentStateIndeterminate
    || sync.pending.length > 0
    || Object.keys(sync.failed).length > 0
  ) {
    return undefined;
  }
  return `HydraDB revision ${sync.readyRevision} is ready. ${sync.added.length} added, ${sync.replaced.length} replaced, ${sync.deleted.length} deleted.`;
}

export function failedIndexSummary(result: IndexResult): string {
  const sync = result.sync;
  const prior = sync.readyRevision ? ` Last verified revision: ${sync.readyRevision}.` : " No verified revision is ready.";
  const uncertainty = sync.currentStateIndeterminate ? " Current HydraDB content may be indeterminate." : "";
  const counts = `${Object.keys(sync.failed).length} failed, ${sync.pending.length} pending.`;
  return `${sync.status || "failed"}: ${counts}${prior}${uncertainty}${sync.warning ? ` ${sync.warning}` : ""}`;
}
