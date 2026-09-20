<div align="center">

# Jev Prune Kit

**Drop the duplicate file-read, keep the evidence.**

A stdlib-only installer, a bounded TypeSafe/Jev assessment engine, three
experimental request-projection adapters, and a reusable native decision-gate
contract for agent harnesses.

`v0.1.0` · `Python ≥ 3.10` · `zero dependencies` · `offline install` · **experimental**

</div>

---

## What this is

Long agent sessions re-read the same file over and over. Each identical result
body is paid for again on every subsequent request. This kit finds those exact
repeats, asks a pinned evaluator whether the older copy can be omitted, and — in
the three harnesses with a native adapter — leaves the older body out of
*outgoing requests only*, replacing it with a one-line marker that names the
retained copy.

```
  native transcript  ──  never edited, never scanned automatically
          │
          ▼
    snapshot()        normalize one explicitly supplied `pi` | `opencode` |
          │           `openai` message list; reject anything ambiguous
          ▼
   candidates()       an older read result whose text AND request arguments
          │           exactly match a later retained one — outside the last
          │           16 messages and the current user turn
          ▼
     prepare()  ───▶  TypeSafe  jev-1.13.0  ───▶  validate_answers()
          │           coverage ≥ .99 · unique ≤ .01 · unresolved ≤ .01
          ▼
     receipts         { session, format, source proof, witness proof }
          │           SHA-256 hashes and native IDs only — never context text
          ▼
      project()       a copy of the outgoing messages, with that one duplicated
                      body replaced by an omission marker. Re-verified from
                      scratch every time; a stale proof retains the original.
```

Nothing is summarized. Call and result envelopes, identities, and every other
role stay byte-identical.

## What this is not

- **Not a universal `/prune`.** Seven of the ten install targets receive an
  assessment *skill* only. A skill cannot edit harness-held context.
- **Not a replacement for `/compact`.** Native compaction keeps its original
  meaning everywhere. Choosing Compact makes zero Jev calls.
- **Not token accounting.** Projection removes result-body *bytes*. Host token
  counters, compaction thresholds and provider-side lineage may still be based
  on the original history.
- **Not live-tested.** No real harness session and no live TypeSafe service were
  used to validate this build. See [VALIDATION.md](docs/VALIDATION.md).
- **Not installed by receiving it.** Nothing is written until `--apply`.

Read [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md) before enabling native adapters.

## Requirements

Python 3.10+ in a persistent location. The Pi and OpenCode adapters use only
Node built-ins supplied by the host — no npm, no pip. Developed and tested on
Linux with Python 3.13.5 and Node 22.16.0; Windows and macOS execution are
untested. No harness executable is bundled or installed.

## Install

Stop running harness sessions first, then extract this directory anywhere.
The default action is a **plan** — no writes, no network:

```powershell
py -3 .\install.py --all --experimental-adapters --pi-choice
```

Add `--apply` to write. This installs the assessment skill into all ten
namespaces and the experimental native plugins into Pi, OpenCode and Hermes:

```powershell
py -3 .\install.py --all --apply --experimental-adapters --pi-choice --activate-hermes
```

On macOS/Linux substitute `python3 ./install.py`. The wrappers `install.sh` and
`install.ps1` forward to the same script.

| Flag | Effect |
|---|---|
| *(none)* | Print the plan. Nothing is written. |
| `--apply` | Perform the preflighted writes. |
| `--all` | Target all ten default roots, even for absent harnesses. Installs no vendor binaries. |
| `--target NAME` | Repeatable. Explicit target selection. |
| `--root NAME=PATH` | Repeatable. Separate profile namespaces. |
| `--experimental-adapters` | Also install the Pi, OpenCode and Hermes native plugins. |
| `--pi-choice` | Pi's Prune/Compact/Pause chooser on threshold and overflow events. Requires the adapters flag. |
| `--activate-hermes` | Run Hermes's own `plugins enable` afterwards. Requires `--apply`. |
| `--home` / `--data-home` | Base for default roots / persistent runtime, manifest and state. |
| `--doctor` | Read-only integrity and capability report. |
| `--uninstall` | Remove unchanged owned files only. |

Omitting `--experimental-adapters`, `--pi-choice` and `--activate-hermes` gives a
skills-only installation, which cannot perform live pruning. An existing native
installation will not silently downgrade to skill-only — uninstall first.

### Self-contained installer

The separately supplied `install_jev_prune.py` embeds this runtime and its docs.
It verifies the embedded payload's SHA-256, extracts safely to a temporary
directory, and copies a persistent runtime before writing any wrapper. It never
downloads or executes an unpinned remote script, and its flags match
`install.py`. The checksum detects corruption; it is not a publisher signature
and not a substitute for reading the source. Regenerate it with
`python3 build_release.py`.

