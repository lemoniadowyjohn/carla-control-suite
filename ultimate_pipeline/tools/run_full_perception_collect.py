from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


def _read_json_if_dict(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _resolve_out_root(path_arg: Path) -> Path:
    requested = Path(path_arg).expanduser()
    return requested if requested.is_absolute() else Path.cwd() / requested


def _manual_slug(args: argparse.Namespace) -> str:
    return str(getattr(args, "manual_town", "Grid0821") or "Grid0821").strip().lower()


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Run manual and auto-tile perception collection in sequence."
    )
    ap.add_argument("--tiles-dir", required=True, type=Path)
    ap.add_argument(
        "--manual-town",
        type=str,
        default="Grid0821",
        help="Manual cooked town for reference capture (default: Grid0821).",
    )
    ap.add_argument("--max-tiles", type=int, default=5)
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--seg", action="store_true")
    ap.add_argument("--num-npcs", type=int, default=5)
    ap.add_argument("--out-root", type=Path, default=Path("thesis_results") / "perception_v1")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-manual", action="store_true")
    ap.add_argument("--skip-tiles", action="store_true")
    ap.add_argument(
        "--calib",
        type=str,
        default="",
        help=(
            "Path to calib JSON. Passed to run_perception_safe --calib. "
            "If empty, run_perception_safe uses its own default."
        ),
    )
    ap.add_argument(
        "--whole-map-xodr",
        type=str,
        default="",
        help=(
            "If set, run auto phase against this single XODR (whole-map mode) "
            "instead of tile sweep. Recommended: "
            "domain_gap_results/auto_aligned_hardened.xodr"
        ),
    )
    ap.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="CARLA server host (default: 127.0.0.1)",
    )
    ap.add_argument(
        "--port",
        type=int,
        default=2000,
        help="CARLA server port (default: 2000)",
    )
    ap.add_argument(
        "--record-route-timeout-s",
        type=float,
        default=300.0,
        help="Timeout budget for each run_perception_safe invocation (default: 300s).",
    )
    ap.add_argument(
        "--sort-by-size",
        action="store_true",
        default=False,
        help="Sort tiles by file size (descending) before sweep.",
    )
    ap.add_argument(
        "--skip-stream-check",
        dest="skip_stream_check",
        action="store_true",
        default=True,
        help="Propagate --skip-stream-check to run_perception_safe invocations.",
    )
    ap.add_argument(
        "--enforce-stream-check",
        dest="skip_stream_check",
        action="store_false",
        help="Disable --skip-stream-check propagation and enforce stream probes.",
    )
    ap.add_argument(
        "--preload-grid0821",
        dest="preload_grid0821",
        action="store_true",
        default=None,
        help="Preload manual town before manual capture.",
    )
    ap.add_argument(
        "--no-preload-grid0821",
        dest="preload_grid0821",
        action="store_false",
        help="Disable manual-town preload for cooked manual towns.",
    )
    return ap.parse_args(list(argv))


def _run_command(cmd: List[str], dry_run: bool) -> int:
    print("CMD:", subprocess.list2cmdline(cmd))
    if dry_run:
        return 0
    result = subprocess.run(cmd, text=True, check=False)
    return int(result.returncode)


def _should_preload_manual_town(args: argparse.Namespace) -> bool:
    manual_town = str(getattr(args, "manual_town", "") or "").strip()
    if (not manual_town) or manual_town.lower().endswith(".xodr"):
        return False
    preload_override: Optional[bool] = getattr(args, "preload_grid0821", None)
    if preload_override is None:
        return True
    return bool(preload_override)


