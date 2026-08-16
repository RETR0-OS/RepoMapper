import { lazy, Suspense } from "react"
import { TooltipProvider } from "@/components/ui/tooltip"
import { Nav } from "@/sections/Nav"
import { Hero } from "@/sections/Hero"
import { Problem } from "@/sections/Problem"
import { TruthRule } from "@/sections/TruthRule"
import { ModeScroll } from "@/sections/ModeScroll"
import { ViewsBento } from "@/sections/ViewsBento"
import { Evidence } from "@/sections/Evidence"
import { HowToUse } from "@/sections/HowToUse"
import { HonestEvidence } from "@/sections/HonestEvidence"
import { Faq } from "@/sections/Faq"
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
      <main>
        <Hero />
        <Problem />
        <TruthRule />
        <ModeScroll />
        <ViewsBento />
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
      </main>
      <Footer />
    </TooltipProvider>
  )
}

export default App
