export interface McpTool {
  name: string
  description: string
}

export const mcpTools: McpTool[] = [
  { name: "repository_query", description: "Hybrid HydraDB repository question." },
  { name: "focus_symbol", description: "Bounded literal retrieval around a known entity." },
  { name: "trace_flow", description: "Bounded multi-hop HydraDB path." },
  { name: "explain_relationship", description: "Evidence for an edge already present in a stored view." },
  { name: "compare_repository_graph", description: "Evolution knowledge for two revisions." },
  { name: "open_system_lens", description: "A shared lens record and its current grounded path." },
  { name: "pin_context", description: "Explicit programmer-selected context in an active Observe session." },
]

export const mcpScopes = [
  { scope: "repository:read", description: "Bounded repository queries and views." },
  { scope: "evidence:read", description: "Source-backed relation explanation." },
  { scope: "observe:read", description: "Explicit Observe correlation and view events." },
]

export const agentCommands = {
  codex: "codex mcp add repository-map --url http://127.0.0.1:<port>/mcp",
  claude: [
    "claude mcp add --transport http --scope local repository-map http://127.0.0.1:<port>/mcp",
    "",
    "# Registering is not signing in. Authorize the server before a headless run:",
    "claude mcp login repository-map",
  ].join("\n"),
}
