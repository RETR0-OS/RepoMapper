#!/usr/bin/env node
// Drive the managed Repository Map path outside VS Code and show every step.
//
// This mirrors what extension/src/managedRuntime.ts does: it starts the bundled
// service, completes the private IPC handshake, serves credentials the way the
// VS Code vault does, attaches with a signed challenge, then calls the same HTTP
// endpoints the extension calls. Each stage prints PASS or FAIL with its reason.
//
// Usage:
//   node scripts/diagnose_managed.mjs [options]
//
// Options:
//   --root <path>       Repository root to attach. Default: this repository.
//   --bundle <path>     Service bundle directory. Default: the staged win32-x64 bundle.
//   --port <number>     Loopback port. Default: 18800.
//   --repository-id <id> Attach as this repository id. Default: the id in
//                       <root>/.hydra-graph/identity.json, which the extension writes.
//                       Without that file only the read-only stages may run.
//   --env <path>        File holding HYDRA_DB_API_KEY and HYDRA_DB_DATABASE. Default: .env
//   --no-credentials    Refuse every credential request, as an unconfigured project does.
//   --index             Also run the real indexing path: preview, confirm, and follow the
//                       background job to its end. THIS WRITES TO HYDRADB. It never runs
//                       unless you pass this flag.
//   --cancel-after <s>  With --index only: cancel the job after this many seconds and
//                       check that it reaches the cancelled state.
//   --http              Also trace each HydraDB request the service makes.
//   --quiet             Show stage results only.
//
// Secrets are never printed. A key is shown as a length and a short fingerprint.

import { spawn } from "node:child_process";
import { createHash, createHmac, randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const IPC_PROTOCOL = "hack-hydra.managed-ipc.v2";
const SERVICE_PROTOCOL = "hack-hydra.managed-service.v2";
const REPOSITORY_ROOT = path.resolve(fileURLToPath(new URL("..", import.meta.url)));

// Analysis and each job request get the hydra.indexTimeoutMs default. The short default
// timeout stays on the fast routes.
const INDEX_TIMEOUT_MS = 300_000;
// The service uploads 25 source cards per ingest batch. Used only to estimate the count
// the preview implies; the started job reports the real number.
const INGEST_BATCH_SIZE = 25;
const JOB_POLL_INTERVAL_MS = 1_000;
// A job that never ends is a failure, not a reason to hang forever.
const JOB_DEADLINE_MS = 7_200_000;
const TERMINAL_JOB_STATES = new Set(["completed", "failed", "cancelled"]);

const options = parseArguments(process.argv.slice(2));
const stages = [];
let child;
let ipcBuffer = "";
let credentialRequests = 0;

function parseArguments(argv) {
  const result = {
    root: REPOSITORY_ROOT,
    bundle: path.join(REPOSITORY_ROOT, "extension", "resources", "service", "win32-x64"),
    port: 18_800,
    envFile: path.join(REPOSITORY_ROOT, ".env"),
    credentials: true,
    index: false,
    cancelAfter: undefined,
    http: false,
    quiet: false
  };
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    if (flag === "--root") result.root = path.resolve(argv[++index]);
    else if (flag === "--bundle") result.bundle = path.resolve(argv[++index]);
    else if (flag === "--port") result.port = Number(argv[++index]);
    else if (flag === "--env") result.envFile = path.resolve(argv[++index]);
    else if (flag === "--repository-id") result.repositoryId = argv[++index];
    else if (flag === "--no-credentials") result.credentials = false;
    else if (flag === "--index") result.index = true;
    else if (flag === "--cancel-after") result.cancelAfter = Number(argv[++index]);
    else if (flag === "--http") result.http = true;
    else if (flag === "--quiet") result.quiet = true;
    else if (flag === "--help" || flag === "-h") {
      console.log(readFileSync(fileURLToPath(import.meta.url), "utf8").split("\n").slice(1, 30).join("\n"));
      process.exit(0);
    } else throw new Error(`Unknown option: ${flag}`);
  }
  if (result.cancelAfter !== undefined) {
    if (!Number.isFinite(result.cancelAfter) || result.cancelAfter < 0) {
      throw new Error("--cancel-after needs a number of seconds");
    }
    if (!result.index) throw new Error("--cancel-after works only together with --index");
  }
  return result;
}

const colors = { pass: "\x1b[32m", fail: "\x1b[31m", dim: "\x1b[90m", bold: "\x1b[1m", off: "\x1b[0m" };

