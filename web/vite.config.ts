import path from "path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

const repoName = process.env.GITHUB_REPOSITORY?.split("/")[1]
const base = repoName ? `/${repoName}/` : "/"

// https://vite.dev/config/
export default defineConfig({
  base,
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    rollupOptions: {
      input: {
        main: path.resolve(__dirname, "index.html"),
        docs: path.resolve(__dirname, "docs.html"),
      },
    },
  },
})
