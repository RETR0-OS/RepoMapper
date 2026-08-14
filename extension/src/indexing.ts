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
  repositoryRoot: string;
  repositoryId: string;
  revisionId: string;
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

export interface IndexingClient {
  previewIndex(revisionId: string): Promise<IndexPreview>;
  indexRepository(revisionId: string): Promise<IndexResult>;
}

export type SafeIndexOutcome =
  | { status: "cancelled"; preview: IndexPreview }
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

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

export function normalizeIndexPreview(value: unknown): IndexPreview {
  const preview = record(value);
  return {
    repositoryRoot: text(preview.repository_root ?? preview.repositoryRoot),
    repositoryId: text(preview.repository_id ?? preview.repositoryId),
    revisionId: text(preview.revision_id ?? preview.revisionId),
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

export async function runSafeIndexing(
  client: IndexingClient,
  revisionId: string,
  confirm: (preview: IndexPreview) => Promise<boolean>
): Promise<SafeIndexOutcome> {
  const preview = await client.previewIndex(revisionId);
  if (preview.uploadsPerformed) {
    throw new Error("The indexing preview unexpectedly reported an upload. Indexing was stopped.");
  }
  if (preview.revisionId !== revisionId) {
    throw new Error("The indexing preview did not match the requested revision. Indexing was stopped.");
  }
  if (!preview.repositoryRoot) {
    throw new Error("The indexing preview did not report the selected workspace root. Indexing was stopped.");
  }
  if (!await confirm(preview)) {
    return { status: "cancelled", preview };
  }
  const result = await client.indexRepository(revisionId);
  return { status: "completed", preview, result };
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
    `Revision: ${preview.revisionId}`,
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
