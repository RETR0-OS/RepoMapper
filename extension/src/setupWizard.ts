import * as vscode from "vscode";
import { CredentialVault, type ProfileSummary } from "./credentials.js";
import type { ResolvedProject } from "./projectIdentity.js";
import { validateApiKey, validateDatabase, validateProfileLabel } from "./setupValidation.js";

export interface SetupResult {
  project: ResolvedProject;
  profile: ProfileSummary;
}

export async function runCredentialSetup(
  vault: CredentialVault,
  project: ResolvedProject
): Promise<SetupResult | undefined> {
  const profile = await selectOrCreateProfile(vault);
  if (!profile) return undefined;
  const database = await vscode.window.showInputBox({
    title: `HydraDB database for ${project.projectName}`,
    prompt: "The database name is saved in encrypted SecretStorage and is not shown again.",
    placeHolder: "Enter the project database",
    password: true,
    ignoreFocusOut: true,
    validateInput: validateDatabase
  });
  if (database === undefined) return undefined;
  const invalidDatabase = validateDatabase(database);
  if (invalidDatabase) {
    void vscode.window.showErrorMessage(invalidDatabase);
    return undefined;
  }
  await vault.bindProject(project.repositoryId, profile.id, database);
  void vscode.window.showInformationMessage(
    `HydraDB credentials are stored securely for ${project.projectName}. The database name will not be displayed.`
  );
  return { project, profile };
}

export async function selectOrCreateProfile(vault: CredentialVault): Promise<ProfileSummary | undefined> {
  const profiles = vault.listProfiles();
  if (profiles.length) {
    type ProfilePick = { label: string; description: string; profile?: ProfileSummary; create?: true };
    const create: ProfilePick = { label: "$(add) Create another account profile", description: "Use a different HydraDB API key", create: true };
    const options: ProfilePick[] = [
      ...profiles.map((profile) => ({ label: profile.label, description: "Stored account profile", profile })),
      create
    ];
    const selected = await vscode.window.showQuickPick(options, {
      title: "Select a HydraDB account profile",
      placeHolder: "Database names are bound separately for each project",
      ignoreFocusOut: true
    });
    if (!selected) return undefined;
    if (selected.profile) return selected.profile;
  }
  return createProfile(vault);
}

export async function createProfile(vault: CredentialVault): Promise<ProfileSummary | undefined> {
  const label = await vscode.window.showInputBox({
    title: "Name this HydraDB account profile",
    prompt: "The label is visible in VS Code. Do not include a key or database name.",
    placeHolder: "Work account",
    ignoreFocusOut: true,
    validateInput: validateProfileLabel
  });
  if (label === undefined || validateProfileLabel(label)) return undefined;
  const apiKey = await vscode.window.showInputBox({
    title: `HydraDB API key for ${label.trim()}`,
    prompt: "The key is saved in encrypted SecretStorage and is not shown again.",
    placeHolder: "Paste the HydraDB API key",
    password: true,
    ignoreFocusOut: true,
    validateInput: validateApiKey
  });
  if (apiKey === undefined || validateApiKey(apiKey)) return undefined;
  return vault.createProfile(label, apiKey);
}

export async function replaceProfileKey(vault: CredentialVault): Promise<void> {
  const profile = await pickExistingProfile(vault, "Select the account profile whose key should change");
  if (!profile) return;
  const apiKey = await vscode.window.showInputBox({
    title: `Replace the API key for ${profile.label}`,
    prompt: "The existing key cannot be revealed. Enter its replacement.",
    password: true,
    ignoreFocusOut: true,
    validateInput: validateApiKey
  });
  if (apiKey === undefined || validateApiKey(apiKey)) return;
  await vault.replaceProfileKey(profile.id, apiKey);
  void vscode.window.showInformationMessage(`The API key for ${profile.label} was replaced.`);
}

export async function removeProjectCredentials(vault: CredentialVault, project: ResolvedProject): Promise<void> {
  if (!vault.hasProjectBinding(project.repositoryId)) {
    void vscode.window.showInformationMessage("This project does not have a stored HydraDB database binding.");
    return;
  }
  const confirmed = await vscode.window.showWarningMessage(
    `Remove the stored HydraDB database binding for ${project.projectName}?`,
    { modal: true, detail: "This does not delete HydraDB data. Argus becomes unavailable until setup is run again." },
    "Remove binding"
  );
  if (confirmed !== "Remove binding") return;
  await vault.removeProjectBinding(project.repositoryId);
  void vscode.window.showInformationMessage(`Removed the stored database binding for ${project.projectName}.`);
}

async function pickExistingProfile(vault: CredentialVault, title: string): Promise<ProfileSummary | undefined> {
  const profiles = vault.listProfiles();
  if (!profiles.length) {
    void vscode.window.showInformationMessage("No HydraDB account profiles are stored.");
    return undefined;
  }
  const selected = await vscode.window.showQuickPick(
    profiles.map((profile) => ({ label: profile.label, profile })),
    { title, ignoreFocusOut: true }
  );
  return selected?.profile;
}
