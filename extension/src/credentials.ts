import { randomBytes, randomUUID } from "node:crypto";

const PROFILE_INDEX_KEY = "hydra.credentials.profiles.v1";
const BINDING_INDEX_KEY = "hydra.credentials.bindings.v1";
const INSTALLATION_KEY = "hydra.credentials.installation.v1";
const PROFILE_PREFIX = "hydra.credentials.profile.v1.";
const BINDING_PREFIX = "hydra.credentials.binding.v1.";
const OAUTH_PREFIX = "hydra.oauth.v1.";

export interface SecretStore {
  get(key: string): Thenable<string | undefined>;
  store(key: string, value: string): Thenable<void>;
  delete(key: string): Thenable<void>;
}

export interface StateStore {
  get<T>(key: string, defaultValue: T): T;
  update(key: string, value: unknown): Thenable<void>;
}

export interface ProfileSummary {
  id: string;
  label: string;
}

export interface ProjectBindingSummary {
  repositoryId: string;
  profileId: string;
}

export interface AcquiredCredentials {
  apiKey: string;
  database: string;
  profileId: string;
}

interface StoredProfile {
  version: 1;
  api_key: string;
}

interface StoredBinding {
  version: 1;
  profile_id: string;
  database: string;
}

interface InstallationSecrets {
  version: 1;
  control_key: string;
  mcp_signing_key: string;
}

export class CredentialVault {
  public constructor(
    private readonly secrets: SecretStore,
    private readonly state: StateStore
  ) {}

  public listProfiles(): ProfileSummary[] {
    const value = this.state.get<unknown>(PROFILE_INDEX_KEY, []);
    if (!Array.isArray(value)) return [];
    return value.flatMap((item) => {
      if (!item || typeof item !== "object") return [];
      const candidate = item as Partial<ProfileSummary>;
      return validOpaqueId(candidate.id) && validLabel(candidate.label)
        ? [{ id: candidate.id, label: candidate.label }]
        : [];
    });
  }

  public async createProfile(label: string, apiKey: string): Promise<ProfileSummary> {
    const cleanLabel = requireLabel(label);
    const cleanKey = requireSecret(apiKey, "HydraDB API key", 8, 8_192);
    const summary = { id: randomUUID(), label: cleanLabel };
    const stored: StoredProfile = { version: 1, api_key: cleanKey };
    await this.secrets.store(`${PROFILE_PREFIX}${summary.id}`, JSON.stringify(stored));
    const profiles = this.listProfiles().filter((profile) => profile.id !== summary.id);
    await this.state.update(PROFILE_INDEX_KEY, [...profiles, summary]);
    return summary;
  }

  public async replaceProfileKey(profileId: string, apiKey: string): Promise<void> {
    this.requireProfile(profileId);
    const stored: StoredProfile = {
      version: 1,
      api_key: requireSecret(apiKey, "HydraDB API key", 8, 8_192)
    };
    await this.secrets.store(`${PROFILE_PREFIX}${profileId}`, JSON.stringify(stored));
  }

  public async deleteProfile(profileId: string): Promise<void> {
    this.requireProfile(profileId);
    if (this.listBindings().some((binding) => binding.profileId === profileId)) {
      throw new Error("Remove or change project bindings before deleting this profile.");
    }
    await this.secrets.delete(`${PROFILE_PREFIX}${profileId}`);
    await this.state.update(
      PROFILE_INDEX_KEY,
      this.listProfiles().filter((profile) => profile.id !== profileId)
    );
  }

  public async bindProject(repositoryId: string, profileId: string, database: string): Promise<void> {
    requireRepositoryId(repositoryId);
    this.requireProfile(profileId);
    const stored: StoredBinding = {
      version: 1,
      profile_id: profileId,
      database: requireSecret(database, "HydraDB database", 1, 512)
    };
    await this.secrets.store(bindingKey(repositoryId), JSON.stringify(stored));
    const bindings = this.listBindings().filter((binding) => binding.repositoryId !== repositoryId);
    await this.state.update(BINDING_INDEX_KEY, [...bindings, { repositoryId, profileId }]);
  }

  public async removeProjectBinding(repositoryId: string): Promise<void> {
    requireRepositoryId(repositoryId);
    await this.secrets.delete(bindingKey(repositoryId));
    await this.state.update(
      BINDING_INDEX_KEY,
      this.listBindings().filter((binding) => binding.repositoryId !== repositoryId)
    );
  }

  public async copyProjectBinding(fromRepositoryId: string, toRepositoryId: string): Promise<boolean> {
    requireRepositoryId(fromRepositoryId);
    requireRepositoryId(toRepositoryId);
    const rawBinding = await this.secrets.get(bindingKey(fromRepositoryId));
    const binding = parseBinding(rawBinding);
    if (!binding) return false;
    await this.secrets.store(bindingKey(toRepositoryId), JSON.stringify(binding));
    const bindings = this.listBindings().filter((item) => (
      item.repositoryId !== fromRepositoryId && item.repositoryId !== toRepositoryId
    ));
    await this.state.update(BINDING_INDEX_KEY, [
      ...bindings,
      { repositoryId: fromRepositoryId, profileId: binding.profile_id },
      { repositoryId: toRepositoryId, profileId: binding.profile_id }
    ]);
    return true;
  }

  public hasProjectBinding(repositoryId: string): boolean {
    return this.listBindings().some((binding) => binding.repositoryId === repositoryId);
  }