// Width of the progress line that is still on screen, so the next write can erase it.
let progressWidth = 0;

function clearProgress() {
  if (progressWidth === 0) return;
  process.stdout.write(`\r${" ".repeat(progressWidth)}\r`);
  progressWidth = 0;
}

// One line that rewrites itself, so a long job does not fill the transcript.
function progress(message) {
  if (options.quiet) return;
  const line = `${"progress".padEnd(9)} ${message}`;
  const padding = line.length < progressWidth ? " ".repeat(progressWidth - line.length) : "";
  process.stdout.write(`\r${colors.dim}${line}${colors.off}${padding}`);
  progressWidth = line.length + padding.length;
}

function log(channel, message) {
  if (options.quiet) return;
  clearProgress();
  console.log(`${colors.dim}${channel.padEnd(9)}${colors.off} ${message}`);
}

const SENSITIVE_FIELD = /(?:authorization|api.?key|control.?key|secret|signature|token)/i;

function safeJsonForLog(value) {
  try {
    return JSON.stringify(value, (key, item) => SENSITIVE_FIELD.test(key) ? "<redacted>" : item);
  } catch {
    return "<unserializable JSON suppressed>";
  }
}

function stage(name, ok, detail) {
  stages.push({ name, ok, detail });
  clearProgress();
  const badge = ok ? `${colors.pass}PASS${colors.off}` : `${colors.fail}FAIL${colors.off}`;
  console.log(`${badge}  ${colors.bold}${name}${colors.off}${detail ? ` ${colors.dim}${detail}${colors.off}` : ""}`);
}

function fingerprint(value) {
  return `${value.length} chars, sha256:${createHash("sha256").update(value).digest("hex").slice(0, 8)}`;
}

function readEnvFile(target) {
  const values = {};
  try {
    for (const line of readFileSync(target, "utf8").split(/\r?\n/)) {
      const match = /^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/.exec(line);
      if (!match || line.trim().startsWith("#")) continue;
      values[match[1]] = match[2].trim().replace(/^["']|["']$/g, "");
    }
  } catch {
    return values;
  }
  return values;
}

// The extension writes the project's real identity here. A run that invents its own id
// instead would write a sync manifest the extension can never load again: the service
// then refuses to start, because the manifest names a repository the project is not.
function readProjectIdentity(root) {
  try {
    const record = JSON.parse(readFileSync(path.join(root, ".hydra-graph", "identity.json"), "utf8"));
    return typeof record.repository_id === "string" && record.repository_id ? record.repository_id : undefined;
  } catch {
    return undefined;
  }
}

// Identical to canonicalChallengeRoot in extension/src/managedProtocol.ts.
function canonicalChallengeRoot(value) {
  let canonical = path.resolve(value).replace(/\\/g, "/").replace(/\/+$/, "") || "/";
  if (process.platform === "win32") canonical = canonical.toLowerCase();
  return canonical;
}

function createProjectAttachment(controlKey, root, repositoryId) {
  const timestamp = Math.floor(Date.now() / 1_000);
  const nonce = randomBytes(24).toString("base64url");
  const canonicalRoot = canonicalChallengeRoot(root);
  const message = [SERVICE_PROTOCOL, timestamp, nonce, canonicalRoot, repositoryId].join("\n");
  log("challenge", `canonical root ${JSON.stringify(canonicalRoot)}`);
  log("challenge", `repository id  ${repositoryId}`);
  return {
    repository_root: root,
    repository_id: repositoryId,
    timestamp,
    nonce,
    signature: createHmac("sha256", controlKey).update(message).digest("base64url")
  };
}

// `silent` keeps the once-a-second job polls out of the transcript unless --http asks for them.
async function fetchJson(url, init = {}, timeoutMs = 10_000, silent = false) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const started = Date.now();
  const traced = !silent || options.http;
  try {
    const response = await fetch(url, { ...init, signal: controller.signal });
    const body = await response.text();
    let parsed;
    try {
      parsed = JSON.parse(body);
    } catch {
      parsed = undefined;
    }
    if (traced) log("http", `${init.method ?? "GET"} ${url} -> ${response.status} ${Date.now() - started}ms`);
    if (traced && body && !options.quiet) {
      const safeBody = parsed === undefined ? "<non-JSON body suppressed>" : safeJsonForLog(parsed);
      log("http", `   body ${safeBody.slice(0, 400)}`);
    }
    return { status: response.status, ok: response.ok, body, json: parsed };
  } finally {
    clearTimeout(timer);
  }
}

function managedAuthorization(port, controlKey, repositoryId, initialToken) {
  let token = initialToken;
  return {
    async fetch(url, init = {}, timeoutMs = 10_000, silent = false) {
      const send = () => fetchJson(url, {
        ...init,
        headers: { ...init.headers, authorization: `Bearer ${token}` }
      }, timeoutMs, silent);
      let result = await send();
      if (result.status !== 401) return result;

      const attachment = createProjectAttachment(controlKey, options.root, repositoryId);
      const renewed = await fetchJson(`http://127.0.0.1:${port}/managed/challenge`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(attachment)
      }, timeoutMs, silent);
      const nextToken = renewed.json?.access_token;
      if (renewed.status !== 200 || typeof nextToken !== "string") return result;
      token = nextToken;
      log("auth", "project access token renewed after 401");
      result = await send();
      return result;
    }
  };
}

