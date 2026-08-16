import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPreviewView } from "../src/previewData.js";
import type { HostToWebviewMessage, WebviewToHostMessage } from "../src/types.js";

interface Harness {
  messages: WebviewToHostMessage[];
  setPointerCapture: ReturnType<typeof vi.fn>;
}

/** Load one clean webview instance with the pointer APIs jsdom does not supply. */
async function mountWebview(): Promise<Harness> {
  vi.resetModules();
  document.body.innerHTML = '<div id="app"></div>';
  const messages: WebviewToHostMessage[] = [];
  const setPointerCapture = vi.fn();
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
  Object.defineProperty(Element.prototype, "setPointerCapture", { configurable: true, value: setPointerCapture });
  Object.defineProperty(Element.prototype, "hasPointerCapture", { configurable: true, value: () => true });
  Object.defineProperty(Element.prototype, "releasePointerCapture", { configurable: true, value: vi.fn() });
  if (!globalThis.CSS?.escape) {
    Object.defineProperty(globalThis, "CSS", { configurable: true, value: { escape: (value: string) => value } });
  }
  await import("../src/webview/main.js");
  Object.defineProperty(document.querySelector("#graph")!, "getBoundingClientRect", {
    configurable: true,
    value: () => ({ left: 0, top: 0, width: 1000, height: 590, right: 1000, bottom: 590, x: 0, y: 0, toJSON: () => ({}) })
  });
  return { messages, setPointerCapture };
}

/** jsdom has no PointerEvent, so carry the pointer fields on a MouseEvent. */
function pointer(target: Element, type: string, clientX: number, clientY: number): void {
  const event = new MouseEvent(type, { bubbles: true, cancelable: true, button: 0, clientX, clientY });
  Object.defineProperty(event, "pointerId", { value: 1 });
  target.dispatchEvent(event);
}

function card(nodeId: string): SVGGElement {
  return document.querySelector<SVGGElement>(`[data-node-id="${nodeId}"]`)!;
}

function inspectorTitle(): string {
  return document.querySelector("#inspector-content .inspector-title h3")?.textContent ?? "";
}

describe("graph node selection", () => {
  let harness: Harness;

  beforeEach(async () => {
    harness = await mountWebview();
    const view = createPreviewView("repository", "file");
    window.dispatchEvent(new MessageEvent<HostToWebviewMessage>("message", {
      data: { type: "view", view, health: { state: "unavailable", message: "Preview only." } }
    }));
  });

  it("shows the evidence of a node that a still click selects", () => {
    const view = createPreviewView("repository", "file");
    const target = view.nodes[2]!;
    expect(inspectorTitle()).toBe(view.nodes[0]!.displayName);

    const group = card(target.id);
    pointer(group, "pointerdown", 300, 200);
    pointer(group, "pointerup", 300, 200);
    group.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    expect(inspectorTitle()).toBe(target.displayName);
    expect(group.classList.contains("is-selected") || card(target.id).classList.contains("is-selected")).toBe(true);
    expect(harness.messages).toContainEqual({ type: "selectItem", itemId: target.id, itemKind: "node" });
    // A capture set on press would move the click event off the card.
    expect(harness.setPointerCapture).not.toHaveBeenCalled();
  });

  it("takes the pointer capture only after the press becomes a drag", () => {
    const view = createPreviewView("repository", "file");
    const target = view.nodes[1]!;
    const group = card(target.id);

    pointer(group, "pointerdown", 300, 200);
    pointer(document.querySelector("#graph")!, "pointermove", 301, 200);
    expect(harness.setPointerCapture).not.toHaveBeenCalled();

    pointer(document.querySelector("#graph")!, "pointermove", 340, 220);
    expect(harness.setPointerCapture).toHaveBeenCalledTimes(1);
  });

  it("selects but does not open source when a drag ends", () => {
    const view = createPreviewView("repository", "file");
    const target = view.nodes[3]!;
    const group = card(target.id);

    pointer(group, "pointerdown", 300, 200);
    pointer(document.querySelector("#graph")!, "pointermove", 360, 240);
    pointer(document.querySelector("#graph")!, "pointerup", 360, 240);
    card(target.id).dispatchEvent(new MouseEvent("click", { bubbles: true }));

    expect(inspectorTitle()).toBe(target.displayName);
    expect(harness.messages).toContainEqual({ type: "selectItem", itemId: target.id, itemKind: "node" });
    expect(harness.messages.some((message) => message.type === "openSource")).toBe(false);
  });

  it("opens the exact source of the clicked node", () => {
    const view = createPreviewView("repository", "file");
    const target = view.nodes[2]!;
    const group = card(target.id);

    pointer(group, "pointerdown", 300, 200);
    pointer(group, "pointerup", 300, 200);
    group.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    expect(harness.messages).toContainEqual({ type: "openSource", itemId: target.id, source: target.source });
  });

  it("keeps the chosen node when the host resends the same view", () => {
    const view = createPreviewView("repository", "file");
    const target = view.nodes[4]!;
    const group = card(target.id);
    pointer(group, "pointerdown", 300, 200);
    pointer(group, "pointerup", 300, 200);
    group.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(inspectorTitle()).toBe(target.displayName);

    window.dispatchEvent(new MessageEvent<HostToWebviewMessage>("message", {
      data: {
        type: "view",
        view: createPreviewView("repository", "file"),
        health: { state: "unavailable", message: "Preview only." }
      }
    }));

    expect(inspectorTitle()).toBe(target.displayName);
  });

  it("resets the selection when a different view arrives", () => {
    const view = createPreviewView("repository", "file");
    const target = view.nodes[4]!;
    const group = card(target.id);
    pointer(group, "pointerdown", 300, 200);
    pointer(group, "pointerup", 300, 200);
    group.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    const explore = createPreviewView("explore", "file");
    window.dispatchEvent(new MessageEvent<HostToWebviewMessage>("message", {
      data: { type: "view", view: explore, health: { state: "unavailable", message: "Preview only." } }
    }));

    expect(inspectorTitle()).toBe(explore.nodes[0]!.displayName);
  });
});
