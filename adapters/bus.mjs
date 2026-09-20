/**
 * jev-bus v1 — cooperative context-transform chaining across independent packages.
 *
 * Vendored BYTE-IDENTICALLY into every participating package. Node built-ins only, and
 * nothing from its host package, so the copies can be compared with sha256. The semantics
 * mirror bus.py exactly; see that file's header for the contract.
 */
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const SCHEMA = "jev-bus.v1";
export const STAGE_SCHEMA = "jev-bus.stage.v1";
const MAX_REGISTRY_BYTES = 256_000;
const MAX_WIRE = 8 * 1024 * 1024;
const DEFAULT_STAGE_TIMEOUT_MS = 6_000;
const DEFAULT_CHAIN_TIMEOUT_MS = 20_000;

export const CONCRETE_CLAIMS = new Set([
  "tool-result:read", "assistant-prose", "system-append", "message-remove", "message-reorder",
]);
export const WILDCARD_CLAIMS = new Set(["tool-result:*"]);
export const TRANSFORM_HOSTS = ["pi", "opencode", "hermes"];

export class BusError extends Error {}

export const hash = (value) => createHash("sha256").update(JSON.stringify(value)).digest("hex");

/** Refuse a symlinked path or any symlinked ancestor; never follow one. */
export function safePath(target) {
  const resolved = path.resolve(target);
  let cursor = resolved;
  for (;;) {
    try { if (fs.lstatSync(cursor).isSymbolicLink()) throw new BusError("Symlinked bus path refused: " + cursor); }
    catch (err) { if (err instanceof BusError) throw err; if (err.code !== "ENOENT") throw err; }
    const parent = path.dirname(cursor);
    if (parent === cursor) break;
    cursor = parent;
  }
  return resolved;
}

export function busHome() {
  return process.env.JEV_BUS_HOME || path.join(os.homedir(), ".jev", "bus");
}

export function registryPath(home) {
  return safePath(path.join(home || busHome(), "v1", "registry.json"));
}

export function claimsOverlap(left, right) {
  if (left === right) return true;
  for (const [wide, narrow] of [[left, right], [right, left]]) {
    if (WILDCARD_CLAIMS.has(wide) && narrow.startsWith(wide.slice(0, -1))) return true;
  }
  return false;
}

function stageApplies(stage, host) {
  const hosts = Array.isArray(stage.hosts) && stage.hosts.length ? stage.hosts : ["*"];
  return hosts.includes("*") || hosts.includes(host);
}

export function assertNoClaimConflict(stages, host) {
  const active = stages.filter((s) => stageApplies(s, host));
  for (let i = 0; i < active.length; i += 1) {
    for (let j = i + 1; j < active.length; j += 1) {
      if (active[i].package === active[j].package) continue;
      for (const a of active[i].claims || []) {
        for (const b of active[j].claims || []) {
          if (claimsOverlap(a, b)) {
            throw new BusError(
              `Bus claim conflict on ${host}: ${active[i].name} claims ${a} and ` +
              `${active[j].name} claims ${b}. Uninstall one, or give them disjoint claims.`);
          }
        }
      }
    }
  }
}

export function loadRegistry(home) {
  const file = registryPath(home);
  if (!fs.existsSync(file)) return { schema: SCHEMA, hosts: {}, stages: [] };
  if (fs.statSync(file).size > MAX_REGISTRY_BYTES) throw new BusError("Bus registry exceeds its size bound");
  const value = JSON.parse(fs.readFileSync(file, "utf8"));
  if (!value || typeof value !== "object" || value.schema !== SCHEMA) {
    throw new BusError("Unrecognized bus registry schema");
  }
  if (typeof value.hosts !== "object" || !Array.isArray(value.stages)) {
    throw new BusError("Bus registry must hold an object of hosts and a list of stages");
  }
  return value;
}

export function carrierOf(host, registry) {
  const reg = registry || loadRegistry();
  const record = reg.hosts?.[host];
  return record && typeof record === "object" ? record.carrier : undefined;
}

/** True when this package owns the host hook. A non-carrier must not register one. */
export function isCarrier(host, pkg, registry) {
  return carrierOf(host, registry) === pkg;
}

export function stagesFor(host, registry) {
  const reg = registry || loadRegistry();
  assertNoClaimConflict(reg.stages, host);
  return reg.stages
    .filter((s) => stageApplies(s, host))
    .sort((a, b) => (a.priority - b.priority) || String(a.name).localeCompare(String(b.name)));
}