function writeToService(frame) {
  if (!options.quiet) {
    try {
      log("ipc-out", safeJsonForLog(JSON.parse(frame)));
    } catch {
      log("ipc-out", "<non-JSON frame suppressed>");
    }
  }
  child.stdin.write(frame, "utf8");
}

function handleServiceLine(line, controlKey, repositoryId, credentials) {
  let message;
  try {
    message = JSON.parse(line);
  } catch {
    // This is exactly the condition that killed the service before the stdout fix.
    stage("IPC channel stays clean", false, "non-protocol line on stdout; content suppressed");
    return;
  }
  log("ipc-in", safeJsonForLog(message));
  if (message.type === "service_hello") {
    writeToService(JSON.stringify({
      protocol: IPC_PROTOCOL,
      type: "service_start",
      repository_root: options.root,
      repository_id: repositoryId,
      control_key: controlKey
    }) + "\n");
    return;
  }
  if (message.type === "credential_status") {
    writeToService(JSON.stringify({
      protocol: IPC_PROTOCOL,
      type: "response",
      request_id: message.request_id,
      ok: true,
      configured: credentials !== undefined
    }) + "\n");
    return;
  }
  if (message.type === "credential_request") {
    credentialRequests += 1;
    if (!credentials) {
      writeToService(JSON.stringify({
        protocol: IPC_PROTOCOL, type: "response", request_id: message.request_id, ok: false
      }) + "\n");
      return;
    }
    // The real vault answers the same way. The secret never reaches this log.
    log("ipc-out", `credential lease #${credentialRequests} for ${message.repository_id} (values hidden)`);
    child.stdin.write(JSON.stringify({
      protocol: IPC_PROTOCOL,
      type: "response",
      request_id: message.request_id,
      ok: true,
      api_key: credentials.apiKey,
      database: credentials.database
    }) + "\n", "utf8");
  }
}

async function waitForVersion(port) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) return { ok: false, reason: `service exited with code ${child.exitCode}` };
    try {
      const result = await fetchJson(`http://127.0.0.1:${port}/version`, { method: "GET" }, 1_000);
      if (result.json?.protocol === SERVICE_PROTOCOL) return { ok: true, version: result.json };
      return { ok: false, reason: `unexpected /version payload: ${result.body.slice(0, 200)}` };
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
  }
  return { ok: false, reason: "no /version response within 30s" };
}

function countFailed(value) {
  if (!value) return 0;
  return Array.isArray(value) ? value.length : Object.keys(value).length;
}

function describeJob(job) {
  return `${job.phase ?? job.state ?? "unknown"} ${job.uploaded_batches ?? 0}/${job.total_batches ?? 0} batches, `
    + `${job.verified_sources ?? 0}/${job.total_sources ?? 0} sources`;
}

function describeOutcome(job, elapsedMs) {
  const sync = job.result?.sync;
  const parts = [`state ${job.state}`, `phase ${job.phase ?? "unknown"}`, `${Math.round(elapsedMs / 1_000)}s`];
  if (sync) {
    parts.push(`sync ${sync.status}`);
    parts.push(`candidate ${sync.candidate_revision ?? "none"}`);
    parts.push(`ready ${sync.ready_revision ?? "none"}`);
    parts.push(`${sync.added?.length ?? 0} added`);
    parts.push(`${sync.replaced?.length ?? 0} replaced`);
    parts.push(`${sync.deleted?.length ?? 0} deleted`);
    if (sync.pending?.length) parts.push(`${sync.pending.length} pending`);
    if (countFailed(sync.failed)) parts.push(`${countFailed(sync.failed)} failed`);
    if (sync.current_state_indeterminate) parts.push("current state indeterminate");
  }
  // `message` is the fixed durability sentence, not a status, so it is not repeated here.
  if (job.error) parts.push(`error: ${String(job.error).slice(0, 200)}`);
  return parts.join(", ");
}

