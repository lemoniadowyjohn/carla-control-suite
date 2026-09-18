#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ultimate_pipeline.tools.carla_preflight

CARLA reachability + optional autostart/restart (Windows-safe).

Writes carla_reachability.json into --out directory.

Exit codes:
  0 = reachable (api_ok && tick_ok)
  1 = unreachable or tick not ok (artifact written)
  2 = artifact write error
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def _tcp_probe(host: str, port: int, timeout_s: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=float(timeout_s)):
            return True
    except OSError:
        return False


def _carla_api_probe(host: str, port: int, timeout_s: float = 10.0, tick_timeout_s: float = 2.0) -> Dict[str, Any]:
    result: Dict[str, Any] = {"api_ok": False, "tick_ok": False, "server_version": None, "map_name": None, "spawn_points": None, "error": None}
    try:
        import carla  # type: ignore
        client = carla.Client(host, int(port))
        client.set_timeout(float(timeout_s))
        try:
            result["server_version"] = client.get_server_version()
        except Exception:
            pass
        world = client.get_world()
        result["api_ok"] = world is not None
        if world:
            try:
                result["map_name"] = world.get_map().name
            except Exception:
                pass
            try:
                result["spawn_points"] = len(world.get_map().get_spawn_points())
            except Exception:
                pass
            try:
                world.wait_for_tick(float(tick_timeout_s))
                result["tick_ok"] = True
            except Exception as e:
                result["tick_ok"] = False
                result["error"] = f"tick_failed: {e}"
    except ImportError as e:
        result["error"] = f"carla_import_failed: {e}"
    except Exception as e:
        result["error"] = f"connection_failed: {e}"
    return result


def _kill_carla_windows() -> Dict[str, Any]:
    out = {"attempted": True, "killed": False, "error": None}
    if os.name != "nt":
        out["error"] = "kill_windows_only"
        return out
    try:
        cp = subprocess.run(["taskkill", "/IM", "CarlaUE4.exe", "/F"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        out["killed"] = (cp.returncode == 0)
        if cp.returncode != 0:
            out["error"] = ((cp.stdout or "") + "\n" + (cp.stderr or ""))[-2000:]
    except Exception as e:
        out["error"] = f"taskkill_failed:{e}"
    return out


def _start_carla_server_windows(carla_exe: str, *, host: str, port: int, wait_s: float = 60.0, extra_args: Optional[list[str]] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"attempted": True, "carla_exe": carla_exe, "pid": None, "started": False, "error": None}
    if os.name != "nt":
        out["error"] = "autostart_windows_only"
        return out
    if not carla_exe or not os.path.exists(carla_exe):
        out["error"] = f"carla_exe_missing:{carla_exe}"
        return out
    args = [carla_exe] + (list(extra_args) if extra_args else [])
    try:
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        p = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                             cwd=str(Path(carla_exe).parent))
        out["pid"] = int(p.pid)
        t0 = time.time()
        while time.time() - t0 < float(wait_s):
            if _tcp_probe(host, port, timeout_s=1.0):
                out["started"] = True
                break
            time.sleep(1.0)
        if not out["started"]:
            out["error"] = f"rpc_port_not_open_after_{wait_s}s"
    except Exception as e:
        out["error"] = f"start_failed:{type(e).__name__}:{e}"
    return out


def run_preflight(
    host: str = "127.0.0.1",
    port: int = 2000,
    streaming_port: Optional[int] = None,
    out_dir: Optional[str] = None,
    timeout_s: float = 10.0,
    skip_api: bool = False,
    *,
    autostart: bool = False,
    force_restart: bool = False,
    carla_exe: Optional[str] = None,
    autostart_wait_s: float = 60.0,
) -> Dict[str, Any]:
    if streaming_port is None:
        streaming_port = int(port) + 1

    timestamp = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()

    rpc_open = _tcp_probe(host, port, timeout_s=min(2.0, timeout_s))
    stream_open = _tcp_probe(host, streaming_port, timeout_s=min(2.0, timeout_s))

    result: Dict[str, Any] = {
        "ok": False,
        "host": host,
        "port": int(port),
        "streaming_port": int(streaming_port),
        "rpc_open": rpc_open,
        "stream_open": stream_open,
        "api_ok": False,
        "tick_ok": False,
        "server_version": None,
        "map_name": None,
        "spawn_points": None,
        "error": None,
        "timestamp": timestamp,
        "elapsed_s": 0.0,
        "autostart": None,
        "kill": None,
    }

    if (force_restart or autostart) and (not rpc_open or force_restart):
        if force_restart:
            result["kill"] = _kill_carla_windows()
            time.sleep(2.0)
        exe = carla_exe or os.getenv("UP_CARLA_EXE") or os.getenv("CARLA_EXE") or ""
        result["autostart"] = _start_carla_server_windows(exe, host=host, port=int(port), wait_s=float(autostart_wait_s))
        rpc_open = _tcp_probe(host, port, timeout_s=min(2.0, timeout_s))
        stream_open = _tcp_probe(host, streaming_port, timeout_s=min(2.0, timeout_s))
        result["rpc_open"] = rpc_open
        result["stream_open"] = stream_open

    if not rpc_open:
        result["error"] = f"rpc_port_closed ({host}:{port})"
    elif skip_api:
        result["ok"] = rpc_open and stream_open
        result["api_ok"] = None
        result["tick_ok"] = None
    else:
        api_result = _carla_api_probe(host, port, timeout_s=timeout_s)
        result.update(api_result)
        result["ok"] = bool(api_result.get("api_ok") and api_result.get("tick_ok"))

        if (not result["ok"]) and force_restart:
            result["kill_2"] = _kill_carla_windows()
            time.sleep(2.0)
            exe = carla_exe or os.getenv("UP_CARLA_EXE") or os.getenv("CARLA_EXE") or ""
            result["autostart_2"] = _start_carla_server_windows(exe, host=host, port=int(port), wait_s=float(autostart_wait_s))
            api2 = _carla_api_probe(host, port, timeout_s=timeout_s)
            result["api_probe_after_restart"] = api2
            result["ok"] = bool(api2.get("api_ok") and api2.get("tick_ok"))
            if not result["ok"] and not result.get("error"):
                result["error"] = api2.get("error")

    result["elapsed_s"] = round(time.monotonic() - t0, 3)

    if out_dir:
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        artifact = out_path / "carla_reachability.json"
        try:
            artifact.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
            result["artifact_path"] = str(artifact)
        except Exception as e:
            result["artifact_write_error"] = str(e)

    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="CARLA preflight reachability check")
    ap.add_argument("--host", default=os.getenv("CARLA_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("CARLA_PORT", "2000")))
    ap.add_argument("--streaming-port", type=int, default=None)
    ap.add_argument("--out", type=str, default=None, help="Output directory for carla_reachability.json")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--skip-api", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--autostart", action="store_true")
    ap.add_argument("--force-restart", action="store_true")
    ap.add_argument("--carla-exe", type=str, default=None)
    ap.add_argument("--autostart-wait-s", type=float, default=60.0)
    args = ap.parse_args()

    result = run_preflight(
        host=args.host,
        port=args.port,
        streaming_port=args.streaming_port,
        out_dir=args.out,
        timeout_s=args.timeout,
        skip_api=args.skip_api,
        autostart=bool(args.autostart),
        force_restart=bool(args.force_restart),
        carla_exe=args.carla_exe,
        autostart_wait_s=float(args.autostart_wait_s),
    )

    if not args.quiet:
        print(json.dumps(result, indent=2))

    if result.get("artifact_write_error"):
        return 2
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
