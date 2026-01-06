# ultimate_pipeline/domain_gap/tile_matcher.py

from __future__ import annotations

import os
import glob
import json
import xml.etree.ElementTree as ET
from typing import Dict, Tuple, Optional

from shapely.geometry import box

from ultimate_pipeline.config.settings import SETTINGS


# ============================================================
# Helpers
# ============================================================

def _safe_float(val: str | None, default: float = 0.0) -> float:
    try:
        return float(val) if val is not None else default
    except Exception:
        return default


def _load_tile_bounds_from_metadata(tiles_dir: str) -> Dict[str, Tuple[float, float, float, float]]:
    """Load bounds per tile from tile_metadata.json if present.

    Returns:
        { "tile_0_0.xodr": (minx, miny, maxx, maxy), ... }
    """
    meta_path = os.path.join(tiles_dir, "tile_metadata.json")
    if not os.path.isfile(meta_path):
        return {}

    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}

    out: Dict[str, Tuple[float, float, float, float]] = {}
    for k, v in data.items():
        if not isinstance(k, str) or k.startswith("_"):
            continue
        if not isinstance(v, dict):
            continue

        b = v.get("bounds")
        if isinstance(b, (list, tuple)) and len(b) == 4:
            try:
                out[k] = (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
                continue
            except Exception:
                pass

        bb = v.get("bbox")
        if isinstance(bb, dict):
            try:
                out[k] = (float(bb["min_x"]), float(bb["min_y"]), float(bb["max_x"]), float(bb["max_y"]))
            except Exception:
                pass

    return out


def _tile_bounds_from_xodr(xodr_path: str) -> Optional[Tuple[float, float, float, float]]:
    """Compute a bounding box from planView geometry anchors.

    Returns (minx, miny, maxx, maxy) or None if empty.
    """
    try:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
    except Exception:
        return None

    xs, ys = [], []

    for geom in root.findall(".//planView/geometry"):
        x = _safe_float(geom.get("x"), default=float("nan"))
        y = _safe_float(geom.get("y"), default=float("nan"))
        if x == x and y == y:  # NaN check
            xs.append(x)
            ys.append(y)

    if not xs or not ys:
        return None

    return (min(xs), min(ys), max(xs), max(ys))


def _iou(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b

    A = box(ax1, ay1, ax2, ay2)
    B = box(bx1, by1, bx2, by2)

    inter = A.intersection(B).area
    union = A.union(B).area
    if union <= 0.0:
        return 0.0
    return float(inter / union)


# ============================================================
# Tile Matcher
# ============================================================

class TileMatcher:
    """Match tiles between two tile directories.

    Important: For deterministic pipelines (same tiler settings), the safest match
    is by tile filename (tile_i_j.xodr). We still keep the IoU-based fallback for
    non-identical grids / legacy exports.
    """

    @staticmethod
    def match_tiles(
        manual_dir: str,
        auto_dir: str,
        *,
        min_iou: float | None = None,
    ) -> Dict[str, Dict]:
        """Return mapping from manual tile to best auto tile.

        Output schema:
            {
              "tile_0_0.xodr": {
                  "match": "tile_0_0.xodr",
                  "iou": 1.0,
                  "status": "matched_by_id"
              },
              ...
            }
        """
        if min_iou is None:
            min_iou = float(getattr(SETTINGS, "TILE_MATCH_MIN_IOU_FOR_GAP", 0.5))

        manual_tiles = sorted(glob.glob(os.path.join(manual_dir, "tile_*.xodr")))
        auto_tiles = sorted(glob.glob(os.path.join(auto_dir, "tile_*.xodr")))

        # Quick index by basename (deterministic path)
        auto_by_name = {os.path.basename(p): p for p in auto_tiles}

        # Prefer metadata bounds if available (fast & consistent)
        manual_meta = _load_tile_bounds_from_metadata(manual_dir)
        auto_meta = _load_tile_bounds_from_metadata(auto_dir)

        # Precompute auto bounds (metadata -> fallback parse)
        auto_bounds: Dict[str, Tuple[float, float, float, float]] = {}
        for p in auto_tiles:
            name = os.path.basename(p)
            b = auto_meta.get(name)
            if b is None:
                b = _tile_bounds_from_xodr(p)
            if b is not None:
                auto_bounds[name] = b

        results: Dict[str, Dict] = {}

        for mp in manual_tiles:
            tile_name = os.path.basename(mp)

            # 1) Deterministic pairing by ID if present in both dirs
            ap = auto_by_name.get(tile_name)
            if ap is not None:
                mb = manual_meta.get(tile_name) or _tile_bounds_from_xodr(mp)

                # try: metadata -> precomputed -> parse auto tile path
                ab = auto_meta.get(tile_name) or auto_bounds.get(tile_name) or _tile_bounds_from_xodr(ap)

                # FIX:
                # - If we can compute IoU, use it even if it's 0.0
                # - Only default to 1.0 when IoU cannot be computed (missing bounds)
                if mb is not None and ab is not None:
                    iou_val = _iou(mb, ab)
                    status = "matched_by_id"
                else:
                    iou_val = 1.0
                    status = "matched_by_id_no_bounds"

                results[tile_name] = {
                    "match": tile_name,
                    "iou": round(float(iou_val), 4),
                    "status": status,
                }
                continue

            # 2) Fallback: IoU search (non-identical grids / legacy tiles)
            mb = manual_meta.get(tile_name)
            if mb is None:
                mb = _tile_bounds_from_xodr(mp)
            if mb is None:
                results[tile_name] = {"match": None, "iou": 0.0, "status": "unmatched_empty"}
                continue

            best_match = None
            best_iou = -1.0
            for aname, ab in auto_bounds.items():
                score = _iou(mb, ab)
                if score > best_iou:
                    best_iou = score
                    best_match = aname

            if best_match and best_iou >= float(min_iou):
                results[tile_name] = {
                    "match": best_match,
                    "iou": round(float(best_iou), 4),
                    "status": "matched_by_iou",
                }
            else:
                results[tile_name] = {
                    "match": best_match,
                    "iou": round(float(max(best_iou, 0.0)), 4),
                    "status": "unmatched_low_iou",
                }

        return results
