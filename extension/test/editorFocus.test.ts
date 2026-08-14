import * as path from "node:path";
import { describe, expect, it, vi } from "vitest";
import { captureEditorFocus, focusedViewRequest } from "../src/editorFocus.js";
import { RepositoryServiceClient } from "../src/serviceClient.js";

const root = path.resolve("C:/work/repository");

describe("editor-native focused views", () => {
  it("captures only a workspace-relative file and converts the selected line to one-based", () => {
    const focus = captureEditorFocus({
      scheme: "file",
      absolutePath: path.resolve(root, "Src/Payments/Api.ts"),
      activeLine: 40
    }, [root]);

    expect(focus).toEqual({ relativePath: "Src/Payments/Api.ts", line: 41 });
    expect(focus?.relativePath).not.toContain(root);
    expect(path.isAbsolute(focus?.relativePath ?? "")).toBe(false);
  });

  it("returns no focus when there is no active editor", () => {
    expect(captureEditorFocus(undefined, [root])).toBeUndefined();
  });

  it.each([
    { scheme: "untitled", absolutePath: path.resolve(root, "scratch.ts"), activeLine: 0 },
    { scheme: "file", absolutePath: path.resolve(root, "../outside.ts"), activeLine: 0 },
    { scheme: "file", absolutePath: path.resolve(`${root}-backup`, "lookalike.ts"), activeLine: 0 }
  ])("rejects an editor outside a concrete workspace file: %j", (editor) => {
    expect(captureEditorFocus(editor, [root])).toBeUndefined();
  });

  it("uses distinct, honest prompts without claiming the cursor identifies a symbol", () => {
    const focus = { relativePath: "src/payments/api.py", line: 17 };
    const show = focusedViewRequest("show", focus);
    const callers = focusedViewRequest("callers", focus);
    const trace = focusedViewRequest("trace", focus);
    const tests = focusedViewRequest("tests", focus);

    expect(show.mode).toBe("repository");
    expect(callers.mode).toBe("explore");
    expect(trace.mode).toBe("trace");
    expect(tests.mode).toBe("explore");
    expect(show.question).toContain("Do not infer an exact symbol");
    expect(callers.question).toContain("only when returned source evidence identifies it");
    expect(trace.question).toContain("Do not invent an exact symbol");
    expect(tests.question).toContain("without guessing");
    for (const request of [show, callers, trace, tests]) {
      expect(request.question).toContain('workspace file "src/payments/api.py" at one-based line 17');
    }
    expect(new Set([show.question, callers.question, trace.question, tests.question]).size).toBe(4);
  });

  it("encodes the bounded focus question on GET /api/views/{mode}", async () => {
    const fetchMock = vi.fn(async (_input: string | URL | Request, _init?: RequestInit) => ({
      ok: true,
      status: 200,
      json: async () => ({
        view_id: "focused", revision_id: "rev-1", mode: "trace", depth: "symbol",
        nodes: [], edges: [], warnings: [],
        hydradb: { available: true, database: "repo", collections: ["current"], graph_context: true },
        budget: { requested_nodes: 20, returned_nodes: 0, requested_edges: 30, returned_edges: 0, truncated: false }
      })
    } as Response));
    const client = new RepositoryServiceClient({
      baseUrl: "http://127.0.0.1:8765",
      timeoutMs: 1000,
      fetchImpl: fetchMock as typeof fetch
    });
    const request = focusedViewRequest("trace", { relativePath: "src/api route.py", line: 9 });

    await client.getView(request.mode, "symbol", { question: request.question });

    expect(fetchMock).toHaveBeenCalledOnce();
    const rawUrl = String(fetchMock.mock.calls[0]?.[0]);
    const url = new URL(rawUrl);
    expect(url.pathname).toBe("/api/views/trace");
    expect(url.searchParams.get("depth")).toBe("symbol");
    expect(url.searchParams.get("question")).toBe(request.question);
    expect(rawUrl).not.toContain("api route.py");
    expect(rawUrl).not.toContain("C:\\");
    expect(rawUrl).toContain("question=");
  });
});