// A verified revision means the job finished and published exactly the candidate it analyzed.
function reachedVerifiedRevision(job) {
  const sync = job.result?.sync;
  return job.state === "completed"
    && sync?.status === "ready"
    && typeof sync.candidate_revision === "string"
    && sync.ready_revision === sync.candidate_revision
    && !(sync.pending?.length)
    && countFailed(sync.failed) === 0;
}

// The real write path: preview, confirm, then follow the background job to a terminal state.
async function runIndex(port, authorized, database) {
  const base = `http://127.0.0.1:${port}`;
  const jsonHeaders = { "content-type": "application/json" };

  console.log(`\n${colors.fail}WARNING${colors.off}  ${colors.bold}--index performs a real HydraDB write${colors.off}`
    + `${colors.dim}: it uploads ${options.root} into database ${database ?? "(none configured)"}.${colors.off}`);

  const preview = await authorized.fetch(`${base}/api/index/preview`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({})
  }, INDEX_TIMEOUT_MS);
  const previewToken = preview.json?.preview_token;
  const sourceCount = preview.json?.source_count;
  const batchEstimate = typeof sourceCount === "number" ? Math.ceil(sourceCount / INGEST_BATCH_SIZE) : "?";
  stage("Index preview reports a revision",
    preview.status === 200 && typeof preview.json?.revision_id === "string" && typeof previewToken === "string",
    preview.status === 200
      ? `revision ${preview.json?.revision_id}, ${sourceCount ?? "?"} sources, `
        + `about ${batchEstimate} ingest batches of ${INGEST_BATCH_SIZE}`
      : `status ${preview.status}: ${preview.json?.detail ?? preview.body.slice(0, 160)}`);
  if (typeof previewToken !== "string") return undefined;

  const started = Date.now();
  const accepted = await authorized.fetch(`${base}/api/index`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ preview_token: previewToken })
  }, INDEX_TIMEOUT_MS);
  let job = accepted.json;
  const jobId = job?.job_id;
  stage("Index job starts", accepted.status === 202 && typeof jobId === "string",
    accepted.status === 202
      ? `job ${jobId}, state ${job?.state}, ${job?.total_batches ?? "?"} batches, ${job?.total_sources ?? "?"} sources`
      : `status ${accepted.status}: ${accepted.json?.detail ?? accepted.body.slice(0, 160)}`);
  if (typeof jobId !== "string") return undefined;

  const goal = options.cancelAfter === undefined
    ? "Index job reaches a verified revision"
    : "Index job reaches the cancelled state";
  const cancelAt = options.cancelAfter === undefined ? undefined : started + options.cancelAfter * 1_000;
  const deadline = started + JOB_DEADLINE_MS;
  let cancelRequested = false;

  while (!TERMINAL_JOB_STATES.has(job?.state)) {
    if (child.exitCode !== null) {
      stage(goal, false, `service exited with code ${child.exitCode}; the job lives in that process only`);
      return undefined;
    }
    if (Date.now() > deadline) {
      stage(goal, false, `no terminal state within ${Math.round(JOB_DEADLINE_MS / 60_000)} minutes, last was ${describeJob(job)}`);
      return undefined;
    }
    if (cancelAt !== undefined && !cancelRequested && Date.now() >= cancelAt) {
      cancelRequested = true;
      const cancelled = await authorized.fetch(`${base}/api/index/jobs/${jobId}/cancel`, {
        method: "POST",
        headers: jsonHeaders,
        body: JSON.stringify({})
      }, INDEX_TIMEOUT_MS);
      log("cancel", `requested after ${options.cancelAfter}s -> status ${cancelled.status}, `
        + `state ${cancelled.json?.state ?? "unknown"}`);
      if (cancelled.status !== 200) {
        stage(goal, false, `cancel returned ${cancelled.status}: ${cancelled.json?.detail ?? cancelled.body.slice(0, 160)}`);
        return undefined;
      }
      if (cancelled.json?.job_id === jobId) job = cancelled.json;
      continue;
    }
    await new Promise((resolve) => setTimeout(resolve, JOB_POLL_INTERVAL_MS));
    const polled = await authorized.fetch(`${base}/api/index/jobs/${jobId}`, {
      method: "GET"
    }, INDEX_TIMEOUT_MS, true);
    if (polled.status !== 200 || !polled.json) {
      stage(goal, false, `job status returned ${polled.status}: ${polled.json?.detail ?? polled.body.slice(0, 160)}`);
      return undefined;
    }
    job = polled.json;
    progress(describeJob(job));
  }
  clearProgress();

  const elapsed = Date.now() - started;
  const ok = cancelRequested ? job.state === "cancelled" : reachedVerifiedRevision(job);
  stage(goal, ok, describeOutcome(job, elapsed));
  return ok ? job : undefined;
}

