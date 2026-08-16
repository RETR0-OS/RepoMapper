import { motion } from "motion/react"
import { cn } from "@/lib/utils"

interface InspectorField {
  label: string
  value: string
}

export function Inspector({
  fields,
  className,
}: {
  fields: InspectorField[]
  className?: string
}) {
  return (
    <div className={cn("rounded-xl border border-border bg-raised p-4", className)}>
      <div className="mb-3 font-mono text-[10px] tracking-widest text-muted-foreground uppercase">
        Evidence inspector
      </div>
      <dl className="space-y-2.5">
        {fields.map((field, i) => (
          <motion.div
            key={field.label}
            className="flex flex-col gap-0.5 border-b border-border/60 pb-2 last:border-0 last:pb-0"
            initial={{ opacity: 0, x: -6 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.35, delay: i * 0.08, ease: [0.16, 1, 0.3, 1] }}
          >
            <dt className="font-mono text-[10px] tracking-wide text-muted-foreground uppercase">
              {field.label}
            </dt>
            <dd className="truncate font-mono text-xs text-foreground">{field.value}</dd>
          </motion.div>
        ))}
      </dl>
    </div>
  )
}
