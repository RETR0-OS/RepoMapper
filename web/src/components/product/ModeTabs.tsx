import { cn } from "@/lib/utils"
import { views, type ViewId } from "@/content/views"

interface ModeTabsProps {
  active: ViewId
  onChange?: (id: ViewId) => void
  className?: string
}

export function ModeTabs({ active, onChange, className }: ModeTabsProps) {
  return (
    <div
      role={onChange ? "tablist" : undefined}
      className={cn("flex items-center gap-1 overflow-x-auto", className)}
    >
      {views.map((view) => {
        const isActive = view.id === active
        return (
          <button
            key={view.id}
            type="button"
            role={onChange ? "tab" : undefined}
            aria-selected={onChange ? isActive : undefined}
            onClick={onChange ? () => onChange(view.id) : undefined}
            className={cn(
              "shrink-0 rounded-md px-2.5 py-1.5 font-mono text-[11px] tracking-wide transition-colors",
              onChange ? "cursor-pointer" : "cursor-default",
              isActive
                ? "bg-raised text-lime"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {view.name}
          </button>
        )
      })}
    </div>
  )
}
