import { useState } from "react"
import { Waypoints } from "lucide-react"
import {
  Navbar,
  NavBody,
  NavItems,
  MobileNav,
  MobileNavHeader,
  MobileNavMenu,
  MobileNavToggle,
} from "@/components/ui/resizable-navbar"
import { Button } from "@/components/ui/button"
import { nav } from "@/content/copy"

function Logo() {
  return (
    <a href="/" className="relative z-20 flex items-center gap-2 px-2 py-1">
      <span className="flex h-7 w-7 items-center justify-center rounded-md border border-lime/40 bg-lime-soft text-lime">
        <Waypoints className="h-4 w-4" strokeWidth={2} />
      </span>
      <span className="font-mono text-sm font-medium text-foreground">{nav.logo}</span>
    </a>
  )
}

export function Nav() {
  const [isOpen, setIsOpen] = useState(false)

  return (
    <Navbar className="top-0">
      <NavBody>
        <Logo />
        <NavItems items={nav.links} />
        <div className="relative z-20 flex items-center gap-2">
          <Button asChild variant="ghost" size="sm">
            <a href="/docs.html">Docs</a>
          </Button>
          <Button asChild size="sm">
            <a href="/#download">Download</a>
          </Button>
        </div>
      </NavBody>

      <MobileNav>
        <MobileNavHeader>
          <Logo />
          <MobileNavToggle isOpen={isOpen} onClick={() => setIsOpen((v) => !v)} />
        </MobileNavHeader>
        <MobileNavMenu isOpen={isOpen} onClose={() => setIsOpen(false)}>
          {nav.links.map((item) => (
            <a
              key={item.link}
              href={item.link}
              onClick={() => setIsOpen(false)}
              className="w-full py-1 text-sm text-foreground/80 hover:text-foreground"
            >
              {item.name}
            </a>
          ))}
          <a
            href="/docs.html"
            onClick={() => setIsOpen(false)}
            className="w-full py-1 text-sm text-foreground/80 hover:text-foreground"
          >
            Docs
          </a>
          <Button asChild className="w-full">
            <a href="/#download" onClick={() => setIsOpen(false)}>
              Download
            </a>
          </Button>
        </MobileNavMenu>
      </MobileNav>
    </Navbar>
  )
}
