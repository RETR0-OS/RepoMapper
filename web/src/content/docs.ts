export const docsIntro = {
  eyebrow: "Documentation",
  headline: "Everything you need to run Argus.",
  subhead:
    "A practical reference for installing the extension, reading the seven views, connecting a coding agent, and understanding exactly what the product does and doesn't promise.",
}

export const contrastView = {
  name: "Contrast",
  verb: "Measure",
  purpose: "Measure the same question asked with and without Argus.",
  landing:
    "Ask one question and it runs twice with the same agent and the same model — once on the harness alone, once on that same harness with Argus added. Both columns are live runs, and every figure comes from the agent's own usage report.",
  description:
    "The same question, answered twice by the same agent and the same model. The base run uses the tools its harness already gives it. The Argus run is that same harness with the loopback MCP endpoint added, so it can also call repository_query, trace_flow, and focus_symbol. The two sides differ by addition only — nothing is taken away to make Argus look better. Both runs are live; neither column is a fixture or a recording.",
  measured:
    "Each column reports the agent's own measured usage: tools available, tool calls, files read, turns, input/output/cache tokens, thinking tokens, duration, and cost in USD. The numbers come from the agent CLI's usage report, not from an Argus estimate. Each side also shows the answer it finished with, so you can weigh quality against cost instead of reading token counts alone.",
  caveats: [
    "Because the Argus run keeps its own tools, a better answer doesn't prove an Argus tool produced it. The tool-call list shows what the agent actually used.",
    "Write, Edit, and NotebookEdit are denied on both sides. Contrast is read-only.",
    "Agent runs are not deterministic. The panel reports the run it made; it does not average runs or claim a general result.",
    "The spawned agent never receives HydraDB credentials. Every HYDRA_DB_* environment variable is stripped before the process starts.",
    "The Argus side needs the repository-map MCP server both registered and signed in for that project. These are two separate steps, and an unauthenticated server is dropped silently — leaving that run with no Argus tools at all.",
    "Contrast needs the claude CLI installed and signed in, and each run costs real money because it is two real agent runs.",
  ],
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
        "Start with Repository for orientation, then move into Explore, Trace, Observe, Compare, Preserve, and Contrast as you work. Selecting a node opens its file at the exact line.",
    },
    {
      title: "Connect Codex or Claude Code (optional)",
      description:
        "Run \"Configure Agents\" to detect installed CLIs and register the loopback MCP endpoint. Nothing is written to agent config beyond the current URL. Registering and signing in are separate steps: approve the consent prompt on first access, or run the sign-in command yourself. Contrast needs a signed-in server, because a headless run can't answer a consent prompt.",
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
