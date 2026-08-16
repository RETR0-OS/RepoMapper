import { Reveal } from "@/components/motion/Reveal"
import { Section, SectionHeader } from "@/components/layout/Section"
import { Inspector } from "@/components/product/Inspector"
import { evidence } from "@/content/copy"

export function Evidence() {
  return (
    <Section id="evidence" tone="default" size="md">
      <SectionHeader index="04" eyebrow={evidence.eyebrow} headline={evidence.headline} align="left" />

      <div className="mt-12 grid grid-cols-1 items-center gap-10 md:grid-cols-2">
        <Reveal delay={0.1}>
          <div>
            <p className="max-w-lg text-lg text-muted-foreground">{evidence.subhead}</p>

            {/* The two stroke samples belong together as a map legend, so they get
                one bordered block rather than two loose rows. */}
            <div className="mt-8 rounded-xl border border-border bg-panel p-4">
              <div className="font-mono text-[11px] tracking-widest text-muted-foreground uppercase">
                Edge key
              </div>

              <div className="mt-3 flex flex-col divide-y divide-border border-t border-border">
                <div className="flex items-center gap-3 py-3">
                  <svg
                    width="28"
                    height="2"
                    viewBox="0 0 28 2"
                    aria-hidden="true"
                    className="shrink-0"
                  >
                    <line x1="0" y1="1" x2="28" y2="1" stroke="var(--cyan-accent)" strokeWidth="2" />
                  </svg>
                  <span className="font-mono text-xs tracking-wide text-cyan-accent uppercase">
                    Exact — deterministic mechanism, named extractor
                  </span>
                </div>

                <div className="flex items-center gap-3 py-3">
                  <svg
                    width="28"
                    height="2"
                    viewBox="0 0 28 2"
                    aria-hidden="true"
                    className="shrink-0"
                  >
                    <line
                      x1="0"
                      y1="1"
                      x2="28"
                      y2="1"
                      stroke="var(--amber-accent)"
                      strokeWidth="2"
                      strokeDasharray="4 3"
                    />
                  </svg>
                  <span className="font-mono text-xs tracking-wide text-amber-accent uppercase">
                    Inferred — deterministic hypothesis, hidden by default
                  </span>
                </div>
              </div>
            </div>
          </div>
        </Reveal>

        <Reveal delay={0.15}>
          <Inspector fields={evidence.inspectorFields} />
        </Reveal>
      </div>
    </Section>
  )
}
