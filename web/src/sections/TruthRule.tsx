import { Fragment } from "react"
import { ArrowRight } from "lucide-react"
import { Reveal, Stagger, StaggerItem } from "@/components/motion/Reveal"
import { truthRule } from "@/content/copy"

export function TruthRule() {
  return (
    <section id="truth-rule" className="py-24 md:py-32">
      <div className="mx-auto max-w-6xl px-6">
        <Reveal>
          <span className="inline-block rounded-full border border-border bg-panel px-3 py-1 font-mono text-[11px] tracking-widest text-lime uppercase">
            {truthRule.eyebrow}
          </span>
        </Reveal>

        <Reveal delay={0.05}>
          <h2 className="mt-5 max-w-3xl text-3xl font-semibold tracking-tight text-foreground md:text-5xl">
            {truthRule.headline}
          </h2>
        </Reveal>

        <Reveal delay={0.1}>
          <p className="mt-6 max-w-2xl text-lg text-muted-foreground">{truthRule.subhead}</p>
        </Reveal>

        <Stagger className="mt-12 grid grid-cols-1 gap-6 md:grid-cols-[1fr_auto_1fr_auto_1fr] md:items-center">
          {truthRule.layers.map((layer, index) => (
            <Fragment key={layer.name}>
              <StaggerItem className="h-full rounded-xl border border-border bg-panel p-5">
                <div className="font-mono text-xs tracking-widest text-lime uppercase">
                  {layer.name}
                </div>
                <p className="mt-3 text-sm text-muted-foreground">{layer.description}</p>
              </StaggerItem>

              {index < truthRule.layers.length - 1 && (
                <StaggerItem className="hidden justify-self-center md:flex md:items-center">
                  <ArrowRight className="size-5 shrink-0 text-muted-foreground" />
                </StaggerItem>
              )}
            </Fragment>
          ))}
        </Stagger>

      </div>
    </section>
  )
}
