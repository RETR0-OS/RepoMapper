import { describe, expect, it, vi } from "vitest";
import { createPreviewView } from "../src/previewData.js";
import type { AgentRunTrace, ContrastState, HostToWebviewMessage, WebviewToHostMessage } from "../src/types.js";

async function mountWebview(): Promise<WebviewToHostMessage[]> {
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
  return messages;
}

const health = { state: "unavailable", message: "Preview only." } as const;

function completed(side: "base" | "argus", overrides: Partial<AgentRunTrace>): AgentRunTrace {
  return {
    side, status: "completed", toolsAvailable: [], mcpServers: [], toolCalls: [], filesRead: [], turns: 0, ...overrides
  };
}

function finishedContrast(): ContrastState {
  return {
    question: "How does a request reach the policy store?",
    status: "done",
    message: "Both sides keep every tool the harness gives them. The Argus side also has the Argus tools.",
    base: completed("base", {
      turns: 17,
      toolsAvailable: ["Bash", "Grep", "Read"],
      toolCalls: [{ name: "Grep", detail: "authorize" }, { name: "Read", detail: "api.py" }],
      filesRead: ["api.py"],
      usage: { inputTokens: 20, outputTokens: 4506, cacheReadTokens: 370213, cacheCreationTokens: 51286, thinkingTokens: 1217 },
      costUsd: 0.8113, durationMs: 72084
    }),
    argus: completed("argus", {
      turns: 2,
      toolsAvailable: ["mcp__argus__trace_flow"],
      mcpServers: ["argus"],
      toolCalls: [{ name: "mcp__argus__trace_flow", detail: "policy store" }],
      usage: { inputTokens: 18, outputTokens: 612, cacheReadTokens: 24180, cacheCreationTokens: 9840, thinkingTokens: 190 },
      costUsd: 0.0721, durationMs: 9120
    })
  };
}

function showContrastMode(): void {
  window.dispatchEvent(new MessageEvent<HostToWebviewMessage>("message", {
    data: { type: "view", view: createPreviewView("contrast", "file"), health }
  }));
}

