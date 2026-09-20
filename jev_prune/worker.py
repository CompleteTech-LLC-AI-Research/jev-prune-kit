"""JSON-over-stdio assessment/projection worker. stdout is exclusively protocol JSON."""
from __future__ import annotations
import sys
from pathlib import Path
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


def bus_handle(request, state_dir: str, profile: str, fmt: str):
    """Serve one jev-bus.stage.v1 request as a stage inside another package's carrier.

    This package's stage claims only `tool-result:read`: it substitutes duplicate read
    bodies IN PLACE and never changes the array length, which is what lets a downstream
    stage keep keying messages by position.

    Only the purely local `project` runs here. Assessment is a paid remote call and stays
    behind the carrier's /prune plus explicit consent, so joining a chain can never start
    billing on its own.
    """
    from .fsutil import ReceiptStore

    session = str(request.get("session") or "")
    messages = request["messages"]
    if not session:
        return {"ok": True, "messages": messages,
                "notes": [{"action": "passthrough", "detail": "no session id supplied"}]}
    receipts, _ = ReceiptStore(Path(state_dir), profile).load(session)
    if not receipts:
        return {"ok": True, "messages": messages,
                "notes": [{"action": "passthrough", "detail": "no approved receipts for this session"}]}
    snap = snapshot(fmt, session, messages)
    if request["op"] == "plan":
        from .core import prepare
        _, selected = prepare(snap, receipts)
        return {"ok": True, "messages": messages,
                "notes": [{"action": "duplicate read bodies eligible", "count": len(selected),
                           "detail": "repeated file reads (approve: jev-prune assess, needs JEV_PRUNE_ALLOW_REMOTE)"}]}
    projected, report = project(snap, receipts)
    notes = []
    if report.get("applied"):
        notes.append({"action": "duplicate read bodies substituted", "count": report["applied"],
                      "bytes": report.get("body_bytes_removed", 0),
                      "detail": "older identical read bodies replaced by a marker naming the retained copy"})
    if report.get("invalid"):
        notes.append({"action": "passthrough", "detail": f"{report['invalid']} stale receipt(s) ignored"})
    return {"ok": True, "messages": projected, "notes": notes}


def bus_main(argv):
    from . import bus

    options = {}
    for flag in ("--state-dir", "--profile", "--format"):
        if flag in argv:
            options[flag] = argv[argv.index(flag) + 1]
    try:
        request = bus.read_stage_request()
        response = bus_handle(request, options["--state-dir"], options["--profile"], options["--format"])
    except Exception as exc:  # a stage must decline, never break the carrier's turn
        response = {"ok": False, "error": str(exc)[:300] if isinstance(exc, (PruneError, bus.BusError)) else type(exc).__name__}
    sys.stdout.write(dumps(response) + "\n")
    return 0


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
