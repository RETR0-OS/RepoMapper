import { FlaskConical, ShieldCheck } from "lucide-react"
import { Stagger, StaggerItem } from "@/components/motion/Reveal"
import { Section, SectionHeader } from "@/components/layout/Section"
import { honestEvidence } from "@/content/copy"

const icons = [FlaskConical, ShieldCheck]
const iconClasses = ["text-lime", "text-cyan-accent"]

export function HonestEvidence() {
  return (
    <Section id="honest-evidence" tone="band" size="sm">
      <SectionHeader
        index="07"
        eyebrow={honestEvidence.eyebrow}
        headline={honestEvidence.headline}
        align="left"
      />

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
    </Section>
  )
}
