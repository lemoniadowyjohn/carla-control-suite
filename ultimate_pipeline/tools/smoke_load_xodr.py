#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Smoke test: verify XODR loads in CARLA (preflight + load + screenshot).

CLI: python -m ultimate_pipeline.tools.smoke_load_xodr --xodr <path> --out <dir> [--host --port]

Writes: preflight_report.json, carla_status.json, run_summary.json, screenshot/
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, List


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    return v.strip().lower() in ("1", "true", "yes", "on", "y") if v else default


def _configure_windows_encoding() -> None:
    """Best-effort UTF-8 encoding for Windows stdout/stderr to prevent mojibake."""
    if sys.platform != "win32":
        return
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True)
    path.write_text(text + ("\n" if not text.endswith("\n") else ""), encoding="utf-8", newline="\n")


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Smoke test: verify XODR loads in CARLA.")
    ap.add_argument("--xodr", type=Path, required=True, help="Input OpenDRIVE file (*.xodr)")
    ap.add_argument("--out", type=Path, required=True, help="Output directory for artifacts")
    ap.add_argument("--host", default="127.0.0.1", help="CARLA host. Default: 127.0.0.1")
    ap.add_argument("--port", type=int, default=2000, help="CARLA port. Default: 2000")
    ap.add_argument("--timeout", type=float, default=180.0, help="CARLA load timeout (s). Default: 180")
    ap.add_argument("--strict-screenshot", action="store_true",
                    help="Make screenshot failure fatal (default: best-effort)")
    ap.add_argument("--no-screenshot", action="store_true", help="Skip screenshot capture entirely")
    ap.add_argument("--screenshot-timeout", type=float, default=8.0,
                    help="Screenshot timeout (s). Default: 8")
    ap.add_argument("--screenshot-retries", type=int, default=0,
                    help="Screenshot retries after initial attempt. Default: 0")
    ap.add_argument("--screenshot-port", type=int, default=None,
                    help="CARLA screenshot RPC port (defaults to --port)")
    ap.add_argument("--qa-sensors", action="store_true",
                    help="Capture a one-frame sensor QA bundle (best-effort)")
    ap.add_argument("--qa-calib", type=Path, default=None,
                    help="Calibration JSON for QA sensors (defaults to repo calib_data.json)")
    return ap.parse_args()


def _default_calib_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    preferred = repo_root / "ultimate_pipeline" / "sensors" / "calib_data.json"
    if preferred.exists():
        return preferred
    fallback = repo_root / "calib_data.json"
    return fallback


def _capture_screenshot_best_effort(
    *,
    host: str,
    port: int,
    out_dir: Path,
    timeout_s: float,
    retries: int,
    warmup: int = 5,
) -> Dict[str, Any]:
    def _load_failure_reason() -> Optional[str]:
        result_path = out_dir / "screenshot_result.json"
        if not result_path.exists():
            return None
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
            return data.get("failure_reason")
        except Exception:
            return None

    cmd: List[str] = [
        sys.executable, "-m", "ultimate_pipeline.tools.carla_screenshot_once",
        "--host", host, "--port", str(port), "--out", str(out_dir),
        "--timeout-s", str(timeout_s), "--warmup", str(warmup),
    ]
    attempts = 0
    last_error: Optional[str] = None
    screenshot_png = out_dir / "screenshot_once.png"

    for attempt in range(retries + 1):
        attempts += 1
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=max(1.0, timeout_s + 2.0),
            )
            combined = (result.stdout or "") + "\n" + (result.stderr or "")
            if "connection refused" in combined.lower():
                last_error = "connection_refused"
                print("[smoke_load_xodr] WARNING: Streaming port connection refused; skipping retries.")
                break
            if result.returncode == 0 and screenshot_png.exists():
                return {
                    "attempted": True,
                    "ok": True,
                    "error": None,
                    "timeout_s": timeout_s,
                    "cmd": cmd,
                    "path": str(screenshot_png),
                    "attempts": attempts,
                    "retries": retries,
                }
            reason = _load_failure_reason()
            if reason:
                last_error = f"exit_code={result.returncode}: {reason}"
            else:
                last_error = f"exit_code={result.returncode}"
        except subprocess.TimeoutExpired:
            last_error = "timeout"
        except Exception as exc:
            last_error = str(exc)

        if attempt < retries:
            print(f"[smoke_load_xodr] WARNING: screenshot attempt {attempt + 1} failed ({last_error}); retrying...")

    print(f"[smoke_load_xodr] WARNING: screenshot failed ({last_error})")
    return {
        "attempted": True,
        "ok": False,
        "error": last_error,
        "timeout_s": timeout_s,
        "cmd": cmd,
        "path": None,
        "attempts": attempts,
        "retries": retries,
    }