## Coverage

| Target | Default install | With `--experimental-adapters` |
|---|---|---|
| **Pi** | assessment skill | native `/prune`, context transform, optional Prune/Compact/Pause chooser |
| **OpenCode** | assessment skill | native `/prune`, experimental message transform |
| **Hermes** | assessment skill | native `/prune [session-id]`, single-user request middleware |
| OpenClaw, Codex, Claude Code, Gemini CLI, Cursor, GitHub Copilot CLI, shared `.agents` | assessment skill | unchanged — no source patch, no settings or hook edits |

No adapter implements the complete native scheduler contract: none certifies a
next-request token budget or transparently resumes a paused task.
[`jev_prune/gate.py`](jev_prune/gate.py) is the executable, tested contract for a
host that can supply those capabilities — see
[docs/NATIVE_CONTRACT.md](docs/NATIVE_CONTRACT.md). The full matrix and every
per-host qualification live in [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).

## Inside the harness

- **Pi** — `/prune` on an idle boundary, after at least one ordinary request.
  `/reload` picks up new extensions. With the optional chooser, Compact passes
  through untouched; Prune and Pause cancel compaction *and stop the current
  run*, requiring an explicit resume. Not a seamless continuation.
- **OpenCode** — restart, then `/prune` once a request has been captured. The
  command deliberately ends with a **visible command-result error** after
  printing its result, so that no new model turn starts. Automatic compaction is
  not intercepted.
- **Hermes** — enable, restart, then `/prune` in an explicitly opted-in
  single-user process. Supply an exact session ID when several are captured.
  Native compression is unchanged.
- **Everything else** — invoke the `jev-prune` skill through the host's skill
  selector (Codex `$jev-prune`; Claude commonly `/jev-prune`). It reports real
  capabilities and can inspect a snapshot you supply explicitly. It is not
  `/prune`, and it does not touch hidden context.

After a manual prune, proof receipts decide which matching outgoing bodies are
omitted. The original transcript is preserved, no native compacted checkpoint is
created, and existing host token counters may still trigger native compaction.

## Enabling remote assessment

Copy `.env.example` to `.env` beside `runner.py` and fill in `TYPESAFE_API_KEY`.
Set `JEV_PRUNE_ALLOW_REMOTE=1` only after reviewing [SECURITY.md](docs/SECURITY.md).
Local `.env` files are ignored by Git.

Assessment reads the runtime-root `.env`, not the current directory or parents.
For installed adapters, set `JEV_PRUNE_ENV_FILE` to the absolute path of your
private `.env` before launching the harness; installation does not copy it.
Process variables override file values, including empty values. Only the key and
remote-consent setting are loaded. Syntax: one `NAME=value` per line, optional
matching single/double quotes, optional `export`, and whole-line `#` comments.
Values are literal: no interpolation, escapes, multiline values, or inline
comments. Inspection, projection, and installation do not load this file.

Installation and `inspect` never call TypeSafe. Remote assessment stays off
until you turn it on, deliberately, in the terminal that launches the harness —
after reading [docs/SECURITY.md](docs/SECURITY.md).

```powershell
$env:JEV_PRUNE_ALLOW_REMOTE = '1'
# TYPESAFE_API_KEY must already be supplied securely in this process.

# Hermes only: a local single-user process, NEVER a shared gateway.
$env:JEV_PRUNE_HERMES_SINGLE_USER = '1'
```

```sh
export JEV_PRUNE_ALLOW_REMOTE=1
# TYPESAFE_API_KEY comes from your secret manager / launch environment.
export JEV_PRUNE_HERMES_SINGLE_USER=1  # only for a local single-user Hermes
```

Supply the key through your usual secret-management mechanism rather than
hardcoding it. The service is pinned to HTTPS `api.typesafe.ai/v1/systemone` and
model `jev-1.13.0`: no configurable endpoint, no redirects, no retry loop.
Assessment sends the current goal plus the selected read arguments and result
bodies — not an exhaustive transcript. That material can still contain private
code, paths or secrets; the credential-pattern check is a veto, **not** a
complete redactor. Python networking does not inherit a host's managed egress or
residency policy. Do not enable it in a restricted environment without approval.

### Bounds