describe("Contrast webview panel", () => {
  it("replaces the graph with the two agent columns", async () => {
    await mountWebview();
    expect(document.querySelector<HTMLElement>("#contrast-panel")!.hidden).toBe(true);
    showContrastMode();
    expect(document.querySelector<HTMLElement>("#contrast-panel")!.hidden).toBe(false);
    expect(document.querySelector<HTMLElement>(".graph-card")!.hidden).toBe(true);
    expect(document.querySelector<HTMLElement>("#path-alternative")!.hidden).toBe(true);
  });

  it("hides the HydraDB-unavailable banner, since Contrast never reads HydraDB", async () => {
    await mountWebview();
    showContrastMode();
    expect(document.querySelector<HTMLElement>("#degraded-banner")!.hidden).toBe(true);
  });

  it("hides the empty metrics box before a question is asked", async () => {
    // Regression: an empty bordered box with no text read as a broken input
    // field to a user who had not asked a question yet.
    await mountWebview();
    showContrastMode();
    expect(document.querySelector<HTMLElement>("#contrast-metrics")!.hidden).toBe(true);
    window.dispatchEvent(new MessageEvent<HostToWebviewMessage>("message", {
      data: { type: "contrast", contrast: { ...finishedContrast(), status: "running" }, health }
    }));
    expect(document.querySelector<HTMLElement>("#contrast-metrics")!.hidden).toBe(false);
  });

  it("opens the panel from a contrast payload alone, with no view message", async () => {
    // Regression: the host used to post only the contrast payload, so the mode
    // never changed and clicking the Contrast tab appeared to do nothing.
    await mountWebview();
    window.dispatchEvent(new MessageEvent<HostToWebviewMessage>("message", {
      data: { type: "contrast", contrast: finishedContrast(), health }
    }));
    expect(document.querySelector<HTMLElement>("#contrast-panel")!.hidden).toBe(false);
    expect(document.querySelector<HTMLElement>(".graph-card")!.hidden).toBe(true);
    const active = document.querySelector<HTMLButtonElement>(".mode-tab.is-active");
    expect(active?.textContent).toBe("Contrast");
    expect(document.querySelector("#contrast-metrics")!.textContent).toContain("426,025 → 34,650");
  });

  it("shows a Contrast tab and switches to it", async () => {
    const messages = await mountWebview();
    const tab = [...document.querySelectorAll<HTMLButtonElement>(".mode-tab")]
      .find((button) => button.textContent === "Contrast");
    expect(tab).toBeDefined();
    tab!.click();
    expect(messages.at(-1)).toEqual({ type: "changeMode", mode: "contrast" });
  });

  it("renders each side's tools, tool calls and measured difference", async () => {
    await mountWebview();
    showContrastMode();
    window.dispatchEvent(new MessageEvent<HostToWebviewMessage>("message", {
      data: { type: "contrast", contrast: finishedContrast(), health }
    }));

    expect(document.querySelector("#contrast-base-status")!.textContent).toBe("Completed");
    expect(document.querySelector("#contrast-base-tools")!.textContent).toContain("Bash, Grep, Read");
    expect(document.querySelectorAll("#contrast-base-calls .contrast-call")).toHaveLength(2);
    expect(document.querySelector("#contrast-argus-calls .contrast-call")!.textContent)
      .toBe("mcp__argus__trace_flow — policy store");

    const metrics = document.querySelector("#contrast-metrics")!.textContent ?? "";
    expect(metrics).toContain("426,025 → 34,650");
    expect(metrics).toContain("391,375 less");
    expect(metrics).not.toContain("still going");
  });

  it("refuses to present an unfinished run as a comparison", async () => {
    await mountWebview();
    showContrastMode();
    const running: ContrastState = {
      ...finishedContrast(),
      status: "running",
      argus: { ...finishedContrast().argus, status: "running" }
    };
    window.dispatchEvent(new MessageEvent<HostToWebviewMessage>("message", {
      data: { type: "contrast", contrast: running, health }
    }));
    expect(document.querySelector(".contrast-caveat")!.textContent).toContain("not final");
  });

  it("says which side did not complete", async () => {
    await mountWebview();
    showContrastMode();
    const cancelled: ContrastState = {
      ...finishedContrast(),
      argus: { ...finishedContrast().argus, status: "cancelled" }
    };
    window.dispatchEvent(new MessageEvent<HostToWebviewMessage>("message", {
      data: { type: "contrast", contrast: cancelled, health }
    }));
    expect(document.querySelector(".contrast-caveat")!.textContent).toContain("not a fair comparison");
    expect(document.querySelector("#contrast-argus-status")!.textContent).toBe("Cancelled");
  });

  it("states that the Argus side only adds tools, and offers no switch to remove any", async () => {
    // The contrast is harness versus harness-with-Argus. There is deliberately
    // no control that takes the agent's own tools away.
    await mountWebview();
    showContrastMode();
    window.dispatchEvent(new MessageEvent<HostToWebviewMessage>("message", {
      data: { type: "contrast", contrast: finishedContrast(), health }
    }));
    expect(document.querySelector("#contrast-note")!.textContent).toContain("also has the Argus tools");
    expect(document.querySelector("#contrast-restrict")).toBeNull();
  });

  it("cancels only while a run is going", async () => {
    const messages = await mountWebview();
    showContrastMode();
    const primary = document.querySelector<HTMLButtonElement>("#primary-action")!;
    expect(primary.textContent).toBe("Cancel contrast");

    primary.click();
    expect(messages.at(-1)).not.toEqual({ type: "cancelContrast" });

    window.dispatchEvent(new MessageEvent<HostToWebviewMessage>("message", {
      data: { type: "contrast", contrast: { ...finishedContrast(), status: "running" }, health }
    }));
    primary.click();
    expect(messages.at(-1)).toEqual({ type: "cancelContrast" });
  });

  it("shows the agent gate inside the panel, not in the hidden graph card", async () => {
    // Regression: the shared agentGate message renders into the graph card's
    // empty state, which Contrast hides. The question box looked broken
    // because the gate was posted but never visible.
    await mountWebview();
    showContrastMode();
    window.dispatchEvent(new MessageEvent<HostToWebviewMessage>("message", {
      data: { type: "agentGate", message: "Contrast needs the Claude Code CLI. Install it and sign in, then try again." }
    }));
    expect(document.querySelector<HTMLElement>("#contrast-panel")!.hidden).toBe(false);
    expect(document.querySelector("#contrast-note")!.textContent).toContain("Claude Code CLI");
    expect(document.querySelector<HTMLElement>("#contrast-gate-button")!.hidden).toBe(false);
    expect(document.querySelector<HTMLElement>("#contrast-metrics")!.hidden).toBe(true);
    expect(document.querySelector<HTMLElement>("#contrast-split")!.hidden).toBe(true);
    // The shared empty state may or may not carry its own hidden flag, but it
    // sits inside .graph-card, which is hidden in Contrast mode regardless.
    expect(document.querySelector<HTMLElement>(".graph-card")!.hidden).toBe(true);
  });

  it("clears the gate once a real contrast run starts", async () => {
    await mountWebview();
    showContrastMode();
    window.dispatchEvent(new MessageEvent<HostToWebviewMessage>("message", {
      data: { type: "agentGate", message: "Contrast needs the Claude Code CLI." }
    }));
    window.dispatchEvent(new MessageEvent<HostToWebviewMessage>("message", {
      data: { type: "contrast", contrast: finishedContrast(), health }
    }));
    expect(document.querySelector<HTMLElement>("#contrast-gate-button")!.hidden).toBe(true);
    expect(document.querySelector<HTMLElement>("#contrast-metrics")!.hidden).toBe(false);
  });

  it("shows each side's final answer, so a person can judge quality directly", async () => {
    await mountWebview();
    showContrastMode();
    const withAnswers: ContrastState = {
      ...finishedContrast(),
      base: { ...finishedContrast().base, answer: "The request enters through api.py." },
      argus: { ...finishedContrast().argus, answer: "The request enters through the router." }
    };
    window.dispatchEvent(new MessageEvent<HostToWebviewMessage>("message", {
      data: { type: "contrast", contrast: withAnswers, health }
    }));
    expect(document.querySelector<HTMLElement>("#contrast-base-answer")!.hidden).toBe(false);
    expect(document.querySelector("#contrast-base-answer")!.textContent).toBe("The request enters through api.py.");
    expect(document.querySelector<HTMLElement>("#contrast-argus-answer")!.hidden).toBe(false);
    expect(document.querySelector("#contrast-argus-answer")!.textContent).toBe("The request enters through the router.");
  });

  it("hides the answer block when the agent has not reported one yet", async () => {
    await mountWebview();
    showContrastMode();
    window.dispatchEvent(new MessageEvent<HostToWebviewMessage>("message", {
      data: { type: "contrast", contrast: { ...finishedContrast(), status: "running" }, health }
    }));
    expect(document.querySelector<HTMLElement>("#contrast-base-answer")!.hidden).toBe(true);
    expect(document.querySelector<HTMLElement>("#contrast-argus-answer")!.hidden).toBe(true);
  });

  it("provides a text equivalent of both trajectories", async () => {
    await mountWebview();
    showContrastMode();
    window.dispatchEvent(new MessageEvent<HostToWebviewMessage>("message", {
      data: { type: "contrast", contrast: finishedContrast(), health }
    }));
    const lines = [...document.querySelectorAll("#contrast-text li")].map((item) => item.textContent);
    expect(lines[0]).toContain("Base agent: Completed");
    expect(lines).toContain("Base agent step 1: Grep — authorize");
    expect(lines.some((line) => line?.startsWith("With Argus:"))).toBe(true);
  });
});
