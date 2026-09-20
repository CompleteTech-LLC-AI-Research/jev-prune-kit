"""Fixed-origin, bounded TypeSafe transport; no retries and no credential logging."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any
from .core import MAX_REQUEST, MAX_RESPONSE, PruneError, dumps, strict_json
from .config import assessment_environment

ENDPOINT = "https://api.typesafe.ai/v1/systemone"

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PruneError("Evaluator redirect refused")


def evaluate(body: dict[str, Any]) -> Any:
    environment = assessment_environment()
    if environment.get("JEV_PRUNE_ALLOW_REMOTE") != "1":
        raise PruneError("Remote assessment disabled. After reviewing disclosure, set JEV_PRUNE_ALLOW_REMOTE=1")
    key = environment.get("TYPESAFE_API_KEY", "")
    if not key or key.strip() != key or "\n" in key or "\r" in key:
        raise PruneError("Missing or invalid TYPESAFE_API_KEY")
    raw = dumps(body).encode()
    if len(raw) > MAX_REQUEST or key.encode() in raw:
        raise PruneError("Evaluator payload bound or credential check failed")
    # Separate process puts a wall-clock bound on DNS, connects, reads and parsing.
    # The credential is inherited, not put on the command line or written to disk.
    try:
        done = subprocess.run([sys.executable, "-m", "jev_prune.client"], input=raw,
                              capture_output=True, timeout=10, check=False, env=environment,
                              cwd=Path(__file__).resolve().parents[1])
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise PruneError("Evaluator deadline or transport startup failure; no edits") from exc
    if done.returncode or len(done.stdout) > MAX_RESPONSE:
        raise PruneError("Evaluator transport failed; no edits")
    return strict_json(done.stdout)


def main() -> int:
    raw = sys.stdin.buffer.read(MAX_REQUEST + 1)
    if len(raw) > MAX_REQUEST:
        return 1
    key = os.environ.get("TYPESAFE_API_KEY", "")
    if os.environ.get("JEV_PRUNE_ALLOW_REMOTE") != "1" or not key:
        return 1
    try:
        req = urllib.request.Request(ENDPOINT, data=raw, method="POST", headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json"})
        opener = urllib.request.build_opener(NoRedirect())
        with opener.open(req, timeout=5) as response:
            if response.status != 200:
                return 1
            data = response.read(MAX_RESPONSE + 1)
        if len(data) > MAX_RESPONSE:
            return 1
        strict_json(data)
        sys.stdout.buffer.write(data)
        return 0
    except Exception:
        # Never print server bodies, request headers, URLs or credentials.
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