function invokeStage(stage, request, workspace, budgetMs) {
  const argv = stage.transport.argv.map((a) => a.split("{workspace}").join(workspace));
  const timeout = Math.min(stage.transport.timeout_ms ?? DEFAULT_STAGE_TIMEOUT_MS, Math.max(budgetMs, 1));
  const body = JSON.stringify(request);
  if (Buffer.byteLength(body) > MAX_WIRE) return Promise.reject(new BusError("Stage request exceeds the wire bound"));
  return new Promise((resolve, reject) => {
    const child = spawn(argv[0], argv.slice(1), {
      shell: false, windowsHide: true, cwd: stage.transport.cwd || undefined,
      stdio: ["pipe", "pipe", "pipe"],
    });
    const chunks = [];
    let size = 0, settled = false;
    const finish = (err, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (err) { child.kill(); reject(err); } else resolve(value);
    };
    const timer = setTimeout(() => finish(new BusError("Stage deadline exceeded")), timeout);
    child.stdout.on("data", (chunk) => {
      size += chunk.length;
      if (size > MAX_WIRE) finish(new BusError("Stage response exceeds the wire bound"));
      else chunks.push(chunk);
    });
    // Never forward a stage's stderr: it can carry local paths or provider diagnostics.
    child.stderr.on("data", () => {});
    child.on("error", () => finish(new BusError("Cannot start the stage runtime")));
    child.stdin.on("error", () => {});
    child.on("close", (code) => {
      if (settled) return;
      if (code !== 0) return finish(new BusError("Stage exited nonzero"));
      try { finish(null, JSON.parse(Buffer.concat(chunks).toString("utf8"))); }
      catch { finish(new BusError("Invalid stage response")); }
    });
    child.stdin.end(body);
  });
}

/**
 * Pipe messages through every stage for this host, in priority order.
 *
 * Resolves {messages, notes, systemAppends}.
 *
 * Fail-safe: a stage that errors, times out, or returns an unrecognized shape contributes
 * nothing and the chain continues with that stage's own input. A transform is applied only
 * when a stage returns a well-formed message list.
 */
export async function runChain(host, messages, options = {}) {
  const {
    session = "", workspace = "", goal = "", api = "", op = "transform",
    acceptsSystemAppend = true,
    registry, chainTimeoutMs = DEFAULT_CHAIN_TIMEOUT_MS, invoke = invokeStage,
  } = options;
  if (op !== "transform" && op !== "plan") throw new BusError("Bus op must be transform or plan");

  let chain;
  // ANY reason the chain cannot be resolved -- a claim conflict, an unreadable or malformed
  // registry, an unresolvable home directory -- must degrade to passthrough. The bus may
  // decline to transform; it may never break the host's turn.
  try { chain = stagesFor(host, registry); }
  catch (err) {
    return { messages, notes: [{ stage: "jev-bus", action: "chain-refused", detail: String(err?.message || err) }], systemAppends: [] };
  }

  const original = messages;
  let current = messages;
  const notes = [];
  const systemAppends = [];
  let remaining = chainTimeoutMs;
  for (const stage of chain) {
    if (remaining <= 0) {
      notes.push({ stage: stage.name, action: "skipped", detail: "chain deadline exhausted" });
      continue;
    }
    const started = Date.now();
    try {
      const response = await invoke(stage, {
        schema: STAGE_SCHEMA, op, host, api, session, workspace, goal,
        accepts_system_append: Boolean(acceptsSystemAppend),
        messages: current, original_messages: original, notes: [...notes],
      }, workspace, remaining);
      if (!response || typeof response !== "object" || response.ok !== true) throw new BusError("Stage declined");
      if (op === "transform") {
        if (!Array.isArray(response.messages)) throw new BusError("Stage returned no message list");
        current = response.messages;
        if (typeof response.system_append === "string" && response.system_append) {
          systemAppends.push(response.system_append);
        }
      }
      for (const note of response.notes || []) {
        if (note && typeof note === "object") notes.push({ ...note, stage: note.stage || stage.name });
      }
    } catch (err) {
      notes.push({ stage: stage.name, action: "passthrough", detail: String(err?.message || err).slice(0, 200) });
    }
    remaining -= Math.max(Date.now() - started, 0);
  }
  return { messages: current, notes, systemAppends };
}

/** Render a combined, package-attributed preview for a carrier's /prune command. */
export function formatPreview(session, notes) {
  const lines = [`/prune preview — session ${session}`];
  const acted = notes.filter((n) => n.action && n.action !== "passthrough" && n.action !== "skipped");
  if (!acted.length) lines.push("  nothing eligible in any registered stage");
  for (const note of acted) {
    const count = note.count === undefined ? "" : String(note.count).padStart(4);
    const bytes = note.bytes === undefined ? "" : `  ${(note.bytes / 1024).toFixed(1)} KB`;
    lines.push(`  ${String(note.stage).padEnd(22)}${count} ${note.detail || note.action}${bytes}`);
  }
  for (const note of notes.filter((n) => n.action === "passthrough" || n.action === "skipped")) {
    lines.push(`  ${String(note.stage).padEnd(22)}  unavailable (${note.detail}); nothing removed`);
  }
  lines.push("This is a preview. Approve in each package's own CLI; the bus approves nothing.");
  return lines.join("\n");
}
