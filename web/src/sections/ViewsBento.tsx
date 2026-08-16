import { Compass, Search, MessageCircleQuestion, GitCompare, BookmarkCheck, Scale, type LucideIcon } from "lucide-react"
import { Stagger, StaggerItem } from "@/components/motion/Reveal"
import { Section, SectionHeader } from "@/components/layout/Section"
import { BentoGrid, BentoGridItem } from "@/components/ui/bento-grid"
import { GlowingEffect } from "@/components/ui/glowing-effect"
import { GraphMock } from "@/components/product/GraphMock"
import { ContrastMock } from "@/components/product/ContrastMock"
import { views, type ViewId } from "@/content/views"
import { contrastView } from "@/content/docs"

const verbIcons: Partial<Record<ViewId, LucideIcon>> = {
  repository: Compass,
  explore: Search,
  trace: MessageCircleQuestion,
  compare: GitCompare,
  preserve: BookmarkCheck,
}

export function ViewsBento() {
  return (
    <Section id="views" tone="default" size="lg">
      <SectionHeader
        index="02"
        eyebrow="Repository → Explore → Trace → Observe → Compare → Preserve → Contrast"
        headline="Seven bounded views, one source of truth."
        sub="Every view renders the same source of truth. Nothing you see was invented for the occasion."
        align="left"
      />

      <Stagger as="div" className="mt-12">
        <BentoGrid className="mx-auto max-w-none md:auto-rows-[13rem] md:grid-cols-3">
          {views.map((view) => {
            const isAnchor = view.id === "observe"
            const VerbIcon = verbIcons[view.id]
            return (
              <StaggerItem
                key={view.id}
                as="div"
                className={isAnchor ? "md:col-span-2 md:row-span-2" : undefined}
              >
                <BentoGridItem
                  className="relative h-full"
                  title={view.name}
                  description={view.purpose}
                  header={
                    isAnchor ? (
                      <>
                        <GlowingEffect
                          disabled={false}
                          spread={32}
                          proximity={64}
                          blur={0}
                        />
                        <GraphMock
                          mode={view.id}
                          showChrome={false}
                          className="pointer-events-none h-52 w-full opacity-90"
                        />
                        <p className="font-mono text-[11px] leading-relaxed text-muted-foreground">
                          {view.description}
                        </p>
                      </>
                    ) : (
                      <div className="flex items-center justify-between">
                        {VerbIcon ? (
                          <span className="flex h-9 w-9 items-center justify-center rounded-md border border-border bg-raised text-muted-foreground transition-colors duration-300 group-hover/bento:border-lime/40 group-hover/bento:text-lime">
                            <VerbIcon className="size-4" strokeWidth={1.75} />
                          </span>
                        ) : (
                          <span />
                        )}
                        <span className="font-mono text-[10px] tracking-widest text-lime uppercase">
                          {view.verb}
                        </span>
                      </div>
                    )
                  }
                />
              </StaggerItem>
            )
          })}

          {/* Five 1x1 tiles plus the 2x2 Observe anchor fill exactly three
              rows. A seventh 1x1 tile would strand two dead cells, so Contrast
              takes the full closing row — which also gives it room for the two
              run columns it shows instead of a graph. */}
          <StaggerItem as="div" className="md:col-span-3">
            <div className="group/bento flex h-full flex-col gap-4 rounded-xl border border-border bg-panel p-4 transition duration-200 hover:border-lime/40 md:flex-row md:items-center md:gap-6">
              <div className="flex flex-col md:w-2/5 md:shrink-0">
                <div className="flex items-center justify-between">
                  <span className="flex h-9 w-9 items-center justify-center rounded-md border border-border bg-raised text-muted-foreground transition-colors duration-300 group-hover/bento:border-lime/40 group-hover/bento:text-lime">
                    <Scale className="size-4" strokeWidth={1.75} />
                  </span>
                  <span className="font-mono text-[10px] tracking-widest text-lime uppercase">
                    {contrastView.verb}
                  </span>
                </div>
                <div className="transition duration-200 group-hover/bento:translate-x-1">
                  <div className="mt-4 mb-2 font-semibold text-foreground">
                    {contrastView.name}
                  </div>
                  <div className="text-xs font-normal text-muted-foreground">
                    {contrastView.purpose}
                  </div>
                </div>
              </div>
              <ContrastMock compact className="w-full min-w-0 md:flex-1" />
            </div>
          </StaggerItem>
        </BentoGrid>
      </Stagger>
    </Section>
  )
}
