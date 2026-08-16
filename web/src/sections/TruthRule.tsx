import { Stagger, StaggerItem } from "@/components/motion/Reveal"
import { Section, SectionHeader } from "@/components/layout/Section"
import { truthRule } from "@/content/copy"

export function TruthRule() {
  return (
    <Section id="truth-rule" tone="band" size="md">
      <SectionHeader
        index="03"
        eyebrow={truthRule.eyebrow}
        headline={truthRule.headline}
        sub={truthRule.subhead}
        align="center"
      />

      <Stagger className="relative mt-16 grid grid-cols-1 gap-8 md:grid-cols-3">
        {/* One continuous rail behind all three layers reads as a single pipeline;
            the numbered nodes below sit on it at `top-4`, the circles' centre. */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-4 hidden border-t border-border md:block"
        />

        {truthRule.layers.map((layer, index) => (
          <StaggerItem key={layer.name} className="relative flex flex-col">
            <div className="flex md:justify-center">
              <span className="flex size-8 items-center justify-center rounded-full border border-lime/40 bg-raised font-mono text-xs text-lime">
                {index + 1}
              </span>
            </div>

            <div className="mt-5 flex-1 rounded-xl border border-border bg-raised p-5">
              <div className="font-mono text-xs tracking-widest text-lime uppercase">
                {layer.name}
              </div>
              <p className="mt-3 text-sm text-muted-foreground">{layer.description}</p>
            </div>
          </StaggerItem>
        ))}
      </Stagger>
    </Section>
  )
}
