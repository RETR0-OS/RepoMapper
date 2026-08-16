import { StickyScroll } from "@/components/ui/sticky-scroll-reveal"
import { GraphMock } from "@/components/product/GraphMock"
import { Reveal } from "@/components/motion/Reveal"
import { views } from "@/content/views"

export function ModeScroll() {
  const content = views.map((view) => ({
    title: `${String(view.index + 1).padStart(2, "0")} · ${view.name}`,
    description: view.description,
    content: (
      <div className="flex h-full w-full items-center justify-center p-3">
        <GraphMock mode={view.id} showChrome={false} className="w-full" />
      </div>
    ),
  }))

  return (
    <section id="signature" className="mx-auto max-w-6xl px-6 py-24 md:py-32">
      <Reveal className="mx-auto mb-12 max-w-2xl text-center">
        <span className="inline-block rounded-full border border-border bg-panel px-3 py-1 font-mono text-[11px] tracking-widest text-lime uppercase">
          One graph, six ways to read it
        </span>
        <h2 className="mt-5 text-3xl font-semibold tracking-tight text-foreground md:text-5xl">
          Scroll through the same repository, six different questions.
        </h2>
        <p className="mt-4 text-muted-foreground">
          Every mode below is reading the same HydraDB-backed graph of one small
          authorization flow — orient, inspect, ask, watch, review, and save, without
          leaving the panel.
        </p>
      </Reveal>

      <StickyScroll content={content} contentClassName="h-[27rem] w-[32rem]" />
    </section>
  )
}
