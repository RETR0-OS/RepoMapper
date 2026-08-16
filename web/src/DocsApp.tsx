import type { ReactNode } from "react"
import { ShieldCheck } from "lucide-react"
import { TooltipProvider } from "@/components/ui/tooltip"
import { Badge } from "@/components/ui/badge"
import { CodeBlock } from "@/components/ui/code-block"
import {
  Accordion,
  AccordionItem,
  AccordionTrigger,
  AccordionContent,
} from "@/components/ui/accordion"
import { Nav } from "@/sections/Nav"
import { Footer } from "@/sections/Footer"
import { views } from "@/content/views"
import { agentCommands, mcpScopes, mcpTools } from "@/content/tools"
import { faq } from "@/content/faq"
import { contrastView, docsIntro, gettingStarted, security, statusLabels } from "@/content/docs"

const tocSections = [
  { id: "getting-started", label: "Getting started" },
  { id: "views", label: "The seven views" },
  { id: "agents", label: "Connecting agents" },
  { id: "security", label: "Security & privacy" },
  { id: "status", label: "Status labels" },
  { id: "faq", label: "FAQ" },
]

function DocSection({
  id,
  title,
  children,
}: {
  id: string
  title: string
  children: ReactNode
}) {
  return (
    <section id={id} className="scroll-mt-28 border-t border-border py-12 first:border-t-0 first:pt-0">
      <h2 className="text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
        {title}
      </h2>
      <div className="mt-6">{children}</div>
    </section>
  )
}

