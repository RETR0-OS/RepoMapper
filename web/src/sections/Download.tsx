import { Download as DownloadIcon } from "lucide-react"
import { Reveal } from "@/components/motion/Reveal"
import { Button } from "@/components/ui/button"
import { CodeBlock } from "@/components/ui/code-block"
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table"
import { download } from "@/content/copy"
import { releaseTargets, downloadUrl, type ReleaseTarget } from "@/content/targets"

function detectPlatformKey(): ReleaseTarget["platformKey"] {
  if (typeof navigator === "undefined") return "windows"
  const ua = navigator.userAgent
  if (/Mac/i.test(ua)) return "mac"
  if (/Linux/i.test(ua) && !/Android/i.test(ua)) return "linux"
  return "windows"
}

function detectPrimaryTarget(): ReleaseTarget {
  const platformKey = detectPlatformKey()
  const isArm = typeof navigator !== "undefined" && /arm64|aarch64/i.test(navigator.userAgent)
  const candidates = releaseTargets.filter((t) => t.platformKey === platformKey)
  const archMatch = candidates.find((t) => /arm64/i.test(t.arch) === isArm)
  return archMatch ?? candidates[0] ?? releaseTargets[0]
}

export function Download() {
  const primaryTarget = detectPrimaryTarget()

  return (
    <section id="download" className="py-24 md:py-32">
      <div className="mx-auto max-w-6xl px-6">
        <Reveal>
          <span className="inline-block rounded-full border border-border bg-panel px-3 py-1 font-mono text-[11px] tracking-widest text-lime uppercase">
            {download.eyebrow}
          </span>
        </Reveal>

        <Reveal delay={0.1}>
          <h2 className="mt-5 text-[clamp(2rem,4vw,2.75rem)] leading-[1.05] font-semibold tracking-[-0.035em] text-foreground">
            {download.headline}
          </h2>
        </Reveal>

        <Reveal delay={0.15}>
          <p className="mt-5 max-w-2xl text-lg text-muted-foreground">{download.subhead}</p>
        </Reveal>

        <Reveal delay={0.2}>
          <div className="mt-8">
            <Button asChild size="lg" className="h-11 px-5">
              <a href={downloadUrl(primaryTarget.artifact)}>
                <DownloadIcon className="size-4" />
                Download for {primaryTarget.os} ({primaryTarget.arch})
              </a>
            </Button>
          </div>
        </Reveal>

        <Reveal delay={0.25}>
          <div className="mt-10 overflow-hidden rounded-xl border border-border bg-panel">
            <Table>
              <TableHeader>
                <TableRow className="border-border hover:bg-transparent">
                  <TableHead className="text-muted-foreground">OS</TableHead>
                  <TableHead className="text-muted-foreground">Architecture</TableHead>
                  <TableHead className="text-right text-muted-foreground">Download</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {releaseTargets.map((target) => (
                  <TableRow key={target.vscodeTarget} className="border-border">
                    <TableCell className="text-foreground">{target.os}</TableCell>
                    <TableCell className="text-muted-foreground">{target.arch}</TableCell>
                    <TableCell className="text-right">
                      <Button asChild variant="outline" size="sm">
                        <a href={downloadUrl(target.artifact)}>
                          <DownloadIcon className="size-3.5" />
                          {target.artifact}
                        </a>
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </Reveal>

        <Reveal delay={0.3}>
          <div className="mt-10 max-w-2xl">
            <p className="mb-3 text-sm text-muted-foreground">
              After it downloads, install the package from VS Code&rsquo;s command line:
            </p>
            <CodeBlock
              language="bash"
              filename="terminal"
              code={`code --install-extension ${primaryTarget.artifact}`}
            />
          </div>
        </Reveal>
      </div>
    </section>
  )
}
