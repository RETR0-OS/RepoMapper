import { Reveal } from "@/components/motion/Reveal"
import { Inspector } from "@/components/product/Inspector"
import { evidence } from "@/content/copy"

export function Evidence() {
  return (
    <section id="evidence" className="py-24 md:py-32">
      <div className="mx-auto max-w-6xl px-6">
        <Reveal>
          <span className="inline-block rounded-full border border-border bg-panel px-3 py-1 font-mono text-[11px] tracking-widest text-lime uppercase">
            {evidence.eyebrow}
          </span>
        </Reveal>

        <Reveal delay={0.05}>
          <h2 className="mt-5 max-w-3xl text-3xl font-semibold tracking-tight text-foreground md:text-5xl">
            {evidence.headline}
          </h2>
        </Reveal>

        <div className="mt-12 grid grid-cols-1 items-center gap-10 md:grid-cols-2">
          <Reveal delay={0.1}>
            <div>
              <p className="max-w-lg text-lg text-muted-foreground">{evidence.subhead}</p>

              <div className="mt-8 flex flex-col gap-3">
                <div className="flex items-center gap-3">
                  <svg width="28" height="2" viewBox="0 0 28 2" aria-hidden="true">
                    <line x1="0" y1="1" x2="28" y2="1" stroke="var(--cyan-accent)" strokeWidth="2" />
                  </svg>
                  <span className="font-mono text-xs tracking-wide text-cyan-accent uppercase">
                    Exact — deterministic mechanism, named extractor
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  <svg width="28" height="2" viewBox="0 0 28 2" aria-hidden="true">
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
          </Reveal>

          <Reveal delay={0.15}>
            <Inspector fields={evidence.inspectorFields} />
          </Reveal>
        </div>
      </div>
    </section>
  )
}
