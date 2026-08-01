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

from ultimate_pipeline.utils.bootstrap import bootstrap_console

bootstrap_console()

import argparse
import datetime
import json
import logging
import os
import random
import sys
import time
import traceback
from typing import Any, Dict, List, Optional


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

log = logging.getLogger("tile_worker")


from ultimate_pipeline.core.s_invariants import scan_s_invariants, fix_s_invariants


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _write(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def _setup_logger() -> None:
    if log.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


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


def _record_streaming_status(rep: Dict[str, Any], host: str, streaming_port: int) -> None:
    """
    Best-effort streaming probe for reporting. Never raises.
    """
    try:
        from ultimate_pipeline.carla_tools.carla_recovery import probe_streaming_port  # type: ignore

        status = probe_streaming_port(
            host,
            int(streaming_port),
            timeout_s=0.4,
            max_attempts=1,
        )
    except Exception as e:
        status = {
            "port": int(streaming_port),
            "optional": True,
            "disabled": False,
            "attempts": 0,
            "status": "unknown",
            "error": str(e),
        }

    rep.setdefault("carla", {})["streaming"] = status
    if status.get("status") in ("refused", "disabled"):
        log.info(
            "Streaming port optional: status=%s port=%s",
            status.get("status"),
            status.get("port"),
        )


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


def _spawn_with_retries(
    world: Any,
    preferred_filter: str = "vehicle.*model3*",
    fallback_filter: str = "vehicle.*",
    max_attempts: int = 5,
    seed: int = 42,
    spawn_points: Optional[List[Any]] = None,
    z_offset_m: float = 0.75,
    forward_m: float = 0.0,
) -> Any:
    """
    Robust-ish ego spawn.
    Why this exists:
    - Some CARLA builds crash natively on certain spawn-related calls.
    - The legacy worker referenced `try_robust_spawn`, but the repo’s canonical
      helper is `try_safe_spawn`.
    Implementation:
    - Deterministically samples spawn points (seeded).
    - Applies a small Z lift (and optional forward nudge) to reduce collisions.
    - Uses `world.try_spawn_actor` via `try_safe_spawn`.
    """
    import carla  # type: ignore
    from ultimate_pipeline.carla_tools.spawn_recovery import try_safe_spawn

    bp_lib = world.get_blueprint_library()
    bps = bp_lib.filter(preferred_filter)
    if not bps:
        bps = bp_lib.filter(fallback_filter)
    if not bps:
        raise RuntimeError("no vehicle blueprints available")
    bp = bps[0]

    spawns = list(spawn_points) if spawn_points is not None else list(world.get_map().get_spawn_points())
    
    log.info(
        "Spawn strategy (robust) | spawn_points=%d | bp_pref=%s | max_attempts=%d | seed=%d",
        len(spawns),
        preferred_filter,
        max_attempts,
        seed,
    )

    rng = random.Random(int(seed))
    attempts: List[Dict[str, Any]] = []
    ego = None

    for attempt_i in range(int(max_attempts)):
        if not spawns:
            break
        spawn_index = rng.randrange(0, len(spawns))
        base_tf = spawns[spawn_index]

        loc = carla.Location(
            x=float(base_tf.location.x),
            y=float(base_tf.location.y),
            z=float(base_tf.location.z) + float(z_offset_m),
        )
        # Optional forward nudge (can help if the spawn point is embedded in geometry)
        try:
            if float(forward_m) != 0.0:
                fwd = base_tf.get_forward_vector()
                loc = carla.Location(
                    x=loc.x + float(fwd.x) * float(forward_m),
                    y=loc.y + float(fwd.y) * float(forward_m),
                    z=loc.z + float(fwd.z) * float(forward_m),
                )
        except Exception:
            pass

        tf = carla.Transform(loc, base_tf.rotation)
        t0 = time.time()
        err: Optional[str] = None
        status = "fail"
        try:
            ego = try_safe_spawn(world, bp, tf, max_tries=1)
            if ego is not None:
                status = "ok"
        except Exception as e:
            err = str(e)

        attempts.append(
            {
                "attempt": attempt_i + 1,
                "spawn_index": spawn_index,
                "location": {"x": float(tf.location.x), "y": float(tf.location.y), "z": float(tf.location.z)},
                "rotation": {
                    "yaw": float(getattr(tf.rotation, "yaw", 0.0)),
                    "pitch": float(getattr(tf.rotation, "pitch", 0.0)),
                    "roll": float(getattr(tf.rotation, "roll", 0.0)),
                },
                "blueprint": bp.id,
                "status": status,
                "elapsed_s": round(time.time() - t0, 6),
                "z_lift_applied_m": float(z_offset_m),
                "forward_shift_m": float(forward_m),
                **({"exception": err} if err else {}),
            }
        )

        if ego is not None:
            log.info("Spawn succeeded on attempt %d", attempt_i + 1)
            return ego, attempts

    raise RuntimeError(
        f"failed to spawn ego after {max_attempts} attempts. "
        f"Attempts: {attempts}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xodr", required=True)
    ap.add_argument("--report_path", required=True)
    ap.add_argument("--timeout_s", type=float, default=180.0)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--fix_s", action="store_true")
    ap.add_argument("--no_spawn", action="store_true")
    args = ap.parse_args()

    _setup_logger()
    log.info("tile_worker start | xodr=%s", args.xodr)

    rep: Dict[str, Any] = {
        "started_at": _now(),
        "tile_path": args.xodr,
        "status": "started",
        "preflight": {},
        "carla": {
            "no_spawn": bool(args.no_spawn),
            "spawn_ok": None,
        },
        "ended_at": None,
    }
    result: Dict[str, Any] = {
        "tile_path": args.xodr,
        "tile_id": os.path.splitext(os.path.basename(args.xodr))[0],
        "map_name": None,
        "spawn": {
            "attempted": False,
            "ok": None,
            "spawn_points": 0,
            "chosen_index": None,
            "chosen_location": None,
            "chosen_rotation": None,
            "blueprint_requested": "vehicle.*model3*",
            "blueprint_used": None,
            "attempts": 0,
            "elapsed_s": None,
            "attempt_log": [],
        },
        "failed_stage": None,
        "exception": None,
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
        streaming_port = int(getattr(SETTINGS, "CARLA_STREAMING_PORT", port + 1) or (port + 1))

        _record_streaming_status(rep, host=host, streaming_port=streaming_port)

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
        result["map_name"] = getattr(world.get_map(), "name", None)
        rep["carla"]["load_ok"] = True
        rep["carla"]["load_s"] = round(time.time() - t0, 3)

        # Optional spawn test
        if not args.no_spawn:
            map_name = getattr(world.get_map(), "name", None)
            log.info("Starting spawn test | map=%s", map_name)
            # IMPORTANT: spawn failures are often "bad luck" with a few spawn points.
            # Use a higher attempt budget for robustness (still deterministic via seed).
            max_attempts = int(getattr(SETTINGS, "TILE_SPAWN_ATTEMPTS", 20) or 20)
            if max_attempts < 5:
                max_attempts = 5
            seed = int(getattr(SETTINGS, "SEED", 42) or 42)
            z_offset_m = float(getattr(SETTINGS, "TILE_SPAWN_Z_OFFSET_M", 0.75) or 0.75)
            forward_m = float(getattr(SETTINGS, "TILE_SPAWN_FORWARD_M", 0.0) or 0.0)
            ego: Any = None
            spawn_attempts: List[Dict[str, Any]] = []
            spawn_points = list(world.get_map().get_spawn_points())
            rep["carla"]["spawn_points"] = len(spawn_points)
            result["spawn"]["spawn_points"] = len(spawn_points)
            result["spawn"]["attempted"] = True
            try:
                ego, spawn_attempts = _spawn_with_retries(
                    world,
                    preferred_filter="vehicle.*model3*",
                    fallback_filter="vehicle.*",
                    max_attempts=max_attempts,
                    seed=seed,
                    spawn_points=spawn_points,
                    z_offset_m=z_offset_m,
                    forward_m=forward_m,
                )
                result["spawn"]["ok"] = True
                result["spawn"]["attempts"] = len(spawn_attempts)
                if spawn_attempts:
                    last = spawn_attempts[-1]
                    result["spawn"]["chosen_index"] = last.get("spawn_index")
                    result["spawn"]["blueprint_used"] = last.get("blueprint")
                    result["spawn"]["elapsed_s"] = last.get("elapsed_s")
                    result["spawn"]["chosen_location"] = last.get("location")
                    result["spawn"]["chosen_rotation"] = last.get("rotation")
                    result["spawn"]["attempt_log"] = spawn_attempts
                rep["carla"]["spawn_ok"] = True
                rep["carla"]["spawn_attempts"] = spawn_attempts
            except Exception as e:
                result["spawn"]["attempt_log"] = spawn_attempts
                result["spawn"]["attempts"] = len(spawn_attempts)
                result["spawn"]["failed_ctx"] = {
                    "spawn_points": len(spawn_points),
                    "map_name": map_name,
                }
                result["failed_stage"] = "spawn"
                result["exception"] = {"type": type(e).__name__, "message": str(e), "traceback": traceback.format_exc()}
                result["spawn"]["ok"] = False
                if rep["carla"].get("spawn_ok") is None:
                    rep["carla"]["spawn_ok"] = False
                raise
            finally:
                if ego:
                    try:
                        ego.destroy()
                    except Exception:
                        pass
            attempted = bool(result["spawn"].get("attempted"))
            if attempted and rep["carla"].get("spawn_ok") is not True:
                rep["carla"]["spawn_attempts"] = spawn_attempts
                rep["carla"]["map_name"] = map_name
                raise RuntimeError(
                    f"failed to spawn ego after retries | map={map_name} | "
                    f"attempts={len(spawn_attempts)} | spawn_points={len(spawn_points)}"
                )
        else:
            # Explicitly record that spawn was not attempted; keep spawn_ok as None.
            result["spawn"]["attempted"] = False
            result["spawn"]["ok"] = None
            rep["carla"]["spawn_ok"] = None
        result["failed_stage"] = None
        result["exception"] = None
        rep["carla"]["result"] = result

        rep["status"] = "ok"
        return 0

    except Exception as e:
        # Tag common readiness issues in a clearer way
        msg = str(e)
        rep["status"] = "carla_failed"
        rep["carla"]["error"] = msg
        if "time-out" in msg.lower() or "timeout" in msg.lower():
            rep["carla"]["error_kind"] = "timeout_or_not_ready"
        result["failed_stage"] = "spawn" if "spawn" in msg.lower() else "load_map"
        result["exception"] = {"type": type(e).__name__, "message": msg, "traceback": traceback.format_exc()}
        attempted = bool(result.get("spawn", {}).get("attempted"))
        if attempted and rep["carla"].get("spawn_ok") is None:
            rep["carla"]["spawn_ok"] = False
        return 3
    except BaseException as e:
        rep["status"] = "unexpected"
        rep["carla"]["error"] = f"{type(e).__name__}: {e}"
        result["failed_stage"] = "unexpected"
        result["exception"] = {"type": type(e).__name__, "message": str(e), "traceback": traceback.format_exc()}
        attempted = bool(result.get("spawn", {}).get("attempted"))
        if attempted and rep["carla"].get("spawn_ok") is None:
            rep["carla"]["spawn_ok"] = False
        return 4
    finally:
        rep["carla"]["result"] = result
        rep["ended_at"] = _now()
        _write(args.report_path, rep)


if __name__ == "__main__":
    raise SystemExit(main())
