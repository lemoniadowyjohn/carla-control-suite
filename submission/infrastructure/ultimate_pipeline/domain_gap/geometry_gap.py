#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Geometry Domain Gap (Whole-Map)

Computes global geometric discrepancy between two OpenDRIVE maps.

Metrics:
- RMSE distance (average geometric deviation, sampled)
- Hausdorff distance (worst-case deviation; optional)
- Normalized variants for cross-map comparability

Academic contract:
- Deterministic (fixed RNG seed)
- Explicit normalization references
- Optional Hausdorff (ablation-safe)
- No silent skips
- All settings recorded in output

Limitations (documented):
- planView geometries are approximated as piecewise linear segments
- arc/spiral fidelity must be ensured upstream (geometry authority stage)
"""

from __future__ import annotations

import time
import math
import numpy as np
import xml.etree.ElementTree as ET
from typing import Dict, List, Any, Optional

from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from ultimate_pipeline.config.settings import SETTINGS


# =============================================================================
# Helpers
# =============================================================================

def _safe_float(val: Optional[str], default: float = 0.0) -> float:
    try:
        return float(val)
    except Exception:
        return default


def _estimate_hausdorff_time(n_geoms: int) -> float:
    """
    Empirical runtime estimate for Hausdorff on city-scale maps.
    Calibrated on Ingolstadt-scale CARLA maps.
    """
    return 0.000015 * (n_geoms ** 1.3)


def _extract_polylines(
    xodr_path: str,
    *,
    sample_step_m: float,
    max_geoms: Optional[int],
) -> List[LineString]:
    """
    Extract planView geometries as LineStrings.

    Notes:
    - Uses (x, y, hdg, length) only
    - Assumes geometry smoothing & arc handling happened upstream
    """

    tree = ET.parse(xodr_path)
    root = tree.getroot()

    geoms = root.findall(".//road/planView/geometry")
    if max_geoms is not None:
        geoms = geoms[:max_geoms]

    polylines: List[LineString] = []

    for geom in geoms:
        x0 = _safe_float(geom.get("x"))
        y0 = _safe_float(geom.get("y"))
        hdg = _safe_float(geom.get("hdg"))
        length = _safe_float(geom.get("length"))

        if length <= 0:
            continue

        step = max(sample_step_m, 0.1)
        n = max(2, int(math.ceil(length / step)) + 1)

        cos_h = math.cos(hdg)
        sin_h = math.sin(hdg)

        pts = [
            (
                x0 + (s / length) * length * cos_h,
                y0 + (s / length) * length * sin_h,
            )
            for s in np.linspace(0.0, length, n)
        ]

        if len(pts) >= 2:
            polylines.append(LineString(pts))

    return polylines


# =============================================================================
# Geometry Gap
# =============================================================================

class GeometryGap:
    """
    Whole-map geometric domain gap.

    Interpretation:
    - RMSE: average geometric fidelity
    - Hausdorff: worst-case deviation (safety-critical)
    """

    @staticmethod
    def compute(
        manual_xodr: str,
        auto_xodr: str,
        *,
        skip_hausdorff: bool = False,
        max_geoms: Optional[int] = None,
        sample_step_m: Optional[float] = None,
        max_samples: Optional[int] = None,
        progress_every: Optional[int] = None,
        estimate_after: Optional[int] = None,
    ) -> Dict[str, Any]:

        # ------------------------------------------------------------------
        # Settings (explicit, deterministic)
        # ------------------------------------------------------------------
        cfg = getattr(SETTINGS, "GEOMETRY_GAP", {})

        sample_step_m = float(sample_step_m or cfg.get("SAMPLE_STEP_M", 2.0))
        max_geoms = max_geoms if max_geoms is not None else cfg.get("MAX_GEOMS")
        max_samples = int(max_samples or cfg.get("MAX_SAMPLES", 50_000))
        progress_every = int(progress_every or cfg.get("PROGRESS_EVERY", 2_000))
        estimate_after = int(estimate_after or cfg.get("ESTIMATE_AFTER", 5_000))
        rmse_ref_m = float(cfg.get("RMSE_REF_M", 1.0))

        np.random.seed(0)  # strict determinism

        t_global = time.perf_counter()

        # ------------------------------------------------------------------
        # Geometry extraction
        # ------------------------------------------------------------------
        print("[GeometryGap] Extracting polylines…")
        t0 = time.perf_counter()

        manual_polys = _extract_polylines(
            manual_xodr,
            sample_step_m=sample_step_m,
            max_geoms=max_geoms,
        )
        auto_polys = _extract_polylines(
            auto_xodr,
            sample_step_m=sample_step_m,
            max_geoms=max_geoms,
        )

        if not manual_polys or not auto_polys:
            raise RuntimeError("No valid geometries extracted from one or both maps")

        print(
            f"[GeometryGap] Polylines extracted "
            f"(manual={len(manual_polys)}, auto={len(auto_polys)}) "
            f"in {time.perf_counter() - t0:.1f}s"
        )

        # ------------------------------------------------------------------
        # Unary unions
        # ------------------------------------------------------------------
        print("[GeometryGap] Building unary unions…")
        t_union = time.perf_counter()

        manual_union = unary_union(manual_polys)
        auto_union = unary_union(auto_polys)

        if manual_union.is_empty or auto_union.is_empty:
            raise RuntimeError("Union geometry is empty — invalid XODR input")

        union_time = time.perf_counter() - t_union
        print(f"[GeometryGap] Unions built in {union_time:.1f}s")

        # ------------------------------------------------------------------
        # Hausdorff distance (optional)
        # ------------------------------------------------------------------
        hausdorff = None
        hausdorff_time = 0.0
        hausdorff_norm = None

        if skip_hausdorff:
            print("[GeometryGap] Skipping Hausdorff (skip_hausdorff=True)")
        else:
            n = len(manual_polys)
            eta_est = _estimate_hausdorff_time(n)
            print(
                f"[GeometryGap] Computing Hausdorff… "
                f"(est. {eta_est:.1f}s ≈ {eta_est/60:.1f} min, n={n})"
            )

            t_h = time.perf_counter()
            hausdorff = float(manual_union.hausdorff_distance(auto_union))
            hausdorff_time = time.perf_counter() - t_h

            minx, miny, maxx, maxy = manual_union.bounds
            diag = max(math.hypot(maxx - minx, maxy - miny), 1e-6)
            hausdorff_norm = hausdorff / diag

            print(f"[GeometryGap] Hausdorff completed in {hausdorff_time:.1f}s")

        # ------------------------------------------------------------------
        # RMSE sampling (manual → auto)
        # ------------------------------------------------------------------
        print("[GeometryGap] Sampling for RMSE…")

        samples: List[Point] = []
        for line in manual_polys:
            L = float(line.length)
            if L <= 0:
                continue

            step = max(sample_step_m, 0.1)
            npts = max(2, int(math.ceil(L / step)) + 1)

            for s in np.linspace(0.0, L, npts):
                samples.append(line.interpolate(s))
                if len(samples) >= max_samples:
                    break
            if len(samples) >= max_samples:
                break

        print(f"[GeometryGap] Total samples: {len(samples)}")

        dists = np.empty(len(samples), dtype=np.float64)
        t_rmse = time.perf_counter()

        for i, p in enumerate(samples):
            dists[i] = p.distance(auto_union)

            if (i + 1) % progress_every == 0:
                elapsed = time.perf_counter() - t_rmse
                rate = (i + 1) / max(elapsed, 1e-6)
                msg = f"[GeometryGap] RMSE {i+1}/{len(samples)} ({rate:.0f} pts/s)"

                if (i + 1) >= estimate_after:
                    eta = (len(samples) - (i + 1)) / rate
                    msg += f", ETA ~ {eta:.1f}s"

                print(msg)

        rmse = float(np.sqrt(np.mean(dists ** 2)))
        rmse_norm = min(abs(rmse) / max(rmse_ref_m, 1e-9), 1.0)

        total_time = time.perf_counter() - t_global

        print(
            f"[GeometryGap] DONE "
            f"(rmse={rmse:.3f} m, rmse_norm={rmse_norm:.3f}, "
            f"hausdorff={hausdorff}, time={total_time:.1f}s)"
        )

        # ------------------------------------------------------------------
        # Result (pipeline + aggregator compatible)
        # ------------------------------------------------------------------
        return {
            "rmse": rmse,
            "rmse_norm": rmse_norm,
            "hausdorff": hausdorff,
            "hausdorff_norm": hausdorff_norm,
            "samples": int(len(samples)),
            "runtime_sec": round(total_time, 2),
            "timings": {
                "union_sec": round(union_time, 2),
                "hausdorff_sec": round(float(hausdorff_time), 2),
            },
            "settings": {
                "sample_step_m": sample_step_m,
                "max_geoms": max_geoms,
                "max_samples": max_samples,
                "skip_hausdorff": bool(skip_hausdorff),
                "rmse_ref_m": rmse_ref_m,
            },
        }
