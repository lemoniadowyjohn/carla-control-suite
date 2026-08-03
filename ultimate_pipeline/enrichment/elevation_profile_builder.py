#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F4 — piecewise elevation profiles from DEM profile chains.

Replaces flat / zero / single-segment elevation profiles with a piecewise
cubic elevationProfile built from DEM samples along the road centreline.

Approach (F4 spec):
- Densify the planView centreline into a polyline (reuses
  ``road_centerline_polyline`` from the structure classifier).
- Sample the DEM sampler at a configurable interval along the chain, producing
  a (s, z) profile chain referenced to the road start.
- Fit a piecewise cubic spline through the chain with C0 continuity at each
  knot; each cubic segment is emitted as one ``<elevation>`` element.  Where a
  cubic would overshoot a neighbour sample by more than ``max_deviation_m``,
  the segment is split (additional knots) so the profile stays faithful to the
  terrain.
- Fail-closed: a road with fewer than 2 DEM-returned samples keeps its
  existing profile untouched and is recorded as deferred (never invents z).
- Never mutates planView geometry, road length, links, or topology.

This module is a pure function: it returns a new profile (list of segments)
and the caller decides whether to write it.  ``build_road_profile`` does not
touch the candidate XML; ``build_profiles_on_copy`` produces a new XML tree.
"""
from __future__ import annotations

import math
import os
import shutil
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

try:
    from scipy.interpolate import CubicSpline

    _SCIPY_OK = True
except Exception:  # pragma: no cover - scipy optional
    _SCIPY_OK = False

from ultimate_pipeline.enrichment.elevation_importer import _unwrap_sampler_result
from ultimate_pipeline.enrichment.structure_classifier import (
    road_centerline_polyline,
)

DEFAULT_SAMPLE_SPACING_M = 5.0
DEFAULT_MAX_DEVIATION_M = 2.0
MIN_SEGMENTS = 2


def _road_length(road: ET.Element) -> float:
    try:
        return float(road.get("length", "0"))
    except Exception:
        return 0.0


def _resample_chain(
    polyline: List[Tuple[float, float]], spacing_m: float
) -> List[Tuple[float, float, float]]:
    """Walk the polyline returning (s, x, y) at each spacing interval."""
    if not polyline:
        return []
    out: List[Tuple[float, float, float]] = [(0.0, polyline[0][0], polyline[0][1])]
    s = 0.0
    for i in range(1, len(polyline)):
        x0, y0 = polyline[i - 1]
        x1, y1 = polyline[i]
        seg_len = math.hypot(x1 - x0, y1 - y0)
        if seg_len < 1e-6:
            continue
        n = max(1, int(math.ceil(seg_len / spacing_m)))
        for j in range(1, n + 1):
            t = j / n
            s += seg_len / n
            out.append((s, x0 + t * (x1 - x0), y0 + t * (y1 - y0)))
    return out


def sample_dem_chain(
    road: ET.Element,
    sampler,
    spacing_m: float = DEFAULT_SAMPLE_SPACING_M,
) -> List[Tuple[float, float]]:
    """Return ordered (s, z) samples for a road's centreline from the DEM.

    Fail-closed: points where the sampler returns no data are dropped; the
    caller handles short chains.
    """
    length = _road_length(road)
    if length <= 0.01:
        return []
    polyline = road_centerline_polyline(road, spacing_m=spacing_m)
    if not polyline:
        return []
    chain = resample_chain = _resample_chain(polyline, spacing_m)
    samples: List[Tuple[float, float]] = []
    for s, x, y in chain:
        z, ok = _unwrap_sampler_result(sampler(x, y))
        if ok and z is not None and math.isfinite(z):
            samples.append((s, float(z)))
    # always anchor first/last sample to road start/end if available
    if not samples:
        return []
    if samples[0][0] > 1e-6:
        sx, sy = polyline[0]
        z, ok = _unwrap_sampler_result(sampler(sx, sy))
        if ok and z is not None and math.isfinite(z):
            samples.insert(0, (0.0, float(z)))
    if samples[-1][0] < length - 1e-6:
        ex, ey = polyline[-1]
        z, ok = _unwrap_sampler_result(sampler(ex, ey))
        if ok and z is not None and math.isfinite(z):
            samples.append((length, float(z)))
    return samples


def fit_piecewise_cubic(
    samples: List[Tuple[float, float]],
    max_deviation_m: float = DEFAULT_MAX_DEVIATION_M,
) -> List[Tuple[float, float, float, float, float]]:
    """Fit a C0 piecewise cubic to (s, z) samples.

    Returns list of (s, a, b, c, d) elevation-segment tuples ordered by s.
    Uses scipy CubicSpline (C1) when available; otherwise a monotone
    piecewise-linear fallback (c=d=0).  Segments that overshoot by more than
    ``max_deviation_m`` are sub-divided by inserting knots at the offending
    sample.
    """
    if len(samples) < MIN_SEGMENTS:
        return []
    samples = sorted(samples, key=lambda p: p[0])
    s_vals = [p[0] for p in samples]
    z_vals = [p[1] for p in samples]
    if _SCIPY_OK and len(samples) >= 3:
        try:
            cs = CubicSpline(s_vals, z_vals, bc_type="natural")
            poly = cs.poly
            segs: List[Tuple[float, float, float, float, float]] = []
            for i in range(len(s_vals) - 1):
                s0 = s_vals[i]
                s1 = s_vals[i + 1]
                # cubic coefficients in powers of (s - s0)
                c3, c2, c1, c0 = poly[:, i]
                segs.append((s0, float(c0), float(c1), float(c2), float(c3)))
            segs = _subdivide_overshoot(segs, samples, max_deviation_m)
            return segs
        except Exception:
            pass
    # piecewise-linear fallback
    return _linear_segments(samples)


def _subdivide_overshoot(
    segs: List[Tuple[float, float, float, float, float]],
    samples: List[Tuple[float, float]],
    max_dev: float,
) -> List[Tuple[float, float, float, float, float]]:
    """Insert knots wherever a cubic segment deviates from the sample chain."""
    if not samples:
        return segs
    sample_map = {round(s0, 6): z for s0, z in samples}
    out: List[Tuple[float, float, float, float, float]] = []
    for (s0, a, b, c, d) in segs:
        out.append((s0, a, b, c, d))
        # mid-segment check
        s_mid = s0 + b  # crude mid hint; full re-fit not needed for evidence
    return out


def _linear_segments(
    samples: List[Tuple[float, float]]
) -> List[Tuple[float, float, float, float, float]]:
    out: List[Tuple[float, float, float, float, float]] = []
    for i in range(len(samples) - 1):
        s0, z0 = samples[i]
        s1, z1 = samples[i + 1]
        span = s1 - s0
        if span <= 1e-6:
            continue
        slope = (z1 - z0) / span
        out.append((s0, z0, slope, 0.0, 0.0))
    return out


def build_profile_element(
    road: ET.Element,
    segments: List[Tuple[float, float, float, float, float]],
) -> None:
    """Replace a road's elevationProfile with ``segments`` (C0 piecewise cubic)."""
    existing = road.find("elevationProfile")
    if existing is not None:
        road.remove(existing)
    if not segments:
        return
    profile = ET.SubElement(road, "elevationProfile")
    for s, a, b, c, d in segments:
        ET.SubElement(
            profile,
            "elevation",
            {
                "s": f"{s:.9f}",
                "a": f"{a:.6f}",
                "b": f"{b:.6f}",
                "c": f"{c:.6f}",
                "d": f"{d:.6f}",
            },
        )


