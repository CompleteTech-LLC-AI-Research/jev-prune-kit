"""Small filesystem primitives. Refuse symlinked destinations; never follow them."""
from __future__ import annotations
import contextlib
import os
from pathlib import Path
import secrets
from .core import PruneError, digest, dumps, strict_json


def safe_path(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    for p in [path, *path.parents]:
        if p.is_symlink():
            raise PruneError("Symlinked destination refused: " + str(p))
    return path


def atomic_write(path: Path, data: bytes) -> None:
    path = safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    safe_path(path)
    tmp = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


@contextlib.contextmanager
def file_lock(path: Path):
    path = safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise PruneError("Another operation holds the lock; do not remove it while a process is running: " + str(path)) from exc
    try:
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)
        path.unlink()


class ReceiptStore:
    def __init__(self, directory: Path, profile: str):
        self.directory, self.profile = safe_path(directory), profile

    def path(self, session: str) -> Path:
        return safe_path(self.directory / (digest([self.profile, session]) + ".json"))

    def load(self, session: str):
        path = self.path(session)
        if not path.exists():
            return [], None
        if path.stat().st_size > 256_000:
            raise PruneError("Receipt store exceeds size bound")
        raw = path.read_bytes()
        data = strict_json(raw)
        if (not isinstance(data, dict) or data.get("schema") != "jev-prune.receipts.v1"
            or data.get("profile") != self.profile or data.get("session") != session
            or not isinstance(data.get("receipts"), list)):
            raise PruneError("Receipt storage identity mismatch")
        return data["receipts"], digest(raw.hex())

    def save(self, session: str, receipts, version) -> None:
        with file_lock(self.path(session).with_suffix(".lock")):
            if self.load(session)[1] != version:
                raise PruneError("Receipt state changed; retry explicitly")
            data = dumps({"schema": "jev-prune.receipts.v1", "profile": self.profile,
                          "session": session, "receipts": receipts}).encode()
            if len(data) > 256_000:
                raise PruneError("Receipt storage bound exceeded")
            atomic_write(self.path(session), data)
