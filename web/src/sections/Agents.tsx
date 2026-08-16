import { ShieldCheck } from "lucide-react"
import { Reveal, Stagger, StaggerItem } from "@/components/motion/Reveal"
import { Section, SectionHeader } from "@/components/layout/Section"
import { Badge } from "@/components/ui/badge"
import { CodeBlock } from "@/components/ui/code-block"
import { agents } from "@/content/copy"
import { agentCommands, mcpScopes, mcpTools } from "@/content/tools"

export function Agents() {
  return (
    <Section id="agents" tone="band" size="md">
      <SectionHeader
        index="05"
        eyebrow={agents.eyebrow}
        headline={agents.headline}
        sub={agents.subhead}
        align="center"
      />

      <Reveal delay={0.15}>
        <div className="mx-auto mt-12 max-w-2xl">
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
        <div className="mt-10 flex items-center justify-center gap-2 font-mono text-xs text-muted-foreground">
          <ShieldCheck className="size-4 shrink-0 text-lime" />
          <span>OAuth 2.1 · PKCE S256 · read-only scopes by default</span>
        </div>
      </Reveal>

      <div className="mt-6 flex flex-wrap justify-center gap-2">
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

      <Stagger className="mt-8 flex flex-wrap justify-center gap-2" staggerChildren={0.04}>
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
    </Section>
  )
}
