# Runtime support is not the same as installation coverage

Version: 0.1.0 — experimental. Documentation checked September 19, 2026.
No real harness session or live TypeSafe service was used to validate this build.

The installer targets OpenClaw, Hermes, OpenCode, Codex, Claude Code, Pi, Gemini
CLI, Cursor, GitHub Copilot CLI, and the shared Agent Skills directory. It does
not install the harness executables themselves.

| Target | Default install | With `--experimental-adapters` | Automatic choice |
|---|---|---|---|
| OpenClaw | `jev-prune` assessment skill | Same; no context-engine replacement | Not implemented |
| Hermes | Assessment skill | Native `/prune [session-id]`; projects repeated read results in supported chat-completions requests | Not implemented; native compression remains unchanged |
| OpenCode | Assessment skill | Native `/prune`; experimental request-message transform | Not implemented; compaction hooks do not provide a suitable complete choice protocol |
| Codex, including an unmodified codex-jev fork | Assessment skill under `.agents/skills` | Same; no Rust source patch in this kit | Not implemented |
| Claude Code | Assessment skill | Same; no automatic settings/hooks edits | Not implemented |
| Pi | Assessment skill | Native `/prune`; proof entries saved through Pi session API; non-destructive context transform | Optional `--pi-choice`: Prune/Compact/Pause for documented threshold/overflow events. Prune/Pause cancel compaction AND stop the current run. Explicit resume required. |
| Gemini CLI | Assessment skill | Same | Not implemented |
| Cursor | Assessment skill | Same | Not implemented |
| GitHub Copilot CLI | Assessment skill | Same | Not implemented |
| Shared `.agents` directory | Standard-format assessment skill | Same | Depends on an external host adapter, not provided |

## What is not finished

**No listed adapter implements the entire requested native scheduler contract.**
In particular, no adapter certifies a complete next-request token budget or
transparently resumes a paused task after pruning. The included `gate.py` gives
an executable, tested integration contract for a host that supplies those
capabilities. It is not automatically wired into Codex or other closed runtimes.

The experimental adapters reduce selected text in matching outgoing request
messages. The native transcript remains intact. Harness-internal token counters,
automatic compression thresholds, provider-side lineage, and compaction inputs
may still be based on the original history. A later native compaction can consume
original transcript material. This kit does not claim otherwise.

Only exact duplicate successful/read-only result bodies are eligible. Read tools
recognized by the current selector are `read`, `read_file`, and `file_read`.
OpenAI chat-completions messages lack a standardized success bit; those records
are also rejected on explicit failure flags and common error text. This is not
proof that every custom tool with one of those names is read-only. Do not use the
adapter with overridden tool semantics without reviewing the selector.

Retained content is not summarized. The selected duplicate body becomes a
bounded omission marker; the call/result envelopes and identities remain. A
later retained result must still match both text and request. If a proof ceases
to match, original content is retained, rather than silently deleting evidence.
Removing a plugin/uninstalling it also removes its projection: original content
can reappear and context pressure can increase.

## Host-specific qualifications

### Pi

Uses public extension registration, `context`, `session_before_compact`,
`ctx.ui.select`, and `pi.appendEntry`. The current docs distinguish `manual`,
`threshold`, and `overflow` compaction reasons. Manual `/compact` bypasses the
new chooser and never invokes Jev. Unknown reasons are not intercepted.

The optional chooser is explicitly a cancellation/stop adapter, NOT the native
resumable pause designed in the earlier specification. Pi may emit its own
cancelled-compaction lifecycle event. It does not emit a fabricated successful
summary. The adapter cannot promise one prompt across all subsequent retries or
across restarts. Known receipts restore from the active branch in the same
session. A fork with a different session ID does not inherit them: reassess.

Do not combine this extension with another extension registering `/prune`.
Existing `context`-transforming extensions or provider caches may interact with
its projections. Verify in a disposable session before enabling on real work.

### OpenCode

Uses the experimental messages-transform hook and mutates its shared array in
place. It registers `/prune` only when no config command already owns that name.
There is no documented successful host-only completion response for
`command.execute.before`; this prototype deliberately terminates that command
with a **visible command error after displaying its result**, preventing the
command template from starting a new model turn. This is a workaround, not a
polished production command API. It does not intercept native compaction.

Proofs are scoped to profile and session ID in a separate sidecar. Freshly resumed
sessions need a normal request before a new manual assessment is available.
Projection can run earlier from existing proofs. Other plugins, nested command
registries, and versions that do not fire experimental hooks need live testing.

### Hermes

The public slash handler receives only a raw argument string, not authenticated
requester/session context. The adapter therefore does nothing unless
`JEV_PRUNE_HERMES_SINGLE_USER=1` is set by the operator. **Never set this flag in
a shared/multi-user gateway.** With multiple captured sessions, an exact session
ID must be supplied; it never guesses the most recent one. `Hermes` here means
the Nous Research Hermes Agent.

The plugin must be enabled with the native plugin manager; the installer can
invoke it with `--activate-hermes`. It uses only public `register_middleware`
and `register_command` APIs. It supports request dictionaries containing
`messages`, not Responses-style `input`, previous-response chains or opaque
server-side conversation objects. Exceptions in Hermes middleware may be logged
and skipped by Hermes; this is not a security enforcement boundary or a
compaction veto. Its native compressor (`/compress` where applicable) is intact.

### Claude Code

Current docs say PreCompact can be blocked. That capability alone neither
provides live history replacement nor implements a recoverable task pause. This
kit intentionally does not edit `settings.json` or install a blocking hook that
pretends otherwise. The skill is assessment-only, normally `/jev-prune`.

### Codex

Current official docs specify `$HOME/.agents/skills` for user skills and explicit
invocation using `$jev-prune` or the skill selector, not an arbitrary native slash
command. `CODEX_HOME` is used for detection only. `--root codex=...` names the
`.agents` directory that your Codex process actually discovers; pointing it at an
authentication directory does not make that directory discoverable. Current
local skill location is shared by identities with the same OS HOME; use separate
HOME/container namespaces for actual isolation. This installer never changes
credentials, `config.toml`, AGENTS.md, or your fork source.

### OpenClaw

A real integrated solution must compose with its selected context engine and
native session lifecycle. The installer does not switch that engine or modify
plugin trust/allowlists. Skill visibility depends on the user's existing policy.

## Primary source reference map

- TypeSafe API: https://docs.typesafe.ai/api
- Pinned model list: https://docs.typesafe.ai/models
- Pi extensions: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md
- OpenCode plugins: https://opencode.ai/docs/plugins/
- OpenCode hook types: https://github.com/anomalyco/opencode/blob/dev/packages/plugin/src/index.ts
- Hermes plugins and middleware: https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/
- Hermes context engines: https://hermes-agent.nousresearch.com/docs/developer-guide/context-engine-plugin
- Claude hooks: https://code.claude.com/docs/en/hooks
- Claude skills: https://code.claude.com/docs/en/skills
- OpenClaw skills: https://docs.openclaw.ai/tools/skills
- OpenClaw engines: https://docs.openclaw.ai/plugins/architecture-internals/context-engines
- Codex skills: https://developers.openai.com/codex/build-skills
- Gemini skills: https://geminicli.com/docs/cli/skills/
- Cursor skills: https://cursor.com/docs/skills
- Copilot skills: https://docs.github.com/en/copilot/concepts/agents/about-agent-skills

The installer reports intended capabilities and file integrity, not a claim of
runtime API compatibility. Versions are not auto-downloaded or silently patched.