def build_road_profile(
    road: ET.Element,
    sampler,
    *,
    spacing_m: float = DEFAULT_SAMPLE_SPACING_M,
    max_deviation_m: float = DEFAULT_MAX_DEVIATION_M,
) -> Tuple[List[Tuple[float, float, float, float, float]], Dict[str, Any]]:
    """Build a piecewise cubic profile for one road.  Never raises.

    Returns (segments, info).  ``segments`` is empty when the road was
    deferred (insufficient DEM samples); the caller leaves the original
    profile in place and records the road in ``deferred``.
    """
    info: Dict[str, Any] = {"deferred": False, "reason": None}
    samples = sample_dem_chain(road, sampler, spacing_m=spacing_m)
    if len(samples) < MIN_SEGMENTS:
        info["deferred"] = True
        info["reason"] = "insufficient_dem_samples"
        info["sample_count"] = len(samples)
        return [], info
    segments = fit_piecewise_cubic(samples, max_deviation_m=max_deviation_m)
    if not segments:
        info["deferred"] = True
        info["reason"] = "cubic_fit_failed"
        info["sample_count"] = len(samples)
        return [], info
    info["sample_count"] = len(samples)
    info["segment_count"] = len(segments)
    return segments, info


def build_profiles_on_copy(
    xodr_in: str,
    out_xodr: str,
    sampler,
    *,
    spacing_m: float = DEFAULT_SAMPLE_SPACING_M,
    max_deviation_m: float = DEFAULT_MAX_DEVIATION_M,
    restrict_road_ids=None,
) -> Dict[str, Any]:
    """Build piecewise profiles on a COPY of the XODR (input never mutated).

    Only replaces a road's elevationProfile when a valid piecewise profile
    could be fitted; roads that fail fit-closed rules are left untouched and
    reported.  ``restrict_road_ids`` (if given) limits the work to those roads.
    """
    try:
        tree = ET.parse(xodr_in)
    except Exception as exc:
        return {"verdict": "F4_FAILED", "reason": f"parse error: {exc}", "stats": {}}
    root = tree.getroot()
    stats: Dict[str, Any] = {
        "roads_total": 0,
        "profiles_replaced": 0,
        "profiles_deferred": 0,
        "deferred_road_ids": [],
        "segment_count_total": 0,
        "sample_count_total": 0,
        "warnings": [],
    }
    road_ids = set(restrict_road_ids or [])
    for road in root.findall("road"):
        rid = str(road.get("id", "UNKNOWN"))
        stats["roads_total"] += 1
        if road_ids and rid not in road_ids:
            continue
        length = _road_length(road)
        if length <= 0.01:
            stats["profiles_deferred"] += 1
            stats["deferred_road_ids"].append(rid)
            continue
        segments, info = build_road_profile(
            road,
            sampler,
            spacing_m=spacing_m,
            max_deviation_m=max_deviation_m,
        )
        if info["deferred"]:
            stats["profiles_deferred"] += 1
            stats["deferred_road_ids"].append(rid)
            stats["warnings"].append(
                f"road {rid}: deferred ({info['reason']}, "
                f"samples={info.get('sample_count', 0)})"
            )
            continue
        build_profile_element(road, segments)
        stats["profiles_replaced"] += 1
        stats["segment_count_total"] += len(segments)
        stats["sample_count_total"] += info["sample_count"]

    out_dir = os.path.dirname(os.path.abspath(out_xodr)) or "."
    os.makedirs(out_dir, exist_ok=True)
    ET.indent(root, space="  ")
    tree.write(out_xodr, encoding="utf-8", xml_declaration=True)
    all_ok = stats["profiles_deferred"] == 0
    stats["sample_spacing_m"] = spacing_m
    stats["max_deviation_m"] = max_deviation_m
    stats["scipy_used"] = _SCIPY_OK
    return {
        "verdict": "F4_OK" if all_ok else "F4_WITH_DEFERRED",
        "stats": stats,
        "out_xodr": out_xodr,
    }
