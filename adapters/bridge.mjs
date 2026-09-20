/** Shared native adapter transport. No shell invocation and no remote call on projection. */
import { spawn } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const MAX = 8 * 1024 * 1024;
export const hash = (v) => createHash("sha256").update(JSON.stringify(v)).digest("hex");
export function messageStamp(messages) { return hash(messages); }

export function rpc(config, op, session, messages, receipts = [], signal) {
  const input = JSON.stringify({ schema: "jev-prune.rpc.v1", op,
    format: config.format, session, messages, receipts });
  if (Buffer.byteLength(input) > MAX) return Promise.reject(new Error("Context exceeds adapter input bound; no edits"));
  if (signal?.aborted) return Promise.reject(new Error("Pruning cancelled"));
  return new Promise((resolve, reject) => {
    const child = spawn(config.python, [config.runner, "--worker"], {
      shell: false, windowsHide: true, cwd: path.dirname(config.runner),
      env: { ...process.env, PYTHONPATH: path.dirname(config.runner) },
      stdio: ["pipe", "pipe", "pipe"],
    });
    let output = [], size = 0, done = false;
    const finish = (error, result) => {
      if (done) return;
      done = true; clearTimeout(timer); signal?.removeEventListener("abort", cancel);
      if (error) { child.kill(); reject(error); } else resolve(result);
    };
    const cancel = () => finish(new Error("Pruning cancelled; no successful commit claimed"));
    const timer = setTimeout(() => finish(new Error("Adapter deadline exceeded")), op === "assess" ? 13_000 : 4_000);
    signal?.addEventListener("abort", cancel, { once: true });
    child.stdout.on("data", (chunk) => {
      size += chunk.length;
      if (size > MAX) finish(new Error("Adapter output exceeds bound"));
      else output.push(chunk);
    });
    // Do not forward subprocess stderr: it may include local path or provider diagnostics.
    child.stderr.on("data", () => {});
    child.on("error", () => finish(new Error("Cannot start the installed Python runtime")));
    child.stdin.on("error", () => {});
    child.on("close", (code) => {
      if (done) return;
      try {
        const result = JSON.parse(Buffer.concat(output).toString("utf8"));
        if (code !== 0 || result.ok !== true) throw new Error(result.error || "Adapter operation failed");
        finish(null, result.result);
      } catch (err) { finish(err instanceof Error ? err : new Error("Invalid adapter response")); }
    });
    child.stdin.end(input);
  });
}

export function assertNoSymlink(target) {
  let cursor = path.resolve(target);
  while (true) {
    try { if (fs.lstatSync(cursor).isSymbolicLink()) throw new Error("Symlinked state paths are refused"); }
    catch (e) { if (e.code !== "ENOENT") throw e; }
    const parent = path.dirname(cursor);
    if (parent === cursor) break;
    cursor = parent;
  }
}

/** Proof-only sidecar. Never stores transcript or API credentials. */
export class ReceiptStore {
  constructor(directory, profile) { this.directory = directory; this.profile = profile; }
  file(session) { return path.join(this.directory, hash([this.profile, session]) + ".json"); }
  load(session) {
    const file = this.file(session); assertNoSymlink(file);
    if (!fs.existsSync(file)) return { receipts: [], version: null };
    if (fs.statSync(file).size > 256_000) throw new Error("Receipt file exceeds bound");
    const raw = fs.readFileSync(file, "utf8"), data = JSON.parse(raw);
    if (data.schema !== "jev-prune.receipts.v1" || data.profile !== this.profile || data.session !== session || !Array.isArray(data.receipts))
      throw new Error("Invalid receipt storage identity");
    return { receipts: data.receipts, version: hash(raw) };
  }
  save(session, receipts, expectedVersion) {
    const file = this.file(session); assertNoSymlink(file);
    fs.mkdirSync(this.directory, { recursive: true, mode: 0o700 });
    assertNoSymlink(file);
    const lock = file + ".lock";
    const fd = fs.openSync(lock, "wx", 0o600);
    let tmp;
    try {
      if (this.load(session).version !== expectedVersion) throw new Error("Pruning state changed; retry explicitly");
      const raw = JSON.stringify({ schema: "jev-prune.receipts.v1", profile: this.profile, session, receipts });
      if (Buffer.byteLength(raw) > 256_000) throw new Error("Receipt storage bound exceeded");
      tmp = file + "." + randomBytes(8).toString("hex") + ".tmp";
      const out = fs.openSync(tmp, "wx", 0o600);
      try { fs.writeFileSync(out, raw); fs.fsyncSync(out); } finally { fs.closeSync(out); }
      fs.renameSync(tmp, file); tmp = undefined;
      // Atomic rename is the visibility boundary. Directory fsync is best-effort
      // for platform portability; no claim of power-loss durability on all OSes.
      if (process.platform !== "win32") {
        try { const d = fs.openSync(this.directory, "r"); try { fs.fsyncSync(d); } finally { fs.closeSync(d); } } catch {}
      }
    } finally {
      if (tmp && fs.existsSync(tmp)) fs.unlinkSync(tmp);
      fs.closeSync(fd); fs.unlinkSync(lock);
    }
  }
}

export function resultText(result) {
  return `Jev assessed ${result.considered} repeated-read pairs; approved ${result.added} new omissions. ` +
    `Projection removes ${result.projection.body_bytes_removed} result-body bytes (not a token measurement). ` +
    "No compaction performed. Native token accounting and automatic compaction remain harness-owned.";
}
