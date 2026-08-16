import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import "./index.css"
import DocsApp from "./DocsApp.tsx"

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <DocsApp />
  </StrictMode>
)
