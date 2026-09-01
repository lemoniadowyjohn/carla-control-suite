#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CARLA smoke suite (best-effort, never hangs).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return bool(default)
    return v.strip().lower() in ("1", "true", "yes", "on", "y")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_commit(repo_root: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip(), None
        return None, (result.stderr.strip() or f"git rev-parse failed with code {result.returncode}")
    except FileNotFoundError:
        return None, "git not found"
    except subprocess.TimeoutExpired:
        return None, "git command timed out"
    except Exception as exc:  # noqa: BLE001
        return None, f"git error: {exc}"


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)
    path.write_text(text + ("\n" if not text.endswith("\n") else ""), encoding="utf-8", newline="\n")


def _output_root_from_settings() -> Path:
    try:
        from ultimate_pipeline.config.settings import SETTINGS

        return Path(getattr(SETTINGS, "PIPELINE_OUTPUT_ROOT", "ultimate_pipeline_out"))
    except Exception:
        return Path("ultimate_pipeline_out")


def _resolve_run_dir(run_dir_arg: Optional[str]) -> Path:
    if run_dir_arg:
        return Path(run_dir_arg)
    root = _output_root_from_settings()
    if not root.exists():
        return Path(".")
    candidates = [p for p in root.iterdir() if p.is_dir()]
    if not candidates:
        return Path(".")
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _find_xodr_in_run(run_dir: Path) -> Tuple[Optional[Path], str]:
    tile = run_dir / "tiles" / "tile_0_0.xodr"
    if tile.exists():
        return tile, str(tile)

    # mtime-newest, not lexicographic: a run dir can carry multiple
    # 08_final*.xodr variants (plain pre-repair, semantic copy,
    # laneSectionFixed repair) -- lexicographic sort picks the pre-repair
    # file ("." < "_" in ASCII), the exact one the repair exists to
    # supersede (prevents CARLA MapBuilder.cpp asserts on load -- directly
    # relevant to this being a CARLA smoke-test tool). Matches the
    # convention already established in artifact_locator.py.
    finals = sorted(run_dir.glob("08_final*.xodr"), key=lambda p: p.stat().st_mtime, reverse=True)
    if finals:
        return finals[0], str(finals[0])

    others = sorted(run_dir.rglob("*.xodr"))
    if others:
        return others[0], str(others[0])
    return None, "not_found"


def _bounds_from_points(points) -> Optional[Dict[str, Any]]:
    if not points:
        return None
    xs = [p.location.x for p in points]
    ys = [p.location.y for p in points]
    return {
        "x_min": min(xs),
        "x_max": max(xs),
        "y_min": min(ys),
        "y_max": max(ys),
    }


def _build_manifest(xodr_path: Optional[Path]) -> Dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[2]
    git_commit, git_err = _git_commit(repo_root)
    inputs = {}
    if xodr_path and xodr_path.exists():
        inputs["xodr_path"] = str(xodr_path)
        inputs["xodr_sha256"] = _sha256(xodr_path)
    return {
        "generated_at_utc": _utc_now(),
        "python_version": sys.version.replace("\n", " "),
        "git_commit": git_commit,
        "git_commit_error": git_err,
        "inputs": inputs,
    }


def _get_carla():
    from ultimate_pipeline.optional.carla_api import get_carla

    return get_carla()


def _load_world(client, xodr_path: Path, timeout: float):
    from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world_from_file

    return load_opendrive_world_from_file(client, xodr_path, timeout_s=timeout, retries=1, do_reload=True)


