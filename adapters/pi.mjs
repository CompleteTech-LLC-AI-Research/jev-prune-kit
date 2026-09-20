/** Experimental Pi request projection. NOT a full resumable host scheduler.
 * Existing /compact is not registered or replaced. Manual compaction passes through.
 * Auto choice is optional: on Prune/Pause this adapter aborts the current run and
 * cancels compaction; the user must resume explicitly. No fake summary is emitted.
 */
import { rpc, messageStamp, resultText } from "./bridge.mjs";
import { runChain, formatPreview } from "./bus.mjs";

const RECEIPT_TYPE = "jev-prune.receipts.v1";
const PACKAGE = "jev-prune-kit";
export default function createPi(pi, config, call = rpc) {
  let cached = null, busy = false;
  const sid = (ctx) => ctx.sessionManager.getSessionId();
  const receipts = (ctx) => {
    const branch = ctx.sessionManager.getBranch();
    const own = branch.filter(e => e.type === "custom" && e.customType === RECEIPT_TYPE);
    if (!own.length) return [];
    const data = own[own.length - 1].data;
    // Do not inherit a different session's projection on fork. Reassess explicitly.
    if (data.session !== sid(ctx)) return [];
    return data.receipts;
  };
  const branchStamp = (ctx) => messageStamp(ctx.sessionManager.getBranch());
  const notify = (ctx, text, level = "info") => { if (ctx.hasUI) ctx.ui.notify(text, level); };
  const prune = async (ctx, signal) => {
    if (busy) throw new Error("An assessment is already in progress");
    if (!cached || cached.session !== sid(ctx)) throw new Error("No captured request in this runtime; run a normal turn first");
    busy = true;
    const stamp = branchStamp(ctx), requestStamp = messageStamp(cached.messages), session = sid(ctx);
    try {
      const result = await call(config, "assess", session, cached.messages, receipts(ctx), signal);
      if (signal?.aborted || sid(ctx) !== session || branchStamp(ctx) !== stamp || !cached || messageStamp(cached.messages) !== requestStamp)
        throw new Error("Session changed during assessment; no receipt committed");
      if (result.added > 0) {
        // appendEntry is the public session-persistence API; never edit JSONL on disk.
        pi.appendEntry(RECEIPT_TYPE, { session, receipts: result.receipts });
      }
      notify(ctx, resultText(result));
      return result;
    } finally { busy = false; }
  };
  pi.on("session_start", async () => { cached = null; busy = false; });
  pi.on("session_tree", async () => { cached = null; });
  // This package is the jev-bus CARRIER for Pi: it owns the context hook and pipes the
  // array through every registered stage, its own dedup included. Pi's context event has
  // no system array, so acceptsSystemAppend is false and a stage returning one is ignored
  // rather than having its text smuggled into the message list.
  pi.on("context", async (event, ctx) => {
    cached = { session: sid(ctx), messages: structuredClone(event.messages) };
    const list = receipts(ctx);
    let { messages, notes } = await runChain("pi", event.messages, {
      session: sid(ctx), workspace: config.workspace || "", acceptsSystemAppend: false,
    });
    for (const note of notes) {
      if (note.action === "passthrough" && !/no approved|no session/.test(note.detail || "")) {
        notify(ctx, `${note.stage}: ${note.detail}; original context retained.`, "warning");
      }
    }
    // The bus is ADDITIVE, never a prerequisite: if it contributed no stage of ours -- a
    // skill-only install, an unreadable registry, or plain standalone use -- fall back to
    // this package's own direct projection, exactly as before jev-bus existed.
    if (!notes.some(n => String(n.stage || "").startsWith("jev-prune."))) {
      if (!list.length) return;
      const result = await call(config, "project", sid(ctx), event.messages, list);
      if (result.projection.invalid) notify(ctx, "Some old pruning proofs no longer match; original evidence retained.", "warning");
      return { messages: result.messages };
    }
    if (!Array.isArray(messages) || messages === event.messages) return;
    return { messages };
  });
  pi.registerCommand("prune", {
    description: "Jev: omit validated repeated read results without summarizing (experimental)",
    handler: async (_args, ctx) => {
      if (!ctx.isIdle()) { notify(ctx, "Wait for an idle request boundary before /prune.", "warning"); return; }
      // Show every stage's candidates first, attributed by package, then assess our own.
      try {
        if (cached?.messages) {
          const { notes } = await runChain("pi", cached.messages, {
            session: sid(ctx), op: "plan", workspace: config.workspace || "",
            acceptsSystemAppend: false,
          });
          if (notes.length) notify(ctx, formatPreview(sid(ctx), notes));
        }
      } catch { /* a preview must never block the real command */ }
      try { await prune(ctx); } catch (err) { notify(ctx, String(err.message || err), "error"); }
    },
  });
  if (config.autoChoice) pi.on("session_before_compact", async (event, ctx) => {
    if (event.reason === "manual") return; // Native /compact: zero Jev calls, no new chooser.
    if (!["threshold", "overflow"].includes(event.reason)) return; // Unknown API: do not claim interception.
    if (!ctx.hasUI) { ctx.abort(); return { cancel: true }; }
    const choice = await ctx.ui.select("Context pressure: choose an operation", [
      "Prune — send selected records to TypeSafe; keep retained text; may free too little",
      "Compact — existing native compaction; may condense details",
      "Pause — no pruning or compaction",
    ]);
    if (choice?.startsWith("Compact")) return;
    if (choice?.startsWith("Prune")) {
      try { await prune(ctx, event.signal); } catch (err) { notify(ctx, String(err.message || err), "error"); }
      notify(ctx, "Compaction cancelled; current run stopped. Resume explicitly, or use /compact. This adapter cannot certify native token headroom.", "warning");
    }
    ctx.abort();
    return { cancel: true };
  });
}
