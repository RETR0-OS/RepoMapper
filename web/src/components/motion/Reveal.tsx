import type { ReactNode } from "react"
import { motion, type Variants } from "motion/react"

const EASE_OUT_EXPO = [0.16, 1, 0.3, 1] as const

interface RevealProps {
  children: ReactNode
  className?: string
  delay?: number
  y?: number
  as?: "div" | "section" | "li"
}

const variants: Variants = {
  hidden: { opacity: 0, y: 16, filter: "blur(4px)" },
  visible: { opacity: 1, y: 0, filter: "blur(0px)" },
}

export function Reveal({ children, className, delay = 0, y = 16, as = "div" }: RevealProps) {
  const Comp = motion[as]
  return (
    <Comp
      className={className}
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, margin: "-15% 0px" }}
      variants={{
        hidden: { ...variants.hidden, y },
        visible: variants.visible,
      }}
      transition={{ duration: 0.5, ease: EASE_OUT_EXPO, delay }}
    >
      {children}
    </Comp>
  )
}

export function Stagger({
  children,
  className,
  staggerChildren = 0.07,
  as = "div",
}: {
  children: ReactNode
  className?: string
  staggerChildren?: number
  as?: "div" | "ul"
}) {
  const Comp = motion[as]
  return (
    <Comp
      className={className}
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, margin: "-15% 0px" }}
      variants={{
        hidden: {},
        visible: { transition: { staggerChildren, delayChildren: 0.05 } },
      }}
    >
      {children}
    </Comp>
  )
}

export function StaggerItem({
  children,
  className,
  y = 12,
  as = "div",
}: {
  children: ReactNode
  className?: string
  y?: number
  as?: "div" | "li"
}) {
  const Comp = motion[as]
  return (
    <Comp
      className={className}
      variants={{
        hidden: { opacity: 0, y },
        visible: {
          opacity: 1,
          y: 0,
          transition: { duration: 0.45, ease: EASE_OUT_EXPO },
        },
      }}
    >
      {children}
    </Comp>
  )
}

export { EASE_OUT_EXPO }
