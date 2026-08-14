import { describe, expect, it } from "vitest";
import { parseWebviewMessage } from "../src/messageValidation.js";

describe("webview message validation", () => {
  it("accepts a valid source-open request with Graph IR coordinates", () => {
    expect(parseWebviewMessage({
      type: "openSource",
      itemId: "edge:1",
      source: { path: "src/api.py", startLine: 10, startColumn: 0, endLine: 10, endColumn: 15 }
    })).toEqual({
      type: "openSource",
      itemId: "edge:1",
      source: { path: "src/api.py", startLine: 10, startColumn: 0, endLine: 10, endColumn: 15 }
    });
  });

  it.each([
    { type: "changeMode", mode: "admin" },
    { type: "changeDepth", depth: "repository" },
    { type: "query", question: "" },
    { type: "openSource", itemId: "x", source: { path: "x", startLine: -1, startColumn: 0, endLine: 1, endColumn: 0 } },
    { type: "persistDisplayState", key: "../../../escape", value: {} },
    { type: "unknown" }
  ])("rejects invalid or unknown host request %j", (message) => {
    expect(parseWebviewMessage(message)).toBeUndefined();
  });

  it("rejects an oversized display state instead of trusting the webview", () => {
    expect(parseWebviewMessage({ type: "persistDisplayState", key: "view:file", value: "x".repeat(50_001) })).toBeUndefined();
  });
});
