/** Experimental OpenCode manual projection adapter. No automatic compaction veto.
 * command.execute.before has no documented host-completed response: a deliberate
 * command error terminates /prune after displaying results, preventing a new LLM
 * turn. This is visible in the TUI. No /compact command is modified.
 */
import { rpc, ReceiptStore, messageStamp, resultText } from "./bridge.mjs";

export default async function createOpenCode(ctx, config, call = rpc) {
  const store = new ReceiptStore(config.stateDir, config.profile);
  const requests = new Map(), busy = new Set();
  let registered = false;
  const toast = async (message, variant = "info") => {
    try { await ctx.client.tui.showToast({ body: { title: "Jev prune", message, variant } }); } catch {}
  };
  return {
    config: async (cfg) => {
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
      if (!registered || input.command !== "prune") return;
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
