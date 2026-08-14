import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize, resolve } from "node:path";

const root = resolve(import.meta.dirname);
const port = Number(process.env.HYDRA_PREVIEW_PORT ?? 4173);
const types = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml" };

createServer((request, response) => {
  const requested = request.url === "/" ? "/preview.html" : decodeURIComponent((request.url ?? "/").split("?")[0]);
  const target = normalize(join(root, requested));
  if (!target.startsWith(root) || !existsSync(target) || !statSync(target).isFile()) {
    response.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
    response.end("Not found");
    return;
  }
  response.writeHead(200, { "content-type": types[extname(target)] ?? "application/octet-stream", "cache-control": "no-store" });
  createReadStream(target).pipe(response);
}).listen(port, "127.0.0.1", () => {
  console.log(`Repository Map preview: http://127.0.0.1:${port}`);
});
