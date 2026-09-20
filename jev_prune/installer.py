"""User-local installer. Default is a plan; --apply is required to write.

No shell-profile edits, credential writes, vendor source patches or changes to
native compaction settings. Only owned files may be upgraded/uninstalled.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from . import __version__
from .core import PruneError, dumps, strict_json
from .fsutil import atomic_write, file_lock, safe_path

PACKAGE = "jev-prune-kit"
TARGETS = ("openclaw", "hermes", "opencode", "codex", "claude", "pi", "gemini", "cursor", "copilot", "generic")
NATIVE = {"pi", "hermes", "opencode"}
BINS = {"openclaw": "openclaw", "hermes": "hermes", "opencode": "opencode", "codex": "codex",
        "claude": "claude", "pi": "pi", "gemini": "gemini", "cursor": "cursor", "copilot": "copilot"}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def root_paths(home: Path, env: dict[str, str]) -> dict[str, Path]:
    def get(name: str, fallback: Path) -> Path:
        value = env.get(name)
        return Path(value).expanduser().absolute() if value else fallback
    xdg = get("XDG_CONFIG_HOME", home / ".config")
    return {
        "openclaw": get("OPENCLAW_STATE_DIR", home / ".openclaw"),
        "hermes": get("HERMES_HOME", home / ".hermes"),
        "opencode": get("OPENCODE_CONFIG_DIR", xdg / "opencode"),
        # Current Codex docs specify ~/.agents/skills, not CODEX_HOME/skills.
        "codex": home / ".agents",
        "claude": get("CLAUDE_CONFIG_DIR", home / ".claude"),
        "pi": get("PI_CODING_AGENT_DIR", home / ".pi" / "agent"),
        "gemini": home / ".gemini", "cursor": home / ".cursor",
        "copilot": home / ".copilot", "generic": home / ".agents",
    }


def capability(name: str, experimental: bool, pi_choice: bool) -> dict:
    native = experimental and name in NATIVE
    return {
        "harness": name, "tier": "experimental-request-projection" if native else "assessment-skill-only",
        "native_prune_command": native,
        "automatic_choice": "Pi cancel/stop adapter; explicit resume required" if name == "pi" and native and pi_choice else False,
        "seamless_safe_resume": False,
        "host_budget_reconciliation": False,
        "provider_lineage_verified": False,
        "complete_native_spec": False,
        "native_compaction_modified": False,
        "activation": "requires hermes plugins enable jev-prune" if name == "hermes" and native else "host skill/plugin discovery; restart or reload",
        "requires_single_user_flag": name == "hermes" and native,
        "live_host_tested": False,
    }


@dataclass(frozen=True)
class Write:
    path: Path
    data: bytes
    kind: str


class Transaction:
    def __init__(self, data_home: Path):
        self.home = safe_path(data_home)
        self.manifest = self.home / "manifest.json"

    def records(self) -> dict:
        safe_path(self.manifest)
        if not self.manifest.exists():
            return {"schema": "jev-prune.install.v1", "files": {}, "targets": []}
        if self.manifest.stat().st_size > 4_000_000:
            raise PruneError("Installation manifest exceeds bound")
        value = strict_json(self.manifest.read_bytes())
        if not isinstance(value, dict) or value.get("schema") != "jev-prune.install.v1" or not isinstance(value.get("files"), dict):
            raise PruneError("Unsupported installation manifest")
        return value

    def validate(self, writes: list[Write], records: dict) -> list[dict]:
        actions, seen = [], {}
        for w in writes:
            path = safe_path(w.path)
            if path in seen:
                if seen[path] != w.data:
                    raise PruneError("Conflicting generated destinations: " + str(path))
                continue
            seen[path] = w.data
            known = records["files"].get(str(path))
            if path.exists():
                if not path.is_file():
                    raise PruneError("Destination is not a regular file: " + str(path))
                raw = path.read_bytes()
                # Do not adopt a pre-existing foreign file, even if bytes coincide.
                if not known or sha(raw) != known.get("sha256"):
                    raise PruneError("Refusing to replace an unowned or edited file: " + str(path))
                action = "unchanged" if raw == w.data else "upgrade"
            else:
                action = "create"
            actions.append({"path": str(path), "action": action, "kind": w.kind, "bytes": len(w.data)})
        return actions

    def apply(self, writes: list[Write], targets: list[dict]) -> dict:
        with file_lock(self.home / "install.lock"):
            records = self.records()
            actions = self.validate(writes, records)  # Whole plan preflight before any host writes.
            write_by_path = {str(safe_path(w.path)): w for w in writes}
            rollback: list[tuple[Path, bytes | None, str]] = []
            try:
                for action in actions:
                    path = Path(action["path"])
                    w = write_by_path[str(path)]
                    if action["action"] == "unchanged":
                        continue
                    old = path.read_bytes() if path.exists() else None
                    if old is not None:
                        backup = self.home / "backups" / (sha(str(path).encode()) + "-" + sha(old) + ".bak")
                        atomic_write(backup, old)
                    rollback.append((path, old, sha(w.data)))
                    atomic_write(path, w.data)
                    records["files"][str(path)] = {"sha256": sha(w.data), "kind": w.kind, "version": __version__}
                # Preserve other profiles recorded by earlier additive installations.
                merged = {(t["harness"], t["root"]): t for t in records.get("targets", [])}
                merged.update({(t["harness"], t["root"]): t for t in targets})
                records.update({"version": __version__, "targets": list(merged.values())})
                atomic_write(self.manifest, (dumps(records) + "\n").encode())
            except BaseException:
                # Best-effort rollback; do not clobber a file edited by another actor.
                for path, old, new_hash in reversed(rollback):
                    if path.exists() and sha(path.read_bytes()) == new_hash:
                        if old is None: path.unlink()
                        else: atomic_write(path, old)
                raise
            return {"actions": actions, "targets": records["targets"], "manifest": str(self.manifest)}

    def uninstall(self, apply: bool) -> dict:
        def run():
            records = self.records()
            actions, retained = [], {}
            preserve_runtime = any(
                meta.get("kind") in {"native-wrapper", "runtime"} and Path(name).is_file()
                and sha(safe_path(Path(name)).read_bytes()) != meta.get("sha256")
                for name, meta in records["files"].items()
            )
            for raw_path, meta in records["files"].items():
                path = safe_path(Path(raw_path))
                if not path.exists():
                    action = "already-absent"
                elif not path.is_file() or sha(path.read_bytes()) != meta.get("sha256"):
                    action = "preserve-user-modified"
                    retained[raw_path] = meta
                elif preserve_runtime and meta.get("kind") == "runtime":
                    action = "preserve-runtime-for-modified-files"
                    retained[raw_path] = meta
                else:
                    action = "remove-owned-file"
                    if apply: path.unlink()
                actions.append({"path": raw_path, "action": action})
            if apply:
                records["files"] = retained
                if not retained: records["targets"] = []
                atomic_write(self.manifest, (dumps(records) + "\n").encode())
            return {"actions": actions, "state_and_backups_preserved": True,
                    "note": "Native plugin enable-list entries are not rewritten; modified wrappers may remain. Projection stops when its plugin is unloaded."}
        if not apply: return run()
        with file_lock(self.home / "install.lock"): return run()

    def doctor(self) -> dict:
        records = self.records()
        files = []
        for name, record in records["files"].items():
            p = Path(name)
            try:
                safe_path(p)
                state = "missing" if not p.is_file() else "ok" if sha(p.read_bytes()) == record["sha256"] else "modified"
            except PruneError: state = "symlink-refused"
            files.append({"path": name, "integrity": state})
        return {"runtime_python": sys.executable, "files": files, "targets": records.get("targets", []),
                "live_runtime_verified": False, "remote_enabled": os.environ.get("JEV_PRUNE_ALLOW_REMOTE") == "1",
                "credential_present": bool(os.environ.get("TYPESAFE_API_KEY")),
                "note": "Integrity check only. Does not verify that a running harness loaded an adapter."}


def skill_text(runtime: Path, python: str) -> bytes:
    # Paths are presented as JSON argv, not unquoted executable shell fragments.
    inspect_args = json.dumps([python, str(runtime / "runner.py"), "inspect", "<explicit-snapshot.json>"])
    return f'''---
name: jev-prune
description: Explicitly inspect Jev pruning capabilities or assess an explicitly supplied native-message snapshot. Do not claim a skill can edit harness-held context.
disable-model-invocation: true
---
# Jev pruning capability and assessment tools

This skill is NOT a native /prune implementation. It cannot edit the harness's
hidden active context or intercept automatic compaction. Never tell the user that
forgetting text, summarizing it, or editing a session transcript equals pruning.

Read `{runtime / 'docs' / 'COMPATIBILITY.md'}` for the exact installed tiers.
For experimental Pi/OpenCode/Hermes, the separately installed native adapter owns
/prune. Report its actual result; do not implement a second prompt-based command.
Native /compact (or Hermes /compress) must retain its original meaning. A prune
request never grants consent to compaction.

For an explicitly supplied snapshot, invoke the local inspector using this argv:
`{inspect_args}`

Snapshot schema: {{"format":"pi|opencode|openai","session":"exact-session-id",
"messages":[native messages],"receipts":[]}}. Do not invent missing messages,
secret transcript locations, or an allegedly complete host snapshot.

Only after the user explicitly approves disclosure to TypeSafe may you change
`inspect` to `assess`. This also requires JEV_PRUNE_ALLOW_REMOTE=1 and
TYPESAFE_API_KEY in the launching process. Do not read, print, or store the key.
Assessment sends the current goal, selected file-read arguments and result bodies;
it returns a proposal, not a live context modification. Never label an exported
proposal as applied, and never invoke native compaction on failure.
'''.encode()


def build_plan(source: Path, data_home: Path, roots: list[tuple[str, Path]], experimental: bool, pi_choice: bool, python: str):
    runtime = data_home / "runtime"
    writes: list[Write] = []
    # Copy only source and documentation; no caches, env files, node_modules or credentials.
    for folder in ("jev_prune", "adapters", "docs"):
        for p in sorted((source / folder).rglob("*")):
            if p.is_file() and p.suffix in {".py", ".mjs", ".md", ".json"} and "__pycache__" not in p.parts and not p.name.startswith(".env"):
                writes.append(Write(runtime / p.relative_to(source), p.read_bytes(), "runtime"))
    writes.append(Write(runtime / "runner.py", (source / "runner.py").read_bytes(), "runtime"))
    targets = []
    stages: list[dict] = []
    for name, root in roots:
        root = safe_path(root)
        cap = capability(name, experimental, pi_choice)
        cap["root"] = str(root)
        targets.append(cap)
        writes.append(Write(root / "skills" / "jev-prune" / "SKILL.md", skill_text(runtime, python), "assessment-skill"))
        # OpenAI honors this explicit-invocation policy; other hosts may ignore it.
        writes.append(Write(root / "skills" / "jev-prune" / "agents" / "openai.yaml",
                            b'policy:\n  allow_implicit_invocation: false\n', "skill-policy"))
        if not experimental or name not in NATIVE:
            continue
        profile = sha((name + "\0" + str(root)).encode())
        config = {"python": python, "runner": str(runtime / "runner.py"), "profile": profile,
                  "format": {"pi": "pi", "opencode": "opencode", "hermes": "openai"}[name],
                  "stateDir": str(data_home / "state" / profile), "autoChoice": name == "pi" and pi_choice}
        stages.append({
            # One stage per (host, root): the profile and state directory are the same ones
            # the native wrapper uses, so a carrier in another package reads exactly the
            # receipts this package approved. Claims only `tool-result:read`, and the
            # projection substitutes bodies in place without changing the array length,
            # which is what lets a downstream stage keep keying messages by position.
            "name": f"jev-prune.dedup@{name}:{profile[:8]}",
            "priority": 100,
            "claims": ["tool-result:read"],
            "hosts": [name],
            "transport": {"kind": "subprocess-json", "argv": [
                python, str(runtime / "runner.py"), "--bus-stage",
                "--state-dir", config["stateDir"], "--profile", profile,
                "--format", config["format"]]},
        })
        if name == "pi":
            text = f'import create from {json.dumps((runtime / "adapters/pi.mjs").as_uri())};\nexport default function(pi) {{ return create(pi, {json.dumps(config)}); }}\n'
            writes.append(Write(root / "extensions" / "jev-prune.ts", text.encode(), "native-wrapper"))
        if name == "opencode":
            text = f'import create from {json.dumps((runtime / "adapters/opencode.mjs").as_uri())};\nexport const JevPrune = async (ctx) => create(ctx, {json.dumps(config)});\n'
            writes.append(Write(root / "plugins" / "jev-prune.ts", text.encode(), "native-wrapper"))
        if name == "hermes":
            text = f'''import importlib.util
import sys
sys.path.insert(0, {str(runtime)!r})
_spec = importlib.util.spec_from_file_location("_jev_prune_hermes_adapter", {str(runtime / "adapters/hermes.py")!r})
_adapter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_adapter)
def register(ctx):
    return _adapter.register(ctx, {config!r})
'''
            writes.append(Write(root / "plugins" / "jev-prune" / "__init__.py", text.encode(), "native-wrapper"))
            writes.append(Write(root / "plugins" / "jev-prune" / "plugin.yaml", f'name: jev-prune\nversion: {__version__}\ndescription: Experimental single-user request projection; native compression unchanged\n'.encode(), "native-manifest"))
    return writes, targets, stages


def activate_hermes(targets: list[dict]) -> list[dict]:
    # Separate opt-in: Hermes's own CLI owns its enable-list and validation.
    exe = shutil.which("hermes")
    out = []
    for target in targets:
        if target["harness"] != "hermes" or not target["native_prune_command"]:
            continue
        if not exe:
            out.append({"root": target["root"], "enabled": False, "reason": "hermes executable not found"})
            continue
        env = {**os.environ, "HERMES_HOME": target["root"]}
        try:
            result = subprocess.run([exe, "plugins", "enable", "jev-prune"], env=env,
                                    capture_output=True, timeout=30, check=False)
            out.append({"root": target["root"], "enabled": result.returncode == 0, "exit_code": result.returncode})
        except (OSError, subprocess.TimeoutExpired):
            out.append({"root": target["root"], "enabled": False, "reason": "activation failed or timed out; inspect native CLI"})
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="Install Jev tools per harness. Default: plan only; runtime support is capability-specific.")
    parser.add_argument("--all", action="store_true", help="Install into every supported default root, including absent harnesses; creates no vendor executables")
    parser.add_argument("--target", action="append", choices=TARGETS, default=[])
    parser.add_argument("--root", action="append", default=[], metavar="HARNESS=PATH", help="Repeat for profile roots. Codex root means .agents directory, not CODEX_HOME")
    parser.add_argument("--home", type=Path, default=Path.home(), help="Base for default roots (useful for image builds/tests)")
    parser.add_argument("--data-home", type=Path, help="Persistent runtime/manifest/state location")
    parser.add_argument("--apply", action="store_true", help="Perform writes; otherwise print plan")
    parser.add_argument("--experimental-adapters", action="store_true", help="Install Pi, OpenCode and Hermes request-projection plugins as well as skills")
    parser.add_argument("--pi-choice", action="store_true", help="Experimental Pi auto-compaction choice. Stops current run on Prune/Pause; explicit resume required")
    parser.add_argument("--activate-hermes", action="store_true", help="After installation, invoke Hermes's native plugin-enable command")
    parser.add_argument("--doctor", action="store_true", help="Read-only installed-file integrity and capability report")
    parser.add_argument("--uninstall", action="store_true", help="Remove unchanged owned files only; keep receipts/backups")
    parser.add_argument("--no-bus", action="store_true", help="Do not participate in jev-bus; own every hook this package supports, as in 0.1.0")
    parser.add_argument("--force-carrier", action="store_true", help="Take a host's transform hook even if another jev-bus package currently carries it")
    args = parser.parse_args(argv)
    try:
        if sys.version_info < (3, 10):
            raise PruneError("Python 3.10 or newer required")
        if args.pi_choice and not args.experimental_adapters:
            raise PruneError("--pi-choice requires --experimental-adapters")
        if args.activate_hermes and (not args.apply or not args.experimental_adapters):
            raise PruneError("--activate-hermes requires --apply and --experimental-adapters")
        home = safe_path(args.home.expanduser().absolute())
        data_home = safe_path((args.data_home or home / ".jev-prune").expanduser().absolute())
        tx = Transaction(data_home)
        if args.doctor:
            print(json.dumps(tx.doctor(), indent=2)); return 0
        if args.uninstall:
            result = tx.uninstall(args.apply)
            if args.apply and not args.no_bus:
                from . import bus
                # A vacated carrier slot is left empty rather than handed to whoever is
                # left: the remaining package must reinstall to take the hook deliberately.
                try: result["jev_bus"] = bus.unregister(PACKAGE)
                except bus.BusError as exc: result["jev_bus"] = {"error": str(exc)}
            print(json.dumps(result, indent=2)); return 0
        defaults = root_paths(home, dict(os.environ))
        roots: list[tuple[str, Path]] = []
        explicit_names = set()
        for value in args.root:
            name, sep, raw = value.partition("=")
            if not sep or name not in TARGETS or not raw:
                raise PruneError("Invalid --root; use HARNESS=PATH with a supported harness")
            roots.append((name, Path(raw).expanduser().absolute()))
            explicit_names.add(name)
        requested = set(TARGETS if args.all else args.target)
        if not requested and not roots:
            requested = {name for name, root in defaults.items() if root.exists() or (name in BINS and shutil.which(BINS[name]))}
            if Path(os.environ.get("CODEX_HOME", str(home / ".codex"))).exists(): requested.add("codex")
        roots.extend((name, defaults[name]) for name in TARGETS if name in requested and name not in explicit_names)
        roots = list(dict.fromkeys(roots))
        if not roots:
            print(json.dumps({"actions": [], "note": "No detected harness roots. Use --all, --target, or --root explicitly."}, indent=2)); return 0
        prior_targets = tx.records().get("targets", [])
        if not args.experimental_adapters:
            for name, root in roots:
                if any(t["harness"] == name and t["root"] == str(safe_path(root))
                       and t.get("native_prune_command") for t in prior_targets):
                    raise PruneError("Existing native adapter: repeat --experimental-adapters when updating, or uninstall before downgrading")
        source = Path(__file__).resolve().parents[1]
        writes, targets, stages = build_plan(source, data_home, roots, args.experimental_adapters, args.pi_choice, sys.executable)
        bus_report = None
        if not args.no_bus and stages:
            from . import bus
            carriers = {name: {"rank": bus.carrier_rank(PACKAGE, name), "root": str(safe_path(root))}
                        for name, root in roots if name in bus.TRANSFORM_HOSTS}
            bus_report = bus.register(PACKAGE, stages, carriers,
                                      force_carrier=args.force_carrier, dry_run=not args.apply)
        if args.apply:
            report = tx.apply(writes, targets)
            if bus_report is not None:
                report["jev_bus"] = bus_report
                for host, holder in bus_report["deferred_to"].items():
                    report.setdefault("notes", []).append(
                        f"jev-bus: {holder} carries {host}; this package runs as a stage in that carrier's chain "
                        f"and registers no competing transform or /prune there.")
                for host, previous in bus_report["took_over"].items():
                    # Its stage entry is already in the registry, and its adapter reads the
                    # carrier at load time, so a host restart is all that is needed.
                    report.setdefault("notes", []).append(
                        f"jev-bus: took the {host} carrier slot from {previous}, which ranks lower there. "
                        f"Restart {host} so that package's adapter re-reads the registry and steps down to a stage.")
            if args.activate_hermes: report["hermes_activation"] = activate_hermes(targets)
        else:
            report = {"actions": tx.validate(writes, tx.records()), "targets": targets}
            if bus_report is not None: report["jev_bus"] = bus_report
        report.update({"applied": args.apply, "remote_called": False,
                       "warning": "No universal native pruning/choice guarantee. Read each target's capabilities. Native adapters are not live-host tested."})
        print(json.dumps(report, indent=2))
        return 0
    except (PruneError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
