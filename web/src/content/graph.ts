import type { ViewId } from "./views"

export type NodeKind = "FILE" | "FUNCTION" | "TEST"
export type NodeState =
  | "idle"
  | "returned"
  | "selected"
  | "opened"
  | "edited"
  | "added"
  | "removed"
  | "modified"

export type EdgeQuality = "exact" | "inferred"
export type EdgeState = "idle" | "active" | "added" | "removed" | "hidden"

export interface GraphNodeData {
  id: string
  kind: NodeKind
  name: string
  path: string
  x: number
  y: number
  /** Only rendered in these modes (compare-only nodes stay out of the rest). */
  modes?: ViewId[]
}

export interface GraphEdgeData {
  id: string
  from: string
  to: string
  predicate: string
  quality: EdgeQuality
  modes?: ViewId[]
}

// 6-column grid, wide margins so cards never clip even in the narrowest
// (~34rem) panel this mock is embedded in. Columns: 13 / 28 / 43 / 58 / 73 / 88.
// Rows: 16 (top) / 50 (middle) / 88 (bottom).
export const graphNodes: GraphNodeData[] = [
  { id: "routes", kind: "FILE", name: "routes.py", path: "api/routes.py", x: 13, y: 50 },
  { id: "handle_login", kind: "FUNCTION", name: "handle_login", path: "api/routes.py:18", x: 28, y: 16 },
  { id: "service", kind: "FILE", name: "service.py", path: "auth/service.py", x: 43, y: 50 },
  { id: "authenticate_user", kind: "FUNCTION", name: "authenticate_user", path: "auth/service.py:42", x: 58, y: 16 },
  { id: "test_auth", kind: "TEST", name: "test_authenticate_user", path: "tests/test_auth.py:11", x: 58, y: 88 },
  { id: "session", kind: "FILE", name: "session.py", path: "db/session.py", x: 73, y: 50 },
  { id: "write_session", kind: "FUNCTION", name: "write_session", path: "db/session.py:27", x: 88, y: 16 },
  {
    id: "revoke_session",
    kind: "FUNCTION",
    name: "revoke_session",
    path: "db/session.py:61",
    x: 88,
    y: 88,
    modes: ["compare"],
  },
  {
    id: "legacy_check",
    kind: "FUNCTION",
    name: "legacy_token_check",
    path: "auth/service.py:88",
    x: 43,
    y: 88,
    modes: ["compare"],
  },
]

export const graphEdges: GraphEdgeData[] = [
  { id: "e1", from: "routes", to: "handle_login", predicate: "contains", quality: "exact" },
  { id: "e2", from: "handle_login", to: "authenticate_user", predicate: "calls", quality: "exact" },
  { id: "e3", from: "service", to: "authenticate_user", predicate: "contains", quality: "exact" },
  { id: "e4", from: "authenticate_user", to: "write_session", predicate: "calls", quality: "exact" },
  { id: "e5", from: "session", to: "write_session", predicate: "contains", quality: "exact" },
  { id: "e6", from: "test_auth", to: "authenticate_user", predicate: "tests", quality: "exact" },
  { id: "e7", from: "handle_login", to: "write_session", predicate: "calls", quality: "inferred" },
  { id: "e8", from: "service", to: "legacy_check", predicate: "contains", quality: "exact", modes: ["compare"] },
  { id: "e9", from: "session", to: "revoke_session", predicate: "contains", quality: "exact", modes: ["compare"] },
]

interface ModeGraphSpec {
  nodeStates: Record<string, NodeState>
  edgeStates: Record<string, EdgeState>
  statusLabel: string
}

const base = (nodeStates: Record<string, NodeState>, edgeStates: Record<string, EdgeState>, statusLabel: string) => ({
  nodeStates,
  edgeStates,
  statusLabel,
})

export const modeGraphs: Record<ViewId, ModeGraphSpec> = {
  repository: base(
    {
      routes: "idle",
      handle_login: "idle",
      service: "idle",
      authenticate_user: "idle",
      test_auth: "idle",
      session: "idle",
      write_session: "idle",
    },
    { e1: "idle", e3: "idle", e5: "idle", e2: "hidden", e4: "hidden", e6: "hidden", e7: "hidden" },
    "HydraDB · revision a41c9f2 ready",
  ),
  explore: base(
    {
      routes: "idle",
      handle_login: "returned",
      service: "returned",
      authenticate_user: "selected",
      test_auth: "returned",
      session: "idle",
      write_session: "returned",
    },
    { e1: "idle", e2: "active", e3: "active", e4: "active", e5: "idle", e6: "active", e7: "hidden" },
    "HydraDB · revision a41c9f2 ready",
  ),
  trace: base(
    {
      routes: "returned",
      handle_login: "returned",
      service: "idle",
      authenticate_user: "returned",
      test_auth: "idle",
      session: "idle",
      write_session: "returned",
    },
    { e1: "active", e2: "active", e3: "idle", e4: "active", e5: "idle", e6: "hidden", e7: "hidden" },
    "HydraDB · hybrid retrieval · thinking",
  ),
  observe: base(
    {
      routes: "returned",
      handle_login: "returned",
      service: "idle",
      authenticate_user: "edited",
      test_auth: "opened",
      session: "idle",
      write_session: "returned",
    },
    { e1: "active", e2: "active", e3: "idle", e4: "active", e5: "idle", e6: "active", e7: "hidden" },
    "Observe · session live",
  ),
  compare: base(
    {
      routes: "idle",
      handle_login: "idle",
      service: "idle",
      authenticate_user: "modified",
      test_auth: "idle",
      session: "idle",
      write_session: "idle",
      revoke_session: "added",
      legacy_check: "removed",
    },
    { e1: "idle", e2: "idle", e3: "idle", e4: "idle", e5: "idle", e6: "hidden", e7: "hidden", e8: "removed", e9: "added" },
    "Compare · a41c9f2 → f7203bd",
  ),
  preserve: base(
    {
      routes: "returned",
      handle_login: "returned",
      service: "idle",
      authenticate_user: "returned",
      test_auth: "idle",
      session: "idle",
      write_session: "returned",
    },
    { e1: "active", e2: "active", e3: "idle", e4: "active", e5: "idle", e6: "hidden", e7: "hidden" },
    "Preserve · lens grounded",
  ),
}
