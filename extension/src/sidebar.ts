import * as path from "node:path";
import * as vscode from "vscode";
import type { ServiceHealth } from "./types.js";

type Section = "current" | "entrypoints" | "lenses" | "changes" | "activity" | "status";

class SummaryItem extends vscode.TreeItem {
  public constructor(
    label: string,
    description: string,
    icon: string,
    command?: vscode.Command
  ) {
    super(label, vscode.TreeItemCollapsibleState.None);
    this.description = description;
    this.iconPath = new vscode.ThemeIcon(icon);
    this.command = command;
    this.tooltip = `${label} — ${description}`;
    this.contextValue = "hydraSummaryItem";
  }
}

class SummaryProvider implements vscode.TreeDataProvider<SummaryItem> {
  private readonly changed = new vscode.EventEmitter<SummaryItem | undefined>();
  public readonly onDidChangeTreeData = this.changed.event;

  public constructor(
    private readonly section: Section,
    private readonly state: SidebarState
  ) {}

  public refresh(): void {
    this.changed.fire(undefined);
  }

  public getTreeItem(element: SummaryItem): vscode.TreeItem {
    return element;
  }

  public getChildren(): SummaryItem[] {
    const open = (mode: string): vscode.Command => ({ command: "hydra.openRepositoryMap", title: "Open map", arguments: [mode] });
    const health = this.state.health;
    if (this.section === "current") {
      const editor = vscode.window.activeTextEditor;
      if (!editor || editor.document.uri.scheme !== "file") {
        return [new SummaryItem("No active source file", "Open a file to focus it", "file", open("repository"))];
      }
      return [new SummaryItem(path.basename(editor.document.fileName), "Active editor", "symbol-file", open("explore"))];
    }
    if (this.section === "status") {
      const indexItem = new SummaryItem("Index this workspace", "Preview scope before uploading", "cloud-upload", {
        command: "hydra.indexRepository", title: "Index workspace"
      });
      if (health.state === "ready") {
        return [
          new SummaryItem("Current revision ready", health.revision ?? "Revision unavailable", "pass", open("repository")),
          new SummaryItem("HydraDB configured", health.collection ?? "Default collection", "database", open("repository")),
          indexItem
        ];
      }
      if (health.state === "indexing") {
        return [new SummaryItem("Indexing", health.message ?? "Last verified revision remains active", "sync~spin", open("repository"))];
      }
      if (health.state === "unverified") {
        return [
          new SummaryItem("Revision not verified", health.message ?? "HydraDB is configured, but no verified revision is ready", "question", open("repository")),
          indexItem
        ];
      }
      if (health.state === "failed") {
        return [
          new SummaryItem("Latest indexing failed", health.message ?? "The prior verified revision remains active", "error", open("repository")),
          indexItem
        ];
      }
      return [
        new SummaryItem("HydraDB unavailable", "Open preview or configure service", "warning", {
          command: "hydra.configureService", title: "Configure service"
        }),
        indexItem
      ];
    }
    const copy: Record<Exclude<Section, "current" | "status">, [string, string, string, string]> = {
      entrypoints: ["Open Argus", health.state === "ready" ? "Load verified entrypoints" : "Requires a verified revision", "symbol-event", "repository"],
      lenses: ["No loaded lenses", health.state === "ready" ? "Open Preserve to review" : "Requires HydraDB Memory", "bookmark", "preserve"],
      changes: ["Review graph changes", health.state === "ready" ? "Compare verified revisions" : "Requires repository service", "diff", "compare"],
      activity: ["Observe agent activity", health.state === "ready" ? "Follow explicit tool events" : "Requires repository service", "pulse", "observe"]
    };
    const [label, detail, icon, mode] = copy[this.section];
    return [new SummaryItem(label, detail, icon, open(mode))];
  }
}

class SidebarState {
  public health: ServiceHealth = { state: "unavailable", message: "Repository service has not been contacted." };
}

export class RepositorySidebar implements vscode.Disposable {
  private readonly state = new SidebarState();
  private readonly providers: SummaryProvider[];
  private readonly disposables: vscode.Disposable[] = [];

  public constructor() {
    const registrations: Array<[string, Section]> = [
      ["hydra.currentSymbol", "current"],
      ["hydra.entrypoints", "entrypoints"],
      ["hydra.savedLenses", "lenses"],
      ["hydra.recentChanges", "changes"],
      ["hydra.agentActivity", "activity"],
      ["hydra.indexStatus", "status"]
    ];
    this.providers = registrations.map(([viewId, section]) => {
      const provider = new SummaryProvider(section, this.state);
      this.disposables.push(vscode.window.registerTreeDataProvider(viewId, provider));
      return provider;
    });
    this.disposables.push(vscode.window.onDidChangeActiveTextEditor(() => this.refresh()));
  }

  public setHealth(health: ServiceHealth): void {
    this.state.health = health;
    this.refresh();
  }

  public refresh(): void {
    this.providers.forEach((provider) => provider.refresh());
  }

  public dispose(): void {
    this.disposables.forEach((disposable) => disposable.dispose());
  }
}
