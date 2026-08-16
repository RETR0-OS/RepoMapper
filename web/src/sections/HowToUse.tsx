import { Stagger, StaggerItem } from "@/components/motion/Reveal"
import { Section, SectionHeader } from "@/components/layout/Section"
import { howToUse } from "@/content/copy"

export function HowToUse() {
  return (
    <Section id="how-to-use" tone="default" size="md">
      <SectionHeader index="06" eyebrow={howToUse.eyebrow} headline={howToUse.headline} align="left" />

      <Stagger className="relative mt-16 grid grid-cols-1 gap-10 md:grid-cols-4 md:gap-8">
        {/* The rail runs through the circles' centre; each circle is opaque, so the
            line reads as connecting the steps instead of cutting through them. */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-4 hidden border-t border-border md:block"
        />

        {howToUse.steps.map((step, index) => (
          <StaggerItem key={step.title} className="relative flex flex-col">
            <span className="flex size-8 items-center justify-center rounded-full border border-lime/40 bg-background font-mono text-xs text-lime">
              {String(index + 1).padStart(2, "0")}
            </span>

            <div className="mt-5 flex-1 rounded-xl border border-border bg-panel p-5">
              <h3 className="text-lg font-semibold text-foreground">{step.title}</h3>
              <p className="mt-2 text-sm text-muted-foreground">{step.description}</p>
            </div>
          </StaggerItem>
        ))}
      </Stagger>
    </Section>
  )
}
