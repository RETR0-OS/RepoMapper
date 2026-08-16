import { motion } from "motion/react"
import { ArrowRight, Download } from "lucide-react"
import { Button } from "@/components/ui/button"
import { DottedGlowBackground } from "@/components/ui/dotted-glow-background"
import { GraphMock } from "@/components/product/GraphMock"
import { hero } from "@/content/copy"

const EASE_OUT_EXPO = [0.16, 1, 0.3, 1] as const

export function Hero() {
  return (
    <section id="top" className="relative overflow-hidden pt-36 pb-20 md:pt-44 md:pb-28">
      <div className="pointer-events-none absolute inset-0 -z-10">
        <DottedGlowBackground
          gap={16}
          radius={1.1}
          color="rgba(237,237,239,0.35)"
          glowColor="rgba(195,245,60,0.9)"
          opacity={0.5}
        />
      </div>

      <div className="mx-auto grid max-w-6xl grid-cols-1 items-center gap-14 px-6 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
        <div>
          <motion.span
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: EASE_OUT_EXPO }}
            className="inline-block rounded-full border border-border bg-panel px-3 py-1 font-mono text-[11px] tracking-widest text-lime uppercase"
          >
            {hero.eyebrow}
          </motion.span>

          {/* The H1 is the LCP element: it renders at full opacity immediately, no entrance animation. */}
          <h1 className="mt-5 text-[clamp(2.75rem,6vw,4.75rem)] leading-[1.02] font-semibold tracking-[-0.035em] text-foreground">
            {hero.headline}
          </h1>

          <motion.p
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.15, ease: EASE_OUT_EXPO }}
            className="mt-6 max-w-lg text-lg text-muted-foreground"
          >
            {hero.subhead}
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.3, ease: EASE_OUT_EXPO }}
            className="mt-8 flex flex-wrap items-center gap-3"
          >
            <Button asChild size="lg" className="h-11 px-5">
              <a href="#download">
                <Download className="size-4" />
                {hero.primaryCta}
              </a>
            </Button>
            <Button asChild size="lg" variant="outline" className="h-11 px-5">
              <a href="/docs.html">
                {hero.secondaryCta}
                <ArrowRight className="size-4" />
              </a>
            </Button>
          </motion.div>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 16, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.7, delay: 0.2, ease: EASE_OUT_EXPO }}
        >
          <GraphMock mode="trace" className="w-full" />
        </motion.div>
      </div>
    </section>
  )
}
