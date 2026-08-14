export type CheckpointSlot = "before" | "after";

export interface CheckpointResponse {
  status: string;
  operation: string;
  slot: CheckpointSlot;
  repositoryId: string;
  revisionId: string;
  checkpointId?: string;
  nodeCount: number;
  edgeCount: number;
  writesPerformed: boolean;
  warnings: string[];
}

export interface PublishResponse {
  status: string;
  operation: string;
  repositoryId: string;
  beforeRevisionId: string;
  afterRevisionId: string;
  sourceIds: string[];
  sourceCount: number;
  writesPerformed: boolean;
  hydradb: Record<string, unknown>;
  warnings: string[];
}

export interface LensResponse {
  status: string;
  operation: string;
  lensId: string;
  sourceId: string;
  name: string;
  savedRevisionId: string;
  previousRevisionId?: string;
  anchorNodeIds: string[];
  edgeIds: string[];
  ownership: string;
  writesPerformed: boolean;
  hydradb: Record<string, unknown>;
  warnings: string[];
}

export interface LensDraft {
  name: string;
  purpose: string;
  viewId: string;
}

export interface EvolutionClient {
  checkpoint(slot: CheckpointSlot, revisionId: string): Promise<CheckpointResponse>;
  publishEvolution(beforeRevisionId: string, afterRevisionId: string, confirm: boolean): Promise<PublishResponse>;
  saveLens(draft: LensDraft, confirm: boolean): Promise<LensResponse>;
  acceptLens(lensId: string, viewId: string, confirm: boolean): Promise<LensResponse>;
}

interface PreviewWriteResponse {
  status: string;
  writesPerformed: boolean;
}

export type ConfirmedWriteOutcome<TPreview, TResult> =
  | { status: "cancelled"; preview: TPreview }
  | { status: "completed"; preview: TPreview; result: TResult };

type UnknownRecord = Record<string, unknown>;

function record(value: unknown): UnknownRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as UnknownRecord : {};
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function count(value: unknown): number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : 0;
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

export function normalizeCheckpoint(value: unknown): CheckpointResponse {
  const item = record(value);
  return {
    status: text(item.status),
    operation: text(item.operation),
    slot: item.slot === "after" ? "after" : "before",
    repositoryId: text(item.repository_id ?? item.repositoryId),
    revisionId: text(item.revision_id ?? item.revisionId),
    checkpointId: text(item.checkpoint_id ?? item.checkpointId) || undefined,
    nodeCount: count(item.node_count ?? item.nodeCount),
    edgeCount: count(item.edge_count ?? item.edgeCount),
    writesPerformed: item.writes_performed === true || item.writesPerformed === true,
    warnings: strings(item.warnings)
  };
}

export function normalizePublish(value: unknown): PublishResponse {
  const item = record(value);
  return {
    status: text(item.status),
    operation: text(item.operation),
    repositoryId: text(item.repository_id ?? item.repositoryId),
    beforeRevisionId: text(item.before_revision_id ?? item.beforeRevisionId),
    afterRevisionId: text(item.after_revision_id ?? item.afterRevisionId),
    sourceIds: strings(item.source_ids ?? item.sourceIds),
    sourceCount: count(item.source_count ?? item.sourceCount),
    writesPerformed: item.writes_performed === true || item.writesPerformed === true,
    hydradb: record(item.hydradb),
    warnings: strings(item.warnings)
  };
}

export function normalizeLens(value: unknown): LensResponse {
  const item = record(value);
  return {
    status: text(item.status),
    operation: text(item.operation),
    lensId: text(item.lens_id ?? item.lensId),
    sourceId: text(item.source_id ?? item.sourceId),
    name: text(item.name),
    savedRevisionId: text(item.saved_revision_id ?? item.savedRevisionId),
    previousRevisionId: text(item.previous_revision_id ?? item.previousRevisionId) || undefined,
    anchorNodeIds: strings(item.anchor_node_ids ?? item.anchorNodeIds),
    edgeIds: strings(item.edge_ids ?? item.edgeIds),
    ownership: text(item.ownership),
    writesPerformed: item.writes_performed === true || item.writesPerformed === true,
    hydradb: record(item.hydradb),
    warnings: strings(item.warnings)
  };
}

export async function previewThenConfirm<TPreview extends PreviewWriteResponse, TResult>(
  previewRequest: () => Promise<TPreview>,
  confirm: (preview: TPreview) => Promise<boolean>,
  confirmedRequest: () => Promise<TResult>
): Promise<ConfirmedWriteOutcome<TPreview, TResult>> {
  const preview = await previewRequest();
  if (preview.status !== "preview" || preview.writesPerformed) {
    throw new Error("The service did not return a safe no-write preview. The operation was stopped.");
  }
  if (!await confirm(preview)) {
    return { status: "cancelled", preview };
  }
  return { status: "completed", preview, result: await confirmedRequest() };
}

export function formatCheckpoint(response: CheckpointResponse): string {
  return [
    `Checkpoint: ${response.slot}`,
    `Repository: ${response.repositoryId || "Not reported"}`,
    `Revision: ${response.revisionId}`,
    `Concrete nodes: ${response.nodeCount}`,
    `Exact and recorded relations: ${response.edgeCount}`,
    ...(response.warnings.length ? ["", "Warnings:", ...response.warnings.map((warning) => `• ${warning}`)] : [])
  ].join("\n");
}