  public async acquire(repositoryId: string): Promise<AcquiredCredentials> {
    requireRepositoryId(repositoryId);
    const rawBinding = await this.secrets.get(bindingKey(repositoryId));
    const binding = parseBinding(rawBinding);
    if (!binding) throw new Error("HydraDB credentials are not configured for this project.");
    const rawProfile = await this.secrets.get(`${PROFILE_PREFIX}${binding.profile_id}`);
    const profile = parseProfile(rawProfile);
    if (!profile) throw new Error("The selected HydraDB account profile is unavailable.");
    return { apiKey: profile.api_key, database: binding.database, profileId: binding.profile_id };
  }

  public async installationSecrets(): Promise<InstallationSecrets> {
    const current = parseInstallation(await this.secrets.get(INSTALLATION_KEY));
    if (current) return current;
    const created: InstallationSecrets = {
      version: 1,
      control_key: randomBytes(32).toString("base64url"),
      mcp_signing_key: randomBytes(32).toString("base64url")
    };
    await this.secrets.store(INSTALLATION_KEY, JSON.stringify(created));
    return created;
  }

  public async readOAuthRecord(key: string): Promise<string | undefined> {
    requireOAuthKey(key);
    return this.secrets.get(`${OAUTH_PREFIX}${key}`);
  }

  public async writeOAuthRecord(key: string, value: string): Promise<void> {
    requireOAuthKey(key);
    if (!value || value.length > 24_000 || /[\u0000]/.test(value)) {
      throw new Error("OAuth grant record is invalid.");
    }
    await this.secrets.store(`${OAUTH_PREFIX}${key}`, value);
  }

  public async deleteOAuthRecord(key: string): Promise<void> {
    requireOAuthKey(key);
    await this.secrets.delete(`${OAUTH_PREFIX}${key}`);
  }

  private listBindings(): ProjectBindingSummary[] {
    const value = this.state.get<unknown>(BINDING_INDEX_KEY, []);
    if (!Array.isArray(value)) return [];
    return value.flatMap((item) => {
      if (!item || typeof item !== "object") return [];
      const candidate = item as Partial<ProjectBindingSummary>;
      return validRepositoryId(candidate.repositoryId) && validOpaqueId(candidate.profileId)
        ? [{ repositoryId: candidate.repositoryId, profileId: candidate.profileId }]
        : [];
    });
  }

  private requireProfile(profileId: string): ProfileSummary {
    if (!validOpaqueId(profileId)) throw new Error("Credential profile ID is invalid.");
    const profile = this.listProfiles().find((candidate) => candidate.id === profileId);
    if (!profile) throw new Error("Credential profile does not exist.");
    return profile;
  }
}

function parseProfile(value: string | undefined): StoredProfile | undefined {
  const parsed = parseObject(value);
  return parsed?.version === 1 && typeof parsed.api_key === "string"
    && validSecret(parsed.api_key, 8, 8_192)
    ? { version: 1, api_key: parsed.api_key }
    : undefined;
}

function parseBinding(value: string | undefined): StoredBinding | undefined {
  const parsed = parseObject(value);
  return parsed?.version === 1 && validOpaqueId(parsed.profile_id)
    && typeof parsed.database === "string" && validSecret(parsed.database, 1, 512)
    ? { version: 1, profile_id: parsed.profile_id, database: parsed.database }
    : undefined;
}

function parseInstallation(value: string | undefined): InstallationSecrets | undefined {
  const parsed = parseObject(value);
  const key = /^[A-Za-z0-9_-]{43}$/;
  return parsed?.version === 1 && typeof parsed.control_key === "string"
    && typeof parsed.mcp_signing_key === "string" && key.test(parsed.control_key)
    && key.test(parsed.mcp_signing_key)
    ? { version: 1, control_key: parsed.control_key, mcp_signing_key: parsed.mcp_signing_key }
    : undefined;
}

function parseObject(value: string | undefined): Record<string, unknown> | undefined {
  if (!value) return undefined;
  try {
    const parsed = JSON.parse(value) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : undefined;
  } catch {
    return undefined;
  }
}

function bindingKey(repositoryId: string): string {
  return `${BINDING_PREFIX}${repositoryId}`;
}

function requireLabel(value: string): string {
  const clean = value.trim();
  if (!validLabel(clean)) throw new Error("Profile label must be 1-80 printable characters.");
  return clean;
}

function validLabel(value: unknown): value is string {
  return typeof value === "string" && value.length >= 1 && value.length <= 80 && !/[\u0000-\u001f\u007f]/.test(value);
}

function requireSecret(value: string, name: string, minimum: number, maximum: number): string {
  const clean = value.trim();
  if (!validSecret(clean, minimum, maximum)) {
    throw new Error(`${name} must be ${minimum}-${maximum} characters without control characters.`);
  }
  return clean;
}

function validSecret(value: string, minimum: number, maximum: number): boolean {
  return value.length >= minimum && value.length <= maximum && !/[\u0000-\u001f\u007f]/.test(value);
}

function validOpaqueId(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

function requireRepositoryId(value: string): void {
  if (!validRepositoryId(value)) throw new Error("Repository ID is invalid.");
}

function validRepositoryId(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value);
}

function requireOAuthKey(value: string): void {
  if (!/^[a-z]+\/[A-Za-z0-9_-]{16,128}$/.test(value)) {
    throw new Error("OAuth grant key is invalid.");
  }
}
