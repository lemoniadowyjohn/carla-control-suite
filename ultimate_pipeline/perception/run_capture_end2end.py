#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Verification (PowerShell):
# python -m ultimate_pipeline.perception.run_capture_end2end --town Grid0828 --carla-exe "E:\CARLA\CARLA_0.9.16\CarlaUE4.exe" --kill-stale --out-dir .\datasets\smoke\grid0828 --duration 10 --fps 10 --low-mem

"""
ultimate_pipeline/perception/run_capture_end2end.py

End-to-end capture orchestrator:
- (optionally) start CARLA server + wait until ready
- load either manual town (Grid0821/Grid0828) OR auto-generated XODR
- spawn ego + Dominik-calibrated sensors
- drive via autopilot and record outputs

This is intentionally thin glue:
- Reuses: ultimate_pipeline/carla_tools/carla_server.py
- Delegates capture logic to: ultimate_pipeline/perception/record_route_fixed.py

Design notes:
- Import-safe: no top-level "import carla"
- No refactor of perception logic; record_route already applies:
  - ignore camera K and D
  - use K_undistortion (pinhole)
  - cTv is vehicle -> camera
  - LiDAR vTl is LiDAR -> vehicle
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import sys
import time
from pathlib import Path
from typing import Optional, Sequence


def _default_calib_path() -> str:
    # repo-relative ultimate_pipeline/sensors/calib_data.json
    return str(Path(__file__).resolve().parent.parent / "sensors" / "calib_data.json")


def _split_flags(flags: Optional[str]) -> list[str]:
    if not flags:
        return []
    # Accept either JSON-ish string or shell-like; keep it simple: shlex split.
    return shlex.split(flags)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _tail_file(path: Path, n_lines: int = 30) -> list[str]:
    if n_lines <= 0:
        return []
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    return lines[-n_lines:]


def _ready_probe(host: str, port: int, *, timeout_s: float, sleep_s: float = 0.3) -> dict:
    carla, err = _try_import_carla()
    if carla is None:
        return {"ok": False, "error": f"carla_import_failed: {err}"}

    deadline = time.time() + float(timeout_s)
    client_timeout_s = float(os.environ.get("UP_CARLA_CLIENT_TIMEOUT_S", "180"))
    report = {
        "host": str(host),
        "port": int(port),
        "timeout_s": float(timeout_s),
        "sleep_s": float(sleep_s),
        "client_timeout_s": float(client_timeout_s),
        "ok": False,
        "attempts": [],
        "last_error": None,
    }
    while time.time() < deadline:
        attempt = {"ts": time.time(), "connect_ok": False, "get_world_ok": False, "get_map_ok": False,
                   "tick_ok": False, "frame_a": None, "frame_b": None, "elapsed_a": None, "elapsed_b": None}
        try:
            client = carla.Client(str(host), int(port))
            client.set_timeout(float(client_timeout_s))
            attempt["connect_ok"] = True

            world = client.get_world()
            attempt["get_world_ok"] = True

            try:
                _ = world.get_map().name
                attempt["get_map_ok"] = True
            except Exception as exc:
                attempt["get_map_ok"] = False
                raise RuntimeError(f"get_map_failed: {exc}")

            snap_a = world.get_snapshot()
            time.sleep(float(sleep_s))
            snap_b = world.get_snapshot()
            frame_a = int(getattr(snap_a, "frame", -1))
            frame_b = int(getattr(snap_b, "frame", -1))
            elapsed_a = float(getattr(getattr(snap_a, "timestamp", None), "elapsed_seconds", -1.0))
            elapsed_b = float(getattr(getattr(snap_b, "timestamp", None), "elapsed_seconds", -1.0))
            attempt["frame_a"] = frame_a
            attempt["frame_b"] = frame_b
            attempt["elapsed_a"] = elapsed_a
            attempt["elapsed_b"] = elapsed_b
            attempt["tick_ok"] = (frame_b != frame_a) or (elapsed_b > elapsed_a)
            if attempt["tick_ok"]:
                report["ok"] = True
                report["attempts"].append(attempt)
                return report
            report["last_error"] = "frames_not_advancing"
        except Exception as exc:
            report["last_error"] = str(exc)
        report["attempts"].append(attempt)
        time.sleep(float(sleep_s))
    return report


def _try_import_carla():
    try:
        import carla  # type: ignore
    except Exception as exc:
        return None, str(exc)
    return carla, None


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=(
            "End-to-end CARLA capture runner.\n\n"
            "Modes:\n"
            "  Manual map: --town Grid0828\n"
            "  Auto map  : --xodr path/to/final.xodr\n\n"
            "If --carla-exe (or env UP_CARLA_EXE) is provided, this script will start CARLA and wait.\n"
            "Otherwise, CARLA must already be running on --host/--port.\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    mg = ap.add_mutually_exclusive_group(required=True)
    mg.add_argument("--town", choices=["Grid0821", "Grid0828"], help="Manual CARLA town name (e.g., Grid0828)")
    mg.add_argument("--xodr", help="Path to OpenDRIVE .xodr to load into CARLA")

    ap.add_argument("--out-dir", required=True, help="Output directory for dataset capture artifacts")
    ap.add_argument("--calib", default=_default_calib_path(), help="Path to calib_data.json (default: repo sensors/calib_data.json)")

    ap.add_argument("--host", default="127.0.0.1", help="CARLA host (default: 127.0.0.1)")
    ap.add_argument("--port", type=int, default=2000, help="CARLA RPC port (default: 2000)")
    ap.add_argument("--tm-port", type=int, default=8000, help="TrafficManager port (default: 8000)")
    ap.add_argument("--seed", type=int, default=0, help="TrafficManager seed (default: 0)")

    ap.add_argument("--vehicle", default="vehicle.audi.a2", help="Ego vehicle blueprint id (default: vehicle.audi.a2)")
    ap.add_argument("--spawn-index", type=int, default=0, help="Spawn point index (default: 0)")

    ap.add_argument("--duration", type=float, default=60.0, help="Capture duration in seconds (default: 60)")
    ap.add_argument("--fps", type=int, default=20, help="Synchronous capture FPS (default: 20)")

    ap.add_argument("--lidar-format", choices=["npz", "ply"], default="npz", help="LiDAR output format (default: npz)")
    ap.add_argument("--seg", action="store_true", help="Also record semantic segmentation cameras")
    ap.add_argument("--seg-converter", choices=["raw", "cityscapes"], default="cityscapes", help="Segmentation converter (default: cityscapes)")

    ap.add_argument("--low-mem", action="store_true", help="Reduce sensor resolution to avoid VRAM/OOM")
    ap.add_argument("--flip-vehicle-y", action="store_true", default=True, help="Flip vehicle Y (default: True)")
    ap.add_argument("--no-flip-vehicle-y", action="store_false", dest="flip_vehicle_y", help="Disable vehicle Y flip")
    ap.add_argument("--opencv-camera-axes", action="store_true", default=True, help="Assume OpenCV camera axes and convert to CARLA (default: True)")
    ap.add_argument("--no-opencv-camera-axes", action="store_false", dest="opencv_camera_axes", help="Disable OpenCV camera axes conversion")

    # Optional CARLA server management
    ap.add_argument("--carla-exe", default=None, help="Path to CarlaUE4.exe. If set (or env UP_CARLA_EXE), starts CARLA.")
    ap.add_argument("--carla-flags", default=None, help="Extra flags for CARLA executable (shell-split string). If omitted, uses carla_server.DEFAULT_FLAGS.")
    ap.add_argument("--kill-stale", action="store_true", help="Kill stale CarlaUE4.exe before starting (Windows only)")

    args = ap.parse_args(argv)

    # Path validation (lightweight, no refactor)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    calib = Path(args.calib)
    if not calib.exists():
        ap.error(f"calib_data.json not found: {calib}")

    if args.xodr:
        xodr = Path(args.xodr)
        if not xodr.exists():
            ap.error(f"XODR not found: {xodr}")

    return args


def _start_carla_if_needed(args: argparse.Namespace, *, out_dir: Path):
    """Start CARLA server if carla exe is provided (arg or env). Returns a Popen-like proc or None."""
    carla_exe = args.carla_exe or os.environ.get("UP_CARLA_EXE")
    if not carla_exe:
        return None

    from ultimate_pipeline.carla_tools.carla_server import ensure_carla_server, DEFAULT_FLAGS

    stdout_path = out_dir / "carla_stdout.log"
    stderr_path = out_dir / "carla_stderr.log"

    flags = _split_flags(args.carla_flags)
    extra_flags: Sequence[str]
    if flags:
        extra_flags = tuple(flags)
    else:
        extra_flags = DEFAULT_FLAGS

    print(f"[carla] Starting CARLA: {carla_exe}")
    if extra_flags:
        print(f"[carla] Flags: {list(extra_flags)}")

    proc = ensure_carla_server(
        host=str(args.host),
        port=int(args.port),
        carla_exe=Path(carla_exe),
        extra_flags=extra_flags,
        timeout_s=float(os.environ.get("UP_CARLA_START_TIMEOUT_S", "180.0")),
        kill_stale=bool(args.kill_stale),
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )
    if proc is None:
        print(f"[carla] CARLA already reachable at {args.host}:{args.port} (not starting a new process).")
    else:
        print(f"[carla] CARLA process started (pid={getattr(proc, 'pid', None)}).")
    return proc


def _terminate_proc(proc) -> None:
    if proc is None:
        return
    try:
        # Best-effort: try a graceful terminate, then kill
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
    except Exception:
        pass


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    proc = None
    try:
        proc = _start_carla_if_needed(args, out_dir=out_dir)

        ready_timeout_s = float(os.environ.get("UP_CARLA_READY_TIMEOUT_S", "180"))
        ready_report = _ready_probe(str(args.host), int(args.port), timeout_s=ready_timeout_s)
        if not ready_report.get("ok", False):
            report_path = out_dir / "carla_ready_report.json"
            _write_json(report_path, ready_report)
            print(f"[ERROR] CARLA not ready within {ready_timeout_s}s. Report: {report_path}")
            if proc is not None:
                stderr_path = out_dir / "carla_stderr.log"
                tail = _tail_file(stderr_path, n_lines=30)
                if tail:
                    print("[carla] Last 30 stderr lines:")
                    for line in tail:
                        print(line)
            return 2

        # Delegate to record_route_fixed (thesis-safe capture runner).
        from ultimate_pipeline.perception import record_route_fixed

        rr_argv: list[str] = []
        if args.town:
            rr_argv += ["--town", str(args.town)]
        else:
            rr_argv += ["--xodr", str(args.xodr)]

        rr_argv += [
            "--calib", str(args.calib),
            "--out-dir", str(args.out_dir),
            "--host", str(args.host),
            "--port", str(args.port),
            "--tm-port", str(args.tm_port),
            "--seed", str(args.seed),
            "--vehicle", str(args.vehicle),
            "--spawn-index", str(args.spawn_index),
            "--duration", str(args.duration),
            "--fps", str(args.fps),
            "--lidar-format", str(args.lidar_format),
        ]

        if args.seg:
            rr_argv.append("--seg")
            rr_argv += ["--seg-converter", str(args.seg_converter)]
        if args.low_mem:
            rr_argv.append("--low-mem")
        if args.flip_vehicle_y:
            rr_argv.append("--flip-vehicle-y")
        else:
            rr_argv.append("--no-flip-vehicle-y")
        if args.opencv_camera_axes:
            rr_argv.append("--opencv-camera-axes")
        else:
            rr_argv.append("--no-opencv-camera-axes")

        print("[capture] Delegating to ultimate_pipeline.perception.record_route_fixed")
        print("[capture] Args:", " ".join(shlex.quote(a) for a in rr_argv))

        return int(record_route_fixed.main(rr_argv))

    except KeyboardInterrupt:
        print("\n[capture] Interrupted.")
        return 130
    finally:
        # Clean up CARLA if we started it
        _terminate_proc(proc)


if __name__ == "__main__":
    raise SystemExit(main())