def run_smoke_suite(
    *,
    xodr_path: Path,
    host: str,
    port: int,
    timeout: float,
    out_dir: Path,
    spawn_ego: bool,
    tick_frames: int,
    screenshot: bool,
    screenshot_timeout: float,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "load_ok": False,
        "error": "",
        "xodr_used": None,
        "xodr_hardener": None,
        "spawn_points_count": 0,
        "waypoints_count": 0,
        "map_bounds": None,
        "ego_spawn_ok": False,
        "tick_ok": False,
        "screenshot_status": {"attempted": False, "ok": False, "error": None, "path": None},
    }
    try:
        carla = _get_carla()
        client = carla.Client(host, port)
        client.set_timeout(timeout)

        # Optional: harden XODR before CARLA import (reduces known crash patterns).
        used_xodr = xodr_path
        hardener_info: Dict[str, Any] = {
            "enabled": _env_bool("UP_ENABLE_XODR_HARDENER", True),
            "applied": False,
            "repair_parampoly3_to_line": _env_bool("UP_REPAIR_PARAMPOLY3_TO_LINE", False),
            "report_path": None,
            "error": None,
        }
        if hardener_info["enabled"]:
            try:
                from ultimate_pipeline.tools.xodr_carla_hardener import harden_xodr

                hardened_path = out_dir / "xodr_hardened.xodr"
                report_path = out_dir / "xodr_hardener_report.json"
                harden_xodr(
                    xodr_path,
                    hardened_path,
                    report_path=report_path,
                    repair_parampoly3_to_line=bool(hardener_info["repair_parampoly3_to_line"]),
                )
                if hardened_path.exists():
                    used_xodr = hardened_path
                    hardener_info["applied"] = True
                    hardener_info["report_path"] = str(report_path)
            except Exception as exc:
                hardener_info["error"] = str(exc)
                used_xodr = xodr_path

        payload["xodr_used"] = str(used_xodr)
        payload["xodr_hardener"] = hardener_info

        world = _load_world(client, used_xodr, timeout)
        carla_map = world.get_map()
        spawn_points = carla_map.get_spawn_points()
        payload["spawn_points_count"] = len(spawn_points)
        waypoints = carla_map.generate_waypoints(2.0)
        payload["waypoints_count"] = len(waypoints)
        bounds = _bounds_from_points(spawn_points) or _bounds_from_points(waypoints)
        payload["map_bounds"] = bounds
        payload["load_ok"] = True
        payload["error"] = ""

        ego_actor = None
        if spawn_ego and spawn_points:
            try:
                blueprint = world.get_blueprint_library().filter("vehicle.*")[0]
                ego_actor = world.spawn_actor(blueprint, spawn_points[0])
                payload["ego_spawn_ok"] = ego_actor is not None
            except Exception as exc:  # noqa: BLE001
                payload["ego_spawn_ok"] = False
                payload["error"] = f"ego_spawn_failed: {exc}"

        if tick_frames > 0:
            try:
                for _ in range(tick_frames):
                    world.tick()
                payload["tick_ok"] = True
            except Exception as exc:  # noqa: BLE001
                payload["tick_ok"] = False
                if not payload["error"]:
                    payload["error"] = f"tick_failed: {exc}"

        if ego_actor is not None:
            try:
                ego_actor.destroy()
            except Exception:
                pass

        streaming_disabled = os.environ.get("UP_DISABLE_STREAMING") or os.environ.get("UP_TILE_QA_DISABLE_STREAMING")
        if screenshot and not streaming_disabled:
            from ultimate_pipeline.tools.smoke_load_xodr import _capture_screenshot_best_effort

            screenshot_dir = out_dir / "screenshot"
            result = _capture_screenshot_best_effort(
                host=host,
                port=port,
                out_dir=screenshot_dir,
                timeout_s=screenshot_timeout,
                retries=0,
            )
            payload["screenshot_status"] = {
                "attempted": result.get("attempted", False),
                "ok": result.get("ok", False),
                "error": result.get("error"),
                "path": result.get("path"),
            }
    except Exception as exc:  # noqa: BLE001
        payload["load_ok"] = False
        payload["error"] = str(exc)
    return payload


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run CARLA smoke suite on an OpenDRIVE map.")
    group = p.add_mutually_exclusive_group(required=False)
    group.add_argument("--xodr", type=Path, help="Input OpenDRIVE file")
    group.add_argument("--run-dir", type=Path, help="Run directory containing tiles or final XODR")
    p.add_argument("--host", default=os.getenv("UP_CARLA_HOST", "127.0.0.1"), help="CARLA host")
    p.add_argument("--port", type=int, default=int(os.getenv("UP_CARLA_PORT", "2000")), help="CARLA port")
    p.add_argument("--timeout", type=float, default=120.0, help="Load timeout (s)")
    p.add_argument("--out", type=Path, required=True, help="Output directory for smoke_suite.json")
    p.add_argument("--spawn-ego", action="store_true", help="Spawn an ego vehicle at a spawn point")
    p.add_argument("--tick-frames", type=int, default=0, help="Tick world N frames (best-effort)")
    p.add_argument("--screenshot", action="store_true", help="Capture a best-effort screenshot")
    p.add_argument("--screenshot-timeout", type=float, default=8.0, help="Screenshot timeout (s)")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    run_dir = _resolve_run_dir(str(args.run_dir) if args.run_dir else None)
    if args.xodr:
        xodr_path = args.xodr
    else:
        xodr_path, _reason = _find_xodr_in_run(run_dir)

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "smoke_suite.json"
    manifest_path = out_dir / "smoke_suite_manifest.json"

    if not xodr_path or not xodr_path.exists():
        payload = {
            "load_ok": False,
            "error": "xodr_missing",
            "spawn_points_count": 0,
            "waypoints_count": 0,
            "map_bounds": None,
            "ego_spawn_ok": False,
            "tick_ok": False,
            "screenshot_status": {"attempted": False, "ok": False, "error": "xodr_missing", "path": None},
        }
        _write_json(report_path, payload)
        _write_json(manifest_path, _build_manifest(xodr_path if xodr_path else None))
        return 2

    payload = run_smoke_suite(
        xodr_path=xodr_path,
        host=args.host,
        port=args.port,
        timeout=args.timeout,
        out_dir=out_dir,
        spawn_ego=args.spawn_ego,
        tick_frames=max(0, args.tick_frames),
        screenshot=args.screenshot,
        screenshot_timeout=args.screenshot_timeout,
    )
    _write_json(report_path, payload)
    _write_json(manifest_path, _build_manifest(xodr_path))
    return 0 if payload.get("load_ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
