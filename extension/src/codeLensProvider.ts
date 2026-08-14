import * as vscode from "vscode";

export class RepositoryMapCodeLensProvider implements vscode.CodeLensProvider {
  public provideCodeLenses(document: vscode.TextDocument): vscode.CodeLens[] {
    if (document.lineCount === 0 || document.uri.scheme !== "file") {
      return [];
    }
    const firstLine = document.lineAt(0).range;
    return [new vscode.CodeLens(firstLine, {
      title: "$(type-hierarchy) View repository graph",
      command: "hydra.showInRepositoryMap",
      tooltip: "Open a bounded repository view for this file"
    })];
  }
}
