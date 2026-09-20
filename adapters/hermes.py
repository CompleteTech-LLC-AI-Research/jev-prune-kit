"""Experimental single-user Hermes request middleware. No compressor replacement.

The public slash-command callback has no authenticated session context. Therefore
live pruning is disabled unless the operator explicitly declares this a single-
user process. Do not set that flag in a shared gateway. No private Hermes APIs.
"""
from __future__ import annotations
import copy
import os
from pathlib import Path
import threading
from collections import OrderedDict
from jev_prune import client
from jev_prune.core import MAX_WIRE, PruneError, assess, digest, dumps, project, snapshot
from jev_prune.fsutil import ReceiptStore


def register(ctx, config):
    if not callable(getattr(ctx, "register_middleware", None)) or not callable(getattr(ctx, "register_command", None)):
        raise RuntimeError("Jev: this Hermes version does not expose the required plugin APIs")
    cache = OrderedDict()
    lock = threading.RLock()
    busy = set()
    store = ReceiptStore(Path(config["stateDir"]), config["profile"])

    def middleware(request, original_request=None, **kwargs):
        if os.environ.get("JEV_PRUNE_HERMES_SINGLE_USER") != "1":
            return None
        session = kwargs.get("session_id")
        if (not isinstance(session, str) or not session or not isinstance(request, dict)
            or not isinstance(request.get("messages"), list) or request.get("previous_response_id")
            or request.get("conversation") or "input" in request):
            return None  # Never pretend to support opaque server-side lineage.
        if len(dumps(request["messages"]).encode()) > MAX_WIRE:
            return None
        messages = copy.deepcopy(request["messages"])
        with lock:
            cache[session] = messages
            cache.move_to_end(session)
            while len(cache) > 8:
                cache.popitem(last=False)
        receipts, _ = store.load(session)
        if not receipts:
            return None
        result, _ = project(snapshot("openai", session, messages), receipts)
        return {"request": {**request, "messages": result}, "source": "jev-prune", "reason": "validated repeated-read projection"}

    def command(raw_args):
        if os.environ.get("JEV_PRUNE_HERMES_SINGLE_USER") != "1":
            return "Jev live pruning disabled. Only a single-user local process may opt in with JEV_PRUNE_HERMES_SINGLE_USER=1. Shared gateways are unsupported."
        with lock:
            session = raw_args.strip()
            if not session and len(cache) == 1:
                session = next(iter(cache))
            if not session or session not in cache:
                return "No unambiguous captured session. Run a normal turn first; for multiple sessions use /prune <exact-session-id>."
            if session in busy:
                return "A pruning assessment is already in progress."
            messages = copy.deepcopy(cache[session])
            stamp = digest(messages)
            busy.add(session)
        try:
            receipts, version = store.load(session)
            snap = snapshot("openai", session, messages)
            result = assess(snap, receipts, client.evaluate)
            with lock:
                if session not in cache or digest(cache[session]) != stamp:
                    raise PruneError("Request changed during assessment; no receipt committed")
                if result["added"]:
                    store.save(session, result["receipts"], version)
            _, report = project(snap, result["receipts"])
            return (f"Jev approved {result['added']} new repeated-read omissions; "
                    f"{report['body_bytes_removed']} result-body bytes omitted in matching future requests. "
                    "This is not a token measurement. No compaction performed; native compression and budgets are unchanged.")
        except PruneError as exc:
            return "No successful pruning commit claimed: " + str(exc)
        except Exception:
            return "Pruning operation failed; inspect local configuration. No compaction requested."
        finally:
            with lock:
                busy.discard(session)

    ctx.register_middleware("llm_request", middleware)
    ctx.register_command("prune", handler=command, description="Jev repeated-read projection (single-user experimental)", args_hint="[session-id]")
