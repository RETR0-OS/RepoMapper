import * as vscode from "vscode";
import { RepositoryMapCodeLensProvider } from "./codeLensProvider.js";
import { GraphPanel } from "./graphPanel.js";
import { RepositorySidebar } from "./sidebar.js";
import type { ServiceHealth, ViewMode } from "./types.js";

export function activate(context: vscode.ExtensionContext): void {
  const repositoryStatus = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 90);
  repositoryStatus.name = "Repository Map";
  repositoryStatus.text = "$(type-hierarchy) Repository Map";
  repositoryStatus.tooltip = "Open the repository observability map";
  repositoryStatus.command = "hydra.openRepositoryMap";
  repositoryStatus.show();

  const hydraStatus = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 89);
  hydraStatus.name = "HydraDB status";
  hydraStatus.command = "hydra.openRepositoryMap";
  hydraStatus.text = "$(warning) HydraDB · unavailable";
  hydraStatus.tooltip = "The local repository service has not reported a ready revision.";
  hydraStatus.show();

  const sidebar = new RepositorySidebar();
  const updateHealth = (health: ServiceHealth): void => {
    sidebar.setHealth(health);
    if (health.state === "ready") {
      hydraStatus.text = `$(database) HydraDB · ${health.revision ?? "current revision ready"}`;
      hydraStatus.tooltip = `${health.database ?? "HydraDB"} · ${health.collection ?? "current collection"}`;
      hydraStatus.backgroundColor = undefined;
    } else if (health.state === "indexing") {
      hydraStatus.text = "$(sync~spin) HydraDB · indexing";
      hydraStatus.tooltip = health.message ?? "Indexing changed repository sources.";
      hydraStatus.backgroundColor = undefined;
    } else {
      hydraStatus.text = "$(warning) HydraDB · unavailable";
      hydraStatus.tooltip = health.message ?? "Repository graph features are paused.";
      hydraStatus.backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
    }
  };

  const panel = new GraphPanel(context, updateHealth);
  const show = (mode: ViewMode) => panel.show(mode);
  const registrations: Array<[string, (...args: unknown[]) => unknown]> = [
    ["hydra.openRepositoryMap", (mode?: unknown) => show(isMode(mode) ? mode : "repository")],
    ["hydra.showInRepositoryMap", () => show("repository")],
    ["hydra.showCallersAndCallees", () => show("explore")],
    ["hydra.traceFlowFromHere", () => show("trace")],
    ["hydra.findTests", () => show("explore")],
    ["hydra.compareGraph", () => show("compare")],
    ["hydra.saveSystemLens", () => show("preserve")],
    ["hydra.followAgent", () => show("observe")],
    ["hydra.refresh", () => panel.refresh()],
    ["hydra.askAboutCode", async () => {
      const question = await vscode.window.showInputBox({
        title: "Ask HydraDB about this code",
        prompt: "Ask a concrete repository or flow question",
        placeHolder: "How does an incoming request reach a database write?",
        ignoreFocusOut: true
      });
      if (question) {
        await panel.show("trace", question);
      }
    }],
    ["hydra.configureService", async () => {
      const configuration = vscode.workspace.getConfiguration("hydra");
      const current = configuration.get<string>("serviceUrl", "http://127.0.0.1:8765");
      const serviceUrl = await vscode.window.showInputBox({
        title: "Configure repository service",
        value: current,
        prompt: "Local HTTP URL for the Python repository service",
        validateInput: (value) => /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?(?:\/.*)?$/i.test(value)
          ? undefined : "Use a local HTTP URL, for example http://127.0.0.1:8765."
      });
      if (serviceUrl) {
        await configuration.update("serviceUrl", serviceUrl, vscode.ConfigurationTarget.Workspace);
        await panel.refresh();
      }
    }]
  ];
  registrations.forEach(([command, handler]) => context.subscriptions.push(vscode.commands.registerCommand(command, handler)));

  context.subscriptions.push(
    repositoryStatus,
    hydraStatus,
    sidebar,
    panel,
    vscode.languages.registerCodeLensProvider({ scheme: "file" }, new RepositoryMapCodeLensProvider())
  );
  void panel.refresh();
}

export function deactivate(): void {}

function isMode(value: unknown): value is ViewMode {
  return typeof value === "string" && ["repository", "explore", "trace", "observe", "compare", "preserve"].includes(value);
}
