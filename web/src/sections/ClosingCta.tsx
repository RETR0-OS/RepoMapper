import { ArrowRight, Download } from "lucide-react"
import { Reveal } from "@/components/motion/Reveal"
import { Button } from "@/components/ui/button"
import { withBase } from "@/lib/utils"
import { closingCta } from "@/content/copy"

/**
 * The page used to stop dead on the FAQ. This is the last beat: full-bleed, one
 * soft lime glow, and the same CTA pair the hero opens with — so the reader
 * lands back on the two actions that matter.
 */
export function ClosingCta() {
  return (
    <section className="relative overflow-hidden border-t border-border py-28 md:py-40">
      <div
        aria-hidden
        className="pointer-events-none absolute top-0 left-1/2 h-[32rem] w-[64rem] max-w-[160vw] -translate-x-1/2 -translate-y-1/3 blur-[130px]"
        style={{
          background:
            "radial-gradient(closest-side, color-mix(in srgb, var(--lime) 16%, transparent), transparent)",
        }}
      />

      <div className="mx-auto max-w-3xl px-6 text-center">
        <Reveal>
          <h2 className="text-[clamp(2.25rem,5vw,3.5rem)] leading-[1.05] font-semibold tracking-[-0.035em] text-foreground">
            {closingCta.headline}
          </h2>

          <p className="mx-auto mt-6 max-w-2xl text-lg text-muted-foreground">
            {closingCta.subhead}
          </p>

          <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
            <Button asChild size="lg" className="h-11 px-5">
              <a href="#download">
                <Download className="size-4" />
                {closingCta.primaryCta}
              </a>
            </Button>
            <Button asChild size="lg" variant="outline" className="h-11 px-5">
              <a href={withBase("/docs.html")}>
                {closingCta.secondaryCta}
                <ArrowRight className="size-4" />
              </a>
            </Button>
          </div>
        </Reveal>
      </div>
    </section>
  )
}
