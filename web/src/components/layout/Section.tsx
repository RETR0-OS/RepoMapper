import type { ReactNode } from "react"
import { cn } from "@/lib/utils"
import { Reveal } from "@/components/motion/Reveal"

/**
 * The page's rhythm system. Every landing section wraps its body in `Section`
 * and opens with `SectionHeader`, so the vertical rhythm, the surface, and the
 * heading treatment are decided in one place instead of being retyped per
 * section — which is how the page ended up looking the same all the way down.
 *
 * `tone="band"` is the variation lever: it renders a full-bleed raised surface
 * with hairline edges. Alternating band and default down the page is what gives
 * the reader a sense of movement between sections.
 */

type SectionTone = "default" | "band"
type SectionSize = "sm" | "md" | "lg"

const sizeClasses: Record<SectionSize, string> = {
  sm: "py-16 md:py-20",
  md: "py-24 md:py-32",
  lg: "py-32 md:py-40",
}

interface SectionProps {
  id?: string
  children: ReactNode
  tone?: SectionTone
  size?: SectionSize
  className?: string
  /** Drops the inner `max-w-6xl` shell for sections that lay out their own. */
  bare?: boolean
}

export function Section({
  id,
  children,
  tone = "default",
  size = "md",
  className,
  bare = false,
}: SectionProps) {
  return (
    <section
      id={id}
      className={cn(
        sizeClasses[size],
        tone === "band" && "border-y border-border bg-panel/40",
        className,
      )}
    >
      {bare ? children : <div className="mx-auto max-w-6xl px-6">{children}</div>}
    </section>
  )
}

interface SectionHeaderProps {
  /** Mono spine marker, e.g. "02". Gives the page a sense of progress. */
  index?: string
  eyebrow?: string
  headline: ReactNode
  sub?: ReactNode
  align?: "left" | "center"
  className?: string
}

export function SectionHeader({
  index,
  eyebrow,
  headline,
  sub,
  align = "left",
  className,
}: SectionHeaderProps) {
  const centered = align === "center"

  return (
    <div className={cn(centered && "text-center", className)}>
      {(index || eyebrow) && (
        <Reveal>
          <div
            className={cn(
              "flex items-center gap-3 font-mono text-[11px] tracking-widest uppercase",
              centered && "justify-center",
            )}
          >
            {index && <span className="text-muted-foreground/60">{index}</span>}
            {index && eyebrow && (
              <span aria-hidden className="h-px w-6 bg-border" />
            )}
            {eyebrow && <span className="text-lime">{eyebrow}</span>}
          </div>
        </Reveal>
      )}

      <Reveal delay={0.05}>
        <h2
          className={cn(
            "mt-5 text-3xl font-semibold tracking-tight text-foreground md:text-5xl",
            centered ? "mx-auto max-w-3xl" : "max-w-3xl",
          )}
        >
          {headline}
        </h2>
      </Reveal>

      {sub && (
        <Reveal delay={0.1}>
          <p
            className={cn(
              "mt-6 text-lg text-muted-foreground",
              centered ? "mx-auto max-w-2xl" : "max-w-2xl",
            )}
          >
            {sub}
          </p>
        </Reveal>
      )}
    </div>
  )
}
