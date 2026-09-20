# Contract for a complete native integration

`jev_prune/gate.py` is a tested state machine intended for a native host adapter,
not a hidden replacement for any vendor runtime.

A host must implement a consistent snapshot/proposal function; a revision covering
appends, pending input, model, policy and destructive edits; a durable atomic
compare-and-swap pruning commit; complete model-aware next-request and scoped
budget accounting; provider history/lineage rebasing; and a direct delegate to its
unchanged native compactor. Compaction events must describe real compaction only.
The host owns its authorization, pending task and safe scheduler boundary.

`Gate.begin(episode_id, original_trigger)` creates one waiting episode. The UI
chooses `Choice.PRUNE`, `Choice.COMPACT` or `Choice.PAUSE`. Choosing Compact calls
the original compactor without Jev. Choosing Prune proposes and commits a
validated projection, then uses the host budget to decide READY vs WAITING.
WAITING permits Compact or Pause, not another automatic prune pass. Failure is
never implicit consent to summarize. Missing/unknown budget cannot yield READY.
A stale episode closes and can be replaced by a new one. Old responses cannot
operate on a new revision. No UI response should be injected as an LLM message.

`manual_prune()` returns APPLIED, not READY: it must not launch an otherwise idle
agent. `manual_compact()` directly delegates with its existing behavior.
The host should add cancellation and serialized access around the state machine;
this Python example is synchronous and is not a concurrency lock by itself.

## Native implementation targets still required

- Codex fork: add a real command/protocol operation plus TUI/app-server choice;
  integrate upstream of local/remote auto-compaction dispatch; implement active
  projection persistence without clearing security review/authorization state;
  reconcile transport lineage and token counters. Do not install the earlier
  private-compactor-snapshot patch as though it implements this contract.
- Claude Code: public skill and PreCompact blocking alone do not expose all host
  responsibilities above. Do not modify live transcript files as a workaround.
- OpenClaw: compose with its selected context engine and session lifecycle,
  preserving the native compact command and audit/source transcript.
- Hermes/OpenCode/Pi: promote the request-only adapters to host-owned projection,
  complete accounting and scheduler transitions before claiming full behavior.

Required tests beyond the current package: native next-inference capture; no
compaction calls on successful prune; authoritative budgets; crash/replay/fork;
retained security evidence; pending tools and user input; cancellations and client
disconnect; every auto-trigger path including smaller-model switch and overflow;
server-side lineage/cache consistency; UI snapshots; shared policy enforcement.

No benchmark or semantic-retention improvement is established by passing the
local contract tests. Evaluate real task success and retained constraints as well
as bytes/tokens, cache effects, Jev cost, latency and compaction frequency.
