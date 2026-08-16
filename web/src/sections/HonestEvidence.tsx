import { FlaskConical, ShieldCheck } from "lucide-react"
import { Reveal, Stagger, StaggerItem } from "@/components/motion/Reveal"
import { honestEvidence } from "@/content/copy"

const icons = [FlaskConical, ShieldCheck]
const iconClasses = ["text-lime", "text-cyan-accent"]

export function HonestEvidence() {
  return (
    <section id="honest-evidence" className="py-24 md:py-32">
      <div className="mx-auto max-w-6xl px-6">
        <Reveal>
          <span className="inline-block rounded-full border border-border bg-panel px-3 py-1 font-mono text-[11px] tracking-widest text-lime uppercase">
            {honestEvidence.eyebrow}
          </span>
        </Reveal>

        <Reveal delay={0.1}>
          <h2 className="mt-5 max-w-2xl text-[clamp(2rem,4vw,2.75rem)] leading-[1.05] font-semibold tracking-[-0.035em] text-foreground">
            {honestEvidence.headline}
          </h2>
        </Reveal>

        <Stagger className="mt-12 grid grid-cols-1 gap-5 md:grid-cols-2">
          {honestEvidence.cards.map((card, i) => {
            const Icon = icons[i]
            return (
              <StaggerItem key={card.title}>
                <div className="h-full rounded-xl border border-border bg-panel p-6">
                  <div className="flex items-center gap-2.5">
                    <Icon className={`size-5 ${iconClasses[i]}`} strokeWidth={2} />
                    <h3 className="font-medium text-foreground">{card.title}</h3>
                  </div>
                  <p className="mt-3 text-sm text-muted-foreground">{card.description}</p>
                </div>
              </StaggerItem>
            )
          })}
        </Stagger>
      </div>
    </section>
  )
}
