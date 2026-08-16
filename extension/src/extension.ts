import * as vscode from "vscode";
import {
  agentRegistrations,
  detectAgentRegistrations,
  formatRegistration,
  registerAgent
} from "./agentSetup.js";
import { RepositoryMapCodeLensProvider } from "./codeLensProvider.js";
import { CredentialVault } from "./credentials.js";
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
import { formatIdentityMigration, previewIdentityMigration } from "./identityMigration.js";
import { ManagedRuntime } from "./managedRuntime.js";
import {
  cancelledIndexSummary,
  failedIndexSummary,
  formatIndexJobProgress,
  formatIndexPreview,
  readyIndexSummary,
  runSafeIndexing
} from "./indexing.js";
import { RepositorySidebar } from "./sidebar.js";
import { resolveCurrentProject } from "./projectResolver.js";
import { writeProjectIdentity, type ResolvedProject } from "./projectIdentity.js";
import { removeProjectCredentials, replaceProfileKey, runCredentialSetup } from "./setupWizard.js";
import type { ServiceHealth, ViewMode } from "./types.js";
import { pendingCompareContext, preserveViewContext } from "./viewContext.js";

let activeRuntime: ManagedRuntime | undefined;

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  let project: ResolvedProject | undefined;
  try {
    project = await resolveCurrentProject();
  } catch (error) {
    void vscode.window.showErrorMessage(
      `Argus could not resolve the current project. ${error instanceof Error ? error.message : "Unknown project error."}`
    );
  }
  const repositoryScope = project;
  const credentialVault = new CredentialVault(context.secrets, context.globalState);
  const runtime = project ? new ManagedRuntime(context, credentialVault, project) : undefined;
  if (project) {
    await context.workspaceState.update("hydra.project.binding.v1", {
      version: 1,
      repositoryId: project.repositoryId
    });
  }
  activeRuntime = runtime;
  const repositoryStatus = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 90);
  repositoryStatus.name = "Argus";
  repositoryStatus.text = "$(type-hierarchy) Argus";
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
      hydraStatus.tooltip = `HydraDB · ${health.collection ?? "current collection"}`;
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

  const configuredClient = () => {
    if (!runtime) {
      throw new Error("Open a local workspace folder to use Argus.");
    }
    const configuration = vscode.workspace.getConfiguration("hydra");
    return runtime.client(configuration.get<number>("indexTimeoutMs", 300000));
  };
  const panel = new GraphPanel(context, updateHealth, repositoryScope, (forWrite) => {
    if (!runtime) throw new Error("Open a local workspace folder to use Argus.");
    const configuration = vscode.workspace.getConfiguration("hydra");
    return runtime.client(forWrite
      ? configuration.get<number>("indexTimeoutMs", 300000)
      : configuration.get<number>("requestTimeoutMs", 120000));
  });
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
      const health = await client.health();
      if (health.state !== "ready" || !health.revision) {
        void vscode.window.showWarningMessage(
          "Index this project to a verified revision before starting or finishing a comparison."
        );
        return;
      }
      if (!state) {
        const beforeRevision = health.revision;
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
        const afterRevision = health.revision;
        if (afterRevision === state.beforeRevision) {
          void vscode.window.showInformationMessage(
            "The verified revision has not changed. Index the changed project, then run Finish comparison again."
          );
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
  const setupProject = async (): Promise<void> => {
    if (!project) {
      void vscode.window.showWarningMessage("Open a local project folder before configuring Argus.");
      return;
    }
    const configured = await runCredentialSetup(credentialVault, project);
    if (!configured) return;
    try {
      await vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: "Testing read-only HydraDB access…",
        cancellable: false
      }, () => configuredClient().testConnection());
    } catch (error) {
      void vscode.window.showErrorMessage(
        `HydraDB read access could not be verified. ${error instanceof Error ? error.message : "Unknown connection error."}`
      );
      await panel.refresh();
      return;
    }
    const next = await vscode.window.showInformationMessage(
      `HydraDB read access is verified for ${project.projectName}. Preview the initial index now?`,
      "Preview initial index",
      "Later"
    );
    if (next === "Preview initial index") await vscode.commands.executeCommand("hydra.indexRepository");
    const agents = await vscode.window.showInformationMessage(
      "Optionally connect Argus to installed coding agents through read-only OAuth.",
      "Configure agents",
      "Later"
    );
    if (agents === "Configure agents") await vscode.commands.executeCommand("hydra.configureAgents");
    await panel.refresh();
  };
  const configureAgents = async (): Promise<void> => {
    if (!runtime || !project) {
      void vscode.window.showWarningMessage("Open a local project folder before configuring coding agents.");
      return;
    }
    try {
      const registrations = agentRegistrations(await runtime.mcpUrl());
      const detected = await vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: "Detecting installed coding agents…",
        cancellable: false
      }, () => detectAgentRegistrations(registrations, project.repositoryRoot));
      if (!detected.length) {
        void vscode.window.showInformationMessage("Codex and Claude Code were not found on this machine.");
        return;
      }
      const selected = await vscode.window.showQuickPick(
        detected.map((registration) => ({
          label: registration.label,
          description: "Streamable HTTP with OAuth",
          detail: formatRegistration(registration),
          registration,
          picked: true
        })),
        {
          title: "Configure Argus agents",
          placeHolder: "Choose the installed clients to configure",
          canPickMany: true,
          ignoreFocusOut: true
        }
      );
      if (!selected?.length) return;
      const commands = selected.map((item) => formatRegistration(item.registration)).join("\n");
      const confirm = await vscode.window.showInformationMessage(
        `Register Argus with ${selected.map((item) => item.label).join(" and ")}?`,
        {
          modal: true,
          detail: `The extension will run exactly:\n${commands}\n\nOnly the loopback MCP URL is stored. Each client must complete read-only OAuth while VS Code is open.`
        },
        "Run registration"
      );
      if (confirm !== "Run registration") return;
      await vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: "Registering Argus with coding agents…",
        cancellable: false
      }, async () => {
        for (const item of selected) await registerAgent(item.registration, project.repositoryRoot);
      });
      void vscode.window.showInformationMessage(
        "Argus was registered. Approve the native read-only consent prompt when an agent first connects."
      );
    } catch (error) {
      void vscode.window.showErrorMessage(
        `Agent setup could not complete. ${error instanceof Error ? error.message : "Unknown agent setup error."}`
      );
    }
  };
  const reviewIdentityMigration = async (prompt = false): Promise<void> => {
    if (!runtime || !project?.candidateIdentity) return;
    const decisionKey = `hydra.identity.keep.${project.candidateIdentity.repository_id}`;
    if (!prompt && context.workspaceState.get<boolean>(decisionKey, false)) return;
    const choice = await vscode.window.showInformationMessage(
      `${project.projectName} now has a canonical Git identity. Review it before changing the existing Argus identity.`,
      "Review migration",
      "Keep existing identity"
    );
    if (choice === "Keep existing identity") {
      await context.workspaceState.update(decisionKey, true);
      return;
    }
    if (choice !== "Review migration") return;
    try {
      const health = await runtime.client(5_000).health();
      const preview = previewIdentityMigration(project.identity, project.candidateIdentity, health);
      if (!preview.canMigrateWithoutOrphans) {
        await vscode.window.showWarningMessage(
          "Repository identity was not changed.",
          { modal: true, detail: formatIdentityMigration(preview) }
        );
        return;
      }
      const confirmed = await vscode.window.showInformationMessage(
        "Adopt the canonical Git repository identity?",
        { modal: true, detail: formatIdentityMigration(preview) },
        "Migrate identity"
      );
      if (confirmed !== "Migrate identity") return;
      const previousId = project.identity.repository_id;
      const candidate = project.candidateIdentity;
      const copied = await credentialVault.copyProjectBinding(previousId, candidate.repository_id);
      try {
        await writeProjectIdentity(project.repositoryRoot, candidate);
      } catch (error) {
        if (copied) await credentialVault.removeProjectBinding(candidate.repository_id);
        throw error;
      }
      await context.workspaceState.update("hydra.project.binding.v1", {
        version: 1,
        repositoryId: candidate.repository_id
      });
      if (copied) await credentialVault.removeProjectBinding(previousId);
      await context.workspaceState.update(decisionKey, undefined);
      const reload = await vscode.window.showInformationMessage(
        "Repository identity migrated safely. Reload VS Code to restart the managed service with the Git identity.",
        "Reload now"
      );
      if (reload === "Reload now") await vscode.commands.executeCommand("workbench.action.reloadWindow");
    } catch (error) {
      void vscode.window.showErrorMessage(
        `Repository identity could not be migrated. ${error instanceof Error ? error.message : "Unknown migration error."}`
      );
    }
  };
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
      try {
        const outcome = await vscode.window.withProgress({
          location: vscode.ProgressLocation.Notification,
          title: "Indexing this project with HydraDB",
          cancellable: true
        }, async (progress, token) => {
          progress.report({ message: "Analyzing the selected project and deriving its revision…" });
          let reported = "";
          return await runSafeIndexing(configuredClient(), async (preview) => {
            const action = await vscode.window.showInformationMessage(
              `Upload automatic revision ${preview.revisionId} from the selected project?`,
              { modal: true, detail: formatIndexPreview(preview) },
              "Upload to HydraDB"
            );
            return action === "Upload to HydraDB";
          }, {
            onProgress: (job) => {
              // Only repeat a message that changed, so the notification does not flicker on every poll.
              const message = formatIndexJobProgress(job);
              if (message === reported) return;
              reported = message;
              progress.report({ message });
            },
            isCancelled: () => token.isCancellationRequested
          });
        });
        if (outcome.status === "cancelled") {
          void vscode.window.showInformationMessage("Indexing cancelled. No source cards were uploaded.");
          return;
        }
        if (outcome.status === "cancelled-by-user") {
          void vscode.window.showWarningMessage(cancelledIndexSummary(outcome.job));
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
      await setupProject();
    }],
    ["hydra.setup", async () => {
      await setupProject();
    }],
    ["hydra.configureAgents", async () => {
      await configureAgents();
    }],
    ["hydra.reviewIdentity", async () => {
      await reviewIdentityMigration(true);
    }],
    ["hydra.replaceApiKey", async () => {
      await replaceProfileKey(credentialVault);
      await panel.refresh();
    }],
    ["hydra.removeProjectBinding", async () => {
      if (!project) return;
      await removeProjectCredentials(credentialVault, project);
      await panel.refresh();
    }]
  ];
  registrations.forEach(([command, handler]) => context.subscriptions.push(vscode.commands.registerCommand(command, handler)));

  context.subscriptions.push(
    repositoryStatus,
    hydraStatus,
    sidebar,
    panel,
    ...(runtime ? [runtime] : []),
    ...(runtime ? [vscode.window.registerUriHandler(runtime)] : []),
    vscode.languages.registerCodeLensProvider({ scheme: "file" }, new RepositoryMapCodeLensProvider())
  );
  if (project && !credentialVault.hasProjectBinding(project.repositoryId)) {
    const action = await vscode.window.showInformationMessage(
      `Set up Argus for ${project.projectName} without using the terminal.`,
      "Start setup"
    );
    if (action === "Start setup") await vscode.commands.executeCommand("hydra.setup");
  }
  await reviewIdentityMigration();
  void panel.refresh();
}

export function deactivate(): void {
  activeRuntime?.dispose();
  activeRuntime = undefined;
}

function isMode(value: unknown): value is ViewMode {
  return typeof value === "string" && ["repository", "explore", "trace", "observe", "compare", "preserve"].includes(value);
}
