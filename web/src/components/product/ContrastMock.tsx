import { cn } from "@/lib/utils"

/**
 * Contrast is the one view that does not render the graph, so it has no
 * GraphMock. It shows two live agent runs side by side instead.
 *
 * The trajectories below are illustrative, in the same way the graph mock's
 * function names are. Deliberately no token or cost figures: those are a
 * measured comparative result, and inventing one here would assert a claim the
 * product refuses to make from a mock.
 */

interface ContrastMockProps {
  className?: string
  /** Drops the footer note and tightens spacing for short tiles. */
  compact?: boolean
}

const baseCalls = ["Grep — complex path", "Bash — git log --oneline", "Read — agent_graph/graph.py", "Grep — def make_plan", "Read — agent_graph/plan.py"]
const argusCalls = ["mcp__repository-map__trace_flow", "mcp__repository-map__focus_symbol"]

function Column({
  label,
  calls,
  accent,
  compact,
}: {
  label: string
  calls: string[]
  accent?: boolean
  compact?: boolean
}) {
  return (
    <div className="flex min-w-0 flex-col gap-2 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <span
          className={cn(
            "font-mono text-[10px] tracking-widest uppercase",
            accent ? "text-lime" : "text-muted-foreground",
          )}
        >
          {label}
        </span>
        <span className="font-mono text-[9px] text-muted-foreground">Completed</span>
      </div>
      <div className="flex flex-col gap-1.5">
        {calls.slice(0, compact ? 3 : calls.length).map((call) => (
          <span
            key={call}
            className="truncate rounded-md border border-border bg-raised px-2 py-1 font-mono text-[9px] text-muted-foreground"
          >
            {call}
          </span>
        ))}
      </div>
    </div>
  )
}

export function ContrastMock({ className, compact = false }: ContrastMockProps) {
  return (
    <div
      className={cn(
        "overflow-hidden rounded-xl border border-border bg-panel shadow-2xl shadow-black/40",
        className,
      )}
    >
      <div className="grid grid-cols-2 divide-x divide-border">
        <Column label="Base agent" calls={baseCalls} compact={compact} />
        <Column label="With Argus" calls={argusCalls} accent compact={compact} />
      </div>
      {!compact && (
        <p className="border-t border-border px-3 py-2 font-mono text-[9px] leading-relaxed text-muted-foreground">
          Both runs are live. Every figure comes from the agent's own usage report.
        </p>
      )}
    </div>
  )
}
