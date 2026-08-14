import * as vscode from "vscode";
import { RepositoryMapCodeLensProvider } from "./codeLensProvider.js";
import { captureEditorFocus, focusedViewRequest, type FocusAction } from "./editorFocus.js";
import { GraphPanel } from "./graphPanel.js";
import {
  failedIndexSummary,
  formatIndexPreview,
  readyIndexSummary,
  runSafeIndexing,
  validateRevisionId,
  type IndexingClient
} from "./indexing.js";
import { RepositoryServiceClient } from "./serviceClient.js";
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
    } else if (health.state === "unverified") {
      hydraStatus.text = "$(question) HydraDB · revision unverified";
      hydraStatus.tooltip = health.message ?? "HydraDB is configured, but no verified revision is ready.";
      hydraStatus.backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
    } else {
      hydraStatus.text = "$(warning) HydraDB · unavailable";
      hydraStatus.tooltip = health.message ?? "Repository graph features are paused.";
      hydraStatus.backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
    }
  };

  const panel = new GraphPanel(context, updateHealth);
  const configuredClient = (): RepositoryServiceClient => {
    const configuration = vscode.workspace.getConfiguration("hydra");
    return new RepositoryServiceClient({
      baseUrl: configuration.get<string>("serviceUrl", "http://127.0.0.1:8765"),
      timeoutMs: configuration.get<number>("indexTimeoutMs", 120000)
    });
  };
  const show = (mode: ViewMode) => panel.show(mode);
  const showFocused = async (action: FocusAction): Promise<void> => {
    const editor = vscode.window.activeTextEditor;
    const focus = captureEditorFocus(editor ? {
      scheme: editor.document.uri.scheme,
      absolutePath: editor.document.uri.fsPath,
      activeLine: editor.selection.active.line
    } : undefined, vscode.workspace.workspaceFolders?.map((folder) => folder.uri.fsPath) ?? []);
    if (!focus) {
      void vscode.window.showWarningMessage("Open a source file inside the active workspace before requesting a focused repository view.");
      return;
    }
    const request = focusedViewRequest(action, focus);
    await panel.showFocused(request.mode, request.question);
  };
  const registrations: Array<[string, (...args: unknown[]) => unknown]> = [
    ["hydra.openRepositoryMap", (mode?: unknown) => show(isMode(mode) ? mode : "repository")],
    ["hydra.showInRepositoryMap", () => showFocused("show")],
    ["hydra.showCallersAndCallees", () => showFocused("callers")],
    ["hydra.traceFlowFromHere", () => showFocused("trace")],
    ["hydra.findTests", () => showFocused("tests")],
    ["hydra.compareGraph", () => show("compare")],
    ["hydra.saveSystemLens", () => show("preserve")],
    ["hydra.followAgent", () => show("observe")],
    ["hydra.refresh", () => panel.refresh()],
    ["hydra.indexRepository", async () => {
      const revisionInput = await vscode.window.showInputBox({
        title: "Index workspace with HydraDB",
        prompt: "Enter the explicit revision ID that will identify this verified repository state",
        placeHolder: "For example: git SHA or demo-before-auth-change",
        ignoreFocusOut: true,
        validateInput: validateRevisionId
      });
      if (revisionInput === undefined) {
        return;
      }
      const revisionId = revisionInput.trim();
      const invalidRevision = validateRevisionId(revisionId);
      if (invalidRevision) {
        void vscode.window.showErrorMessage(invalidRevision);
        return;
      }
      const client = configuredClient();
      const progressClient: IndexingClient = {
        previewIndex: async (revision) => await vscode.window.withProgress({
          location: vscode.ProgressLocation.Notification,
          title: `Analyzing configured repository root for ${revision}…`,
          cancellable: false
        }, () => client.previewIndex(revision)),
        indexRepository: async (revision) => await vscode.window.withProgress({
          location: vscode.ProgressLocation.Notification,
          title: `Uploading revision ${revision} to HydraDB…`,
          cancellable: false
        }, () => client.indexRepository(revision))
      };
      try {
        const outcome = await runSafeIndexing(progressClient, revisionId, async (preview) => {
          const action = await vscode.window.showInformationMessage(
            `Upload revision ${revisionId} from the configured repository root?`,
            { modal: true, detail: formatIndexPreview(preview) },
            "Upload to HydraDB"
          );
          return action === "Upload to HydraDB";
        });
        if (outcome.status === "cancelled") {
          void vscode.window.showInformationMessage("Indexing cancelled. No source cards were uploaded.");
          return;
        }
        await panel.refresh();
        const ready = readyIndexSummary(outcome.result);
        if (ready) {
          void vscode.window.showInformationMessage(ready);
        } else {
          void vscode.window.showErrorMessage(`HydraDB indexing did not produce a ready revision. ${failedIndexSummary(outcome.result)}`);
        }
      } catch (error) {
        await panel.refresh();
        void vscode.window.showErrorMessage(
          `HydraDB indexing could not complete. ${error instanceof Error ? error.message : "Unknown service error."}`
        );
      }
    }],
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
