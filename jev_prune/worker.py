"""JSON-over-stdio assessment/projection worker. stdout is exclusively protocol JSON."""
from __future__ import annotations
import sys
from . import client
from .core import MAX_WIRE, PruneError, assess, dumps, project, snapshot, strict_json


def handle(req):
    if not isinstance(req, dict) or req.get("schema") != "jev-prune.rpc.v1":
        raise PruneError("Unsupported worker request")
    snap = snapshot(req.get("format"), req.get("session"), req.get("messages"))
    receipts = req.get("receipts", [])
    operation = req.get("op")
    if operation == "assess":
        result = assess(snap, receipts, client.evaluate)
        _, report = project(snap, result["receipts"])
        return {"ok": True, "result": {**result, "projection": report, "compaction_performed": False}}
    if operation == "project":
        messages, report = project(snap, receipts)
        return {"ok": True, "result": {"messages": messages, "projection": report, "revision": snap.revision}}
    if operation == "inspect":
        from .core import prepare
        _, selected = prepare(snap, receipts)
        return {"ok": True, "result": {"revision": snap.revision, "eligible_pairs": len(selected), "remote_called": False}}
    raise PruneError("Unsupported worker operation")


def main():
    try:
        data = sys.stdin.buffer.read(MAX_WIRE + 1)
        if len(data) > MAX_WIRE:
            raise PruneError("Local request exceeds adapter bound")
        response = handle(strict_json(data))
    except PruneError as exc:
        response = {"ok": False, "error": str(exc)}
    except Exception:
        response = {"ok": False, "error": "Adapter validation or processing failure; no successful edit claimed"}
    sys.stdout.write(dumps(response) + "\n")
    return 0 if response["ok"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
