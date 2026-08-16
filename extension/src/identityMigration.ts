import type { ProjectIdentityRecord } from "./projectIdentity.js";
import type { ServiceHealth } from "./types.js";

export interface IdentityMigrationPreview {
  currentRepositoryId: string;
  candidateRepositoryId: string;
  indexedSourceCount: number;
  canMigrateWithoutOrphans: boolean;
  explanation: string;
}

export function previewIdentityMigration(
  current: ProjectIdentityRecord,
  candidate: ProjectIdentityRecord,
  health: ServiceHealth
): IdentityMigrationPreview {
  if (current.repository_id === candidate.repository_id || candidate.source !== "git-origin") {
    throw new Error("Identity migration requires a different canonical Git identity.");
  }
  if (health.repositoryId && health.repositoryId !== current.repository_id) {
    throw new Error("The managed service is bound to a different repository identity.");
  }
  const indexedSourceCount = health.sourceCount ?? -1;
  const canMigrateWithoutOrphans = indexedSourceCount === 0 && health.state !== "indexing";
  return {
    currentRepositoryId: current.repository_id,
    candidateRepositoryId: candidate.repository_id,
    indexedSourceCount,
    canMigrateWithoutOrphans,
    explanation: canMigrateWithoutOrphans
      ? "No indexed current sources exist, so the local identity and secure database binding can move without orphaning HydraDB data."
      : "Argus will keep the existing identity because it cannot prove exhaustive deletion of current and evolution sources. Reset or migrate the HydraDB data explicitly before changing this identity."
  };
}

export function formatIdentityMigration(preview: IdentityMigrationPreview): string {
  const count = preview.indexedSourceCount < 0 ? "unknown" : String(preview.indexedSourceCount);
  return [
    `Current identity: ${preview.currentRepositoryId}`,
    `Canonical Git identity: ${preview.candidateRepositoryId}`,
    `Verified local source manifest: ${count} source cards`,
    "",
    preview.explanation
  ].join("\n");
}