| | |
|---|---|
| Candidate pairs per assessment | 8 |
| Bytes per result body or goal | 8,000 |
| TypeSafe request / response | 24,000 / 32,000 bytes |
| Receipts per session | 128 |
| Local adapter input / output | 8 MiB |
| Protected tail | current user turn + last 16 records |
| Eligible tools | `read`, `read_file`, `file_read` |
| Deadlines | 10 s transport child process, 13 s JS bridge assessment |

These are in-code resource limits, not performance promises, and no probability
threshold is a semantic safety guarantee.

## Profiles and containers

The persistent runtime defaults to `~/.jev-prune/runtime`; override with
`--data-home`. Repeated `--root` selects separate namespaces without touching
credentials:

```powershell
py -3 .\install.py --apply --experimental-adapters `
  --root 'claude=C:\Users\Tim\claude-personal' `
  --root 'claude=C:\Users\Tim\claude-work' `
  --root 'hermes=C:\Users\Tim\hermes-local' `
  --root 'opencode=C:\Users\Tim\.config\opencode'
```

Launch each harness with its matching config-home setting. Root discovery honors
`CLAUDE_CONFIG_DIR`, `HERMES_HOME`, `OPENCLAW_STATE_DIR`, `OPENCODE_CONFIG_DIR`,
`PI_CODING_AGENT_DIR` and `XDG_CONFIG_HOME`. `CODEX_HOME` detects an
installation, but current Codex user skills live at `HOME/.agents/skills` — an
explicit Codex root names that `.agents` namespace, not an auth or config
directory. Use separate OS HOMEs or containers for distinct global Codex skill
visibility.

Inside a container, run the installer *in that container* with its persistent
user-home volume mounted
(`--home /home/agent --data-home /home/agent/.jev-prune`). No root needed. Never
copy a Windows-generated wrapper into Linux: the embedded runtime and
interpreter paths are absolute. Symlinked destinations are refused.

## Inspect, and uninstall

```powershell
py -3 .\install.py --doctor
py -3 .\install.py --uninstall                  # preview
py -3 .\install.py --uninstall --apply          # remove unchanged owned files
```

Doctor verifies file hashes and reports *intended* capabilities — it cannot
confirm that a running harness actually loaded an adapter. Uninstall preserves
modified files, receipts, backups and native plugin-manager configuration;
remove an obsolete Hermes enable-list entry with Hermes's own manager. Removing
a projection adapter makes the original context visible again, which can
increase context pressure. Stop and restart harnesses around these operations.

## Standalone use

```sh
python3 runner.py inspect examples/pi-snapshot.json
# Only after remote consent and credentials are configured:
python3 runner.py assess examples/pi-snapshot.json
```

The example is fabricated test data. `inspect` performs no model call. `assess`
returns a hash-bound proposal; it does not apply anything to a live harness. The
core recognizes only explicitly supported native message formats — it never
guesses a transcript layout and never scans host session directories.

A snapshot is `{"format": "pi"|"opencode"|"openai", "session": "<exact-id>",
"messages": [...], "receipts": []}`.

## Tests

```sh
python3 -m unittest discover -s tests -v      # 73 tests
node --test tests/native.test.mjs             # 15 tests, drives the real worker
python3 examples/gate_demo.py --choice prune  # offline host-contract demo
```

Set `PYTHON_BINARY` if `python3` is not the interpreter the Node suite should
spawn. Raw logs from the reference run are in `tests-python.log` and
`tests-node.log`. **88 passing local tests are not 88 live harness or model
tests** — evaluator responses are deterministic fixtures, not measured accuracy
or savings. [VALIDATION.md](docs/VALIDATION.md) lists exactly what was and was
not exercised.

## Repository map

| Path | Role |
|---|---|
| `jev_prune/core.py` | Snapshot normalization, conservative selection, receipt validation, projection |
| `jev_prune/client.py` | Bounded TypeSafe transport, isolated in a child process |
| `jev_prune/worker.py` | JSON-over-stdio `assess` / `project` / `inspect` protocol |
| `jev_prune/gate.py` | Host decision-state contract: Prune, Compact, Pause |
| `jev_prune/installer.py` | Root detection, plans, backups, ownership, doctor, removal |
| `jev_prune/fsutil.py` | Symlink refusal, atomic writes, locks, receipt store |
| `adapters/` | `pi.mjs`, `opencode.mjs`, `hermes.py` and the shared `bridge.mjs` |
| `docs/` | [Compatibility](docs/COMPATIBILITY.md) · [Security](docs/SECURITY.md) · [Validation](docs/VALIDATION.md) · [Native contract](docs/NATIVE_CONTRACT.md) |
| `build_release.py` | Reproducible self-contained installer and source ZIP |

There is no MCP server in this kit. An MCP assessment tool alone would not grant
context-editing authority.
