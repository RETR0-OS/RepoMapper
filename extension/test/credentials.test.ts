import { describe, expect, it } from "vitest";
import { CredentialVault, type SecretStore, type StateStore } from "../src/credentials.js";

class MemorySecrets implements SecretStore {
  public readonly values = new Map<string, string>();
  public readonly reads: string[] = [];
  public get(key: string): Promise<string | undefined> {
    this.reads.push(key);
    return Promise.resolve(this.values.get(key));
  }
  public store(key: string, value: string): Promise<void> {
    this.values.set(key, value);
    return Promise.resolve();
  }
  public delete(key: string): Promise<void> {
    this.values.delete(key);
    return Promise.resolve();
  }
}

class MemoryState implements StateStore {
  public readonly values = new Map<string, unknown>();
  public get<T>(key: string, defaultValue: T): T {
    return (this.values.has(key) ? this.values.get(key) : defaultValue) as T;
  }
  public update(key: string, value: unknown): Promise<void> {
    this.values.set(key, value);
    return Promise.resolve();
  }
}

describe("CredentialVault", () => {
  it("keeps API keys and databases out of ordinary state", async () => {
    const secrets = new MemorySecrets();
    const state = new MemoryState();
    const vault = new CredentialVault(secrets, state);
    const profile = await vault.createProfile("Work", "hydra-secret-key");
    await vault.bindProject("git:repo:1234567890abcdef1234", profile.id, "private-database");
    expect(JSON.stringify([...state.values])).not.toContain("hydra-secret-key");
    expect(JSON.stringify([...state.values])).not.toContain("private-database");
    await expect(vault.acquire("git:repo:1234567890abcdef1234")).resolves.toEqual({
      apiKey: "hydra-secret-key",
      database: "private-database",
      profileId: profile.id
    });
  });

  it("reads both secret records for every acquisition instead of caching", async () => {
    const secrets = new MemorySecrets();
    const vault = new CredentialVault(secrets, new MemoryState());
    const profile = await vault.createProfile("Default", "first-secret-key");
    await vault.bindProject("local:repo:123e4567-e89b-42d3-a456-426614174000", profile.id, "first-db");
    await vault.acquire("local:repo:123e4567-e89b-42d3-a456-426614174000");
    await vault.replaceProfileKey(profile.id, "second-secret-key");
    await vault.bindProject("local:repo:123e4567-e89b-42d3-a456-426614174000", profile.id, "second-db");
    await expect(vault.acquire("local:repo:123e4567-e89b-42d3-a456-426614174000")).resolves.toMatchObject({
      apiKey: "second-secret-key", database: "second-db"
    });
    expect(secrets.reads.filter((key) => key.includes("binding.v1")).length).toBe(2);
    expect(secrets.reads.filter((key) => key.includes("profile.v1")).length).toBe(2);
  });

  it("supports one profile across project-specific databases", async () => {
    const vault = new CredentialVault(new MemorySecrets(), new MemoryState());
    const profile = await vault.createProfile("Shared account", "shared-secret-key");
    await vault.bindProject("git:one:1234567890abcdef1234", profile.id, "database-one");
    await vault.bindProject("git:two:1234567890abcdef1234", profile.id, "database-two");
    expect((await vault.acquire("git:one:1234567890abcdef1234")).database).toBe("database-one");
    expect((await vault.acquire("git:two:1234567890abcdef1234")).database).toBe("database-two");
  });

  it("fails closed for corrupt or missing secret records", async () => {
    const secrets = new MemorySecrets();
    const state = new MemoryState();
    const vault = new CredentialVault(secrets, state);
    await expect(vault.acquire("git:repo:1234567890abcdef1234")).rejects.toThrow("not configured");
    const profile = await vault.createProfile("Default", "valid-secret-key");
    await vault.bindProject("git:repo:1234567890abcdef1234", profile.id, "database");
    for (const [key] of secrets.values) {
      if (key.includes("profile.v1")) secrets.values.set(key, "{broken");
    }
    await expect(vault.acquire("git:repo:1234567890abcdef1234")).rejects.toThrow("unavailable");
  });

  it("creates stable installation secrets only in secret storage", async () => {
    const secrets = new MemorySecrets();
    const state = new MemoryState();
    const vault = new CredentialVault(secrets, state);
    const first = await vault.installationSecrets();
    const second = await vault.installationSecrets();
    expect(second).toEqual(first);
    expect(first.control_key).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(JSON.stringify([...state.values])).not.toContain(first.control_key);
  });

  it("keeps OAuth clients and rotating grants only in secret storage", async () => {
    const secrets = new MemorySecrets();
    const state = new MemoryState();
    const vault = new CredentialVault(secrets, state);
    const key = `access/${"a".repeat(64)}`;
    const record = JSON.stringify({ access_token: "opaque-agent-token" });

    await vault.writeOAuthRecord(key, record);
    expect(await vault.readOAuthRecord(key)).toBe(record);
    expect(JSON.stringify([...state.values])).not.toContain("opaque-agent-token");
    await vault.deleteOAuthRecord(key);
    expect(await vault.readOAuthRecord(key)).toBeUndefined();
  });
});
