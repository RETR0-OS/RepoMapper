import { Reveal, Stagger, StaggerItem } from "@/components/motion/Reveal"
import { Section, SectionHeader } from "@/components/layout/Section"
import { problem } from "@/content/copy"

export function Problem() {
  return (
    <Section id="problem" tone="band" size="md">
      <SectionHeader
        index="01"
        eyebrow={problem.eyebrow}
        headline={problem.headline}
        sub={problem.subhead}
        align="center"
      />

      {/* The losses read as a ledger, not a bullet list — a numbered two-column
          table makes the count itself part of the argument. */}
      <Stagger as="ul" className="mt-14 grid grid-cols-1 gap-x-10 md:grid-cols-2">
        {problem.losses.map((loss, index) => (
          <StaggerItem
            key={loss}
            as="li"
            className="flex items-start gap-4 border-t border-border py-4"
          >
            <span className="font-mono text-xs text-muted-foreground/60 tabular-nums">
              {String(index + 1).padStart(2, "0")}
            </span>
            <span className="font-mono text-sm text-foreground">{loss}</span>
          </StaggerItem>
        ))}
      </Stagger>

      <Reveal delay={0.1}>
        <blockquote className="mx-auto mt-14 max-w-2xl border-l-2 border-lime pl-5 text-xl text-foreground md:text-2xl">
          {problem.closing}
        </blockquote>
      </Reveal>
    </Section>
  )
}
