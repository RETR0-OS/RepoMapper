import type { GraphView, ServiceHealth } from "./types.js";

export interface ViewStatusPresentation {
  health: ServiceHealth;
  verified: boolean;
  label: string;
  revisionLabel: string;
  tone: "ready" | "loading" | "degraded";
  bannerHidden: boolean;
  bannerTitle: string;
  bannerMessage: string;
}

export function isConcreteRevision(value: string | undefined): value is string {
  return Boolean(value && value !== "current" && value !== "unknown" && value !== "preview");
}

export function reconcileHealthWithView(health: ServiceHealth, view: GraphView): ServiceHealth {
  if (view.preview) {
    return {
      ...health,
      state: "unavailable",
      message: health.message ?? "The repository service is unavailable."
    };
  }
  if (!view.hydradb || view.hydradb.available === false) {
    return {
      ...health,
      state: "unavailable",
      message: view.warnings[0] ?? "HydraDB is unavailable for this view; no local retrieval fallback is active."
    };
  }
  if (health.state === "ready" && (
    !isConcreteRevision(health.revision)
    || !isConcreteRevision(view.revision)
    || health.revision !== view.revision
  )) {
    return {
      ...health,
      state: "unverified",
      message: "HydraDB responded, but this view is not pinned to the service's verified revision."
    };
  }
  return health;
}

export function deriveViewStatus(view: GraphView, health: ServiceHealth): ViewStatusPresentation {
  const effective = reconcileHealthWithView(health, view);
  const verified = effective.state === "ready"
    && view.hydradb?.available === true
    && isConcreteRevision(effective.revision)
    && effective.revision === view.revision;

  if (view.preview) {
    return {
      health: effective,
      verified: false,
      label: "Preview · service unavailable",
      revisionLabel: "Not a repository result",
      tone: "degraded",
      bannerHidden: false,
      bannerTitle: "Interactive preview",
      bannerMessage: `${effective.message ?? "The repository service is unavailable."} No HydraDB result is being shown.`
    };
  }
  if (verified) {
    return {
      health: effective,
      verified: true,
      label: `HydraDB · revision ${view.revision} ready`,
      revisionLabel: `Verified revision ${view.revision}`,
      tone: "ready",
      bannerHidden: true,
      bannerTitle: "Verified revision",
      bannerMessage: ""
    };
  }
  if (effective.state === "indexing") {
    return {
      health: effective,
      verified: false,
      label: "HydraDB · indexing",
      revisionLabel: isConcreteRevision(effective.revision) ? `Last verified ${effective.revision}` : "No verified revision",
      tone: "loading",
      bannerHidden: false,
      bannerTitle: "Indexing in progress",
      bannerMessage: effective.message ?? "The last verified revision remains active until indexing completes."
    };
  }
  if (effective.state === "unverified") {
    return {
      health: effective,
      verified: false,
      label: "HydraDB · revision unverified",
      revisionLabel: "No verified revision",
      tone: "degraded",
      bannerHidden: false,
      bannerTitle: "Revision not verified",
      bannerMessage: effective.message ?? "This view is not pinned to a verified repository revision."
    };
  }
  if (effective.state === "failed") {
    return {
      health: effective,
      verified: false,
      label: "HydraDB · indexing failed",
      revisionLabel: isConcreteRevision(effective.revision) ? `Last verified ${effective.revision}` : "No verified revision",
      tone: "degraded",
      bannerHidden: false,
      bannerTitle: "Indexing failed",
      bannerMessage: effective.message ?? "The candidate revision failed. A partial revision is not being shown as current."
    };
  }
  return {
    health: effective,
    verified: false,
    label: "HydraDB · unavailable for this view",
    revisionLabel: "No verified result",
    tone: "degraded",
    bannerHidden: false,
    bannerTitle: "Repository graph unavailable",
    bannerMessage: effective.message ?? "HydraDB is unavailable for this view; no local retrieval fallback is active."
  };
}
