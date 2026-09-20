# Security, privacy, and failure behavior

## Consent and data flow

Installation and `inspect` do not call TypeSafe. A native `/prune` assessment
requires `JEV_PRUNE_ALLOW_REMOTE=1` and `TYPESAFE_API_KEY` in the process launching
the harness. Selecting Compact never calls Jev. Assessment sends only a bounded
current goal and eligible repeated file-read arguments/results, not an exhaustive
transcript. The selected material can still contain private code, paths, business
information or secrets. A small set of common credential patterns is vetoed;
this is NOT a complete secret detector or redactor.

The service is pinned to HTTPS `api.typesafe.ai/v1/systemone` and model
`jev-1.13.0`. There is no configurable untrusted remote endpoint, automatic
redirect, or retry loop. API credentials stay in inherited environment variables;
they are not written to the installer manifest, command-line arguments, receipts
or logs. The operating system may still expose process environments to suitably
privileged users. Launch harnesses from a trusted, private account.

**The Python worker uses OS networking, not every harness's managed HTTP client.**
It cannot automatically enforce a harness-specific egress allowlist, residency,
provider retention agreement or tenant policy. Do not enable remote assessment
until the deployment's data and networking policies explicitly permit it. Proxy
and CA behavior follows Python/OS configuration. Do not disable certificate
verification to make it work. There is no live service or model-quality test in
this release.

## Bounds and deterministic controls

Only exact repeated result text from recognized read tools, with a later matching
request/result witness, can be selected. User, system, developer, assistant
messages and other tool types are never rewritten. Current user-turn and latest
16 message records are protected. Multimodal or ambiguous records, duplicate
identities, missing witnesses, unknown formats and unsupported goal content are
retained. The first release may free very little or nothing.

Maximums: 8 pairs per assessment; 8,000 UTF-8 bytes per text/goal;
24,000 bytes per TypeSafe request; 32,000 response bytes; 128 receipts;
8 MiB local adapter input/output. The TypeSafe transport is isolated in a child
with a 10-second wall deadline; the JS bridge allows 13 seconds for assessment
including process startup. These are configurable-in-code resource limits, not
promised performance. No high probability is a semantic safety guarantee.

Expected answer keys, answer type, model and finite probability range are checked.
Thresholds (coverage >= .99; unique/unresolved <= .01) are experimental. Receipts
store hashes and IDs, not raw context. Every projection rechecks both source and
retained witness. It cannot turn a stale receipt into permission to delete a
changed record. Unmatched proofs retain originals and may lose the prior savings.

## Local installation boundaries

No administrator privileges, vendor package upgrades, shell-profile changes,
credential files, token-limit settings, hook settings or transcript surgery.
Only explicitly owned paths are written. Existing foreign/edited files cause a
refusal. Destination symlinks are refused. Paths are JSON-encoded or passed as
argv, never interpolated into a shell command. Roots can be overridden per
profile and container. Generated wrappers depend on a persistent runtime, never
a temporary extraction directory. Profiles share immutable runtime code; proof
state is separately namespaced.

Installation preflights the whole plan, uses atomic per-file replacement and
backs up owned files before upgrading them. It attempts rollback on exceptions.
**It is not a crash-atomic transaction over every harness directory.** Stop all
harnesses before installing/upgrading/removing. After interruption, inspect the
manifest/doctor report rather than deleting a lock while a process is active.
Filesystem fsync and rename semantics vary by OS/filesystem. Unix new files are
private (0600), directories 0700; Windows permissions inherit the account's ACLs.
Use a private user-owned location. Do not claim universal power-loss durability.

Uninstall removes only unchanged owned files and preserves user edits, receipts,
backups and native plugin manager configuration. If an owned runtime/wrapper was
modified, required runtime files are retained for manual review. Hermes enable
list entries may remain after removal; its manager owns those. Uninstalling an
adapter stops its request projection and may increase subsequent context size.

## Non-goals in this release

No malicious-same-user isolation; extensions already execute as the user. No
protected multi-user Hermes gateway. No universal safe pause/resume, token-budget
reconciliation or opaque provider lineage handling. No automatic proof migration
across host forks. No promise of lower total cost: the Jev request, cache misses
and rework must be measured. The `gate.py` host contract is separate from these
experimental adapters, and does not establish native enforcement by itself.
