"""jev-bus v1 — cooperative context-transform chaining across independent packages.

This file is vendored BYTE-IDENTICALLY into every participating package. It imports
nothing but the standard library and nothing from its host package, so the copies can
be compared with sha256. Do not add package-relative imports.

The contract in one paragraph: for each host, exactly one package is the CARRIER and
owns the host's message-transform hook. Every other package registers a STAGE. The
carrier pipes the message list through the stages in priority order. Each stage declares
the message CLAIMS it may modify; two stages claiming overlapping classes on one host is
a hard failure, which is what makes double-registration structurally impossible rather
than merely discouraged.

A stage never approves anything. The bus moves messages and notes; every package keeps
its own approval path, its own file ownership and its own durable state.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any

SCHEMA = "jev-bus.v1"
STAGE_SCHEMA = "jev-bus.stage.v1"
MAX_REGISTRY_BYTES = 256_000
MAX_WIRE = 8 * 1024 * 1024
DEFAULT_STAGE_TIMEOUT_MS = 6_000
DEFAULT_CHAIN_TIMEOUT_MS = 20_000

# A closed vocabulary. A stage may only declare claims from this set; an unknown claim is
# refused rather than ignored, so a future claim class cannot silently overlap an old one.
CONCRETE_CLAIMS = frozenset({
    "tool-result:read",
    "assistant-prose",
    "system-append",
    "message-remove",
    "message-reorder",
})
WILDCARD_CLAIMS = frozenset({"tool-result:*"})
CLAIMS = CONCRETE_CLAIMS | WILDCARD_CLAIMS

# Hosts that expose an outgoing-request transform. Anything else can still carry MCP,
# skills and capture, but cannot host a chain, and the installers must not pretend it can.
TRANSFORM_HOSTS = ("pi", "opencode", "hermes")

# Which package should own each host's hook, by depth of its native integration. Rank, not
# install order, decides, so the two installers agree whichever runs first. Both vendored
# copies of this file carry the same table; changing it on one side only is a bug.
#
#   jev-prune-kit    pi       sole Pi adapter; the other package has no Pi support at all
#                    hermes   real llm_request middleware; the other only has shell hooks,
#                             which inject evidence and cannot remove a message
#                    opencode a v1-era message transform only
#   jev-context-fabric opencode implements both the V1 and V2 plugin APIs
CARRIER_RANKS = {
    "jev-prune-kit": {"pi": 100, "hermes": 100, "opencode": 10},
    "jev-context-fabric": {"opencode": 50},
}


def carrier_rank(package: str, host: str) -> int:
    return CARRIER_RANKS.get(package, {}).get(host, 0)


class BusError(ValueError):
    """The only error type safe to show a user; never contains context text."""


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def strict_json(raw: bytes | str) -> Any:
    def reject(pairs):
        seen = {}
        for key, item in pairs:
            if key in seen:
                raise BusError("Duplicate key in bus JSON")
            seen[key] = item
        return seen

    return json.loads(raw, object_pairs_hook=reject, parse_constant=_reject_constant)


def _reject_constant(name: str):
    raise BusError(f"Non-finite number in bus JSON: {name}")


def safe_path(path: Path) -> Path:
    resolved = Path(os.path.abspath(path))
    for candidate in [resolved, *resolved.parents]:
        if candidate.is_symlink():
            raise BusError(f"Symlinked bus path refused: {candidate}")
    return resolved


def atomic_write(path: Path, data: bytes) -> None:
    path = safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    handle = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


@contextlib.contextmanager
def file_lock(path: Path):
    """Exclusive-create lock. Not reentrant and it does not reap a stale file: take it once
    around a whole registry edit, never once per stage."""
    path = safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise BusError(
            "Another bus operation holds the lock; do not remove it while a process runs: " + str(path)
        ) from exc
    try:
        os.write(handle, str(os.getpid()).encode())
        yield
    finally:
        os.close(handle)
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


def bus_home() -> Path:
    return Path(os.environ.get("JEV_BUS_HOME", str(Path.home() / ".jev" / "bus"))).expanduser()


def registry_path(home: Path | None = None) -> Path:
    return safe_path((home or bus_home()) / "v1" / "registry.json")


# --------------------------------------------------------------------------- claims


def claims_overlap(left: str, right: str) -> bool:
    """Wildcards subsume their family; concrete claims collide only with themselves."""
    if left == right:
        return True
    for wide, narrow in ((left, right), (right, left)):
        if wide in WILDCARD_CLAIMS and narrow.startswith(wide[:-1]):
            return True
    return False


def validate_claims(claims: Any) -> list[str]:
    if not isinstance(claims, list) or not claims:
        raise BusError("A stage must declare at least one claim")
    out: list[str] = []
    for claim in claims:
        if not isinstance(claim, str) or claim not in CLAIMS:
            raise BusError(f"Unknown bus claim: {claim!r}")
        if claim in out:
            raise BusError(f"Duplicate claim: {claim}")
        out.append(claim)
    return sorted(out)


def stage_applies(stage: dict, host: str) -> bool:
    hosts = stage.get("hosts") or ["*"]
    return "*" in hosts or host in hosts


def assert_no_claim_conflict(stages: list[dict], host: str) -> None:
    """Raise if two DIFFERENT packages claim overlapping classes on one host."""
    active = [s for s in stages if stage_applies(s, host)]
    for i, first in enumerate(active):
        for second in active[i + 1:]:
            if first.get("package") == second.get("package"):
                continue
            for a in first.get("claims", []):
                for b in second.get("claims", []):
                    if claims_overlap(a, b):
                        raise BusError(
                            f"Bus claim conflict on {host}: {first['name']} claims {a!r} and "
                            f"{second['name']} claims {b!r}. Uninstall one, or give them "
                            f"disjoint claims; the bus will not order an ambiguous edit."
                        )


# --------------------------------------------------------------------------- registry


def empty_registry() -> dict:
    return {"schema": SCHEMA, "hosts": {}, "stages": []}


def validate_registry(value: Any) -> dict:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise BusError("Unrecognized bus registry schema")
    hosts = value.get("hosts")
    stages = value.get("stages")
    if not isinstance(hosts, dict) or not isinstance(stages, list):
        raise BusError("Bus registry must hold an object of hosts and a list of stages")
    seen: set[str] = set()
    for stage in stages:
        if not isinstance(stage, dict):
            raise BusError("Each bus stage must be an object")
        for key in ("name", "package"):
            if not isinstance(stage.get(key), str) or not stage[key].strip():
                raise BusError(f"Bus stage requires a nonempty {key}")
        if stage["name"] in seen:
            raise BusError(f"Duplicate bus stage name: {stage['name']}")
        seen.add(stage["name"])
        if not isinstance(stage.get("priority"), int) or isinstance(stage.get("priority"), bool):
            raise BusError("Bus stage priority must be an integer")
        stage["claims"] = validate_claims(stage.get("claims"))
        transport = stage.get("transport")
        if not isinstance(transport, dict) or transport.get("kind") != "subprocess-json":
            raise BusError("Bus stage transport must be subprocess-json")
        argv = transport.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            raise BusError("Bus stage transport requires a nonempty string argv")
    for host, record in hosts.items():
        if not isinstance(record, dict) or not isinstance(record.get("carrier"), str):
            raise BusError(f"Bus host {host} must record a carrier package")
    for host in hosts:
        assert_no_claim_conflict(stages, host)
    return value


def load(home: Path | None = None) -> dict:
    path = registry_path(home)
    if not path.exists():
        return empty_registry()
    if path.stat().st_size > MAX_REGISTRY_BYTES:
        raise BusError("Bus registry exceeds its size bound")
    return validate_registry(strict_json(path.read_bytes()))


def _write(registry: dict, home: Path | None = None) -> None:
    data = dumps(validate_registry(registry)).encode()
    if len(data) > MAX_REGISTRY_BYTES:
        raise BusError("Bus registry would exceed its size bound")
    atomic_write(registry_path(home), data)


def carrier_of(host: str, registry: dict | None = None, home: Path | None = None) -> str | None:
    reg = registry if registry is not None else load(home)
    record = reg["hosts"].get(host)
    return record.get("carrier") if isinstance(record, dict) else None


def stages_for(host: str, registry: dict | None = None, home: Path | None = None) -> list[dict]:
    reg = registry if registry is not None else load(home)
    assert_no_claim_conflict(reg["stages"], host)
    active = [s for s in reg["stages"] if stage_applies(s, host)]
    # Stable: priority first, then name, so an equal-priority pair never reorders per run.
    return sorted(active, key=lambda s: (s["priority"], s["name"]))


def register(
    package: str,
    stages: list[dict] | None = None,
    carriers: dict[str, dict] | None = None,
    *,
    home: Path | None = None,
    force_carrier: bool = False,
    dry_run: bool = False,
) -> dict:
    """Idempotently record one package's stages and carrier claims.

    Returns a report naming which carrier slots were taken, which were already held by
    another package (the caller must then install stage-only), and which were refused.
    With dry_run, compute the same report and write nothing, so an installer preview can
    state exactly which hooks it would own before touching a single file.
    """
    if dry_run:
        return _register(load(home), package, stages, carriers, force_carrier, None, False)
    lock = registry_path(home).with_suffix(".lock")
    with file_lock(lock):
        registry = load(home)
        return _register(registry, package, stages, carriers, force_carrier, home, True)


def _register(registry, package, stages, carriers, force_carrier, home, commit) -> dict:
    registry["stages"] = [s for s in registry["stages"] if s.get("package") != package]
    for stage in stages or []:
        entry = dict(stage)
        entry["package"] = package
        entry["claims"] = validate_claims(entry.get("claims"))
        registry["stages"].append(entry)

    report = {"package": package, "carrier_of": [], "deferred_to": {}, "took_over": {},
              "stages": [s["name"] for s in stages or []]}
    for host, record in (carriers or {}).items():
        if host not in TRANSFORM_HOSTS:
            raise BusError(f"{host} exposes no message-transform API; it cannot have a carrier")
        rank = record.get("rank")
        if not isinstance(rank, int) or isinstance(rank, bool):
            raise BusError(f"A carrier claim for {host} must declare an integer rank")
        held = registry["hosts"].get(host)
        holder = held.get("carrier") if isinstance(held, dict) else None
        held_rank = held.get("rank", 0) if isinstance(held, dict) else 0
        # Rank, not install order, decides the carrier: whichever package has the deeper
        # native integration for a host owns its hook however the two were installed.
        # Ties go to the incumbent, so a reinstall never flips a settled assignment.
        if holder and holder != package and not force_carrier and rank <= held_rank:
            report["deferred_to"][host] = holder
            continue
        if holder and holder != package:
            report["took_over"][host] = holder
        registry["hosts"][host] = {**record, "carrier": package, "rank": rank}
        report["carrier_of"].append(host)
    if commit:
        _write(registry, home)
    else:
        validate_registry(registry)  # a preview must still refuse a claim conflict
    return report


def unregister(package: str, *, home: Path | None = None) -> dict:
    """Remove one package's entries. A vacated carrier slot is left empty, never
    reassigned silently: the remaining package must reinstall to claim the hook."""
    path = registry_path(home)
    if not path.exists():
        return {"package": package, "removed_stages": [], "released": []}
    with file_lock(path.with_suffix(".lock")):
        registry = load(home)
        removed = [s["name"] for s in registry["stages"] if s.get("package") == package]
        registry["stages"] = [s for s in registry["stages"] if s.get("package") != package]
        released = [h for h, r in registry["hosts"].items() if isinstance(r, dict) and r.get("carrier") == package]
        for host in released:
            del registry["hosts"][host]
        if not registry["stages"] and not registry["hosts"]:
            path.unlink()
        else:
            _write(registry, home)
        return {"package": package, "removed_stages": removed, "released": released}


# ----------------------------------------------------------------------------- chain


def _invoke(stage: dict, request: dict, workspace: str, budget_ms: int) -> dict:
    transport = stage["transport"]
    argv = [a.replace("{workspace}", workspace) for a in transport["argv"]]
    timeout = min(int(transport.get("timeout_ms", DEFAULT_STAGE_TIMEOUT_MS)), max(budget_ms, 1)) / 1000
    body = dumps(request).encode()
    if len(body) > MAX_WIRE:
        raise BusError("Stage request exceeds the wire bound")
    completed = subprocess.run(
        argv,
        input=body,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,  # never surface a stage's local paths or provider text
        timeout=timeout,
        shell=False,
        cwd=transport.get("cwd") or None,
        check=False,
    )
    if completed.returncode != 0:
        raise BusError("Stage exited nonzero")
    if len(completed.stdout) > MAX_WIRE:
        raise BusError("Stage response exceeds the wire bound")
    return strict_json(completed.stdout)


def run_chain(
    host: str,
    messages: list,
    *,
    session: str,
    workspace: str = "",
    goal: str = "",
    api: str = "",
    op: str = "transform",
    accepts_system_append: bool = True,
    registry: dict | None = None,
    home: Path | None = None,
    chain_timeout_ms: int = DEFAULT_CHAIN_TIMEOUT_MS,
    invoke=_invoke,
) -> tuple[list, list[dict], list[str]]:
    """Pipe messages through every stage registered for this host, in priority order.

    Returns (messages, notes, system_appends).

    Fail-safe by construction: a stage that errors, times out, or returns a shape the bus
    does not recognize contributes NOTHING and the chain continues with that stage's own
    input. A transform is applied only when a stage returns a well-formed message list.
    """
    if op not in ("transform", "plan"):
        raise BusError("Bus op must be transform or plan")
    try:
        chain = stages_for(host, registry, home)
    except Exception as exc:  # noqa: BLE001
        # ANY reason the chain cannot be resolved -- a claim conflict, an unreadable or
        # malformed registry, even an environment with no resolvable home directory -- must
        # degrade to passthrough. The bus may decline to transform; it may never break the
        # host's turn.
        detail = str(exc) if isinstance(exc, BusError) else type(exc).__name__
        return messages, [{"stage": "jev-bus", "action": "chain-refused", "detail": detail}], []

    original = messages
    current = messages
    notes: list[dict] = []
    appends: list[str] = []
    remaining = chain_timeout_ms
    for stage in chain:
        if remaining <= 0:
            notes.append({"stage": stage["name"], "action": "skipped", "detail": "chain deadline exhausted"})
            continue
        request = {
            "schema": STAGE_SCHEMA,
            "op": op,
            "host": host,
            "api": api,
            "session": session,
            "workspace": workspace,
            "goal": goal,
            "accepts_system_append": bool(accepts_system_append),
            "messages": current,
            "original_messages": original,
            "notes": list(notes),
        }
        started = _now_ms()
        try:
            response = invoke(stage, request, workspace, remaining)
            if not isinstance(response, dict) or response.get("ok") is not True:
                raise BusError("Stage declined")
            produced = response.get("messages")
            if op == "transform":
                if not isinstance(produced, list):
                    raise BusError("Stage returned no message list")
                current = produced
                extra = response.get("system_append")
                if isinstance(extra, str) and extra:
                    appends.append(extra)
            for note in response.get("notes") or []:
                if isinstance(note, dict):
                    notes.append({**note, "stage": note.get("stage") or stage["name"]})
        except Exception as exc:  # noqa: BLE001 - a stage must never break the turn
            notes.append({
                "stage": stage["name"],
                "action": "passthrough",
                "detail": str(exc)[:200] if isinstance(exc, BusError) else type(exc).__name__,
            })
        remaining -= max(_now_ms() - started, 0)
    return current, notes, appends


def _now_ms() -> int:
    import time

    return int(time.monotonic() * 1000)


def read_stage_request(stream=None) -> dict:
    """Read one jev-bus.stage.v1 object from stdin. Used by each package's stage entry."""
    raw = (stream or sys.stdin.buffer).read(MAX_WIRE + 1)
    if len(raw) > MAX_WIRE:
        raise BusError("Stage request exceeds the wire bound")
    request = strict_json(raw)
    if not isinstance(request, dict) or request.get("schema") != STAGE_SCHEMA:
        raise BusError("Unsupported stage request schema")
    if request.get("op") not in ("transform", "plan"):
        raise BusError("Unsupported stage op")
    if not isinstance(request.get("messages"), list):
        raise BusError("Stage request requires a message list")
    return request
