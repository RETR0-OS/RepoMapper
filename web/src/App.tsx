import { lazy, Suspense } from "react"
import { TooltipProvider } from "@/components/ui/tooltip"
import { Nav } from "@/sections/Nav"
import { Hero } from "@/sections/Hero"
import { Problem } from "@/sections/Problem"
import { TruthRule } from "@/sections/TruthRule"
import { ViewsBento } from "@/sections/ViewsBento"
import { Evidence } from "@/sections/Evidence"
import { HowToUse } from "@/sections/HowToUse"
import { HonestEvidence } from "@/sections/HonestEvidence"
import { Faq } from "@/sections/Faq"
import { ClosingCta } from "@/sections/ClosingCta"
import { Footer } from "@/sections/Footer"

// Both pull in react-syntax-highlighter (CodeBlock/Terminal), which is the
// single largest dependency in the bundle — keep it out of the initial chunk.
const Agents = lazy(() => import("@/sections/Agents").then((m) => ({ default: m.Agents })))
const Download = lazy(() => import("@/sections/Download").then((m) => ({ default: m.Download })))

function SectionFallback() {
  return <div className="h-[32rem]" aria-hidden />
}

export function App() {
  return (
    <TooltipProvider delayDuration={150}>
      <div className="grain-overlay" aria-hidden />
      <a
        href="#top"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-[100] focus:rounded-md focus:border focus:border-lime focus:bg-panel focus:px-3 focus:py-2 focus:text-sm focus:text-foreground"
      >
        Skip to content
      </a>
      <Nav />
      {/* Order matters twice over. The product (ViewsBento) sits directly after
          the problem, so a reader meets the tool before the trust argument.
          And the sections alternate default/band surfaces all the way down —
          see Section's `tone` prop — so no two neighbours look alike. */}
      <main>
        <Hero />
        <Problem />
        <ViewsBento />
        <TruthRule />
        <Evidence />
        <Suspense fallback={<SectionFallback />}>
          <Agents />
        </Suspense>
        <HowToUse />
        <HonestEvidence />
        <Suspense fallback={<SectionFallback />}>
          <Download />
        </Suspense>
        <Faq />
        <ClosingCta />
      </main>
      <Footer />
    </TooltipProvider>
  )
}

export default App
