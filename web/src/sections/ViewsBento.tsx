import { Compass, Search, MessageCircleQuestion, GitCompare, BookmarkCheck, type LucideIcon } from "lucide-react"
import { Reveal, Stagger, StaggerItem } from "@/components/motion/Reveal"
import { BentoGrid, BentoGridItem } from "@/components/ui/bento-grid"
import { GlowingEffect } from "@/components/ui/glowing-effect"
import { GraphMock } from "@/components/product/GraphMock"
import { views, type ViewId } from "@/content/views"

const verbIcons: Partial<Record<ViewId, LucideIcon>> = {
  repository: Compass,
  explore: Search,
  trace: MessageCircleQuestion,
  compare: GitCompare,
  preserve: BookmarkCheck,
}

export function ViewsBento() {
  return (
    <section id="views" className="py-24 md:py-32">
      <div className="mx-auto max-w-6xl px-6">
        <Reveal>
          <span className="inline-block rounded-full border border-border bg-panel px-3 py-1 font-mono text-[11px] tracking-widest text-lime uppercase">
            Repository &rarr; Explore &rarr; Trace &rarr; Observe &rarr; Compare &rarr; Preserve
          </span>
        </Reveal>

        <Reveal delay={0.05}>
          <h2 className="mt-5 max-w-3xl text-3xl font-semibold tracking-tight text-foreground md:text-5xl">
            Six bounded views, one graph.
          </h2>
        </Reveal>

        <Reveal delay={0.1}>
          <p className="mt-6 max-w-2xl text-lg text-muted-foreground">
            Every view renders the same source of truth. Nothing you see was invented for the
            occasion.
          </p>
        </Reveal>

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
          </BentoGrid>
        </Stagger>
      </div>
    </section>
  )
}
