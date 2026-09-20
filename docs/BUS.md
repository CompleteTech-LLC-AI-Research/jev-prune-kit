# jev-bus v1 — the shared context-transform contract

This file is **identical in `jev-context-fabric` and `jev-prune-kit`**. It specifies how two
independently installed packages transform the same message list without conflicting.

## The problem it solves

Both packages want to edit a host's outgoing request. Before jev-bus, both registered
OpenCode's `experimental.chat.messages.transform` and both tried to claim `/prune` through
mechanisms that could not see each other — one writing `commands/prune.md`, the other setting
`cfg.command.prune`. Two independent mutations of one array, in undefined order.

jev-bus replaces that with: **one carrier per host, many ordered stages.**

## Roles

| Role | Meaning |
|:--|:--|
| **Carrier** | The single package that registers the host's transform hook and owns `/prune` there. |
| **Stage** | A package that contributes an edit *inside* the carrier's chain. |

Every package is a stage everywhere it is installed. A package is additionally the carrier
wherever it holds the slot.

## Hosts that can carry a chain

`pi`, `opencode`, `hermes` — and no others.

This is a **host-API ceiling, not a package limitation.** OpenClaw, Codex, Claude Code,
Gemini CLI, Cursor and GitHub Copilot CLI expose no outgoing-request transform. Both packages
still install MCP, skills and capture there; neither can project. `register()` refuses a
carrier claim for any host outside this set rather than letting an installer imply otherwise.

## Carrier ranks

Rank, not install order, decides. Both vendored copies carry the same table, so the two
installers reach the same answer whichever runs first, and a tie keeps the incumbent so a
reinstall never flips a settled assignment.

| Package | Host | Rank | Why |
|:--|:--|--:|:--|
| `jev-prune-kit` | `pi` | 100 | Sole Pi adapter; the other package has no Pi support at all |
| `jev-prune-kit` | `hermes` | 100 | Real `llm_request` middleware; the other has only shell hooks, which inject evidence and cannot remove a message |
| `jev-prune-kit` | `opencode` | 10 | A v1-era message transform only |
| `jev-context-fabric` | `opencode` | 50 | Implements both the V1 and V2 plugin APIs |

Outcome: `opencode` → `jev-context-fabric`; `pi` and `hermes` → `jev-prune-kit`.

`--force-carrier` overrides rank and reports the package it displaced. `--no-bus` opts out
entirely and restores standalone 0.1.0 behaviour, conflicts included.

## Claims

A stage declares which message classes it may modify, from a closed vocabulary:

`tool-result:read` · `tool-result:*` · `assistant-prose` · `system-append` ·
`message-remove` · `message-reorder`

**Two different packages claiming overlapping classes on one host is a hard install
failure.** That is the structural guarantee: double-registration becomes impossible rather
than merely discouraged. A wildcard subsumes its family. An unknown claim is refused, never
ignored, so a future class cannot silently overlap an old one. One package may hold several
claims; only cross-package overlap is a conflict.

| Package | Claims | Effect |
|:--|:--|:--|
| `jev-prune-kit` | `tool-result:read` | Substitutes duplicate read bodies **in place** |
| `jev-context-fabric` | `assistant-prose`, `message-remove`, `system-append` | Removes approved prose; appends retrieved evidence |

Disjoint, so both run in one chain.

## Order is load-bearing

Priority 100 (dedup) runs before 200 (view). This is not cosmetic.

`jev-context-fabric` keys every message as `sha256([index, message])`, so identity depends on
array position. `jev-prune-kit` substitutes bodies **without changing the array length**,
while `jev-context-fabric` **removes** messages. Dedup must therefore run first: it cannot
shift the indices the other package keys on, and it only touches tool results, which that
package never excludes. Reverse the order and every downstream key would be invalidated.

Ties break by stage name, so an equal-priority pair never reorders between runs.

## Stage protocol

Single-shot JSON over stdio, one object in, one object out — the transport both packages
already used.

**Request**

```json
{ "schema": "jev-bus.stage.v1", "op": "transform" | "plan",
  "host": "opencode", "api": "v2", "session": "...", "workspace": "...", "goal": "...",
  "accepts_system_append": true,
  "messages": [...], "original_messages": [...], "notes": [...] }
```

