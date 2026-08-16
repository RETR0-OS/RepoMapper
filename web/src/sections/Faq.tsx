import { Reveal } from "@/components/motion/Reveal"
import {
  Accordion,
  AccordionItem,
  AccordionTrigger,
  AccordionContent,
} from "@/components/ui/accordion"
import { faq } from "@/content/faq"

export function Faq() {
  return (
    <section id="faq" className="py-24 md:py-32">
      <div className="mx-auto max-w-3xl px-6">
        <Reveal>
          <span className="inline-block rounded-full border border-border bg-panel px-3 py-1 font-mono text-[11px] tracking-widest text-lime uppercase">
            Questions
          </span>
        </Reveal>

        <Reveal delay={0.1}>
          <h2 className="mt-5 text-[clamp(2rem,4vw,2.75rem)] leading-[1.05] font-semibold tracking-[-0.035em] text-foreground">
            Common questions
          </h2>
        </Reveal>

        <Reveal delay={0.2}>
          <Accordion type="single" collapsible className="mt-10">
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
        </Reveal>
      </div>
    </section>
  )
}
