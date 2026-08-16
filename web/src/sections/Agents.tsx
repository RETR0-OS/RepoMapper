import { ShieldCheck } from "lucide-react"
import { Reveal, Stagger, StaggerItem } from "@/components/motion/Reveal"
import { Badge } from "@/components/ui/badge"
import { CodeBlock } from "@/components/ui/code-block"
import { agents } from "@/content/copy"
import { agentCommands, mcpScopes, mcpTools } from "@/content/tools"

export function Agents() {
  return (
    <section id="agents" className="py-24 md:py-32">
      <div className="mx-auto max-w-6xl px-6">
        <Reveal>
          <span className="inline-block rounded-full border border-border bg-panel px-3 py-1 font-mono text-[11px] tracking-widest text-lime uppercase">
            {agents.eyebrow}
          </span>
        </Reveal>

        <Reveal delay={0.05}>
          <h2 className="mt-5 max-w-3xl text-3xl font-semibold tracking-tight text-foreground md:text-5xl">
            {agents.headline}
          </h2>
        </Reveal>

        <Reveal delay={0.1}>
          <p className="mt-6 max-w-2xl text-lg text-muted-foreground">{agents.subhead}</p>
        </Reveal>

        <Reveal delay={0.15}>
          <div className="mt-12 max-w-2xl">
            <CodeBlock
              language="bash"
              filename="mcp"
              tabs={[
                { name: "Codex", code: agentCommands.codex, language: "bash" },
                { name: "Claude Code", code: agentCommands.claude, language: "bash" },
              ]}
            />
          </div>
        </Reveal>

        <Reveal delay={0.2}>
          <div className="mt-10 flex items-center gap-2 font-mono text-xs text-muted-foreground">
            <ShieldCheck className="size-4 shrink-0 text-lime" />
            <span>OAuth 2.1 · PKCE S256 · read-only scopes by default</span>
          </div>
        </Reveal>

        <div className="mt-6 flex flex-wrap gap-2">
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

        <Stagger className="mt-8 flex flex-wrap gap-2" staggerChildren={0.04}>
          {mcpTools.map((tool) => (
            <StaggerItem key={tool.name}>
              <span
                title={tool.description}
                className="rounded-full border border-border bg-panel px-2.5 py-1 font-mono text-xs text-muted-foreground"
              >
                {tool.name}
              </span>
            </StaggerItem>
          ))}
        </Stagger>
      </div>
    </section>
  )
}
