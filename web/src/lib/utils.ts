import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// GitHub Pages serves the site from /<repo>/, so a root-absolute href would drop the
// repo segment. Prefix those links with the Vite base ("/" in dev, "/<repo>/" in CI).
const BASE = import.meta.env.BASE_URL.replace(/\/$/, "")

export function withBase(path: string) {
  if (!path.startsWith("/")) return path
  return path === "/" ? `${BASE}/` : `${BASE}${path}`
}
