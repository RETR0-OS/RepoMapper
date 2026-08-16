import { Reveal } from "@/components/motion/Reveal"
import { Section, SectionHeader } from "@/components/layout/Section"
import {
  Accordion,
  AccordionItem,
  AccordionTrigger,
  AccordionContent,
} from "@/components/ui/accordion"
import { faq } from "@/content/faq"

export function Faq() {
  return (
    <Section id="faq" tone="band" size="md">
      <SectionHeader
        index="09"
        eyebrow="Questions"
        headline="Common questions"
        align="center"
      />

      <Reveal delay={0.2}>
        <Accordion type="single" collapsible className="mx-auto mt-10 max-w-3xl">
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
    </Section>
  )
}
