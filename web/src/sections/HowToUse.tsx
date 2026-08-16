import { Reveal, Stagger, StaggerItem } from "@/components/motion/Reveal"
import { howToUse } from "@/content/copy"

export function HowToUse() {
  return (
    <section id="how-to-use" className="py-24 md:py-32">
      <div className="mx-auto max-w-6xl px-6">
        <Reveal>
          <span className="inline-block rounded-full border border-border bg-panel px-3 py-1 font-mono text-[11px] tracking-widest text-lime uppercase">
            {howToUse.eyebrow}
          </span>
        </Reveal>

        <Reveal delay={0.05}>
          <h2 className="mt-5 max-w-3xl text-3xl font-semibold tracking-tight text-foreground md:text-5xl">
            {howToUse.headline}
          </h2>
        </Reveal>

        <Stagger className="relative mt-16 grid grid-cols-1 gap-10 md:grid-cols-4 md:gap-8">
          <div className="pointer-events-none absolute inset-x-0 top-[0.4rem] hidden border-t border-border md:block" />

          {howToUse.steps.map((step, index) => (
            <StaggerItem key={step.title} className="relative">
              <div className="font-mono text-sm text-lime">
                {String(index + 1).padStart(2, "0")}
              </div>
              <h3 className="mt-4 text-lg font-semibold text-foreground">{step.title}</h3>
              <p className="mt-2 text-sm text-muted-foreground">{step.description}</p>
            </StaggerItem>
          ))}
        </Stagger>
      </div>
    </section>
  )
}
