#!/usr/bin/env python3
"""
Windows-friendly manual tiler (self-contained, no subprocess).

Outputs:
  <out>/tiles/tile_*.xodr
  <out>/tile_metadata.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Tuple

from ultimate_pipeline.tiling.tile_extractor import TileExtractor
from ultimate_pipeline.tiling.tile_metadata import TileMetadata
from ultimate_pipeline.core.georef_utils import parse_georeference


def _validate_inputs(xodr_path: Path, tile_size: float, buffer_m: float) -> Tuple[bool, str]:
    if not xodr_path.is_file():
        return False, f"Manual XODR not found: {xodr_path}"
    if tile_size <= 0:
        return False, "tile-size must be greater than zero"
    if buffer_m < 0:
        return False, "buffer-m must be zero or positive"
    return True, ""


def _post_check(out_dir: Path, tiles_dir: Path) -> Tuple[bool, int]:
    meta_path = out_dir / "tile_metadata.json"
    tiles = list(tiles_dir.glob("tile_*.xodr"))
    if not meta_path.is_file():
        print(f"ERROR: Missing tile_metadata.json at {meta_path}")
        return False, 5
    if not tiles:
        print(f"ERROR: No tile_*.xodr found under {tiles_dir}")
        return False, 6
    print(f"OK: metadata: {meta_path}")
    print(f"OK: tiles_dir: {tiles_dir} (count={len(tiles)})")
    return True, 0


def _read_georef_info(xodr_path: Path) -> Tuple[str, bool]:
    try:
        import xml.etree.ElementTree as ET
        root = ET.parse(str(xodr_path)).getroot()
        header = root.find("header")
        if header is None:
            return "", False
        geo = header.find("geoReference")
        valid, params_complete, norm = parse_georeference(geo.text if geo is not None else None)
        return str(norm or ""), bool(params_complete)
    except Exception:
        return "", False


def _read_origin_from_meta(path: Path) -> Tuple[float | None, float | None, float | None, float | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None, None, None, None

    if isinstance(data, dict) and "tiles" in data and "origin_x" in data and "origin_y" in data:
        try:
            ox = float(data.get("origin_x"))
            oy = float(data.get("origin_y"))
        except Exception:
            ox = oy = None
        try:
            ts = float(data.get("tile_size_m")) if data.get("tile_size_m") is not None else None
        except Exception:
            ts = None
        try:
            bm = float(data.get("buffer_m")) if data.get("buffer_m") is not None else None
        except Exception:
            bm = None
        return ox, oy, ts, bm

    if isinstance(data, dict):
        min_x = None
        min_y = None
        for k, v in data.items():
            if not isinstance(k, str) or k.startswith("_") or not isinstance(v, dict):
                continue
            bbox = v.get("bbox") or {}
            bounds = v.get("bounds")
            if isinstance(bounds, (list, tuple)) and len(bounds) == 4:
                try:
                    bx0, by0 = float(bounds[0]), float(bounds[1])
                except Exception:
                    continue
            elif isinstance(bbox, dict):
                try:
                    bx0, by0 = float(bbox.get("min_x")), float(bbox.get("min_y"))
                except Exception:
                    continue
            else:
                continue
            if min_x is None or bx0 < min_x:
                min_x = bx0
            if min_y is None or by0 < min_y:
                min_y = by0
        return min_x, min_y, None, None

    return None, None, None, None


def _write_diagnostics(out_dir: Path, diag: dict) -> None:
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    diag_path = out_dir / "tiler_diagnostics.json"
    try:
        diag_path.write_text(json.dumps(diag, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"WARNING: Failed to write diagnostics: {exc}")


def _write_console_log(out_dir: Path, lines: list[str]) -> None:
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    log_path = out_dir / "tiler_console.log"
    try:
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"WARNING: Failed to write console log: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Tile a manual OpenDRIVE (.xodr) map (Windows-safe).")
    ap.add_argument("--xodr", required=True, help="Path to manual .xodr file")
    ap.add_argument("--out", required=True, help="Output directory for tiles + metadata")
    ap.add_argument("--tile-size", type=float, default=500.0, help="Tile size in meters (default: 500)")
    ap.add_argument("--buffer-m", type=float, default=50.0, help="Buffer in meters (default: 50)")
    ap.add_argument("--origin-x", type=float, default=None, help="Optional grid origin X override (meters)")
    ap.add_argument("--origin-y", type=float, default=None, help="Optional grid origin Y override (meters)")
    ap.add_argument("--origin-from-meta", default="", help="Optional tile_manifest.json or tile_metadata.json to copy grid origin")
    ap.add_argument("--overwrite", action="store_true", help="Accepted as a no-op for compatibility")
    args = ap.parse_args()

    start_time = time.time()
    xodr_path = Path(args.xodr).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    tiles_dir = out_dir / "tiles"
    log_lines: list[str] = []

    def _log(msg: str) -> None:
        print(msg)
        log_lines.append(msg)

    diag = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python_executable": sys.executable,
        "argv": sys.argv,
        "manual_xodr_path": str(xodr_path),
        "out_dir": str(out_dir),
        "tiles_dir": str(tiles_dir),
        "resolved_paths": {
            "xodr": str(xodr_path),
            "out": str(out_dir),
            "tiles_dir": str(tiles_dir),
        },
        "tile_size_m": float(args.tile_size),
        "buffer_m": float(args.buffer_m),
        "origin_x": args.origin_x,
        "origin_y": args.origin_y,
        "origin_override_used": {"x": args.origin_x, "y": args.origin_y, "from_origin_from_meta": False},
        "roads_scanned": None,
        "candidate_tiles": None,
        "tiles_written": 0,
        "first_error": None,
        "exception": None,
        "runtime_sec": None,
    }
    return_code = 0

    try:
        if args.origin_from_meta:
            meta_path = Path(args.origin_from_meta).expanduser()
            if meta_path.is_file():
                ox, oy, ts, bm = _read_origin_from_meta(meta_path)
                if ox is not None and args.origin_x is None:
                    args.origin_x = ox
                if oy is not None and args.origin_y is None:
                    args.origin_y = oy
                if ts is not None and args.tile_size == 500.0:
                    args.tile_size = float(ts)
                if bm is not None and args.buffer_m == 50.0:
                    args.buffer_m = float(bm)
                _log(f"INFO: origin-from-meta: {meta_path}")
                if ox is not None or oy is not None:
                    _log(f"INFO: origin override: x={args.origin_x} y={args.origin_y}")
                diag["origin_override_used"]["from_origin_from_meta"] = True
            else:
                _log(f"WARNING: origin-from-meta not found: {meta_path}")
            diag["tile_size_m"] = float(args.tile_size)
            diag["buffer_m"] = float(args.buffer_m)
            diag["origin_x"] = args.origin_x
            diag["origin_y"] = args.origin_y
            diag["origin_override_used"]["x"] = args.origin_x
            diag["origin_override_used"]["y"] = args.origin_y

        ok, msg = _validate_inputs(xodr_path, args.tile_size, args.buffer_m)
        if not ok:
            diag["first_error"] = msg
            _log(f"ERROR: {msg}")
            return_code = 2
            return return_code

        if args.overwrite:
            _log("INFO: --overwrite provided (no-op)")

        try:
            tiles_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            diag["first_error"] = f"Could not create output directory {tiles_dir} ({exc})"
            _log(f"ERROR: Could not create output directory {tiles_dir} ({exc})")
            return_code = 3
            return return_code

        _log(f"INFO: Tiling manual map -> {tiles_dir}")
        if int(os.getenv("UP_TILE_PROGRESS_EVERY", "0") or "0") > 0:
            _log("INFO: Tile progress logging enabled via UP_TILE_PROGRESS_EVERY")
        try:
            tiles, tile_health = TileExtractor.tile(
                str(xodr_path),
                str(tiles_dir),
                tile_size=float(args.tile_size),
                tile_buffer_m=float(args.buffer_m),
                origin_x=args.origin_x,
                origin_y=args.origin_y,
            )
        except Exception as exc:
            diag["first_error"] = f"Tiler failed: {exc}"
            _log(f"ERROR: Tiler failed: {exc}")
            return_code = 4
            return return_code

        metadata_path = out_dir / "tile_metadata.json"
        try:
            TileMetadata.write_from_health(str(tiles_dir), tile_health, str(metadata_path))
        except Exception as exc:
            diag["first_error"] = f"Failed to write tile metadata: {exc}"
            _log(f"ERROR: Failed to write tile metadata: {exc}")
            return_code = 5
            return return_code

        georef_norm, georef_params_complete = _read_georef_info(xodr_path)
        manifest_path = out_dir / "tile_manifest.json"
        frame_method = "native" if (args.origin_x is None and args.origin_y is None) else "origin_override"
        transform = None
        if frame_method == "origin_override":
            transform = {"origin_x": args.origin_x, "origin_y": args.origin_y}
        try:
            TileMetadata.write_manifest(
                str(tiles_dir),
                str(metadata_path),
                str(manifest_path),
                proj4_norm=georef_norm,
                proj4_params_complete=georef_params_complete,
                tile_size_m=float(args.tile_size),
                buffer_m=float(args.buffer_m),
                frame_method=frame_method,
                transform=transform,
                origin_x=args.origin_x,
                origin_y=args.origin_y,
            )
            _log(f"OK: manifest: {manifest_path}")
            if georef_norm:
                _log(f"OK: canonical CRS (proj4_norm): {georef_norm}")
                if not georef_params_complete:
                    _log("WARNING: geoReference params incomplete (params_complete=false)")
        except Exception as exc:
            diag["first_error"] = f"Failed to write tile manifest: {exc}"
            _log(f"ERROR: Failed to write tile manifest: {exc}")
            return_code = 7
            return return_code

        roads_scanned = None
        candidate_tiles = None
        if isinstance(tile_health, dict):
            roads_scanned = tile_health.get("roads_scanned", None)
            candidate_tiles = tile_health.get("candidate_tiles", None)
        diag["roads_scanned"] = roads_scanned
        diag["candidate_tiles"] = candidate_tiles
        tile_count = len(tiles) if tiles else 0
        diag["tiles_written"] = int(tile_count)
        if tile_count <= 0:
            msg = (
                "0 tiles written. Likely causes: wrong origin-from-meta, no spatial overlap "
                "with auto grid, or overly strict extraction. See tiler_diagnostics.json and tiler_console.log."
            )
            diag["first_error"] = msg
            _log(f"ERROR: {msg}")
            return_code = 6
            return return_code
        _log(f"INFO: Tiles written: {tile_count}")

        ok, code = _post_check(out_dir, tiles_dir)
        return_code = code if not ok else 0
        return return_code
    except Exception as exc:
        diag["first_error"] = f"Unhandled exception: {exc}"
        diag["exception"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback_tail": "".join(traceback.format_exc().splitlines()[-15:]),
        }
        return_code = 1
        _log(f"ERROR: Unhandled exception: {exc}")
        return return_code
    finally:
        diag["runtime_sec"] = round(time.time() - start_time, 3)
        _write_diagnostics(out_dir, diag)
        _write_console_log(out_dir, log_lines)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: tile_manual_xodr_windows failed: {exc}")
        raise SystemExit(1)
