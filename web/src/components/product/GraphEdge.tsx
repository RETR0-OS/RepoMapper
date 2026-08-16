import { motion } from "motion/react"
import { cn } from "@/lib/utils"
import type { EdgeQuality, EdgeState } from "@/content/graph"

interface GraphEdgeProps {
  x1: number
  y1: number
  x2: number
  y2: number
  quality: EdgeQuality
  state: EdgeState
  reduced?: boolean
}

const strokeByState: Record<Exclude<EdgeState, "hidden">, string> = {
  idle: "var(--border)",
  active: "var(--cyan-accent)",
  added: "var(--lime)",
  removed: "var(--danger)",
}

export function GraphEdge({ x1, y1, x2, y2, quality, state, reduced }: GraphEdgeProps) {
  const cx = x1 + (x2 - x1) * 0.5
  const d = `M ${x1} ${y1} C ${cx} ${y1}, ${cx} ${y2}, ${x2} ${y2}`
  const visible = state !== "hidden"
  const isDashed = quality === "inferred" || state === "removed"
  const stroke = strokeByState[state === "hidden" ? "idle" : state]

  return (
    <motion.path
      d={d}
      fill="none"
      stroke={stroke}
      strokeWidth={state === "active" || state === "added" ? 1.4 : 0.9}
      strokeDasharray={isDashed ? "3 2.5" : undefined}
      strokeLinecap="round"
      className={cn(quality === "inferred" && "opacity-70")}
      initial={false}
      animate={
        reduced
          ? { opacity: visible ? 1 : 0 }
          : { opacity: visible ? 1 : 0, pathLength: visible ? 1 : 0 }
      }
      transition={{ duration: reduced ? 0.2 : 0.6, ease: [0.16, 1, 0.3, 1] }}
    />
  )
}
