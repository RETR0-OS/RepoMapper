import { Waypoints } from "lucide-react"

const productLinks = [
  { name: "Product", link: "/#views" },
  { name: "Evidence", link: "/#evidence" },
  { name: "Agents", link: "/#agents" },
  { name: "Docs", link: "/docs.html" },
  { name: "Download", link: "/#download" },
  { name: "FAQ", link: "/#faq" },
]

export function Footer() {
  return (
    <footer className="border-t border-border py-12">
      <div className="mx-auto grid max-w-6xl grid-cols-1 gap-8 px-6 md:grid-cols-3">
        <div>
          <a href="/" className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-md border border-lime/40 bg-lime-soft text-lime">
              <Waypoints className="h-4 w-4" strokeWidth={2} />
            </span>
            <span className="font-mono text-sm font-medium text-foreground">Argus</span>
          </a>
          <p className="mt-3 max-w-xs text-sm text-muted-foreground">
            HydraDB-backed repository observability for agentic coding.
          </p>
        </div>

        <div>
          <span className="font-mono text-[11px] tracking-widest text-muted-foreground uppercase">
            Links
          </span>
          <ul className="mt-3 flex flex-col gap-2">
            {productLinks.map((item) => (
              <li key={item.link}>
                <a
                  href={item.link}
                  className="text-sm text-foreground/80 transition-colors hover:text-foreground"
                >
                  {item.name}
                </a>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <span className="font-mono text-[11px] tracking-widest text-muted-foreground uppercase">
            Platforms
          </span>
          <p className="mt-3 text-sm text-muted-foreground">
            Built for local VS Code desktop — Windows, macOS, and Linux, x64 and ARM64.
          </p>
          <p className="mt-4 text-xs text-muted-foreground">© Argus</p>
        </div>
      </div>
    </footer>
  )
}
