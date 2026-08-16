export const nav = {
  logo: "Argus",
  links: [
    { name: "Product", link: "/#views" },
    { name: "Evidence", link: "/#evidence" },
    { name: "Agents", link: "/#agents" },
  ],
}

export const hero = {
  eyebrow: "Repository observability for agentic coding",
  headline: "See your code like your agent.",
  subhead:
    "Argus is a HydraDB-backed VS Code extension. Explore how your repository actually works, watch the exact context a coding agent retrieved, and review what its edit changed — all from one graph, grounded in source.",
  primaryCta: "Download the extension",
  secondaryCta: "Read the docs",
}

export const problem = {
  eyebrow: "The problem",
  headline: "Your agent can ship 40 files before you finish your coffee.",
  subhead:
    "Agentic coding increases the rate a repository changes. You can approve edit after edit without rebuilding a reliable mental model of the system. Over time you lose track of:",
  losses: [
    "Where important behavior actually lives",
    "Which entrypoint leads to which outcome",
    "Which symbols and systems depend on one another",
    "Which tests protect an important path",
    "How configuration and infrastructure reach runtime code",
    "What repository evidence the agent used, and what its change structurally did",
  ],
  closing:
    "Code search finds text. Static diagrams go stale. A generic force-directed graph becomes an unreadable hairball.",
}

export const truthRule = {
  eyebrow: "The truth rule",
  headline: "Nothing you see is guessed.",
  subhead:
    "Local analysis creates deterministic source cards and exact relations for indexing — it is never a hidden retrieval fallback. When HydraDB is unavailable, the product says so. It does not quietly substitute a local search result.",
  layers: [
    {
      name: "Repository truth",
      description:
        "A local analyzer reads source code and emits concrete nodes, relations, and evidence as Graph IR.",
    },
    {
      name: "Queryable knowledge",
      description:
        "Source cards and exact relations are synchronized to HydraDB. HydraDB filters, ranks, and returns relevant chunks and graph paths.",
    },
    {
      name: "Bounded views",
      description:
        "The VS Code extension and the repository MCP tools show the returned slice. They never query a hidden local graph.",
    },
  ],
}

export const evidence = {
  eyebrow: "Evidence, not vibes",
  headline: "Every edge opens the line that proves it.",
  subhead:
    "An exact relation is supported by a deterministic mechanism — syntax, resolved names, explicit filesystem ownership — and carries named extractor provenance. An inferred relation is a deterministic hypothesis, structurally and visually separate, hidden by default. Moving two nodes closer together does not make them more related.",
  inspectorFields: [
    { label: "Why shown", value: "Returned by the current bounded view" },
    { label: "Method", value: "resolved-import-graph · no LLM" },
    { label: "Stable ID", value: "fn:service/hydra_graph/query.py::run_query" },
    { label: "Revision", value: "a41c9f2 · verified" },
    { label: "HydraDB", value: "hybrid retrieval · graph_context=true" },
  ],
}

export const agents = {
  eyebrow: "One graph, two audiences",
  headline: "You and your agent read the same HydraDB graph.",
  subhead:
    "Argus exposes one Streamable HTTP MCP endpoint inside the managed service — not a second process, and available only while VS Code is running. Codex and Claude Code connect to the same bounded, evidenced context you see in the panel.",
}

export const howToUse = {
  eyebrow: "How to use it",
  headline: "Plug and Play.",
  steps: [
    {
      title: "Install",
      description:
        "Install the platform-specific Argus package and open your project folder in VS Code.",
    },
    {
      title: "Connect HydraDB",
      description:
        "Create or select a HydraDB account profile, then enter the API key and this project's database name in masked fields.",
    },
    {
      title: "Preview and confirm",
      description:
        "Review the local analysis preview — discovered files, node and relation counts, every generated source card — before anything uploads.",
    },
    {
      title: "Open the map",
      description:
        "Start with Repository for orientation, then move into Explore, Trace, Observe, Compare, and Preserve as you work.",
    },
  ],
}

export const honestEvidence = {
  eyebrow: "Honest by design",
  headline: "We show our work, including where it's incomplete.",
  cards: [
    {
      title: "A/B/C evaluation harness",
      description:
        "A checked evaluation compares a TF-IDF baseline, HydraDB without graph context, and HydraDB with graph context, scoring required nodes, exact and inferred relation hits, and evidence-span hits separately. Comparative claims are refused when the inputs are incomplete or mismatched.",
    },
    {
      title: "Security boundary",
      description:
        "API keys and database bindings live only in VS Code SecretStorage. The service is loopback-only. MCP uses OAuth 2.1 with PKCE S256, short-lived access tokens, and rotating refresh tokens, with read-only scopes by default.",
    },
  ],
}

export const download = {
  eyebrow: "Get it",
  headline: "Download Argus",
  subhead:
    "Six platform-specific VSIX packages. Each bundles the TypeScript extension and a native one-directory Python service build — end users never install Python or Node.",
}