def _run_qa_sensors_best_effort(
    *,
    xodr_path: Path,
    out_dir: Path,
    host: str,
    port: int,
    calib_json: Path,
    timeout_s: float = 120.0,
) -> Dict[str, Any]:
    cmd: List[str] = [
        sys.executable, "-m", "ultimate_pipeline.tools.thesis_qa_bundle",
        "--xodr", str(xodr_path), "--calib-json", str(calib_json),
        "--out-dir", str(out_dir), "--host", host, "--port", str(port),
    ]
    manifest_path = out_dir / "thesis_qa_bundle" / "manifest.json"
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if result.returncode == 0 and manifest_path.exists():
            return {
                "attempted": True,
                "ok": True,
                "error": None,
                "cmd": cmd,
                "manifest": str(manifest_path),
            }
        error = f"exit_code={result.returncode}"
    except subprocess.TimeoutExpired:
        error = "timeout"
    except Exception as exc:
        error = str(exc)

    print(f"[smoke_load_xodr] WARNING: QA sensors failed ({error})")
    return {
        "attempted": True,
        "ok": False,
        "error": error,
        "cmd": cmd,
        "manifest": str(manifest_path) if manifest_path.exists() else None,
    }


def _center_spectator_on_map(world, carla) -> Dict[str, Any]:
    """Move spectator to map center at high altitude with top-down view.

    Returns dict with spectator transform info for carla_status.json.
    """
    result = {"centered": False, "method": "unknown", "transform": None}

    try:
        carla_map = world.get_map()
        spawn_points = carla_map.get_spawn_points()

        # Determine center from spawn points or waypoints
        if spawn_points:
            xs = [sp.location.x for sp in spawn_points]
            ys = [sp.location.y for sp in spawn_points]
            center_x = sum(xs) / len(xs)
            center_y = sum(ys) / len(ys)
            result["method"] = "spawn_points"
        else:
            # Fallback: sample waypoints
            waypoints = carla_map.generate_waypoints(50.0)
            if waypoints:
                xs = [wp.transform.location.x for wp in waypoints[:200]]
                ys = [wp.transform.location.y for wp in waypoints[:200]]
                center_x = sum(xs) / len(xs)
                center_y = sum(ys) / len(ys)
                result["method"] = "waypoints"
            else:
                result["method"] = "fallback_origin"
                center_x, center_y = 0.0, 0.0

        # Set spectator to high altitude looking down
        altitude = 300.0
        spectator = world.get_spectator()
        transform = carla.Transform(
            carla.Location(x=center_x, y=center_y, z=altitude),
            carla.Rotation(pitch=-90.0, yaw=0.0, roll=0.0)
        )
        spectator.set_transform(transform)

        result["centered"] = True
        result["transform"] = {
            "x": round(center_x, 2),
            "y": round(center_y, 2),
            "z": round(altitude, 2),
            "pitch": -90.0,
            "yaw": 0.0,
            "roll": 0.0,
        }

        print(f"[smoke_load_xodr] Spectator centered at ({center_x:.1f}, {center_y:.1f}, {altitude:.1f}) via {result['method']}")

    except Exception as exc:
        result["error"] = str(exc)
        print(f"[smoke_load_xodr] Spectator centering failed: {exc}")

    return result


