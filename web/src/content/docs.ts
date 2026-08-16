export const docsIntro = {
  eyebrow: "Documentation",
  headline: "Everything you need to run Argus.",
  subhead:
    "A practical reference for installing the extension, reading the six views, connecting a coding agent, and understanding exactly what the product does and doesn't promise.",
}

export interface DocStep {
  title: string
  description: string
}

export const gettingStarted: { headline: string; steps: DocStep[] } = {
  headline: "Getting started",
  steps: [
    {
      title: "Install the extension",
      description:
        "Install the platform-specific Argus package, then open your project folder in VS Code. You don't need Python, Node, npm, or a separate MCP process.",
    },
    {
      title: "Connect HydraDB",
      description:
        "Create or select a HydraDB account profile, then enter the API key and this project's database name in masked fields. A profile can be reused across multiple projects with different databases.",
    },
    {
      title: "Preview and confirm the index",
      description:
        "Review the local analysis preview first — discovered files, node and relation counts, every generated source card. Nothing uploads until you explicitly confirm.",
    },
    {
      title: "Open Argus",
      description:
        "Start with Repository for orientation, then move into Explore, Trace, Observe, Compare, and Preserve as you work. Selecting a node opens its file at the exact line.",
    },
    {
      title: "Connect Codex or Claude Code (optional)",
      description:
        "Run \"Configure Agents\" to detect installed CLIs and register the loopback MCP endpoint. First access opens a native consent dialog — nothing is written to agent config beyond the current URL.",
    },
    {
      title: "Re-index after meaningful changes",
      description:
        "Run \"Index Workspace with HydraDB\" after a significant edit so Repository, Trace, and Observe stay pinned to a current verified revision.",
    },
  ],
}

export const security = {
  headline: "Security & privacy",
  points: [
    {
      title: "Credentials never leave VS Code",
      description:
        "Your HydraDB API key and database name live only in VS Code's built-in SecretStorage — never in settings, project files, environment variables, command arguments, or logs.",
    },
    {
      title: "Loopback-only service",
      description:
        "The bundled service binds to loopback only and is never exposed to your network. It enforces host checks, size limits, rate limits, and explicit write confirmation.",
    },
    {
      title: "Agent access is scoped and short-lived",
      description:
        "MCP uses OAuth 2.1 with PKCE S256, 5-minute access tokens, and rotating 1-day refresh tokens. Scopes are read-only by default: repository:read, evidence:read, observe:read.",
    },
    {
      title: "No silent fallback",
      description:
        "If HydraDB can't be reached, the panel shows an explicit degraded state. It never substitutes a local guess and presents it as real repository data.",
    },
  ],
}

export interface StatusLabel {
  label: string
  meaning: string
}

export const statusLabels: StatusLabel[] = [
  { label: "HydraDB · revision … ready", meaning: "The visible result is pinned to HydraDB's verified revision." },
  { label: "HydraDB · indexing", meaning: "A candidate revision is being indexed. The last verified revision stays active in the meantime." },
  { label: "HydraDB · revision unverified", meaning: "HydraDB answered, but the view isn't yet proven to match the verified revision." },
  { label: "HydraDB · indexing failed", meaning: "The candidate didn't become current. A partial revision is never shown as ready." },
  { label: "HydraDB · unavailable for this view", meaning: "No HydraDB-backed result is available for this view — and nothing is faked in its place." },
  { label: "Preview · service unavailable", meaning: "A bounded interaction demo shown only to teach the controls. It is never labeled as real repository data." },
]
