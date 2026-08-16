import { describe, expect, it, vi } from "vitest";
import { createPreviewView } from "../src/previewData.js";
import type { HostToWebviewMessage, WebviewToHostMessage } from "../src/types.js";

describe("Observe webview interaction", () => {
  it("keeps pause state across view updates and exposes the bounded buffer count", async () => {
    vi.resetModules();
    document.body.innerHTML = '<div id="app"></div>';
    const messages: WebviewToHostMessage[] = [];
    Object.defineProperty(window, "acquireVsCodeApi", {
      configurable: true,
      value: () => ({
        postMessage: (message: WebviewToHostMessage) => messages.push(message),
        getState: () => undefined,
        setState: () => undefined
      })
    });
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined })
    });
    await import("../src/webview/main.js");
    const view = createPreviewView("observe", "symbol");
    view.nodes[0] = { ...view.nodes[0]!, state: "edited" };
    window.dispatchEvent(new MessageEvent<HostToWebviewMessage>("message", {
      data: { type: "view", view, health: { state: "unavailable", message: "Preview only." } }
    }));

    const primary = document.querySelector<HTMLButtonElement>("#primary-action")!;
    expect(primary.textContent).toBe("Pause traversal");
    expect(document.querySelector(`[data-node-id="${view.nodes[0]!.id}"]`)?.classList.contains("state-edited")).toBe(true);
    primary.click();
    expect(messages.at(-1)).toEqual({ type: "setObservePaused", paused: true });

    window.dispatchEvent(new MessageEvent<HostToWebviewMessage>("message", {
      data: { type: "observeStatus", active: true, paused: true, bufferedCount: 3, sessionId: "session-1" }
    }));
    expect(primary.textContent).toBe("Resume traversal (3)");
    window.dispatchEvent(new MessageEvent<HostToWebviewMessage>("message", {
      data: { type: "view", view, health: { state: "unavailable", message: "Preview only." } }
    }));
    expect(primary.textContent).toBe("Resume traversal (3)");
    primary.click();
    expect(messages.at(-1)).toEqual({ type: "setObservePaused", paused: false });

    window.dispatchEvent(new MessageEvent<HostToWebviewMessage>("message", {
      data: { type: "observeStatus", active: false, paused: false, bufferedCount: 0, message: "Restart required." }
    }));
    expect(primary.textContent).toBe("Restart follow");
    primary.click();
    expect(messages.at(-1)).toEqual({ type: "retry" });
  });
});
