export interface FaqItem {
  question: string
  answer: string
}

export const faq: FaqItem[] = [
  {
    question: "What do I need to get started?",
    answer:
      "Just VS Code and a HydraDB account. Install the extension, point it at your project, and it walks you through the rest — no Python, Node, or separate server to install or run yourself.",
  },
  {
    question: "Does my source code get sent anywhere I don't control?",
    answer:
      "It goes into your own HydraDB account, under your own database — never to us. Your API key stays in VS Code's built-in secure credential storage, not in a config file, a log, or a prompt handed to an agent.",
  },
  {
    question: "Will it slow down VS Code or my machine?",
    answer:
      "No. Indexing runs in a lightweight background service on your machine and only talks to HydraDB over a local connection. You decide when to index, and you can review what's about to be sent before it uploads.",
  },
  {
    question: "Does it work with the AI coding agent I already use?",
    answer:
      "Yes — Codex and Claude Code can connect through the same panel you use, so you and your agent are always looking at the same graph, not two different mental models of your codebase.",
  },
  {
    question: "What if I can't trust what the extension shows me?",
    answer:
      "If HydraDB can't be reached, the extension tells you plainly instead of quietly showing a guess. You'll never see a fabricated result labeled as real.",
  },
  {
    question: "Which platforms and languages are supported today?",
    answer:
      "Windows, macOS, and Linux, on local VS Code desktop. Python repositories are fully supported today, with more languages on the way.",
  },
]
