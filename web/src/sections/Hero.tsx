import { useRef } from "react"
import { motion, useReducedMotion, useScroll, useTransform } from "motion/react"
import { ArrowRight, Download } from "lucide-react"
import { Button } from "@/components/ui/button"
import { BorderBeam } from "@/components/ui/border-beam"
import { DottedGlowBackground } from "@/components/ui/dotted-glow-background"
import { GraphMock } from "@/components/product/GraphMock"
import { EASE_OUT_EXPO } from "@/components/motion/Reveal"
import { withBase } from "@/lib/utils"
import { hero } from "@/content/copy"

export function Hero() {
  const sectionRef = useRef<HTMLElement>(null)
  const prefersReduced = useReducedMotion()

  const { scrollYProgress } = useScroll({
    target: sectionRef,
    offset: ["start start", "end start"],
  })

  // Hooks stay unconditional; the reduced-motion branch simply never reads these.
  const rotateX = useTransform(scrollYProgress, [0, 0.35], ["12deg", "0deg"])
  const scale = useTransform(scrollYProgress, [0, 0.35], [0.94, 1])

  return (
    <section
      id="top"
      ref={sectionRef}
      className="relative overflow-hidden pt-32 pb-24 md:pt-44 md:pb-32"
    >
      <div className="pointer-events-none absolute inset-0 -z-10">
        <DottedGlowBackground
          gap={16}
          radius={1.1}
          color="rgba(237,237,239,0.35)"
          glowColor="rgba(195,245,60,0.9)"
          opacity={0.5}
        />
      </div>

      <div
        aria-hidden
        className="pointer-events-none absolute top-[42%] left-1/2 -z-10 h-[38rem] w-[80rem] max-w-[140vw] -translate-x-1/2 blur-[120px]"
        style={{
          background:
            "radial-gradient(closest-side, color-mix(in srgb, var(--lime) 18%, transparent), transparent)",
        }}
      />

      <div className="mx-auto max-w-6xl px-6 text-center">
        <motion.span
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: EASE_OUT_EXPO }}
          className="inline-block rounded-full border border-border bg-panel px-3 py-1 font-mono text-[11px] tracking-widest text-lime uppercase"
        >
          {hero.eyebrow}
        </motion.span>

        {/* The H1 is the LCP element: it renders at full opacity immediately, no entrance animation. */}
        <h1 className="mt-6 text-[clamp(3rem,8vw,6.25rem)] leading-[0.98] font-semibold tracking-[-0.04em] text-foreground">
          {hero.headline}
        </h1>

        <motion.p
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.15, ease: EASE_OUT_EXPO }}
          className="mx-auto mt-6 max-w-2xl text-lg text-muted-foreground"
        >
          {hero.subhead}
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.3, ease: EASE_OUT_EXPO }}
          className="mt-8 flex flex-wrap items-center justify-center gap-3"
        >
          <Button asChild size="lg" className="h-11 px-5">
            <a href="#download">
              <Download className="size-4" />
              {hero.primaryCta}
            </a>
          </Button>
          <Button asChild size="lg" variant="outline" className="h-11 px-5">
            <a href={withBase("/docs.html")}>
              {hero.secondaryCta}
              <ArrowRight className="size-4" />
            </a>
          </Button>
        </motion.div>
      </div>

      {/* Margin stays tight on purpose: the top of the mock has to clear the fold at 1440x900. */}
      <div className="perspective-hero mt-14 px-6 md:mt-16">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.2, ease: EASE_OUT_EXPO }}
          style={prefersReduced ? undefined : { rotateX, scale, transformOrigin: "50% 0%" }}
          className="hero-mask relative mx-auto max-w-5xl rounded-xl"
        >
          <GraphMock mode="trace" className="w-full" />
          <BorderBeam
            size={220}
            duration={14}
            colorFrom="var(--lime)"
            colorTo="var(--cyan-accent)"
          />
        </motion.div>
      </div>
    </section>
  )
}
