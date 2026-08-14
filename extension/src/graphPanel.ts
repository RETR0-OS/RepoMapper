import * as crypto from "node:crypto";
import * as vscode from "vscode";
import { createPreviewView } from "./previewData.js";
import { RepositoryServiceClient, ServiceError } from "./serviceClient.js";
import { validateSourceRange } from "./sourceNavigation.js";
import type {
  GraphDepth,
  HostToWebviewMessage,
  ServiceHealth,
  ViewMode,
  WebviewToHostMessage
} from "./types.js";
import { safeDisplayStateKey } from "./webview/graphState.js";

export class GraphPanel implements vscode.Disposable {
  private panel: vscode.WebviewPanel | undefined;
  private mode: ViewMode = "repository";
  private depth: GraphDepth = "file";
  private selectedId: string | undefined;
  private health: ServiceHealth = { state: "unavailable" };
  private readonly disposables: vscode.Disposable[] = [];

  public constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly onHealthChanged: (health: ServiceHealth) => void
  ) {}

  public async show(mode: ViewMode = this.mode, question?: string): Promise<void> {
    this.mode = mode;
    if (!this.panel) {
      this.panel = vscode.window.createWebviewPanel(
        "hydra.repositoryMap",
        "Repository Map",
        vscode.ViewColumn.Active,
        {
          enableScripts: true,
          retainContextWhenHidden: true,
          localResourceRoots: [vscode.Uri.joinPath(this.context.extensionUri, "dist")]
        }
      );
      this.panel.webview.html = this.html(this.panel.webview);
      this.disposables.push(this.panel.onDidDispose(() => { this.panel = undefined; }));
      this.disposables.push(this.panel.webview.onDidReceiveMessage((message: WebviewToHostMessage) => this.handleMessage(message)));
    } else {
      this.panel.reveal(vscode.ViewColumn.Active, true);
    }
    if (question) {
      await this.ask(question);
    } else {
      await this.loadView();
    }
  }

  public async refresh(): Promise<void> {
    if (this.panel) {
      await this.loadView();
    } else {
      await this.updateHealth();
    }
  }

  public dispose(): void {
    this.panel?.dispose();
    this.disposables.forEach((disposable) => disposable.dispose());
  }

  private client(): RepositoryServiceClient {
    const configuration = vscode.workspace.getConfiguration("hydra");
    return new RepositoryServiceClient({
      baseUrl: configuration.get<string>("serviceUrl", "http://127.0.0.1:8765"),
      timeoutMs: configuration.get<number>("requestTimeoutMs", 5000)
    });
  }

  private async handleMessage(message: WebviewToHostMessage): Promise<void> {
    switch (message.type) {
      case "ready":
        await this.loadView();
        break;
      case "changeMode":
        this.mode = message.mode;
        await this.loadView();
        break;
      case "changeDepth":
        this.depth = message.depth;
        await this.loadView();
        break;
      case "query":
        await this.ask(message.question);
        break;
      case "openSource":
        this.selectedId = message.itemId;
        await this.openSource(message.itemId, message.source);
        break;
      case "primaryAction":
        this.selectedId = message.selectedId;
        await this.runPrimaryAction(message.mode, message.selectedId);
        break;
      case "retry":
        await this.loadView();
        break;
      case "persistDisplayState":
        if (safeDisplayStateKey(message.key) && JSON.stringify(message.value).length < 50_000) {
          await this.context.workspaceState.update(`hydra.display.${message.key}`, message.value);
        }
        break;
    }
  }

  private async loadView(): Promise<void> {
    this.post({ type: "loading", mode: this.mode, message: `Loading ${this.mode} view…` });
    try {
      const [health, view] = await Promise.all([this.client().health(), this.client().getView(this.mode, this.depth)]);
      this.setHealth(health);
      this.post({ type: "view", view, health });
    } catch (error) {
      const message = error instanceof ServiceError ? error.message : "Repository service is unavailable.";
      const health: ServiceHealth = { state: "unavailable", message };
      this.setHealth(health);
      this.post({ type: "view", view: createPreviewView(this.mode, this.depth), health });
    }
  }

  private async ask(question: string): Promise<void> {
    const trimmed = question.trim();
    if (!trimmed) {
      this.post({ type: "error", message: "Enter a repository question first.", recoverable: true });
      return;
    }
    this.mode = "trace";
    this.post({ type: "loading", mode: "trace", message: "Asking HydraDB for a bounded graph path…" });
    try {
      const view = await this.client().query(trimmed, this.depth);
      const health = await this.updateHealth();
      this.post({ type: "view", view, health });
    } catch (error) {
      const message = error instanceof ServiceError ? error.message : "The query could not be completed.";
      const health: ServiceHealth = { state: "unavailable", message };
      this.setHealth(health);
      const preview = createPreviewView("trace", this.depth);
      preview.warnings.unshift(`Query unavailable: ${message}`);
      this.post({ type: "view", view: preview, health });
    }
  }

  private async runPrimaryAction(mode: ViewMode, selectedId?: string): Promise<void> {
    if (this.health.state !== "ready") {
      this.post({
        type: "actionResult",
        action: mode,
        message: "This action needs the repository service. The preview remains interactive, but it does not change repository truth."
      });
      return;
    }
    try {
      const result = await this.client().runAction(mode, selectedId);
      this.post({ type: "actionResult", action: mode, message: result.message, view: result.view });
    } catch (error) {
      this.post({
        type: "error",
        message: error instanceof Error ? error.message : "The action could not be completed.",
        recoverable: true
      });
    }
  }

  private async updateHealth(): Promise<ServiceHealth> {
    try {
      const health = await this.client().health();
      this.setHealth(health);
      return health;
    } catch (error) {
      const health: ServiceHealth = {
        state: "unavailable",
        message: error instanceof Error ? error.message : "Repository service is unavailable."
      };
      this.setHealth(health);
      return health;
    }
  }

  private setHealth(health: ServiceHealth): void {
    this.health = health;
    this.onHealthChanged(health);
  }

  private async openSource(itemId: string, source: Extract<WebviewToHostMessage, { type: "openSource" }>["source"]): Promise<void> {
    const roots = vscode.workspace.workspaceFolders?.map((folder) => folder.uri.fsPath) ?? [];
    const validated = validateSourceRange(source, roots);
    if (!validated) {
      void vscode.window.showWarningMessage("Repository Map blocked a source path outside the active workspace.");
      return;
    }
    const uri = vscode.Uri.file(validated.absolutePath);
    try {
      const stat = await vscode.workspace.fs.stat(uri);
      if ((stat.type & vscode.FileType.Directory) !== 0) {
        await vscode.commands.executeCommand("revealInExplorer", uri);
      } else {
        const document = await vscode.workspace.openTextDocument(uri);
        const startLine = Math.min(validated.startLine - 1, Math.max(0, document.lineCount - 1));
        const endLine = Math.min(validated.endLine - 1, Math.max(0, document.lineCount - 1));
        const range = new vscode.Range(
          startLine,
          Math.min(validated.startColumn, document.lineAt(startLine).text.length),
          endLine,
          Math.min(validated.endColumn, document.lineAt(endLine).text.length)
        );
        const editor = await vscode.window.showTextDocument(document, { preview: true, preserveFocus: false });
        editor.selection = new vscode.Selection(range.start, range.end);
        editor.revealRange(range, vscode.TextEditorRevealType.InCenterIfOutsideViewport);
      }
      this.post({ type: "sourceOpened", itemId });
    } catch {
      void vscode.window.showWarningMessage(`Source evidence is not available at ${source.path}.`);
    }
  }

  private post(message: HostToWebviewMessage): void {
    void this.panel?.webview.postMessage(message);
  }

  private html(webview: vscode.Webview): string {
    const nonce = crypto.randomBytes(18).toString("base64");
    const script = webview.asWebviewUri(vscode.Uri.joinPath(this.context.extensionUri, "dist", "webview.js"));
    const styles = webview.asWebviewUri(vscode.Uri.joinPath(this.context.extensionUri, "dist", "webview.css"));
    return `<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource}; script-src 'nonce-${nonce}'; font-src ${webview.cspSource};">
  <link rel="stylesheet" href="${styles}">
  <title>Repository Map</title>
</head>
<body>
  <div id="app"></div>
  <script nonce="${nonce}" src="${script}"></script>
</body>
</html>`;
  }
}