async function verifyIndexedRetrieval(port, authorized, revisionId) {
  const base = `http://127.0.0.1:${port}`;
  const health = await authorized.fetch(`${base}/health`, { method: "GET" });
  stage("Health publishes the verified revision",
    health.status === 200
      && health.json?.state === "ready"
      && health.json?.revision_verified === true
      && health.json?.revision_id === revisionId,
    health.status === 200
      ? `state ${health.json?.state}, revision ${health.json?.revision_id ?? "none"}`
      : `status ${health.status}: ${health.json?.detail ?? health.body.slice(0, 160)}`);

  const result = await authorized.fetch(`${base}/api/query`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      question: "How are agent runs created, controlled, and cleaned up by the session manager?",
      depth: "symbol",
      revision: "current",
      max_nodes: 50,
      max_edges: 80,
      max_context_chars: 15_000,
      query_by: "hybrid",
      mode: "thinking",
      graph_context: true
    })
  }, 120_000);
  const nodes = Array.isArray(result.json?.nodes) ? result.json.nodes : [];
  const edges = Array.isArray(result.json?.edges) ? result.json.edges : [];
  const exactByog = edges.filter((edge) => edge?.quality === "exact"
    && edge?.attributes?.hydradb_origin === "byog"
    && Array.isArray(edge?.evidence)
    && edge.evidence.length > 0);
  stage("HydraDB retrieval returns grounded exact structure",
    result.status === 200
      && result.json?.hydradb?.available === true
      && result.json?.revision_id === revisionId
      && nodes.length > 0
      && exactByog.length > 0,
    result.status === 200
      ? `${nodes.length} nodes, ${edges.length} edges, ${exactByog.length} exact BYOG edges, revision ${result.json?.revision_id ?? "none"}`
      : `status ${result.status}: ${result.json?.detail ?? result.body.slice(0, 160)}`);
}

