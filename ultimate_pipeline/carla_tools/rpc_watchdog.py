"""Hard monotonic watchdog for CARLA RPC probes (never targets the server).

Only the short-lived, launch-owned probe child may be terminated. A timeout is
not evidence the CARLA server is dead or safe to restart. The worker target must
be importable/picklable under Windows multiprocessing's spawn start method.
"""
from __future__ import annotations

import math
import multiprocessing
import time
from typing import Any, Callable


def _probe_child(sender: Any, fn: Callable, args: tuple, kwargs: dict) -> None:
    try:
        result = fn(*args, **kwargs)
        sender.send(("ok", result))
    except BaseException as exc:
        try:
            sender.send(("error", type(exc).__name__, str(exc)))
        except Exception:
            pass
    finally:
        sender.close()


def supervise(
    fn: Callable,
    *,
    args: tuple = (),
    kwargs: dict | None = None,
    timeout_s: float,
) -> dict:
    """Run one RPC probe in a disposable spawned process with a hard budget.

    The returned dict has ok=False for spawn/worker/deadline errors. A valid
    function result must itself be a dict (and should include its own status).
    Returns without trusting a mock Client.set_timeout or wall-clock time.
    """
    try:
        budget=float(timeout_s)
    except (TypeError, ValueError):
        return {"ok": False, "status": "PROBE_INVALID_TIMEOUT"}
    if not math.isfinite(budget) or budget <= 0:
        return {"ok": False, "status": "PROBE_INVALID_TIMEOUT"}
    deadline=time.monotonic()+budget
    ctx=multiprocessing.get_context("spawn")
    receiver,sender=ctx.Pipe(duplex=False)
    proc=ctx.Process(target=_probe_child,args=(sender,fn,tuple(args),dict(kwargs or {})),daemon=False)
    try:
        proc.start()
    except Exception as exc:
        receiver.close()
        sender.close()
        return {"ok": False, "status": "PROBE_SPAWN_FAILED", "last_error": str(exc)}
    sender.close()
    payload=None
    try:
        while True:
            remaining=deadline-time.monotonic()
            if remaining <= 0:
                break
            if receiver.poll(min(0.05,remaining)):
                try:
                    payload=receiver.recv()
                except (EOFError, OSError) as exc:
                    payload=("error", "PROBE_IPC_FAILED", str(exc))
                break
            if not proc.is_alive():
                # A fast crash can race with OS pipe delivery; poll once more.
                if receiver.poll(0):
                    payload=receiver.recv()
                break
    finally:
        receiver.close()
        # Only this subprocess is under our ownership. No CARLA PID, image name,
        # process group, or externally occupied RPC port is ever terminated.
        proc.join(timeout=min(0.2,max(0.0,deadline-time.monotonic())))
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=0.5)
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=0.5)
    if proc.is_alive():
        return {"ok": False, "status": "PROBE_REAP_FAILED"}
    if payload is None:
        return {"ok": False, "status": "PROBE_TIMEOUT" if time.monotonic() >= deadline
                else "PROBE_EXITED_WITHOUT_RESULT", "worker_exitcode": proc.exitcode}
    if payload[0] != "ok":
        return {"ok": False, "status": "PROBE_ERROR", "error_type":payload[1],
                "last_error":payload[2], "worker_exitcode": proc.exitcode}
    if not isinstance(payload[1],dict):
        return {"ok": False, "status": "PROBE_MALFORMED_RESULT"}
    if time.monotonic() > deadline:
        return {"ok": False, "status": "PROBE_LATE_RESULT"}
    return payload[1]
