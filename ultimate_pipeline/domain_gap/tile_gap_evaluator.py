# ultimate_pipeline/domain_gap/tile_gap_evaluator.py

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

import numpy as np
from shapely.geometry import LineString, box
from shapely.ops import unary_union

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.domain_gap.tile_matcher import intersection_bbox


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


def _bounds_from_lines(
    lines: List[LineString],
) -> Optional[Tuple[float, float, float, float]]:
    if not lines:
        return None

    union = unary_union(lines)
    if union.is_empty:
        return None

    minx, miny, maxx, maxy = union.bounds
    if maxx <= minx or maxy <= miny:
        return None
    return (float(minx), float(miny), float(maxx), float(maxy))


def _clip_centerlines_to_bbox(
    lines: List[LineString],
    bbox: Tuple[float, float, float, float],
) -> List[LineString]:
    clip_poly = box(*bbox)
    clipped: List[LineString] = []

    for line in lines:
        try:
            geom = line.intersection(clip_poly)
        except Exception:
            continue
        if geom.is_empty:
            continue
        if geom.geom_type == "LineString":
            clipped.append(geom)
            continue
        geoms = getattr(geom, "geoms", None)
        if geoms is None:
            continue
        for subgeom in geoms:
            if subgeom.geom_type == "LineString" and not subgeom.is_empty:
                clipped.append(subgeom)

    return clipped


def _compute_sampled_rmse(
    manual_union,
    auto_union,
    *,
    rmse_samples: int,
) -> float | None:
    length = manual_union.length
    if length <= 1e-6:
        return None

    n = min(rmse_samples, max(10, int(length)))
    diffs = []

    for i in range(n):
        p = manual_union.interpolate(i / (n - 1), normalized=True)
        d = p.distance(auto_union)
        diffs.append(d * d)

    return float(math.sqrt(sum(diffs) / len(diffs)))


def _skip_low_iou_geometry_metrics(
    *,
    match_status: str | None,
    matched_iou: float | None,
    min_iou: float,
) -> Dict | None:
    normalized_status = str(match_status or "").strip()
    if normalized_status == "unmatched_low_iou":
        return {
            "hausdorff": None,
            "rmse": None,
            "rmse_cropped": None,
            "manual_roads": None,
            "auto_roads": None,
            "status": "skipped_low_iou",
            "disabled": True,
            "reason": "iou_below_threshold",
            "skip_reason": "tile_match_status=unmatched_low_iou",
            "matched_iou": matched_iou,
            "min_iou_for_gap": float(min_iou),
        }

    if matched_iou is not None and float(matched_iou) < float(min_iou):
        return {
            "hausdorff": None,
            "rmse": None,
            "rmse_cropped": None,
            "manual_roads": None,
            "auto_roads": None,
            "status": "skipped_low_iou",
            "disabled": True,
            "reason": "iou_below_threshold",
            "skip_reason": f"iou={float(matched_iou):.3f} < {float(min_iou):.3f}",
            "matched_iou": float(matched_iou),
            "min_iou_for_gap": float(min_iou),
        }

    return None


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
        match_status: str | None = None,
        matched_iou: float | None = None,
        min_iou: float | None = None,
    ) -> Dict:
        rmse_samples = rmse_samples or getattr(
            SETTINGS, "TILE_GAP_RMSE_SAMPLES", 200
        )
        min_iou = float(
            min_iou
            if min_iou is not None
            else getattr(SETTINGS, "TILE_MATCH_MIN_IOU_FOR_GAP", 0.5)
        )

        skipped = _skip_low_iou_geometry_metrics(
            match_status=match_status,
            matched_iou=matched_iou,
            min_iou=min_iou,
        )
        if skipped is not None:
            return skipped

        A = _extract_centerlines(tile_manual)
        B = _extract_centerlines(tile_auto)

        if not A or not B:
            return {
                "hausdorff": None,
                "rmse": None,
                "rmse_cropped": None,
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
                "rmse_cropped": None,
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
        rmse = _compute_sampled_rmse(A_u, B_u, rmse_samples=rmse_samples)

        rmse_cropped = None
        manual_bbox = _bounds_from_lines(A)
        auto_bbox = _bounds_from_lines(B)
        if manual_bbox is not None and auto_bbox is not None:
            overlap_bbox = intersection_bbox(manual_bbox, auto_bbox)
            if overlap_bbox is not None:
                A_clipped = _clip_centerlines_to_bbox(A, overlap_bbox)
                B_clipped = _clip_centerlines_to_bbox(B, overlap_bbox)
                if A_clipped and B_clipped:
                    A_clipped_u = unary_union(A_clipped)
                    B_clipped_u = unary_union(B_clipped)
                    if not A_clipped_u.is_empty and not B_clipped_u.is_empty:
                        rmse_cropped = _compute_sampled_rmse(
                            A_clipped_u,
                            B_clipped_u,
                            rmse_samples=rmse_samples,
                        )

        return {
            "hausdorff": hausdorff,
            "rmse": rmse,
            "rmse_cropped": rmse_cropped,
            "manual_roads": len(A),
            "auto_roads": len(B),
            "status": "ok",
        }