def _preload_manual_town(args: argparse.Namespace, out_root: Path) -> bool:
    manual_town = str(getattr(args, "manual_town", "") or "").strip() or "Grid0821"
    status_path = out_root / "preload_status.json"
    payload: Dict[str, Any] = {
        "status": "STARTED",
        "map": str(manual_town),
        "host": str(args.host),
        "port": int(args.port),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(status_path, payload)
    if bool(getattr(args, "dry_run", False)):
        print(f"Preloading {manual_town}... (dry-run)", flush=True)
        payload.update(
            {
                "status": "DRY_RUN",
                "actual_map_name": str(manual_town),
                "stabilization_wait_s": 0,
            }
        )
        _write_json(status_path, payload)
        return True
    try:
        import carla  # type: ignore

        client = carla.Client(str(args.host), int(args.port))
        client.set_timeout(180.0)
        print(f"Preloading {manual_town}...", flush=True)
        world = client.load_world(str(manual_town))
        map_name = str(world.get_map().name or "")
        spawn_points = len(world.get_map().get_spawn_points() or [])
        print(f"Preloaded map: {map_name} | spawn points: {spawn_points}", flush=True)
        print("Waiting 25s for map stabilization...", flush=True)
        time.sleep(25.0)
        payload.update(
            {
                "status": "OK",
                "actual_map_name": map_name,
                "spawn_points": int(spawn_points),
                "stabilization_wait_s": 25,
            }
        )
        _write_json(status_path, payload)
        return True
    except Exception as exc:
        payload.update({"status": "MAP_PRELOAD_FAILED", "error": str(exc)})
        _write_json(status_path, payload)
        return False


def _manual_phase(args: argparse.Namespace, out_root: Path) -> Dict[str, Any]:
    if args.skip_manual:
        return {"status": "skipped", "frames_recorded": 0}

    manual_out = out_root / f"manual_{_manual_slug(args)}"
    cmd = [
        sys.executable,
        "-m",
        "ultimate_pipeline.tools.run_perception_safe",
        "--enable-capture",
        "--relax-evidence-pack",
        "--manual-town",
        str(args.manual_town),
        "--town",
        str(args.manual_town),
        "--use-current-world",
        "--frames",
        str(int(args.frames)),
        "--record-route-timeout-s",
        str(float(args.record_route_timeout_s)),
        "--out",
        str(manual_out),
    ]
    if bool(getattr(args, "skip_stream_check", True)):
        cmd.append("--skip-stream-check")
    if args.seg:
        cmd.append("--seg")
    if int(getattr(args, "num_npcs", 0) or 0) > 0:
        cmd += ["--num-npcs", str(int(args.num_npcs))]
    if getattr(args, "calib", ""):
        cmd += ["--calib", str(args.calib)]
    cmd += ["--host", str(args.host), "--port", str(args.port)]

    return_code = _run_command(cmd, bool(args.dry_run))
    if args.dry_run:
        return {
            "status": "skipped",
            "frames_recorded": 0,
            "returncode": 0,
            "output_dir": str(manual_out),
        }

    recording_summary = _read_json_if_dict(manual_out / "recording_summary.json")
    frames_recorded = int(recording_summary.get("frames_recorded", 0) or 0)
    status = "ok" if return_code == 0 and frames_recorded > 0 else "failed"
    return {
        "status": status,
        "frames_recorded": frames_recorded,
        "returncode": int(return_code),
        "output_dir": str(manual_out),
    }


def _tiles_phase(args: argparse.Namespace, out_root: Path) -> Dict[str, Any]:
    if args.skip_tiles:
        return {
            "status": "skipped",
            "tiles_attempted": 0,
            "tiles_with_frames": 0,
            "total_frames": 0,
        }

    auto_out = out_root / "auto_tiles"
    cmd = [
        sys.executable,
        "-m",
        "ultimate_pipeline.tools.run_tile_perception_sweep",
        "--tiles-dir",
        str(Path(args.tiles_dir).expanduser()),
        "--max-tiles",
        str(int(args.max_tiles)),
        "--out-root",
        str(auto_out),
        "--manual-town",
        str(args.manual_town),
    ]
    if bool(getattr(args, "sort_by_size", False)):
        cmd.append("--sort-by-size")
    cmd += [
        "--frames",
        str(int(args.frames)),
        "--num-npcs",
        str(int(args.num_npcs)),
        "--record-route-timeout-s",
        str(float(args.record_route_timeout_s)),
    ]
    if bool(getattr(args, "skip_stream_check", True)):
        cmd.append("--skip-stream-check")
    if getattr(args, "calib", ""):
        cmd += ["--calib", str(args.calib)]
    cmd += ["--host", str(args.host), "--port", str(args.port)]
    if args.seg:
        cmd.append("--seg")

    return_code = _run_command(cmd, bool(args.dry_run))
    if args.dry_run:
        return {
            "status": "skipped",
            "tiles_attempted": int(args.max_tiles),
            "tiles_with_frames": 0,
            "total_frames": 0,
            "returncode": 0,
            "output_dir": str(auto_out),
        }

    sweep_summary = _read_json_if_dict(auto_out / "sweep_summary.json")
    tiles_attempted = int(sweep_summary.get("tiles_attempted", 0) or 0)
    tiles_with_frames = int(sweep_summary.get("tiles_with_frames", 0) or 0)
    total_frames = int(sweep_summary.get("total_frames", 0) or 0)
    status = "ok" if return_code == 0 and total_frames > 0 else "failed"
    return {
        "status": status,
        "tiles_attempted": tiles_attempted,
        "tiles_with_frames": tiles_with_frames,
        "total_frames": total_frames,
        "returncode": int(return_code),
        "output_dir": str(auto_out),
    }


def _whole_map_phase(args: argparse.Namespace, out_root: Path) -> Dict[str, Any]:
    whole_map_out = out_root / "auto_whole_map"
    xodr_path = Path(args.whole_map_xodr).expanduser()
    if not xodr_path.is_absolute():
        xodr_path = Path.cwd() / xodr_path
    cmd = [
        sys.executable,
        "-m",
        "ultimate_pipeline.tools.run_perception_safe",
        "--enable-capture",
        "--relax-evidence-pack",
        "--xodr-in",
        str(xodr_path),
        "--frames",
        str(int(args.frames)),
        "--record-route-timeout-s",
        str(float(args.record_route_timeout_s)),
        "--host",
        str(args.host),
        "--port",
        str(args.port),
        "--out",
        str(whole_map_out),
    ]
    if bool(getattr(args, "skip_stream_check", True)):
        cmd.append("--skip-stream-check")
    if getattr(args, "calib", ""):
        cmd += ["--calib", str(args.calib)]
    if args.seg:
        cmd.append("--seg")
    if getattr(args, "num_npcs", 0) > 0:
        cmd += ["--num-npcs", str(args.num_npcs)]
    return_code = _run_command(cmd, bool(args.dry_run))
    if args.dry_run:
        return {
            "status": "dry_run",
            "frames_recorded": 0,
            "returncode": 0,
            "output_dir": str(whole_map_out),
            "mode": "whole_map",
        }
    recording_summary = _read_json_if_dict(whole_map_out / "recording_summary.json")
    frames_recorded = int(recording_summary.get("frames_recorded", 0) or 0)
    return {
        "status": "ok" if return_code == 0 and frames_recorded > 0 else "failed",
        "frames_recorded": frames_recorded,
        "returncode": int(return_code),
        "output_dir": str(whole_map_out),
        "mode": "whole_map",
        "xodr": str(xodr_path),
    }


def _rq3_status(*, dry_run: bool, manual_frames: int, auto_frames: int) -> str:
    if dry_run:
        return "DRY_RUN"
    if manual_frames > 0 and auto_frames > 0:
        return "COMPLETE"
    if manual_frames > 0 or auto_frames > 0:
        return "PARTIAL"
    return "BLOCKED"


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    out_root = _resolve_out_root(Path(args.out_root))
    out_root.mkdir(parents=True, exist_ok=True)

    if (not bool(args.skip_manual)) and _should_preload_manual_town(args):
        if not _preload_manual_town(args, out_root):
            print("RQ3 STATUS: BLOCKED")
            return 1

    manual = _manual_phase(args, out_root)
    if getattr(args, "whole_map_xodr", ""):
        auto_tiles = _whole_map_phase(args, out_root)
    else:
        auto_tiles = _tiles_phase(args, out_root)

    manual_frames = int(manual.get("frames_recorded", 0) or 0)
    auto_total_frames = int(
        auto_tiles.get("total_frames", auto_tiles.get("frames_recorded", 0)) or 0
    )
    manual_key = f"manual_{_manual_slug(args)}"

    summary = {
        manual_key: {
            "frames_recorded": manual_frames,
            "status": str(manual.get("status", "skipped")),
        },
        "auto_tiles": {
            "tiles_attempted": int(auto_tiles.get("tiles_attempted", 0) or 0),
            "tiles_with_frames": int(auto_tiles.get("tiles_with_frames", 0) or 0),
            "total_frames": auto_total_frames,
        },
        "rq3_evidence_complete": bool(manual_frames > 0 and auto_total_frames > 0),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dry_run": bool(args.dry_run),
    }

    _write_json(out_root / "collection_summary.json", summary)
    pair_report = {
        "auto": {
            "mode": auto_tiles.get("mode", "tiles"),
            "xodr": auto_tiles.get("xodr", auto_tiles.get("output_dir", "")),
            "frames_recorded": auto_total_frames,
            "output_dir": auto_tiles.get("output_dir", ""),
            "status": auto_tiles.get("status", ""),
        },
        "manual": {
            "map": str(args.manual_town),
            "frames_recorded": manual_frames,
            "output_dir": manual.get("output_dir", ""),
            "status": manual.get("status", ""),
        },
        "pair_complete": bool(manual_frames > 0 and auto_total_frames > 0),
        "calib_used": str(getattr(args, "calib", "") or "run_perception_safe_default"),
        "host": str(args.host),
        "port": int(args.port),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dry_run": bool(args.dry_run),
    }
    _write_json(out_root / "perception_pair_report.json", pair_report)

    rq3_status = _rq3_status(
        dry_run=bool(args.dry_run),
        manual_frames=manual_frames,
        auto_frames=auto_total_frames,
    )
    print(f"RQ3 STATUS: {rq3_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