export function DocsApp() {
  return (
    <TooltipProvider delayDuration={150}>
      <div className="grain-overlay" aria-hidden />
      <a
        href="#doc-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-[100] focus:rounded-md focus:border focus:border-lime focus:bg-panel focus:px-3 focus:py-2 focus:text-sm focus:text-foreground"
      >
        Skip to content
      </a>
      <Nav />

      <main className="mx-auto max-w-6xl px-6 pt-32 pb-24 md:pt-40">
        <span className="inline-block rounded-full border border-border bg-panel px-3 py-1 font-mono text-[11px] tracking-widest text-lime uppercase">
          {docsIntro.eyebrow}
        </span>
        <h1 className="mt-5 max-w-3xl text-[clamp(2.25rem,4.5vw,3.25rem)] leading-[1.05] font-semibold tracking-[-0.035em] text-foreground">
          {docsIntro.headline}
        </h1>
        <p className="mt-4 max-w-2xl text-lg text-muted-foreground">{docsIntro.subhead}</p>

        <div className="mt-16 grid grid-cols-1 gap-12 lg:grid-cols-[200px_1fr]">
          <nav aria-label="On this page" className="hidden lg:block">
            <div className="sticky top-28">
              <span className="font-mono text-[10px] tracking-widest text-muted-foreground uppercase">
                On this page
              </span>
              <ul className="mt-3 flex flex-col gap-2.5 border-l border-border pl-4">
                {tocSections.map((item) => (
                  <li key={item.id}>
                    <a
                      href={`#${item.id}`}
                      className="text-sm text-muted-foreground transition-colors hover:text-lime"
                    >
                      {item.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          </nav>

          <div id="doc-content">
            <DocSection id="getting-started" title={gettingStarted.headline}>
              <ol className="space-y-6">
                {gettingStarted.steps.map((step, i) => (
                  <li key={step.title} className="flex gap-4">
                    <span className="mt-0.5 shrink-0 font-mono text-xs text-lime">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <div>
                      <h3 className="font-medium text-foreground">{step.title}</h3>
                      <p className="mt-1 text-sm text-muted-foreground">{step.description}</p>
                    </div>
                  </li>
                ))}
              </ol>
            </DocSection>

            <DocSection id="views" title="The seven views">
              <div className="space-y-5">
                {views.map((view) => (
                  <div key={view.id} className="rounded-xl border border-border bg-panel p-5">
                    <div className="flex items-baseline justify-between gap-3">
                      <h3 className="font-medium text-foreground">{view.name}</h3>
                      <span className="font-mono text-[10px] tracking-widest text-lime uppercase">
                        {view.verb}
                      </span>
                    </div>
                    <p className="mt-1.5 text-sm text-muted-foreground">{view.description}</p>
                    <p className="mt-2 font-mono text-xs text-muted-foreground">
                      Primary action: <span className="text-foreground/80">{view.primaryAction}</span>
                    </p>
                  </div>
                ))}

                <div className="rounded-xl border border-border bg-panel p-5">
                  <div className="flex items-baseline justify-between gap-3">
                    <h3 className="font-medium text-foreground">{contrastView.name}</h3>
                    <span className="font-mono text-[10px] tracking-widest text-lime uppercase">
                      {contrastView.verb}
                    </span>
                  </div>
                  <p className="mt-1.5 text-sm text-muted-foreground">{contrastView.description}</p>
                  <p className="mt-2 text-sm text-muted-foreground">{contrastView.measured}</p>
                  <ul className="mt-3 space-y-1.5">
                    {contrastView.caveats.map((caveat) => (
                      <li key={caveat} className="font-mono text-xs leading-relaxed text-muted-foreground">
                        {caveat}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </DocSection>

            <DocSection id="agents" title="Connecting agents">
              <p className="max-w-2xl text-muted-foreground">
                Argus exposes one Streamable HTTP MCP endpoint inside the managed
                service — not a second process, and available only while VS Code is running.
                Codex and Claude Code connect to the same bounded, evidenced context you see in
                the panel.
              </p>

              <div className="mt-6 max-w-2xl">
                <CodeBlock
                  language="bash"
                  filename="mcp"
                  tabs={[
                    { name: "Codex", code: agentCommands.codex, language: "bash" },
                    { name: "Claude Code", code: agentCommands.claude, language: "bash" },
                  ]}
                />
              </div>

              <div className="mt-6 flex items-center gap-2 font-mono text-xs text-muted-foreground">
                <ShieldCheck className="size-4 shrink-0 text-lime" />
                <span>OAuth 2.1 · PKCE S256 · read-only scopes by default</span>
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                {mcpScopes.map((s) => (
                  <Badge
                    key={s.scope}
                    variant="outline"
                    title={s.description}
                    className="h-auto rounded-full border-border bg-panel px-3 py-1 font-mono text-[11px] text-muted-foreground"
                  >
                    {s.scope}
                  </Badge>
                ))}
              </div>

              <p className="mt-6 mb-2 font-mono text-[10px] tracking-widest text-muted-foreground uppercase">
                MCP tools
              </p>
              <div className="flex flex-wrap gap-2">
                {mcpTools.map((tool) => (
                  <span
                    key={tool.name}
                    title={tool.description}
                    className="rounded-full border border-border bg-panel px-2.5 py-1 font-mono text-xs text-muted-foreground"
                  >
                    {tool.name}
                  </span>
                ))}
              </div>
            </DocSection>

            <DocSection id="security" title={security.headline}>
              <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
                {security.points.map((point) => (
                  <div key={point.title} className="rounded-xl border border-border bg-panel p-5">
                    <h3 className="font-medium text-foreground">{point.title}</h3>
                    <p className="mt-1.5 text-sm text-muted-foreground">{point.description}</p>
                  </div>
                ))}
              </div>
            </DocSection>

            <DocSection id="status" title="Status labels">
              <p className="max-w-2xl text-muted-foreground">
                The panel shows a ready state only when the local service, the returned view,
                and HydraDB all agree on the same verified revision. Every other state is named
                plainly instead of implied.
              </p>
              <div className="mt-6 overflow-hidden rounded-xl border border-border bg-panel">
                {statusLabels.map((item, i) => (
                  <div
                    key={item.label}
                    className={`flex flex-col gap-1 px-5 py-4 sm:flex-row sm:items-baseline sm:gap-6 ${
                      i > 0 ? "border-t border-border" : ""
                    }`}
                  >
                    <span className="w-64 shrink-0 font-mono text-xs text-lime">{item.label}</span>
                    <span className="text-sm text-muted-foreground">{item.meaning}</span>
                  </div>
                ))}
              </div>
            </DocSection>

            <DocSection id="faq" title="FAQ">
              <Accordion type="single" collapsible>
                {faq.map((item) => (
                  <AccordionItem key={item.question} value={item.question}>
                    <AccordionTrigger className="text-base text-foreground">
                      {item.question}
                    </AccordionTrigger>
                    <AccordionContent className="text-muted-foreground">
                      {item.answer}
                    </AccordionContent>
                  </AccordionItem>
                ))}
              </Accordion>
            </DocSection>
          </div>
        </div>
      </main>

      <Footer />
    </TooltipProvider>
  )
}

export default DocsApp
