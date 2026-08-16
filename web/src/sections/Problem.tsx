import { AlertCircle } from "lucide-react"
import { Reveal, Stagger, StaggerItem } from "@/components/motion/Reveal"
import { problem } from "@/content/copy"

export function Problem() {
  return (
    <section id="problem" className="py-24 md:py-32">
      <div className="mx-auto max-w-6xl px-6">
        <Reveal>
          <span className="inline-block rounded-full border border-border bg-panel px-3 py-1 font-mono text-[11px] tracking-widest text-lime uppercase">
            {problem.eyebrow}
          </span>
        </Reveal>

        <Reveal delay={0.05}>
          <h2 className="mt-5 max-w-3xl text-3xl font-semibold tracking-tight text-foreground md:text-5xl">
            {problem.headline}
          </h2>
        </Reveal>

        <Reveal delay={0.1}>
          <p className="mt-6 max-w-2xl text-lg text-muted-foreground">{problem.subhead}</p>
        </Reveal>

        <Stagger as="ul" className="mt-8 flex max-w-2xl flex-col gap-3">
          {problem.losses.map((loss) => (
            <StaggerItem key={loss} as="li" className="flex items-start gap-3">
              <AlertCircle className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
              <span className="font-mono text-sm text-foreground">{loss}</span>
            </StaggerItem>
          ))}
        </Stagger>

        <Reveal delay={0.1}>
          <p className="mt-10 max-w-2xl text-base text-muted-foreground italic">
            {problem.closing}
          </p>
        </Reveal>
      </div>
    </section>
  )
}
