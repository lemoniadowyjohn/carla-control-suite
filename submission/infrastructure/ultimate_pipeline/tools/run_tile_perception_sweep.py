from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple


def _parse_args(argv: Sequence[str]) -> Tuple[argparse.Namespace, List[str]]:
    ap = argparse.ArgumentParser(
        description="Run perception capture over auto-generated XODR tiles."
    )
    ap.add_argument(
        "--tiles-dir",
        required=True,
        type=Path,
        help="Directory containing tile_i_j.xodr files.",
    )
    ap.add_argument(
        "--max-tiles",
        type=int,
        default=5,
        help="Maximum number of tile XODRs to process (default: 5).",
    )
    ap.add_argument(
        "--out-root",
        type=Path,
        default=Path("recordings") / "tile_sweep",
        help="Root directory for tile outputs (default: recordings/tile_sweep).",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the selected tile paths without launching CARLA.",
    )
    ap.add_argument(
        "--manual-town",
        default="Grid0821",
        help="Manual-town reference passed to run_perception_safe (default: Grid0821).",
    )
    ap.add_argument(
        "--sort-by-size",
        action="store_true",
        default=False,
        help=(
            "Sort tiles by file size descending "
            "(largest = most roads = best spawn rate)."
        ),
    )
    return ap.parse_known_args(list(argv))


def _extract_arg_value(args: Sequence[str], flag: str) -> str | None:
    for idx, token in enumerate(args):
        if token == flag and idx + 1 < len(args):
            return str(args[idx + 1])
        if token.startswith(flag + "="):
            return token.split("=", 1)[1]
    return None


def _without_flag(args: Sequence[str], flag: str) -> List[str]:
    cleaned: List[str] = []
    skip_next = False
    for token in args:
        if skip_next:
            skip_next = False
            continue
        if token == flag:
            skip_next = True
            continue
        if token.startswith(flag + "="):
            continue
        cleaned.append(token)
    return cleaned


def _resolve_out_root(path_arg: Path) -> Path:
    requested = Path(path_arg).expanduser()
    return requested if requested.is_absolute() else Path.cwd() / requested


def _collect_tiles(
    tiles_dir: Path,
    max_tiles: int,
    sort_by_size: bool = False,
) -> List[Path]:
    tiles = [p for p in tiles_dir.glob("*.xodr") if p.is_file()]
    if sort_by_size:
        tiles = sorted(tiles, key=lambda p: -p.stat().st_size)
    else:
        tiles = sorted(tiles, key=lambda p: p.name)
    return tiles[: max(0, int(max_tiles))]


def _read_json_if_dict(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_command(
    *,
    tile_path: Path,
    out_dir: Path,
    manual_town: str,
    passthrough: Sequence[str],
) -> List[str]:
    forwarded = list(passthrough)
    for flag in ("--xodr-in", "--out", "--manual-town"):
        forwarded = _without_flag(forwarded, flag)

    cmd = [
        sys.executable,
        "-m",
        "ultimate_pipeline.tools.run_perception_safe",
        "--enable-capture",
        "--relax-evidence-pack",
        "--manual-town",
        str(manual_town),
        "--xodr-in",
        str(tile_path),
        "--out",
        str(out_dir),
    ]
    cmd.extend(forwarded)
    return cmd


def _tile_status_payload(
    *,
    tile_id: str,
    tile_path: Path,
    out_dir: Path,
    result: subprocess.CompletedProcess[str] | None,
    dry_run: bool,
) -> Dict[str, Any]:
    recording_summary = _read_json_if_dict(out_dir / "recording_summary.json")
    perception_status = _read_json_if_dict(out_dir / "perception_status.json")

    frames_recorded = int(
        recording_summary.get(
            "frames_recorded",
            perception_status.get("frames_recorded", 0),
        )
        or 0
    )
    semseg_files = int(
        recording_summary.get(
            "semseg_files",
            perception_status.get("semseg_files", 0),
        )
        or 0
    )
    evidence_pack_ok = bool(perception_status.get("evidence_pack_ok", False))

    payload: Dict[str, Any] = {
        "tile_id": str(tile_id),
        "tile_path": str(tile_path),
        "output_dir": str(out_dir),
        "dry_run": bool(dry_run),
        "frames_recorded": int(frames_recorded),
        "semseg_files": int(semseg_files),
        "evidence_pack_ok": bool(evidence_pack_ok),
        "recording_status": str(recording_summary.get("status", "") or ""),
        "failure_reason": str(
            recording_summary.get("failure_reason")
            or perception_status.get("failure_reason")
            or ""
        ),
        "carla_status_present": (out_dir / "carla_status.json").is_file(),
        "perception_status_present": (out_dir / "perception_status.json").is_file(),
        "recording_summary_present": (out_dir / "recording_summary.json").is_file(),
    }
    if result is not None:
        payload["returncode"] = int(result.returncode)
    return payload


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args, passthrough = _parse_args(sys.argv[1:] if argv is None else argv)
    tiles_dir = Path(args.tiles_dir).expanduser()
    if not tiles_dir.is_dir():
        raise SystemExit(f"--tiles-dir not found: {tiles_dir}")

    out_root = _resolve_out_root(Path(args.out_root))
    tiles = _collect_tiles(
        tiles_dir,
        int(args.max_tiles),
        sort_by_size=bool(getattr(args, "sort_by_size", False)),
    )
    if not tiles:
        raise SystemExit(f"No .xodr tiles found under: {tiles_dir}")

    tile_results: List[Dict[str, Any]] = []
    tiles_captured = 0
    tiles_with_frames = 0
    total_frames = 0

    for tile_path in tiles:
        tile_id = tile_path.stem
        out_dir = out_root / tile_id
        if args.dry_run:
            print(str(tile_path))
            tile_results.append(
                {
                    "tile_id": tile_id,
                    "tile_path": str(tile_path),
                    "dry_run": True,
                }
            )
            continue

        out_dir.mkdir(parents=True, exist_ok=True)
        cmd = _build_command(
            tile_path=tile_path,
            out_dir=out_dir,
            manual_town=str(args.manual_town),
            passthrough=passthrough,
        )
        result = subprocess.run(cmd, text=True, check=False)
        tile_status = _tile_status_payload(
            tile_id=tile_id,
            tile_path=tile_path,
            out_dir=out_dir,
            result=result,
            dry_run=False,
        )
        _write_json(out_dir / "tile_status.json", tile_status)
        tile_results.append(tile_status)
        tiles_captured += 1
        frames_recorded = int(tile_status.get("frames_recorded", 0) or 0)
        total_frames += frames_recorded
        if frames_recorded > 0:
            tiles_with_frames += 1
        else:
            print(f"WARNING: {tile_id} recorded 0 frames; continuing.")

    sweep_summary = {
        "tiles_attempted": int(len(tiles)),
        "tiles_captured": int(tiles_captured),
        "tiles_with_frames": int(tiles_with_frames),
        "total_frames": int(total_frames),
        "tile_results": tile_results,
    }
    _write_json(out_root / "sweep_summary.json", sweep_summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
