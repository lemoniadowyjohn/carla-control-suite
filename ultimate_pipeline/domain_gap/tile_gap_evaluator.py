# ultimate_pipeline/domain_gap/tile_gap_evaluator.py

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Dict, List

import numpy as np
from shapely.geometry import LineString
from shapely.ops import unary_union

from ultimate_pipeline.config.settings import SETTINGS


# ============================================================
# Helpers
# ============================================================

def _safe_float(val: str | None, default: float = 0.0) -> float:
    try:
        return float(val) if val is not None else default
    except Exception:
        return default


def _extract_centerlines(
    path: str,
    *,
    samples_per_geom: int = 15,
) -> List[LineString]:
    """
    Approximate road centerlines from OpenDRIVE planView geometries.

    NOTE:
    - Uses straight-line sampling per geometry block
    - Ignores spiral / arc curvature (acceptable for tile-level *relative* gap)
    """
    tree = ET.parse(path)
    root = tree.getroot()

    lines: List[LineString] = []

    for road in root.findall("road"):
        xs: List[float] = []
        ys: List[float] = []

        for g in road.findall("./planView/geometry"):
            x0 = _safe_float(g.get("x"))
            y0 = _safe_float(g.get("y"))
            hdg = _safe_float(g.get("hdg"))
            length = _safe_float(g.get("length"))

            if length <= 0:
                continue

            s_vals = np.linspace(0.0, length, samples_per_geom)

            cos_h = math.cos(hdg)
            sin_h = math.sin(hdg)

            for s in s_vals:
                xs.append(x0 + s * cos_h)
                ys.append(y0 + s * sin_h)

        if len(xs) >= 2:
            try:
                lines.append(LineString(zip(xs, ys)))
            except Exception:
                continue

    return lines


# ============================================================
# Tile Gap Evaluator
# ============================================================

class TileGapEvaluator:
    """
    Compute geometry domain gap for a *single tile*:
      - Hausdorff distance
      - RMSE (sampled)

    Intended use:
      - per-tile diagnostics
      - heatmaps
      - tile rejection gates
    """

    @staticmethod
    def compute(
        tile_manual: str,
        tile_auto: str,
        *,
        rmse_samples: int | None = None,
    ) -> Dict:
        rmse_samples = rmse_samples or getattr(
            SETTINGS, "TILE_GAP_RMSE_SAMPLES", 200
        )

        A = _extract_centerlines(tile_manual)
        B = _extract_centerlines(tile_auto)

        if not A or not B:
            return {
                "hausdorff": None,
                "rmse": None,
                "manual_roads": len(A),
                "auto_roads": len(B),
                "status": "empty_geometry",
            }

        A_u = unary_union(A)
        B_u = unary_union(B)

        if A_u.is_empty or B_u.is_empty:
            return {
                "hausdorff": None,
                "rmse": None,
                "manual_roads": len(A),
                "auto_roads": len(B),
                "status": "empty_union",
            }

        # -------------------------
        # Hausdorff
        # -------------------------
        hausdorff = float(A_u.hausdorff_distance(B_u))

        # -------------------------
        # RMSE (sampled)
        # -------------------------
        length = A_u.length
        if length <= 1e-6:
            rmse = None
        else:
            n = min(rmse_samples, max(10, int(length)))
            diffs = []

            for i in range(n):
                p = A_u.interpolate(i / (n - 1), normalized=True)
                d = p.distance(B_u)
                diffs.append(d * d)

            rmse = float(math.sqrt(sum(diffs) / len(diffs)))

        return {
            "hausdorff": hausdorff,
            "rmse": rmse,
            "manual_roads": len(A),
            "auto_roads": len(B),
            "status": "ok",
        }
