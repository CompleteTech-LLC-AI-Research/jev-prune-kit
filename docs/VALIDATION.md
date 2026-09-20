# Local validation report — Jev Prune Kit 0.1.0

Validation date: September 19, 2026 (America/New_York).
Execution environment: Linux; Python 3.13.5; Node.js 22.16.0.

## Executed successfully

| Check | Result |
|---|---|
| Python unittest suite | **73 tests passed**, no failures or skips |
| Node built-in test suite | **15 tests passed**, no failures or skips |
| Python source compilation | Passed for runtime, adapters, installer and examples |
| Node syntax checks | Passed for every `.mjs` adapter/bridge |
| Offline gate demo | Prune case returned READY with one simulated assessment and **zero simulated compaction calls** |
| Standalone inspector fixture | One eligible exact-repeat pair; **no remote call** |
| Self-contained installer smoke test | Passed in an isolated temporary HOME with spaces |

The standalone smoke run covered: a no-write preview; installation into all ten
target namespaces; wrappers pointing to a persistent runtime rather than the
temporary bootstrap directory; repeat installation producing unchanged actions;
all managed files passing integrity checks; execution of the installed Python
worker; and removal of unchanged managed files on uninstall. It did not start
any actual harness executable or activate a real Hermes installation.

## Coverage

The Python suite exercises exact-repeat selection, protected recent/current-turn
context, failed/multimodal/ambiguous records, secret-pattern vetoes, oversized
inputs, strict model/answer validation, missing API consent/key, session binding,
stale/missing proofs, receipt dependency checks, all three native formats, and
no-network inspection. Decision-gate tests cover direct native compaction,
manual prune, sufficient/insufficient/unknown budgets, failure without fallback,
pause, duplicate/stale choices, compare-and-swap failure and episode replacement.

Installer/storage tests cover ten targets, root environment overrides, explicit
profiles, current Codex skill location, idempotence, foreign-file conflicts,
modified files, upgrade backups, safe uninstall, preserved runtimes for modified
wrappers, symlink refusal, dry-run/doctor no-write behavior and receipt CAS.
Hermes tests use a stub plugin context and mocked Jev answers.

Node tests exercise the **real Python stdio worker** for offline inspection and
projection, plus stub-host Pi/OpenCode hook contracts. They verify native compact
pass-through without assessment, Pi stop/cancel behavior, manual receipt
persistence, changed-branch refusal, fork isolation, OpenCode in-place array
mutation, command collision protection, visible command completion stop, and
profile-separated receipt stores.

## Not validated

- Live TypeSafe API availability, response compatibility, accuracy or calibration.
- Actual Pi, Hermes, OpenCode, OpenClaw, Codex, Claude, Gemini, Cursor or Copilot
  sessions; plugin loading/version compatibility; UI behavior or native scheduler
  invariants in those applications.
- Windows/macOS execution, Windows ACLs or platform-specific config discovery.
- Full provider-token accounting, provider-side previous-response lineage, prompt
  cache behavior, task quality or measured dollar/token savings.
- End-to-end recovery after crash/power loss, every host fork/replay path, all
  automatic compaction paths or seamless user-choice pause/resume.
- Hermes native plugin-enable command on a real installation or multi-user gateway.

**88 passing local tests are not 88 live harness or model tests.** Assessment
responses are deterministic fixtures. This is an experimental source release,
not a claim that the full native specification is installed everywhere.

Raw logs are included at `tests-python.log` and `tests-node.log` in the source ZIP.
