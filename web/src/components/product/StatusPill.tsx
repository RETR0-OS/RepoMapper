import { cn } from "@/lib/utils"

type Tone = "ready" | "live" | "degraded"

function toneFromLabel(label: string): Tone {
  if (label.toLowerCase().includes("degraded") || label.toLowerCase().includes("unavailable")) {
    return "degraded"
  }
  if (label.toLowerCase().includes("session live") || label.toLowerCase().includes("thinking")) {
    return "live"
  }
  return "ready"
}

const dotClass: Record<Tone, string> = {
  ready: "bg-lime",
  live: "bg-cyan-accent",
  degraded: "bg-amber-accent",
}

export function StatusPill({ label, className }: { label: string; className?: string }) {
  const tone = toneFromLabel(label)
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-border bg-panel px-2.5 py-1 font-mono text-[10px] tracking-wide text-muted-foreground whitespace-nowrap",
        className,
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", dotClass[tone])} />
      {label}
    </span>
  )
}
