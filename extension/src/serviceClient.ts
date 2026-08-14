import type { GraphDepth, GraphView, ServiceHealth, ViewMode, ViewRequestContext } from "./types.js";
import { normalizeIndexPreview, normalizeIndexResult, type IndexPreview, type IndexResult } from "./indexing.js";
import {
  normalizeCheckpoint,
  normalizeLens,
  normalizePublish,
  type CheckpointResponse,
  type CheckpointSlot,
  type LensDraft,
  type LensResponse,
  type PublishResponse
} from "./evolution.js";
import { normalizeGraphView, normalizeHealth } from "./viewAdapter.js";

export class ServiceError extends Error {
  public constructor(
    message: string,
    public readonly status?: number,
    public readonly causeValue?: unknown
  ) {
    super(message);
    this.name = "ServiceError";
  }
}

export interface ServiceClientOptions {
  baseUrl: string;
  timeoutMs: number;
  fetchImpl?: typeof fetch;
}

export function requireLoopbackServiceUrl(value: string): string {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new ServiceError("Repository service URL must be a valid loopback HTTP URL.");
  }
  const loopbackHosts = new Set(["localhost", "127.0.0.1", "[::1]", "::1"]);
  if (!loopbackHosts.has(url.hostname.toLowerCase()) || !["http:", "https:"].includes(url.protocol)) {
    throw new ServiceError("Repository service URL must use localhost, 127.0.0.1, or ::1.");
  }
  if (url.username || url.password || url.search || url.hash) {
    throw new ServiceError("Repository service URL cannot contain credentials, query parameters, or fragments.");
  }
  return url.toString().replace(/\/+$/, "");
}

export class RepositoryServiceClient {
  private readonly fetchImpl: typeof fetch;
  private readonly baseUrl: string;

  public constructor(private readonly options: ServiceClientOptions) {
    this.baseUrl = requireLoopbackServiceUrl(options.baseUrl);
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  public async health(): Promise<ServiceHealth> {
    return normalizeHealth(await this.request<unknown>("/health", { method: "GET" }));
  }

  public async getView(mode: ViewMode, depth: GraphDepth, context: ViewRequestContext = {}): Promise<GraphView> {
    const query = new URLSearchParams({ depth });
    if (context.question) query.set("question", context.question);
    if (context.beforeRevision) query.set("before_revision", context.beforeRevision);
    if (context.afterRevision) query.set("after_revision", context.afterRevision);
    if (context.lens) query.set("lens", context.lens);
    return normalizeGraphView(await this.request<unknown>(`/api/views/${mode}?${query.toString()}`, { method: "GET" }), mode);
  }

  public async query(question: string, depth: GraphDepth): Promise<GraphView> {
    const response = await this.request<unknown>("/api/query", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ question, depth, query_by: "hybrid", mode: "thinking", graph_context: true })
    });
    return normalizeGraphView(response, "trace");
  }

  public async runAction(mode: ViewMode, selectedId?: string): Promise<{ message: string; view?: GraphView }> {
    const response = await this.request<Record<string, unknown>>(`/api/views/${mode}/action`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ selected_id: selectedId })
    });
    return {
      message: typeof response.message === "string" ? response.message : "Action completed.",
      view: response.view ? normalizeGraphView(response.view, mode) : undefined
    };
  }

  public async sidebar(): Promise<unknown> {
    return this.request<unknown>("/api/sidebar", { method: "GET" });
  }

  public async previewIndex(revisionId: string): Promise<IndexPreview> {
    const response = await this.request<unknown>("/api/index/preview", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ revision_id: revisionId })
    });
    return normalizeIndexPreview(response);
  }

  public async indexRepository(revisionId: string): Promise<IndexResult> {
    const response = await this.request<unknown>("/api/index", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ revision_id: revisionId })
    });
    return normalizeIndexResult(response);
  }

  public async checkpoint(slot: CheckpointSlot, revisionId: string): Promise<CheckpointResponse> {
    const response = await this.request<unknown>(`/api/evolution/checkpoints/${slot}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ revision_id: revisionId })
    });
    return normalizeCheckpoint(response);
  }

  public async publishEvolution(beforeRevisionId: string, afterRevisionId: string, confirm: boolean): Promise<PublishResponse> {
    const response = await this.request<unknown>("/api/evolution/publish", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ before_revision_id: beforeRevisionId, after_revision_id: afterRevisionId, confirm })
    });
    return normalizePublish(response);
  }

  public async saveLens(draft: LensDraft, confirm: boolean): Promise<LensResponse> {
    const response = await this.request<unknown>("/api/lenses", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: draft.name, purpose: draft.purpose, view_id: draft.viewId, notes: null, confirm })
    });
    return normalizeLens(response);
  }

  public async acceptLens(lensId: string, viewId: string, confirm: boolean): Promise<LensResponse> {
    const response = await this.request<unknown>(`/api/lenses/${encodeURIComponent(lensId)}/accept`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ view_id: viewId, confirm })
    });
    return normalizeLens(response);
  }

  private async request<T>(path: string, init: RequestInit): Promise<T> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.options.timeoutMs);
    try {
      const response = await this.fetchImpl(`${this.baseUrl}${path}`, { ...init, signal: controller.signal });
      if (!response.ok) {
        throw new ServiceError(`Repository service returned ${response.status}.`, response.status);
      }
      return (await response.json()) as T;
    } catch (error) {
      if (error instanceof ServiceError) {
        throw error;
      }
      const message = error instanceof Error && error.name === "AbortError"
        ? `Repository service timed out after ${this.options.timeoutMs} ms.`
        : "Repository service is unavailable.";
      throw new ServiceError(message, undefined, error);
    } finally {
      clearTimeout(timeout);
    }
  }
}
