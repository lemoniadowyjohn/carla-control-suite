from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional, Tuple, Any

@dataclass(frozen=True)
class TileGridSpec:
    origin_x: float
    origin_y: float
    tile_size_m: float
    buffer_m: float
    highway_aware_buffer: Optional[bool] = None
    highway_alpha: Optional[float] = None


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _read_json(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _tile_id_ij(name: str) -> Optional[Tuple[int, int]]:
    m = re.match(r"tile_(\d+)_(\d+)\.xodr$", os.path.basename(name))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _bounds_from_xodr(path: str) -> Optional[Tuple[float, float, float, float]]:
    # Fast-ish bbox from planView geometry anchors
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return None
    xs, ys = [], []
    for g in root.findall(".//planView/geometry"):
        x = _safe_float(g.get("x"))
        y = _safe_float(g.get("y"))
        if x is None or y is None:
            continue
        xs.append(x)
        ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _infer_tile_size_from_bbox(b: Tuple[float, float, float, float], buffer_m: float) -> Optional[float]:
    minx, miny, maxx, maxy = b
    w = maxx - minx
    h = maxy - miny
    if w <= 0 or h <= 0:
        return None
    # tiles are usually square-ish; width ~= tile_size + 2*buffer
    size = ((w + h) / 2.0) - 2.0 * buffer_m
    if size <= 0:
        return None
    # snap to nearest 10m to avoid floating jitter
    return float(round(size / 10.0) * 10.0)


def load_grid_spec_from_meta_or_tiles(tiles_dir: str) -> Optional[TileGridSpec]:
    """Load grid spec robustly from tile_metadata/manifest or infer from tiles.

    Supported layouts:
      - <tiles_dir>/tile_metadata.json
      - <tiles_dir>/../tile_metadata.json
      - <tiles_dir>/tile_manifest.json
      - <tiles_dir>/../tile_manifest.json

    If origin_x/origin_y/tile_size_m are missing, infer them from:
      - tile filename indices (tile_i_j.xodr)
      - planView geometry anchor bboxes

    Returns:
      TileGridSpec or None if insufficient information.
    """

    meta_candidates = [
        os.path.join(tiles_dir, "tile_metadata.json"),
        os.path.join(os.path.dirname(tiles_dir), "tile_metadata.json"),
    ]
    manifest_candidates = [
        os.path.join(tiles_dir, "tile_manifest.json"),
        os.path.join(os.path.dirname(tiles_dir), "tile_manifest.json"),
    ]

    meta = None
    for p in meta_candidates:
        if os.path.isfile(p):
            meta = _read_json(p)
            if isinstance(meta, dict):
                break

    manifest = None
    for p in manifest_candidates:
        if os.path.isfile(p):
            manifest = _read_json(p)
            if isinstance(manifest, dict):
                break

    buffer_m: Optional[float] = None
    tile_size_m: Optional[float] = None
    origin_x: Optional[float] = None
    origin_y: Optional[float] = None
    highway_aware: Optional[bool] = None
    highway_alpha: Optional[float] = None

    def scan_obj(obj: dict) -> None:
        nonlocal buffer_m, tile_size_m, origin_x, origin_y, highway_aware, highway_alpha
        for k, v in obj.items():
            lk = str(k).lower()
            if buffer_m is None and lk in ("tile_buffer_m", "tile_buffer", "buffer", "buffer_m"):
                buffer_m = _safe_float(v)
            if tile_size_m is None and lk in ("tile_size_m", "tile_size", "tile_size_meters", "tile_size_meter"):
                tile_size_m = _safe_float(v)
            if origin_x is None and lk in ("origin_x", "tile_origin_x", "grid_origin_x", "x0"):
                origin_x = _safe_float(v)
            if origin_y is None and lk in ("origin_y", "tile_origin_y", "grid_origin_y", "y0"):
                origin_y = _safe_float(v)
            if highway_aware is None and lk in (
                "enable_highway_aware_tile_buffer",
                "highway_aware_buffer",
                "enable_highway_buffer",
            ):
                if isinstance(v, bool):
                    highway_aware = v
            if highway_alpha is None and lk in ("highway_tile_buffer_alpha", "highway_alpha"):
                highway_alpha = _safe_float(v)
            if isinstance(v, dict):
                scan_obj(v)

    if isinstance(meta, dict):
        scan_obj(meta)
    if isinstance(manifest, dict):
        scan_obj(manifest)

    # If buffer missing, default to canonical 50m (your manual tiles config)
    if buffer_m is None:
        buffer_m = 50.0

    # Infer missing values from tile geometry + indices
    tiles = [f for f in os.listdir(tiles_dir) if f.lower().endswith(".xodr") and f.startswith("tile_")]
    if tiles and (origin_x is None or origin_y is None or tile_size_m is None):
        tiles_sorted = sorted(tiles, key=lambda n: (_tile_id_ij(n) or (9999, 9999)))
        for t in tiles_sorted[:10]:
            ij = _tile_id_ij(t)
            if ij is None:
                continue
            b = _bounds_from_xodr(os.path.join(tiles_dir, t))
            if b is None:
                continue
            if tile_size_m is None:
                tile_size_m = _infer_tile_size_from_bbox(b, buffer_m) or tile_size_m
            if tile_size_m is None:
                continue
            i, j = ij
            minx, miny, *_ = b
            if origin_x is None:
                origin_x = float(minx - i * tile_size_m)
            if origin_y is None:
                origin_y = float(miny - j * tile_size_m)
            if origin_x is not None and origin_y is not None and tile_size_m is not None:
                break

    if origin_x is None or origin_y is None or tile_size_m is None or buffer_m is None:
        return None

    return TileGridSpec(
        origin_x=float(origin_x),
        origin_y=float(origin_y),
        tile_size_m=float(tile_size_m),
        buffer_m=float(buffer_m),
        highway_aware_buffer=highway_aware,
        highway_alpha=highway_alpha,
    )
