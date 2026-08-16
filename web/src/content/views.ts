export type ViewId =
  | "repository"
  | "explore"
  | "trace"
  | "observe"
  | "compare"
  | "preserve"

export interface ProductView {
  id: ViewId
  index: number
  name: string
  verb: string
  purpose: string
  description: string
  primaryAction: string
}

export const views: ProductView[] = [
  {
    id: "repository",
    index: 0,
    name: "Repository",
    verb: "Orient",
    purpose: "Orient to concrete packages, files, or symbols.",
    description:
      "A deterministic 2D structure map. Move between package, file, and symbol depth. Exact relations only — never an invented concept node.",
    primaryAction: "Open local graph",
  },
  {
    id: "explore",
    index: 1,
    name: "Explore",
    verb: "Inspect",
    purpose: "Inspect a bounded neighborhood around code.",
    description:
      "Select a symbol and see its returned callers, callees, imports, and tests. Expansion asks the service for the next bounded result — it is never invented locally.",
    primaryAction: "Expand graph",
  },
  {
    id: "trace",
    index: 2,
    name: "Trace",
    verb: "Ask",
    purpose: "Explain a returned system path left to right.",
    description:
      'Ask "How does an incoming request reach a database write?" HydraDB performs hybrid retrieval with graph context and returns a readable, evidenced path.',
    primaryAction: "Replay path",
  },
  {
    id: "observe",
    index: 3,
    name: "Observe",
    verb: "Watch",
    purpose: "Follow explicit repository activity for one verified revision.",
    description:
      "See the same HydraDB queries, returned context, selections, and evidence opens your coding agent used — not its hidden reasoning, only what it actually retrieved.",
    primaryAction: "Pause follow",
  },
  {
    id: "compare",
    index: 4,
    name: "Compare",
    verb: "Review",
    purpose: "Review a published structural delta between two revisions.",
    description:
      "Added, removed, and modified nodes and edges get distinct treatment. See exactly what an agent's edit changed in the graph, not just in the diff.",
    primaryAction: "Review changes",
  },
  {
    id: "preserve",
    index: 5,
    name: "Preserve",
    verb: "Save",
    purpose: "Maintain a grounded, shared System Lens across revisions.",
    description:
      "Save an important path — authentication, checkout, deployment — grounded in graph IDs. When the code changes, review and accept drift instead of a diagram going stale.",
    primaryAction: "Accept drift",
  },
]