export function formatPublish(response: PublishResponse): string {
  const hydradb = record(response.hydradb);
  return [
    `Repository: ${response.repositoryId || "Not reported"}`,
    `Before revision: ${response.beforeRevisionId}`,
    `After revision: ${response.afterRevisionId}`,
    `Delta source cards: ${response.sourceCount}`,
    `HydraDB available: ${hydradb.available === true ? "yes" : "no"}`,
    `HydraDB write attempted: ${hydradb.write_attempted === true ? "yes" : "no"}`,
    ...(response.sourceIds.length ? ["", "HydraDB evolution sources:", ...response.sourceIds.slice(0, 16).map((id) => `• ${id}`)] : []),
    ...(response.warnings.length ? ["", "Warnings:", ...response.warnings.map((warning) => `• ${warning}`)] : [])
  ].join("\n");
}

export function formatLens(response: LensResponse, purpose?: string): string {
  const hydradb = record(response.hydradb);
  return [
    `Lens: ${response.name || response.lensId}`,
    ...(purpose ? [`Purpose: ${purpose}`] : []),
    `Saved revision: ${response.savedRevisionId || "Not reported"}`,
    ...(response.previousRevisionId ? [`Previous revision: ${response.previousRevisionId}`] : []),
    `Grounded anchor nodes: ${response.anchorNodeIds.length}`,
    `Grounded exact edges: ${response.edgeIds.length}`,
    `Ownership: ${response.ownership || "Not reported"}`,
    `HydraDB available: ${hydradb.available === true ? "yes" : "no"}`,
    `HydraDB write attempted: ${hydradb.write_attempted === true ? "yes" : "no"}`,
    ...(response.warnings.length ? ["", "Warnings:", ...response.warnings.map((warning) => `• ${warning}`)] : [])
  ].join("\n");
}

export function publishPreviewMatches(response: PublishResponse, beforeRevisionId: string, afterRevisionId: string): boolean {
  const hydradb = record(response.hydradb);
  return response.status === "preview"
    && response.operation === "publish_delta"
    && !response.writesPerformed
    && response.beforeRevisionId === beforeRevisionId
    && response.afterRevisionId === afterRevisionId
    && response.sourceCount > 0
    && response.sourceCount === response.sourceIds.length
    && response.sourceIds.every(Boolean)
    && new Set(response.sourceIds).size === response.sourceIds.length
    && hydradb.write_attempted === false;
}

export function lensPreviewMatches(
  response: LensResponse,
  operation: "save_lens" | "accept_lens",
  revisionId: string,
  lensId?: string
): boolean {
  const hydradb = record(response.hydradb);
  return response.status === "preview"
    && response.operation === operation
    && !response.writesPerformed
    && response.savedRevisionId === revisionId
    && Boolean(response.lensId)
    && (lensId === undefined || response.lensId === lensId)
    && Boolean(response.sourceId)
    && response.anchorNodeIds.length > 0
    && response.edgeIds.length > 0
    && response.ownership === "shared"
    && hydradb.write_attempted === false;
}

export function checkpointWasCaptured(response: CheckpointResponse, slot: CheckpointSlot, revisionId: string): boolean {
  return response.status === "captured"
    && response.operation === "capture_checkpoint"
    && response.writesPerformed
    && response.slot === slot
    && response.revisionId === revisionId
    && Boolean(response.checkpointId)
    && response.nodeCount > 0;
}

export function publishIsReady(response: PublishResponse, beforeRevisionId: string, afterRevisionId: string): boolean {
  const hydradb = record(response.hydradb);
  return response.status === "ready"
    && response.operation === "publish_delta"
    && response.writesPerformed
    && response.beforeRevisionId === beforeRevisionId
    && response.afterRevisionId === afterRevisionId
    && response.sourceCount > 0
    && response.sourceCount === response.sourceIds.length
    && response.sourceIds.every(Boolean)
    && new Set(response.sourceIds).size === response.sourceIds.length
    && hydradb.available === true
    && hydradb.write_attempted === true;
}

export function lensWriteIsReady(response: LensResponse, revisionId: string): boolean {
  const hydradb = record(response.hydradb);
  return response.status === "ready"
    && ["save_lens", "accept_lens"].includes(response.operation)
    && response.writesPerformed
    && response.savedRevisionId === revisionId
    && Boolean(response.lensId)
    && Boolean(response.sourceId)
    && response.anchorNodeIds.length > 0
    && response.anchorNodeIds.every(Boolean)
    && response.edgeIds.length > 0
    && response.edgeIds.every(Boolean)
    && response.ownership === "shared"
    && hydradb.available === true
    && hydradb.write_attempted === true;
}

export function validateLensName(value: string): string | undefined {
  const trimmed = value.trim();
  if (!trimmed) return "Enter a concise System Lens name.";
  if (trimmed.length > 80) return "System Lens names must be 80 characters or fewer.";
  return undefined;
}

export function validateLensPurpose(value: string): string | undefined {
  const trimmed = value.trim();
  if (!trimmed) return "Describe the grounded flow this lens preserves.";
  if (trimmed.length > 240) return "System Lens purposes must be 240 characters or fewer.";
  return undefined;
}
