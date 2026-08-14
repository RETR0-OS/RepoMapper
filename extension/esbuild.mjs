import * as esbuild from "esbuild";

const watch = process.argv.includes("--watch");
const shared = {
  bundle: true,
  sourcemap: true,
  minify: false,
  logLevel: "info"
};

const contexts = await Promise.all([
  esbuild.context({
    ...shared,
    entryPoints: ["src/extension.ts"],
    outfile: "dist/extension.js",
    platform: "node",
    format: "cjs",
    external: ["vscode"]
  }),
  esbuild.context({
    ...shared,
    entryPoints: ["src/webview/main.ts"],
    outfile: "dist/webview.js",
    platform: "browser",
    format: "iife"
  })
]);

if (watch) {
  await Promise.all(contexts.map((context) => context.watch()));
  console.log("Watching extension and webview sources...");
} else {
  await Promise.all(contexts.map((context) => context.rebuild()));
  await Promise.all(contexts.map((context) => context.dispose()));
}