async function main() {
  const executable = path.join(options.bundle, process.platform === "win32" ? "hydra-graph.exe" : "hydra-graph");
  const environment = readEnvFile(options.envFile);
  const apiKey = environment.HYDRA_DB_API_KEY;
  const database = environment.HYDRA_DB_DATABASE;
  const credentials = options.credentials && apiKey && database ? { apiKey, database } : undefined;
  const controlKey = randomBytes(32).toString("base64url");
  const storedIdentity = readProjectIdentity(options.root);
  const repositoryId = options.repositoryId
    ?? storedIdentity
    ?? `local:diagnose:${createHash("sha256").update(canonicalChallengeRoot(options.root)).digest("hex").slice(0, 20)}`;
  const identitySource = options.repositoryId ? "--repository-id" : (storedIdentity ? ".hydra-graph/identity.json" : "synthetic");

  console.log(`${colors.bold}Repository Map managed diagnosis${colors.off}`);
  console.log(`${colors.dim}bundle     ${executable}`);
  console.log(`root       ${options.root}`);
  console.log(`port       ${options.port}`);
  console.log(`env file   ${options.envFile}`);
  console.log(`api key    ${apiKey ? fingerprint(apiKey) : "not set"}`);
  console.log(`database   ${database ? database : "not set"}`);
  console.log(`repo id    ${repositoryId} (from ${identitySource})`);
  console.log(`credential mode ${credentials ? "serve from env file" : "refuse (unconfigured project)"}${colors.off}\n`);

  // A synthetic id plus --index writes a manifest under a repository the extension does not
  // know, and the service then exits at startup for that project until the file is removed.
  if (options.index && identitySource === "synthetic") {
    console.log(`${colors.fail}WARNING${colors.off}  ${colors.bold}This root has no .hydra-graph/identity.json${colors.off}`
      + `${colors.dim}, so --index would write a sync manifest under a synthetic repository id.`
      + ` Open the project in VS Code once, or pass --repository-id, then run again.${colors.off}\n`);
    process.exitCode = 1;
    return;
  }

  const childEnvironment = { ...process.env };
  // managedRuntime.ts strips these so the service can never read ambient credentials.
  for (const key of Object.keys(childEnvironment)) {
    if (key.toUpperCase().startsWith("HYDRA_DB_")) delete childEnvironment[key];
  }
  if (options.http) childEnvironment.HYDRA_DEBUG_HTTP = "1";

  child = spawn(executable, ["serve", "--managed", "--port", String(options.port)], {
    cwd: options.bundle,
    env: childEnvironment,
    stdio: ["pipe", "pipe", "pipe"],
    windowsHide: true
  });
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (chunk) => {
    for (const line of chunk.split(/\r?\n/)) if (line.trim()) log("service", line.trim());
  });
  child.stdout.on("data", (chunk) => {
    ipcBuffer += chunk;
    let newline = ipcBuffer.indexOf("\n");
    while (newline >= 0) {
      const line = ipcBuffer.slice(0, newline).trim();
      ipcBuffer = ipcBuffer.slice(newline + 1);
      if (line) handleServiceLine(line, controlKey, repositoryId, credentials);
      newline = ipcBuffer.indexOf("\n");
    }
  });

  const version = await waitForVersion(options.port);
  stage("Service starts and serves /version", version.ok, version.ok ? `version ${version.version.version}` : version.reason);
  if (!version.ok) return finish();

  // Any non-JSON line would already have recorded a failing stage above.
  stage("IPC channel stays clean", !stages.some((item) => item.name === "IPC channel stays clean" && !item.ok));

  const attachment = createProjectAttachment(controlKey, options.root, repositoryId);
  const attach = await fetchJson(`http://127.0.0.1:${options.port}/managed/challenge`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(attachment)
  });
  const token = attach.json?.access_token;
  stage("Signed attachment is accepted", attach.status === 200 && typeof token === "string",
    attach.status === 200 ? "access token issued" : `status ${attach.status}: ${attach.json?.detail ?? attach.body.slice(0, 160)}`);
  if (!token) return finish();

  const authorized = managedAuthorization(options.port, controlKey, repositoryId, token);
  const health = await authorized.fetch(`http://127.0.0.1:${options.port}/health`, { method: "GET" });
  stage("Health reports project state", health.status === 200,
    health.status === 200
      ? `state=${health.json?.state} credentials_configured=${health.json?.credentials_configured}`
      : `status ${health.status}: ${health.json?.detail ?? ""}`);

  const setup = await authorized.fetch(`http://127.0.0.1:${options.port}/api/setup/test`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({})
  }, 30_000);
  stage("HydraDB read access verified", setup.status === 200 && setup.json?.status === "connected",
    setup.status === 200 ? "read-only query succeeded" : `status ${setup.status}: ${setup.json?.detail ?? setup.body.slice(0, 160)}`);

  // Everything above is read-only. The index stages below write to HydraDB, so they need --index.
  if (options.index) {
    const job = await runIndex(options.port, authorized, database);
    if (job && options.cancelAfter === undefined) {
      await verifyIndexedRetrieval(options.port, authorized, job.revision_id);
    }
  }

  stage("Credential broker was used", credentialRequests > 0 || !credentials,
    `${credentialRequests} lease request(s)`);

  return finish();
}

function finish() {
  clearProgress();
  if (child && !child.killed) child.kill();
  const failed = stages.filter((item) => !item.ok);
  console.log(`\n${colors.bold}${stages.length - failed.length}/${stages.length} stages passed${colors.off}`);
  if (failed.length) {
    console.log(`${colors.fail}First failure: ${failed[0].name}${colors.off} ${failed[0].detail ?? ""}`);
  }
  process.exitCode = failed.length ? 1 : 0;
}

main().catch((error) => {
  clearProgress();
  console.error(`${colors.fail}Diagnosis could not finish:${colors.off}`, error);
  if (child && !child.killed) child.kill();
  process.exitCode = 1;
});
