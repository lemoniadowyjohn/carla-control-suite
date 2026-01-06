#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tile QA worker (subprocess-safe).

Writes a JSON report even if CARLA crashes.
Runs S-invariants preflight first; can auto-fix with --fix_s.

Exit codes:
  0 = ok
  2 = preflight_failed
  3 = carla_failed
  4 = unexpected
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from typing import Any, Dict


# -----------------------------------------------------------------------------
# Windows console hardening: NEVER crash because of emojis/arrows in logs.
# -----------------------------------------------------------------------------
def _force_utf8_console() -> None:
    """
    Best-effort: avoid UnicodeEncodeError on Windows consoles/subprocess logs.
    errors="replace" ensures printing fancy characters never kills the worker.
    """
    for s in (sys.stdout, sys.stderr):
        try:
            if hasattr(s, "reconfigure"):
                s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_force_utf8_console()


from ultimate_pipeline.core.s_invariants import scan_s_invariants, fix_s_invariants


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _write(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def _wait_carla_ready(client: Any, timeout_s: float = 45.0, poll_s: float = 0.5) -> None:
    """
    CARLA can accept TCP connections and still not be ready to service RPC calls.
    This waits until client.get_world() succeeds consistently (or times out).
    """
    t0 = time.time()
    last: Exception | None = None
    while time.time() - t0 < timeout_s:
        try:
            _ = client.get_world()
            return
        except Exception as e:
            last = e
            time.sleep(poll_s)
    raise RuntimeError(f"CARLA not ready after {timeout_s:.1f}s: {last}")


def _get_client(host: str, port: int, timeout_s: float) -> Any:
    """
    Prefer a recovery-aware client if available; otherwise fall back to the
    existing autostart utility.
    """
    # 1) Try recovery-aware client (if your repo has it)
    try:
        from ultimate_pipeline.carla_tools.carla_recovery import get_reliable_client  # type: ignore

        client = get_reliable_client()  # should internally handle restarts/ports
        try:
            client.set_timeout(max(30.0, float(timeout_s)))
        except Exception:
            pass
        return client
    except Exception:
        pass

    # 2) Fallback: your existing autostart helper
    from ultimate_pipeline.core.carla_utils import autostart_carla_if_needed  # type: ignore

    client = autostart_carla_if_needed(host=host, port=port, timeout_s=float(timeout_s))
    try:
        client.set_timeout(max(30.0, float(timeout_s)))
    except Exception:
        pass
    return client


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xodr", required=True)
    ap.add_argument("--report_path", required=True)
    ap.add_argument("--timeout_s", type=float, default=180.0)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--fix_s", action="store_true")
    ap.add_argument("--no_spawn", action="store_true")
    args = ap.parse_args()

    rep: Dict[str, Any] = {
        "started_at": _now(),
        "tile_path": args.xodr,
        "status": "started",
        "preflight": {},
        "carla": {},
        "ended_at": None,
    }
    _write(args.report_path, rep)

    try:
        tile_path = args.xodr

        # ---------------------------------------------------------
        # 1) Preflight S-invariants
        # ---------------------------------------------------------
        pre = scan_s_invariants(tile_path)
        rep["preflight"] = pre.to_dict()

        if pre.negative_s_count > 0 or rep["preflight"].get("monotonic_issues"):
            if args.fix_s:
                fixed = (
                    tile_path[:-5] + ".sfixed.xodr"
                    if tile_path.lower().endswith(".xodr")
                    else tile_path + ".sfixed.xodr"
                )
                fx = fix_s_invariants(tile_path, fixed, verbose=False)
                rep["preflight"]["s_fix"] = fx
                post = scan_s_invariants(fixed)
                rep["preflight"]["post_fix"] = post.to_dict()
                tile_path = fixed

                if post.negative_s_count > 0 or rep["preflight"]["post_fix"].get("monotonic_issues"):
                    rep["status"] = "preflight_failed"
                    rep["ended_at"] = _now()
                    _write(args.report_path, rep)
                    return 2
            else:
                rep["status"] = "preflight_failed"
                rep["ended_at"] = _now()
                _write(args.report_path, rep)
                return 2

        # ---------------------------------------------------------
        # 2) CARLA load
        # ---------------------------------------------------------
        import carla  # type: ignore
        from ultimate_pipeline.config.settings import SETTINGS  # type: ignore
        from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world  # type: ignore

        host = getattr(SETTINGS, "CARLA_HOST", "127.0.0.1")
        port = int(getattr(SETTINGS, "CARLA_PORT", 2000))

        # Get a client + force sane timeout (prevents the 2000ms import timeout trap)
        client = _get_client(host=host, port=port, timeout_s=float(args.timeout_s))

        # IMPORTANT: CARLA may be "listening" but not ready to import yet.
        # This is especially true right after a restart.
        _wait_carla_ready(client, timeout_s=max(45.0, float(args.timeout_s) * 0.25))

        # Read XODR
        with open(tile_path, "r", encoding="utf-8") as f:
            xodr_text = f.read()

        params = carla.OpendriveGenerationParameters()
        try:
            params.map_layers = carla.MapLayer.NONE
        except Exception:
            pass

        # Some CARLA builds need a little breathing room between readiness and import.
        time.sleep(0.25)

        t0 = time.time()
        world = load_opendrive_world(
            client,
            xodr_text,
            params=params,
            timeout_s=float(args.timeout_s),
            retries=int(args.retries),
            do_reload=True,
            fallback_enabled=False,  # never silently fall back to built-in maps
        )

        rep["carla"]["load_ok"] = True
        rep["carla"]["load_s"] = round(time.time() - t0, 3)

        # Optional spawn test
        if not args.no_spawn:
            bp_lib = world.get_blueprint_library()
            bps = bp_lib.filter("vehicle.*model3*")
            bp = bps[0] if bps else bp_lib.filter("vehicle.*")[0]
            spawns = world.get_map().get_spawn_points()
            if not spawns:
                raise RuntimeError("no spawn points in map")
            ego = world.try_spawn_actor(bp, spawns[0])
            if ego is None:
                raise RuntimeError("failed to spawn ego")
            ego.destroy()
            rep["carla"]["spawn_ok"] = True

        rep["status"] = "ok"
        rep["ended_at"] = _now()
        _write(args.report_path, rep)
        return 0

    except Exception as e:
        # Tag common readiness issues in a clearer way
        msg = str(e)
        rep["status"] = "carla_failed"
        rep["carla"]["error"] = msg
        if "time-out" in msg.lower() or "timeout" in msg.lower():
            rep["carla"]["error_kind"] = "timeout_or_not_ready"
        rep["ended_at"] = _now()
        _write(args.report_path, rep)
        return 3
    except BaseException as e:
        rep["status"] = "unexpected"
        rep["carla"]["error"] = f"{type(e).__name__}: {e}"
        rep["ended_at"] = _now()
        _write(args.report_path, rep)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
