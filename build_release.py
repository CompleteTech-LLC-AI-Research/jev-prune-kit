"""Reproducibly bundle local source into a self-contained installer and source ZIP."""
from pathlib import Path
import base64
import hashlib
import io
import textwrap
import zipfile

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent


def packed(files):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel, raw in sorted(files):
            info = zipfile.ZipInfo(rel, (2026, 9, 19, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, raw)
    return data.getvalue()

payload_files=[]
for directory in ("jev_prune", "adapters", "docs"):
    for p in (ROOT/directory).rglob("*"):
        if p.is_file() and p.suffix in {".py", ".mjs", ".md", ".json"} and "__pycache__" not in p.parts:
            payload_files.append((p.relative_to(ROOT).as_posix(), p.read_bytes()))
for name in ("install.py", "runner.py"):
    payload_files.append((name,(ROOT/name).read_bytes()))
payload=packed(payload_files)
checksum=hashlib.sha256(payload).hexdigest()
encoded="\n".join(textwrap.wrap(base64.b64encode(payload).decode(),100))
header='''#!/usr/bin/env python3
"""Jev Prune Kit 0.1.0 — self-contained, offline, capability-aware installer.

Default action is a plan. Examples:
  python install_jev_prune.py --all
  python install_jev_prune.py --all --apply --experimental-adapters --pi-choice
  python install_jev_prune.py --doctor
  python install_jev_prune.py --uninstall --apply

Skills alone do NOT prune live harness context. Experimental native plugins:
Pi, OpenCode and Hermes, with explicit limitations. No full universal native
Prune/Compact/Pause implementation. No API keys or remote calls at installation.
Review the accompanying source ZIP and runtime/docs/COMPATIBILITY.md.
"""
import base64
import hashlib
import io
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import tempfile
import zipfile

'''
body='''
def main():
    if sys.version_info < (3, 10):
        print("Python 3.10 or newer is required", file=sys.stderr)
        return 1
    try:
        raw = base64.b64decode(PAYLOAD)
        if hashlib.sha256(raw).hexdigest() != SHA256:
            raise ValueError("Embedded payload checksum mismatch")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive, tempfile.TemporaryDirectory(prefix="jev-prune-installer-") as tmp:
            entries = archive.infolist()
            if len(entries) > 256 or sum(i.file_size for i in entries) > 2_000_000:
                raise ValueError("Embedded payload exceeds extraction bound")
            seen = set()
            for entry in entries:
                path = PurePosixPath(entry.filename)
                if (path.is_absolute() or ".." in path.parts or "\\\\" in entry.filename
                    or ":" in entry.filename or entry.filename in seen
                    or stat.S_ISLNK(entry.external_attr >> 16)):
                    raise ValueError("Unsafe embedded archive entry")
                seen.add(entry.filename)
                target = Path(tmp).joinpath(*path.parts)
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(entry))
            # Wrappers target the persistent installed runtime, not this temp copy.
            return subprocess.run([sys.executable, str(Path(tmp)/"install.py"), *sys.argv[1:]], check=False).returncode
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print("Installer failed: " + str(exc), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
'''
(OUT/"install_jev_prune.py").write_text(header+'SHA256 = '+repr(checksum)+'\nPAYLOAD = """\n'+encoded+'\n"""\n'+body)

source_files=[]
for p in ROOT.rglob("*"):
    if not p.is_file() or "__pycache__" in p.parts or p.name in {"tests-initial.log", "tests-second.log"}:
        continue
    if p.suffix in {".py", ".mjs", ".md", ".json", ".toml", ".ps1", ".sh", ".log"}:
        source_files.append(("jev-prune-kit/"+p.relative_to(ROOT).as_posix(),p.read_bytes()))
(OUT/"jev-prune-kit.zip").write_bytes(packed(source_files))
checks=[]
for name in ("install_jev_prune.py", "jev-prune-kit.zip"):
    checks.append(hashlib.sha256((OUT/name).read_bytes()).hexdigest()+"  "+name)
(OUT/"jev-prune-SHA256SUMS.txt").write_text("\n".join(checks)+"\n")
print("Created",OUT/"install_jev_prune.py",OUT/"jev-prune-kit.zip")
