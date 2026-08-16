import type { GraphDepth, GraphView, ServiceHealth, ViewMode, ViewRequestContext } from "./types.js";
import { normalizeIndexJob, normalizeIndexPreview, type IndexJob, type IndexPreview } from "./indexing.js";
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
import {
  normalizeObserveComplete,
  normalizeObserveRecorded,
  normalizeObserveSession,
  type ObserveCompleteResponse,
  type ObserveRecordedResponse,
  type ObserveSessionResponse
} from "./observe.js";
import { normalizeGraphView, normalizeHealth } from "./viewAdapter.js";
import type { RepositoryScope } from "./workspaceScope.js";

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
  baseUrlProvider?: () => Promise<string>;
  authorizationProvider?: () => Promise<string>;
  timeoutMs: number;
  repositoryScope?: RepositoryScope;
  fetchImpl?: typeof fetch;
  sessionInvalidator?: () => void;
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

/**
 * Keep the managed runtime's own failure reason. A crashed service, a failed integrity
 * check, or a lost port lock each explain themselves, and that sentence must reach the
 * user instead of a generic transport message.
 */
async function runtimeStep(provider: () => Promise<string>): Promise<string> {
  try {
    return await provider();
  } catch (error) {
    if (error instanceof ServiceError) throw error;
    throw new ServiceError(
      error instanceof Error && error.message.trim()
        ? error.message.trim()
        : "Repository service runtime could not start.",
      undefined,
      error
    );
  }
}

/** Return the service's own failure reason, so a status code alone never hides the cause. */
async function failureDetail(response: Response): Promise<string> {
  try {
    const parsed = JSON.parse(await response.text()) as unknown;
    if (!parsed || typeof parsed !== "object") return "";
    const detail = (parsed as Record<string, unknown>).detail;
    return typeof detail === "string" && detail.trim() ? ` ${detail.trim().slice(0, 200)}` : "";
  } catch {
    return "";
  }
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

  public async testConnection(): Promise<void> {
    const response = await this.request<Record<string, unknown>>("/api/setup/test", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({})
    });
    if (response.status !== "connected" || response.write_performed !== false) {
      throw new ServiceError("HydraDB connection test did not return a safe read-only result.");
    }
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

  public async previewIndex(): Promise<IndexPreview> {
    const response = await this.request<unknown>("/api/index/preview", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({})
    });
    return normalizeIndexPreview(response);
  }

  public async startIndexJob(previewToken: string): Promise<IndexJob> {
    return normalizeIndexJob(await this.request<unknown>("/api/index", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ preview_token: previewToken })
    }));
  }

  public async indexJobStatus(jobId: string): Promise<IndexJob> {
    return normalizeIndexJob(await this.request<unknown>(`/api/index/jobs/${encodeURIComponent(jobId)}`, { method: "GET" }));
  }

  public async cancelIndexJob(jobId: string): Promise<IndexJob> {
    return normalizeIndexJob(await this.request<unknown>(`/api/index/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({})
    }));
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

  public async startObserveSession(): Promise<ObserveSessionResponse> {
    return normalizeObserveSession(await this.request<unknown>("/api/observe/sessions", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({})
    }));
  }

  public async completeObserveSession(sessionId: string): Promise<ObserveCompleteResponse> {
    return normalizeObserveComplete(await this.request<unknown>(`/api/observe/sessions/${encodeURIComponent(sessionId)}/complete`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({})
    }));
  }

  public async observeEvents(sessionId: string, afterEventId?: string): Promise<unknown> {
    const query = new URLSearchParams({ session_id: sessionId });
    if (afterEventId) query.set("after_event_id", afterEventId);
    return this.request<unknown>(`/api/events?${query.toString()}`, { method: "GET" });
  }

  public async getViewById(viewId: string): Promise<GraphView> {
    return normalizeGraphView(await this.request<unknown>(`/api/views/by-id/${encodeURIComponent(viewId)}`, { method: "GET" }), "observe");
  }

  public async recordObserveInteraction(
    kind: "selection" | "evidence-opened",
    viewId: string,
    itemId: string,
    itemKind: "node" | "edge"
  ): Promise<ObserveRecordedResponse> {
    return normalizeObserveRecorded(await this.request<unknown>(`/api/views/${encodeURIComponent(viewId)}/${kind}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ item_id: itemId, item_kind: itemKind })
    }));
  }

  public async recordWorkspaceChange(viewId: string, path: string): Promise<ObserveRecordedResponse> {
    return normalizeObserveRecorded(await this.request<unknown>(`/api/views/${encodeURIComponent(viewId)}/workspace-change`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ path })
    }));
  }

  private async request<T>(path: string, init: RequestInit): Promise<T> {
    try {
      return await this.attempt<T>(path, init);
    } catch (error) {
      // Only HTTP 401 proves the project grant is stale; timeouts and dropped connections must keep the session.
      if (!(error instanceof ServiceError) || error.status !== 401) throw error;
      this.options.sessionInvalidator?.();
      // A retry may only replay a body that was never consumed by the first attempt.
      if (init.body !== undefined && init.body !== null && typeof init.body !== "string") throw error;
      return await this.attempt<T>(path, init);
    }
  }

  private async attempt<T>(path: string, init: RequestInit): Promise<T> {
    // The runtime reports why it could not start, and that reason is the only actionable
    // one. It is resolved outside the transport handler below, which would otherwise
    // replace every cause with the generic "service is unavailable" sentence.
    //
    // Starting the runtime also runs before the abort timer, so its cost is not part of
    // the request budget. A slow handshake therefore looks like a slow service. Both
    // durations are measured, and both are named in the timeout message.
    const handshakeStart = Date.now();
    const headers = new Headers(init.headers);
    if (this.options.authorizationProvider) {
      headers.set("Authorization", await runtimeStep(this.options.authorizationProvider));
    }
    if (this.options.repositoryScope) {
      headers.set(
        "X-Hydra-Repository-Root",
        encodeURIComponent(this.options.repositoryScope.repositoryRoot)
      );
      headers.set("X-Hydra-Repository-Id", this.options.repositoryScope.repositoryId);
    }
    const configuredBaseUrl = this.options.baseUrlProvider
      ? requireLoopbackServiceUrl(await runtimeStep(this.options.baseUrlProvider))
      : this.baseUrl;
    const handshakeMs = Date.now() - handshakeStart;

    const controller = new AbortController();
    // Every attempt gets its own budget, so a retry never inherits the first attempt's expired timer.
    const timeout = setTimeout(() => controller.abort(), this.options.timeoutMs);
    const requestStart = Date.now();
    try {
      const response = await this.fetchImpl(`${configuredBaseUrl}${path}`, {
        ...init,
        headers,
        signal: controller.signal
      });
      if (!response.ok) {
        throw new ServiceError(
          `Repository service returned ${response.status}.${await failureDetail(response)}`,
          response.status
        );
      }
      return (await response.json()) as T;
    } catch (error) {
      if (error instanceof ServiceError) {
        throw error;
      }
      const requestMs = Date.now() - requestStart;
      const message = error instanceof Error && error.name === "AbortError"
        ? `Repository service timed out after ${requestMs} ms `
          + `of the ${this.options.timeoutMs} ms budget for ${path}`
          + `${handshakeMs > 0 ? `, plus ${handshakeMs} ms to start the runtime` : ""}.`
        : "Repository service is unavailable.";
      throw new ServiceError(message, undefined, error);
    } finally {
      clearTimeout(timeout);
    }
  }
}
