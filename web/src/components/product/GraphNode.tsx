import { motion } from "motion/react"
import { cn } from "@/lib/utils"
import type { GraphNodeData, NodeState } from "@/content/graph"

const stateClasses: Record<NodeState, string> = {
  idle: "border-border bg-panel text-muted-foreground",
  returned: "border-cyan-accent/50 bg-panel text-foreground shadow-[0_0_0_1px_var(--cyan-accent)_inset] shadow-cyan-accent/10",
  selected: "border-lime bg-lime-soft text-foreground shadow-[0_0_0_2px_var(--lime)_inset]",
  opened: "border-amber-accent bg-panel text-foreground shadow-[0_0_0_2px_var(--amber-accent)_inset]",
  edited: "border-lime bg-lime-soft/70 text-foreground shadow-[0_0_0_2px_var(--lime)_inset]",
  added: "border-lime bg-lime-soft text-foreground",
  removed: "border-danger/70 border-dashed bg-panel text-muted-foreground opacity-70",
  modified: "border-amber-accent bg-panel text-foreground shadow-[0_0_0_1px_var(--amber-accent)_inset]",
}

const badgeText: Partial<Record<NodeState, string>> = {
  selected: "selected",
  opened: "opened",
  edited: "edited",
  added: "added",
  removed: "removed",
  modified: "modified",
}

const badgeClasses: Partial<Record<NodeState, string>> = {
  selected: "text-lime",
  opened: "text-amber-accent",
  edited: "text-lime",
  added: "text-lime",
  removed: "text-danger",
  modified: "text-amber-accent",
}

interface GraphNodeProps {
  node: GraphNodeData
  state: NodeState
  visible: boolean
}

export function GraphNode({ node, state, visible }: GraphNodeProps) {
  const badge = badgeText[state]

  return (
    <motion.div
      className="absolute w-[116px] -translate-x-1/2 -translate-y-1/2"
      style={{ left: `${node.x}%`, top: `${node.y}%` }}
      animate={{ opacity: visible ? 1 : 0, scale: visible ? 1 : 0.92 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
    >
      <div
        className={cn(
          "rounded-lg border px-2.5 py-2 font-mono text-[10px] leading-tight transition-colors duration-200",
          stateClasses[state],
        )}
      >
        <div className="flex items-center justify-between gap-2">
          <span className="tracking-widest text-muted-foreground uppercase">{node.kind}</span>
          {badge && (
            <span className={cn("tracking-widest uppercase", badgeClasses[state])}>{badge}</span>
          )}
        </div>
        <div className="mt-1 truncate font-sans text-[12px] font-medium text-foreground">
          {node.name}
        </div>
        <div className="mt-0.5 truncate text-muted-foreground">{node.path}</div>
      </div>
    </motion.div>
  )
}
