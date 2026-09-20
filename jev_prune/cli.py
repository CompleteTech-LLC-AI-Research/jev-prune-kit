"""Portable CLI: inspect or assess an explicitly supplied normalized snapshot."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
from .core import MAX_WIRE, PruneError, dumps, strict_json
from .worker import handle


def main(argv=None):
    parser = argparse.ArgumentParser(description="Jev pruning tools. Assessment is NOT live harness context editing.")
    parser.add_argument("operation", choices=["inspect", "assess"])
    parser.add_argument("snapshot", type=Path, help="JSON {format,session,messages,receipts?}; no automatic transcript scanning")
    args = parser.parse_args(argv)
    try:
        with args.snapshot.open("rb") as stream:
            raw = stream.read(MAX_WIRE + 1)
        if len(raw) > MAX_WIRE:
            raise PruneError("Snapshot too large")
        req = strict_json(raw)
        req.update({"schema": "jev-prune.rpc.v1", "op": args.operation})
        result = handle(req)
        print(dumps(result))
        return 0
    except PruneError as exc:
        print(dumps({"ok": False, "error": str(exc)}))
        return 1
    except (OSError, AttributeError):
        print(dumps({"ok": False, "error": "Cannot read a valid snapshot file"}))
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
