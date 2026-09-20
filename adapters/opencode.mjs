/** Experimental OpenCode manual projection adapter. No automatic compaction veto.
 * command.execute.before has no documented host-completed response: a deliberate
 * command error terminates /prune after displaying results, preventing a new LLM
 * turn. This is visible in the TUI. No /compact command is modified.
 */
import { rpc, ReceiptStore, messageStamp, resultText } from "./bridge.mjs";
import { carrierOf } from "./bus.mjs";

const PACKAGE = "jev-prune-kit";

export default async function createOpenCode(ctx, config, call = rpc) {
  const store = new ReceiptStore(config.stateDir, config.profile);
  const requests = new Map(), busy = new Set();
  let registered = false;
  // When another jev-bus package carries OpenCode, this adapter must NOT register a
  // competing /prune or a second message transform: it runs as a stage inside that
  // carrier's chain instead, invoked through runner.py --bus-stage. Deciding once at
  // load time keeps a mid-session registry edit from changing behaviour under a turn.
  let carrier = PACKAGE;
  try { carrier = carrierOf("opencode") || PACKAGE; } catch { carrier = PACKAGE; }
  const carrying = carrier === PACKAGE;
  const toast = async (message, variant = "info") => {
    try { await ctx.client.tui.showToast({ body: { title: "Jev prune", message, variant } }); } catch {}
  };
  return {
    config: async (cfg) => {
      if (!carrying) return;  // the carrier owns /prune and shows a combined preview
      cfg.command ??= {};
      // Never override an existing user command.
      if (cfg.command.prune) { await toast("/prune already exists; Jev command not registered.", "warning"); return; }
      cfg.command.prune = { description: "Jev repeated-read pruning (experimental, manual only)",
        template: "Do not claim context was pruned. The native Jev plugin must handle this command." };
      registered = true;
    },
    "experimental.chat.messages.transform": async (_input, output) => {
      const messages = output.messages;
      if (!Array.isArray(messages)) throw new Error("Jev: incompatible OpenCode message transform API");
      // Still capture the request so /prune assessment has something to work from, but
      // leave the projection to the carrier's chain, which invokes this package as a stage.
      if (!carrying) {
        const seen = new Set(messages.map(m => m.info?.sessionID).filter(Boolean));
        if (seen.size === 1) {
          requests.set([...seen][0], structuredClone(messages));
          while (requests.size > 8) requests.delete(requests.keys().next().value);
        }
        return;
      }
      const ids = new Set(messages.map(m => m.info?.sessionID).filter(Boolean));
      if (ids.size !== 1) return; // Do not project an ambiguous/multi-session request.
      const session = [...ids][0];
      requests.set(session, structuredClone(messages));
      while (requests.size > 8) requests.delete(requests.keys().next().value);
      const previous = store.load(session);
      if (!previous.receipts.length) return;
      const result = await call(config, "project", session, messages, previous.receipts);
      if (result.projection.invalid) await toast("Old proof mismatch: original evidence retained.", "warning");
      // The current plugin API shares this array with the caller: mutate in place.
      output.messages.splice(0, output.messages.length, ...result.messages);
    },
    "command.execute.before": async (input, _output) => {
      if (!carrying || !registered || input.command !== "prune") return;
      const session = input.sessionID;
      let message;
      try {
        if (busy.has(session)) throw new Error("A pruning assessment is already in progress");
        const messages = requests.get(session);
        if (!messages) throw new Error("No captured request for this session; run a normal turn first");
        busy.add(session);
        const stamp = messageStamp(messages), previous = store.load(session);
        const result = await call(config, "assess", session, messages, previous.receipts);
        if (!requests.has(session) || messageStamp(requests.get(session)) !== stamp)
          throw new Error("Request changed during assessment; no receipt committed");
        if (result.added > 0) store.save(session, result.receipts, previous.version);
        message = resultText(result);
      } catch (err) { message = String(err.message || err); }
      finally { busy.delete(session); }
      await toast(message);
      // Deliberate visible stop, not a fake assistant response or compaction.
      throw new Error("[Jev /prune completed without a model turn] " + message);
    },
  };
}
