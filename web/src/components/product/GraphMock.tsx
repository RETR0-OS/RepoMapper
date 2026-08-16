import { useReducedMotion } from "motion/react"
import { cn } from "@/lib/utils"
import { graphNodes, graphEdges, modeGraphs } from "@/content/graph"
import type { ViewId } from "@/content/views"
import { GraphNode } from "./GraphNode"
import { GraphEdge } from "./GraphEdge"
import { StatusPill } from "./StatusPill"
import { ModeTabs } from "./ModeTabs"

interface GraphMockProps {
  mode: ViewId
  onModeChange?: (id: ViewId) => void
  showChrome?: boolean
  className?: string
}

export function GraphMock({ mode, onModeChange, showChrome = true, className }: GraphMockProps) {
  const prefersReduced = useReducedMotion()
  const spec = modeGraphs[mode]

  const nodesById = Object.fromEntries(graphNodes.map((n) => [n.id, n]))

  return (
    <div
      className={cn(
        "overflow-hidden rounded-xl border border-border bg-panel shadow-2xl shadow-black/40",
        className,
      )}
    >
      {showChrome && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
          <ModeTabs active={mode} onChange={onModeChange} />
          <StatusPill label={spec.statusLabel} />
        </div>
      )}
      <div className="graph-canvas relative aspect-[3/2] w-full">
        <svg
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          className="absolute inset-0 h-full w-full"
        >
          {graphEdges.map((edge) => {
            const from = nodesById[edge.from]
            const to = nodesById[edge.to]
            const edgeVisible = !edge.modes || edge.modes.includes(mode)
            const state = edgeVisible ? (spec.edgeStates[edge.id] ?? "idle") : "hidden"
            return (
              <GraphEdge
                key={edge.id}
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
                quality={edge.quality}
                state={state}
                reduced={!!prefersReduced}
              />
            )
          })}
        </svg>
        {graphNodes.map((node) => {
          const nodeVisible = !node.modes || node.modes.includes(mode)
          const state = spec.nodeStates[node.id] ?? "idle"
          return (
            <GraphNode
              key={node.id}
              node={node}
              state={nodeVisible ? state : "idle"}
              visible={nodeVisible}
            />
          )
        })}
      </div>
    </div>
  )
}
