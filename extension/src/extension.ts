import * as vscode from "vscode";
import { RepositoryMapCodeLensProvider } from "./codeLensProvider.js";
import { captureEditorFocus, focusedViewRequest, type FocusAction } from "./editorFocus.js";
import {
  formatCheckpoint,
  formatLens,
  formatPublish,
  previewThenConfirm,
  checkpointWasCaptured,
  lensPreviewMatches,
  lensWriteIsReady,
  publishPreviewMatches,
  publishIsReady,
  validateLensName,
  validateLensPurpose,
  type CheckpointSlot,
  type EvolutionClient,
  type LensDraft
} from "./evolution.js";
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
import { pendingCompareContext, preserveViewContext } from "./viewContext.js";
import { createRepositoryScope, type RepositoryScope } from "./workspaceScope.js";

export function activate(context: vscode.ExtensionContext): void {
  const repositoryScope = activeRepositoryScope();
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
      hydraStatus.text = `$(database) HydraDB · ${health.revision ?? "ready"}`;
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

  const panel = new GraphPanel(context, updateHealth, repositoryScope);
  const configuredClient = (): RepositoryServiceClient => {
    if (!repositoryScope) {
      throw new Error("Open a local workspace folder to use Repository Map.");
    }
    const configuration = vscode.workspace.getConfiguration("hydra");
    return new RepositoryServiceClient({
      baseUrl: configuration.get<string>("serviceUrl", "http://127.0.0.1:8765"),
      repositoryScope,
      timeoutMs: configuration.get<number>("indexTimeoutMs", 120000)
    });
  };
  const promptRevision = async (title: string, prompt: string): Promise<string | undefined> => {
    const value = await vscode.window.showInputBox({
      title,
      prompt,
      placeHolder: "Explicit revision ID, such as a Git SHA",
      ignoreFocusOut: true,
      validateInput: validateRevisionId
    });
    if (value === undefined) return undefined;
    const revision = value.trim();
    const invalid = validateRevisionId(revision);
    if (invalid) {
      void vscode.window.showErrorMessage(invalid);
      return undefined;
    }
    return revision;
  };
  const checkpoint = async (
    client: EvolutionClient,
    slot: CheckpointSlot,
    revisionId: string
  ): Promise<boolean> => {
    const action = await vscode.window.showInformationMessage(
      `Capture the ${slot} checkpoint for revision ${revisionId}?`,
      {
        modal: true,
        detail: "This performs bounded local repository analysis for comparison. It does not publish graph-delta Knowledge to HydraDB."
      },
      `Capture ${slot} checkpoint`
    );
    if (action !== `Capture ${slot} checkpoint`) return false;
    const result = await client.checkpoint(slot, revisionId);
    if (!checkpointWasCaptured(result, slot, revisionId)) {
      throw new Error(`The ${slot} checkpoint was not captured. ${result.warnings.join(" ")}`.trim());
    }
    void vscode.window.showInformationMessage(
      `${slot === "before" ? "Before" : "After"} checkpoint captured. ${formatCheckpoint(result)}`
    );
    return true;
  };
  const runCompareWorkflow = async (): Promise<void> => {
    const stateKey = "hydra.compare.pending";
    type CompareState = { beforeRevision: string; afterRevision?: string };
    const storedState = context.workspaceState.get<unknown>(stateKey);
    let state: CompareState | undefined = pendingCompareContext(storedState);
    if (storedState !== undefined && !state) {
      await context.workspaceState.update(stateKey, undefined);
      void vscode.window.showWarningMessage("Discarded invalid pending comparison state. Start the before checkpoint again.");
    }
    try {
      const client = configuredClient();
      if (!state) {
        const beforeRevision = await promptRevision(
          "Capture graph before change",
          "Enter the currently verified revision before making the agent change"
        );
        if (!beforeRevision) return;
        if (!await checkpoint(client, "before", beforeRevision)) {
          void vscode.window.showInformationMessage("Before checkpoint cancelled. No comparison state was written.");
          return;
        }
        state = { beforeRevision };
        await context.workspaceState.update(stateKey, state);
        void vscode.window.showInformationMessage(
          `Before checkpoint ${beforeRevision} captured. Make and index the change, then run Compare Graph again to capture the after revision and publish its delta.`
        );
        return;
      }
      if (!state.afterRevision) {
        const afterRevision = await promptRevision(
          "Capture graph after change",
          `Before revision is ${state.beforeRevision}. Enter the verified revision after the change.`
        );
        if (!afterRevision) return;
        if (afterRevision === state.beforeRevision) {
          void vscode.window.showErrorMessage("Before and after revision IDs must be different.");
          return;
        }
        if (!await checkpoint(client, "after", afterRevision)) {
          void vscode.window.showInformationMessage("After checkpoint cancelled. The before checkpoint remains available.");
          return;
        }
        state = { ...state, afterRevision };
        await context.workspaceState.update(stateKey, state);
      }
      const beforeRevision = state.beforeRevision;
      const afterRevision = state.afterRevision;
      if (!afterRevision) return;
      const publish = await previewThenConfirm(
        () => client.publishEvolution(beforeRevision, afterRevision, false),
        async (preview) => {
          if (!publishPreviewMatches(preview, beforeRevision, afterRevision)) {
            throw new Error("Evolution preview did not contain a safe, concrete delta for the captured revisions.");
          }
          const action = await vscode.window.showInformationMessage(
            `Publish the graph delta from ${beforeRevision} to ${afterRevision}?`,
            { modal: true, detail: formatPublish(preview) },
            "Publish graph delta"
          );
          return action === "Publish graph delta";
        },
        () => client.publishEvolution(beforeRevision, afterRevision, true)
      );
      if (publish.status === "cancelled") {
        void vscode.window.showInformationMessage("Delta publication cancelled. Both checkpoints remain available for review.");
        return;
      }
      const result = publish.result;
      if (!publishIsReady(result, beforeRevision, afterRevision)) {
        void vscode.window.showErrorMessage(
          `Graph delta is not ready (${result.status || "unknown"}). ${result.warnings.join(" ")}`.trim()
        );
        return;
      }
      await context.workspaceState.update(stateKey, undefined);
      void vscode.window.showInformationMessage(
        `Published ${result.sourceCount} evolution source ${result.sourceCount === 1 ? "card" : "cards"} for ${beforeRevision} → ${afterRevision}.`
      );
      await panel.showCompare(beforeRevision, afterRevision);
    } catch (error) {
      void vscode.window.showErrorMessage(
        `Graph comparison could not complete. ${error instanceof Error ? error.message : "Unknown service error."}`
      );
    }
  };
  const saveCurrentLens = async (): Promise<void> => {
    const grounded = panel.currentGroundedView();
    if (!grounded) {
      void vscode.window.showWarningMessage("Open a HydraDB-backed view at a verified revision before saving a System Lens.");
      return;
    }
    const nameInput = await vscode.window.showInputBox({
      title: "Save current view as a System Lens",
      prompt: "Give this grounded flow a concise name",
      placeHolder: "Authentication",
      ignoreFocusOut: true,
      validateInput: validateLensName
    });
    if (nameInput === undefined || validateLensName(nameInput)) return;
    const purposeInput = await vscode.window.showInputBox({
      title: `Purpose of ${nameInput.trim()}`,
      prompt: "Describe the system flow this lens should preserve",
      placeHolder: "Validate a session, load policy, authorize the action, and audit the result.",
      ignoreFocusOut: true,
      validateInput: validateLensPurpose
    });
    if (purposeInput === undefined || validateLensPurpose(purposeInput)) return;
    const draft: LensDraft = { name: nameInput.trim(), purpose: purposeInput.trim(), viewId: grounded.viewId };
    try {
      const client = configuredClient();
      const save = await previewThenConfirm(
        () => client.saveLens(draft, false),
        async (preview) => {
          if (!lensPreviewMatches(preview, "save_lens", grounded.revision) || !preserveViewContext(preview.lensId)) {
            throw new Error("Lens preview was not grounded in the current verified graph view.");
          }
          const action = await vscode.window.showInformationMessage(
            `Save ${draft.name} as a grounded System Lens?`,
            { modal: true, detail: formatLens(preview, draft.purpose) },
            "Save System Lens"
          );
          return action === "Save System Lens";
        },
        () => client.saveLens(draft, true)
      );
      if (save.status === "cancelled") {
        void vscode.window.showInformationMessage("System Lens save cancelled. No HydraDB source was written.");
        return;
      }
      const result = save.result;
      if (result.operation !== "save_lens" || !preserveViewContext(result.lensId) || !lensWriteIsReady(result, grounded.revision)) {
        void vscode.window.showErrorMessage(
          `System Lens was not saved (${result.status || "unknown"}). ${result.warnings.join(" ")}`.trim()
        );
        return;
      }
      void vscode.window.showInformationMessage(`Saved ${result.name || draft.name} at verified revision ${result.savedRevisionId}.`);
      await panel.showPreserve(result.lensId);
    } catch (error) {
      void vscode.window.showErrorMessage(
        `System Lens could not be saved. ${error instanceof Error ? error.message : "Unknown service error."}`
      );
    }
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
    ["hydra.compareGraph", () => runCompareWorkflow()],
    ["hydra.saveSystemLens", () => saveCurrentLens()],
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
      const progressClient: IndexingClient = {
        previewIndex: async (revision) => await vscode.window.withProgress({
          location: vscode.ProgressLocation.Notification,
          title: `Analyzing selected workspace for ${revision}…`,
          cancellable: false
        }, () => configuredClient().previewIndex(revision)),
        indexRepository: async (revision) => await vscode.window.withProgress({
          location: vscode.ProgressLocation.Notification,
          title: `Uploading revision ${revision} to HydraDB…`,
          cancellable: false
        }, () => configuredClient().indexRepository(revision))
      };
      try {
        const outcome = await runSafeIndexing(progressClient, revisionId, async (preview) => {
          const action = await vscode.window.showInformationMessage(
            `Upload revision ${revisionId} from the selected workspace?`,
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

function activeRepositoryScope(): RepositoryScope | undefined {
  const folders = vscode.workspace.workspaceFolders?.filter((folder) => folder.uri.scheme === "file") ?? [];
  const folder = folders[0];
  if (!folder) return undefined;
  return createRepositoryScope(folder.uri.fsPath, folder.name);
}