**Response**

```json
{ "ok": true, "messages": [...], "system_append": "...",
  "notes": [{ "stage": "...", "action": "...", "count": 3, "bytes": 41822, "detail": "..." }] }
```

`original_messages` is the pristine pre-chain array. A stage that keys or fingerprints
messages must use it, not the possibly-mutated `messages`; otherwise an upstream edit re-keys
everything and stales every open plan.

`accepts_system_append` is false when the carrier has no system array in that hook, or
already injects evidence through a separate hook. A stage must then return no
`system_append` rather than smuggling the text into the message list.

## Fail-safety

**A stage may decline. It may never break the host's turn.**

A stage that errors, times out, exits nonzero, or returns an unrecognized shape contributes
nothing; the chain continues with *that stage's own input*. Any failure to resolve the chain
at all — a claim conflict, an unreadable or malformed registry, even an environment with no
resolvable home directory — degrades to passthrough with a `chain-refused` note.

**The bus is additive, never a prerequisite.** Every carrier keeps its standalone path: if
the chain contributed no stage of its own package, the carrier performs its original direct
transform exactly as it did before jev-bus existed. Installing the bus can subtract
capability from nobody.

## Registry

`~/.jev/bus/v1/registry.json`, overridable with `JEV_BUS_HOME`. Written under an
exclusive-create lock, atomically, refusing symlinked paths, bounded at 256 KB.

```json
{ "schema": "jev-bus.v1",
  "hosts": { "opencode": { "carrier": "jev-context-fabric", "rank": 50, "api": "v2" } },
  "stages": [
    { "name": "jev-prune.dedup@opencode:1a2b3c4d", "package": "jev-prune-kit",
      "priority": 100, "claims": ["tool-result:read"], "hosts": ["opencode"],
      "transport": { "kind": "subprocess-json", "argv": ["...", "--bus-stage", "..."] } }
  ] }
```

The registry is **additive metadata, never a file-ownership claim.** Each package keeps its
own manifest and owns only its own files: `install-receipt.json` for `jev-context-fabric`,
`manifest.json` for `jev-prune-kit`. Uninstalling removes only that package's entries, and a
vacated carrier slot is left **empty rather than reassigned** — the survivor must reinstall
to take the hook deliberately.

## Approval

**The bus approves nothing.** `op: "plan"` is a preview that never mutates the array. The
carrier renders a combined, package-attributed preview; approval stays in each package's own
CLI, with its own consent requirements:

```
/prune preview — session abc123
  jev-prune.dedup        3  duplicate read bodies       41.8 KB
  jev-context.view       7  assistant-prose messages    12.1 KB
approve:  jev-prune   assess        (needs JEV_PRUNE_ALLOW_REMOTE)
          jev-context prune-apply PLAN_ID --enable-native
```

Joining a chain never starts a paid call. `jev-prune-kit`'s stage runs only its local
`project`; remote assessment stays behind `/prune` plus explicit consent.

Native `/compact` is untouched by both packages, as before.

## Vendored file integrity

The contract is vendored, not depended on, because both packages advertise a zero-dependency
offline install. Both copies must stay byte-identical; each repository's test suite fails if
its copy drifts from these hashes.

| File | sha256 |
|:--|:--|
| `bus.py` | `514e59a2776ae1adbed5bbcf8e669d4fa15972877440a15cf8b00516bbfb87b7` |
| `bus.mjs` | `907758980cd5939a341eb9ab04bed183c1b928f19e5faad690508581f9882cf0` |

Located at `src/jev_context/bus.py` + `adapters/bus.mjs` in `jev-context-fabric`, and
`jev_prune/bus.py` + `adapters/bus.mjs` in `jev-prune-kit`. Changing the contract means
editing both packages and updating this table in both.

## What is still not true

- **Nothing here is live-host tested.** Every check in both repositories runs against mock
  hosts. A passing mock certifies the adapter's shape, not the host's behaviour.
- The bus adds one subprocess hop per stage. The carrier enforces a total chain deadline, so
  a slow stage degrades to passthrough rather than stalling a turn.
- Coordination does not create capability. Dedup still cannot project in a host with no
  transform API, and no measured token or task-quality result is claimed by either package.