def main() -> int:
    _configure_windows_encoding()
    args = _parse_args()
    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    xodr_path = args.xodr.resolve()
    tile_validation_mode = "merged_or_full"
    if xodr_path.name.lower().startswith("tile_"):
        if xodr_path.name.lower() == "tile_0_0.xodr":
            tile_validation_mode = "canonical_tile"
        else:
            tile_validation_mode = "non_canonical_tile"
            print("[smoke_load_xodr] WARNING: non-canonical tile selected; use tile_0_0.xodr for smoke load.")

    carla_status_path = out_dir / "carla_status.json"
    run_summary_path = out_dir / "run_summary.json"
    carla_status: Dict[str, Any] = {"status": "pending", "reason": "", "timestamp": timestamp}
    run_summary: Dict[str, Any] = {
        "xodr_path": str(xodr_path), "out_dir": str(out_dir), "timestamp": timestamp,
        "preflight_report": None, "carla_status": None, "screenshot": None, "success": False,
        "screenshot_attempted": False,
        "screenshot_ok": False,
        "screenshot_error": None,
        "screenshot_timeout_s": args.screenshot_timeout,
        "screenshot_cmd": None,
        "screenshot_retries": max(0, args.screenshot_retries),
        "screenshot_status": None,
        "qa_sensors_attempted": False,
        "qa_sensors_ok": False,
        "qa_sensors_error": None,
        "qa_sensors_manifest": None,
        "tile_validation_mode": tile_validation_mode,
    }

    # Step 1: Preflight validation
    print(f"[smoke_load_xodr] Running preflight on: {xodr_path}")
    from ultimate_pipeline.tools.preflight_xodr_loadability import run_preflight
    preflight_report = run_preflight(xodr_path, out_dir)
    preflight_status = preflight_report.get("summary", {}).get("status", "fail")
    run_summary["preflight_report"] = str(out_dir / "preflight_report.json")

    if preflight_status != "ok" and not _env_bool("UP_ALLOW_PREFLIGHT_FAIL"):
        print(f"[smoke_load_xodr] Preflight FAILED (status={preflight_status}). Exiting.")
        carla_status.update({"status": "skipped", "reason": f"preflight_failed: {preflight_status}"})
        _write_json(carla_status_path, carla_status)
        run_summary["carla_status"] = str(carla_status_path)
        _write_json(run_summary_path, run_summary)
        return 2
    if preflight_status != "ok":
        print(f"[smoke_load_xodr] Preflight failed but UP_ALLOW_PREFLIGHT_FAIL=1, continuing...")

    if _env_bool("UP_DISABLE_CARLA"):
        carla_status.update({"status": "skipped", "reason": "disabled_by_env"})
        run_summary["carla_status"] = str(carla_status_path)
        run_summary["screenshot_status"] = "skipped"
        run_summary["screenshot_error"] = "disabled_by_env"
        _write_json(carla_status_path, carla_status)
        _write_json(run_summary_path, run_summary)
        return 0

    # Step 2: CARLA load
    print(f"[smoke_load_xodr] Attempting CARLA load (host={args.host}, port={args.port})...")
    try:
        from ultimate_pipeline.optional.carla_api import get_carla
        carla = get_carla()
    except Exception as exc:
        carla_status.update({"status": "fail", "reason": f"carla_import_failed: {exc}"})
        _write_json(carla_status_path, carla_status)
        run_summary["carla_status"] = str(carla_status_path)
        _write_json(run_summary_path, run_summary)
        print(f"[smoke_load_xodr] CARLA import failed: {exc}")
        return 1

    try:
        from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world_from_file
        client = carla.Client(args.host, args.port)
        client.set_timeout(args.timeout)
        t0 = time.time()
        world = load_opendrive_world_from_file(client, xodr_path, timeout_s=args.timeout, retries=1, do_reload=True)
        load_elapsed = time.time() - t0
        carla_map = world.get_map()
        map_name = carla_map.name if carla_map else "unknown"
        carla_status.update({"status": "loaded", "reason": "", "map_name": map_name, "load_elapsed_s": round(load_elapsed, 2)})
        print(f"[smoke_load_xodr] CARLA load SUCCESS (map={map_name}, elapsed={load_elapsed:.1f}s)")

        # Center spectator on map for QA visibility
        spectator_result = _center_spectator_on_map(world, carla)
        carla_status["spectator_transform"] = spectator_result.get("transform")
        carla_status["spectator_method"] = spectator_result.get("method")

    except Exception as exc:
        carla_status.update({"status": "fail", "reason": str(exc)})
        _write_json(carla_status_path, carla_status)
        run_summary["carla_status"] = str(carla_status_path)
        _write_json(run_summary_path, run_summary)
        print(f"[smoke_load_xodr] CARLA load FAILED: {exc}")
        return 1

    _write_json(carla_status_path, carla_status)
    run_summary["carla_status"] = str(carla_status_path)

    # Step 3: Screenshot (best-effort unless --strict-screenshot)
    screenshot_dir = out_dir / "screenshot"
    screenshot_port = args.screenshot_port if args.screenshot_port is not None else args.port
    streaming_disabled = _env_bool("UP_DISABLE_STREAMING") or _env_bool("UP_TILE_QA_DISABLE_STREAMING")
    screenshot_status_detail = {
        "attempted": False,
        "ok": False,
        "error": None,
        "timeout_s": args.screenshot_timeout,
        "cmd": None,
        "retries": max(0, args.screenshot_retries),
    }
    if args.no_screenshot or streaming_disabled:
        run_summary["screenshot_status"] = "skipped"
        if args.no_screenshot:
            run_summary["screenshot_error"] = "disabled_by_flag"
            screenshot_status_detail["error"] = "disabled_by_flag"
            print("[smoke_load_xodr] Screenshot disabled via --no-screenshot.")
        else:
            run_summary["screenshot_error"] = "disabled_by_env"
            screenshot_status_detail["error"] = "disabled_by_env"
            print("[smoke_load_xodr] Screenshot disabled via UP_* streaming flag.")
    else:
        print("[smoke_load_xodr] Capturing screenshot (best-effort)...")
        screenshot_result = _capture_screenshot_best_effort(
            host=args.host,
            port=screenshot_port,
            out_dir=screenshot_dir,
            timeout_s=args.screenshot_timeout,
            retries=max(0, args.screenshot_retries),
        )
        run_summary["screenshot_attempted"] = screenshot_result.get("attempted", False)
        run_summary["screenshot_ok"] = screenshot_result.get("ok", False)
        run_summary["screenshot_error"] = screenshot_result.get("error")
        run_summary["screenshot_cmd"] = screenshot_result.get("cmd")
        run_summary["screenshot_retries"] = screenshot_result.get("retries", max(0, args.screenshot_retries))
        run_summary["screenshot_status"] = "ok" if screenshot_result.get("ok") else "failed"
        screenshot_status_detail.update(
            {
                "attempted": screenshot_result.get("attempted", False),
                "ok": screenshot_result.get("ok", False),
                "error": screenshot_result.get("error"),
                "cmd": screenshot_result.get("cmd"),
                "retries": screenshot_result.get("retries", max(0, args.screenshot_retries)),
            }
        )
        if screenshot_result.get("path"):
            run_summary["screenshot"] = screenshot_result["path"]
            print(f"[smoke_load_xodr] Screenshot saved: {screenshot_result['path']}")
        if not screenshot_result.get("ok") and args.strict_screenshot:
            print("[smoke_load_xodr] WARNING: --strict-screenshot ignored; keeping best-effort behavior.")

    # Optional QA sensors capture (best-effort)
    if args.qa_sensors:
        calib_path = (args.qa_calib or _default_calib_path()).resolve()
        run_summary["qa_sensors_attempted"] = True
        if not calib_path.exists():
            run_summary["qa_sensors_ok"] = False
            run_summary["qa_sensors_error"] = f"calib_not_found: {calib_path}"
            print(f"[smoke_load_xodr] WARNING: QA calib not found: {calib_path}")
        else:
            qa_result = _run_qa_sensors_best_effort(
                xodr_path=xodr_path,
                out_dir=out_dir,
                host=args.host,
                port=args.port,
                calib_json=calib_path,
            )
            run_summary["qa_sensors_ok"] = qa_result.get("ok", False)
            run_summary["qa_sensors_error"] = qa_result.get("error")
            run_summary["qa_sensors_manifest"] = qa_result.get("manifest")
            if not qa_result.get("ok"):
                print("[smoke_load_xodr] WARNING: QA sensors capture failed.")
    else:
        run_summary["qa_sensors_attempted"] = False

    carla_status["screenshot_status"] = screenshot_status_detail
    _write_json(carla_status_path, carla_status)

    # Final summary
    run_summary["success"] = carla_status["status"] == "loaded"
    _write_json(run_summary_path, run_summary)
    print(f"[smoke_load_xodr] Manifest: {run_summary_path}")
    print(f"[smoke_load_xodr] Overall: {'SUCCESS' if run_summary['success'] else 'FAIL'}")
    return 0 if run_summary["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
