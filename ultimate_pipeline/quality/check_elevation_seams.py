#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Elevation seam gate for OpenDRIVE maps.

Detects large Z jumps along road reference lines.
"""

from __future__ import annotations

import math
import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple


def _safe_float(value: Optional[str], default: float = 0.0) -> float:
    try:
        parsed = float(value) if value is not None else default
    except Exception:
        return default
    # float("nan")/float("inf") parse without raising; a non-finite elevation
    # coefficient must fail closed to `default` rather than silently poison
    # every downstream comparison (NaN comparisons are always False, so the
    # seam-jump gate would otherwise never fire for that road).
    return parsed if math.isfinite(parsed) else default


def _percentile(values: List[float], pct: float) -> Optional[float]:
    if not values:
        return None
    pct = max(0.0, min(100.0, float(pct)))
    values = sorted(values)
    k = (len(values) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(values[int(k)])
    d0 = values[int(f)] * (c - k)
    d1 = values[int(c)] * (k - f)
    return float(d0 + d1)


def _finite_coefficient(value: Optional[str], label: str) -> float:
    """Reject malformed coefficients rather than interpreting them as flat terrain."""
    if value is None:
        raise ValueError(f"missing elevation coefficient {label}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid elevation coefficient {label}: {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"non-finite elevation coefficient {label}: {value!r}")
    return number


def _poly_z(segment: Tuple[float, float, float, float, float], s: float) -> float:
    s0, a, b, c, d = segment
    ds = max(0.0, s - s0)
    z = a + b * ds + c * ds * ds + d * ds * ds * ds
    if not math.isfinite(z):
        raise ValueError(f"non-finite elevation at s={s}")
    return z


def _parse_elevation_profile(road: ET.Element) -> List[Tuple[float, float, float, float, float]]:
    profile = road.find("elevationProfile")
    if profile is None:
        return []
    segments: List[Tuple[float, float, float, float, float]] = []
    for el in profile.findall("elevation"):
        segments.append(tuple(
            _finite_coefficient(el.get(field), field) for field in ("s", "a", "b", "c", "d")
        ))
    segments.sort(key=lambda v: v[0])
    for previous, current in zip(segments, segments[1:]):
        if current[0] <= previous[0]:
            raise ValueError(f"duplicate/overlapping elevation segment s={current[0]}")
    if segments and segments[0][0] != 0.0:
        raise ValueError("elevation profile does not begin at s=0")
    return segments


def _elevation_at_s(segments: List[Tuple[float, float, float, float, float]], s: float) -> float:
    if not segments:
        return 0.0
    seg = segments[0]
    for candidate in segments:
        if s >= candidate[0]:
            seg = candidate
        else:
            break
    return _poly_z(seg, s)


def check_elevation_seams(
    xodr_path: str,
    *,
    sample_step_m: float = 5.0,
    step_threshold_m: float = 1.5,
    max_jump_m: float = 5.0,
    max_steps: int = 50,
    p95_threshold_m: float = 1.0,
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "ok": True,
        "xodr_path": xodr_path,
        "sample_step_m": sample_step_m,
        "step_threshold_m": step_threshold_m,
        "max_jump_m": max_jump_m,
        "max_steps": max_steps,
        "p95_threshold_m": p95_threshold_m,
        "num_roads": 0,
        "total_samples": 0,
        "total_steps": 0,
        "seam_stats": {},
        "elevation_stats": {},
        "per_road": {},
        "top_offenders": [],
        "warnings": [],
        "invalid_roads": [],
    }

    # The caller may supply configuration, not just the default 5 m interval.
    # Zero/negative/non-finite intervals would hang or suppress all checks.
    for name, value in (
        ("sample_step_m", sample_step_m),
        ("step_threshold_m", step_threshold_m),
        ("max_jump_m", max_jump_m),
        ("p95_threshold_m", p95_threshold_m),
    ):
        if not isinstance(value, (int, float)) or not math.isfinite(value) or (
            value <= 0 if name == "sample_step_m" else value < 0
        ):
            report["ok"] = False
            report["warnings"].append(f"invalid {name}: {value!r}")
            return report

    try:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
    except Exception as exc:
        report["ok"] = False
        report["warnings"].append(f"failed to parse xodr: {exc}")
        return report

    roads = root.findall("road") if root.tag == "OpenDRIVE" else []
    report["num_roads"] = len(roads)
    if not roads:
        report["ok"] = False
        report["warnings"].append("no OpenDRIVE roads to evaluate")
        return report

    all_jumps: List[float] = []
    z_min = None
    z_max = None
    per_road: Dict[str, Any] = {}

    all_boundary_jumps: List[float] = []
    # This is a resource-admission ceiling, not a relaxation of seam thresholds.
    max_samples_per_road = 1_000_000

    for road in roads:
        rid = (road.get("id") or "").strip()
        try:
            length = _finite_coefficient(road.get("length"), "road length")
            if length <= 0:
                raise ValueError("road length must be positive")
            if math.ceil(length / sample_step_m) > max_samples_per_road:
                raise ValueError("sampling requires more than 1000000 intervals")
            segments = _parse_elevation_profile(road)
            if segments and segments[-1][0] > length:
                raise ValueError("elevation segment starts beyond road length")

            s = 0.0
            prev_z = _elevation_at_s(segments, s)
            road_jumps: List[float] = []
            boundary_jumps: List[float] = []
            steps = 0

            z_min = prev_z if z_min is None else min(z_min, prev_z)
            z_max = prev_z if z_max is None else max(z_max, prev_z)

            # Explicitly evaluate both sides of every polynomial boundary.
            # Sampling only at 0,5,10... can miss a spike at 2 m that
            # returns to zero at 4 m, even on an otherwise flat road.
            for previous, current in zip(segments, segments[1:]):
                boundary_s = current[0]
                left_z = _poly_z(previous, boundary_s)
                right_z = current[1]
                boundary_jumps.append(abs(right_z - left_z))
                z_min = min(z_min, left_z, right_z)
                z_max = max(z_max, left_z, right_z)

            # Include the final partial interval; a 3 m road must be measured
            # even with the historical default 5 m sample interval.
            while s < length:
                next_s = min(length, s + sample_step_m)
                if next_s <= s:
                    raise ValueError("sampling interval cannot advance at road precision")
                s = next_s
                z = _elevation_at_s(segments, s)
                dz = abs(z - prev_z)
                road_jumps.append(dz)
                all_jumps.append(dz)
                if dz > step_threshold_m:
                    steps += 1
                prev_z = z
                z_min = min(z_min, z)
                z_max = max(z_max, z)

            all_boundary_jumps.extend(boundary_jumps)
            per_road[rid] = {
                "road_id": rid,
                "samples": len(road_jumps) + 1,
                "step_count": steps,
                "max_jump": max(road_jumps + boundary_jumps, default=0.0),
                "p95_jump": _percentile(road_jumps, 95.0),
                "boundary_checks": len(boundary_jumps),
                "boundary_discontinuities": sum(
                    jump > step_threshold_m for jump in boundary_jumps
                ),
                "max_boundary_jump": max(boundary_jumps, default=0.0),
            }
            report["total_samples"] += len(road_jumps) + 1
            report["total_steps"] += steps
        except (TypeError, ValueError, OverflowError) as exc:
            report["invalid_roads"].append({"road_id": rid, "reason": str(exc)})

    max_jump = max(all_jumps + all_boundary_jumps, default=0.0)
    p95_jump = _percentile(all_jumps, 95.0) if all_jumps else 0.0
    total_jump_samples = len(all_jumps)
    bad_fraction = (report["total_steps"] / float(total_jump_samples)) if total_jump_samples else 0.0

    # Threshold scaling: for large maps, absolute seam-step counts scale with map size.
    # Use a fraction-based threshold to keep the gate comparable across areas.
    try:
        max_bad_fraction = float(os.getenv("UP_ELEV_SEAM_MAX_BAD_FRACTION", "0.002") or "0.002")
    except Exception:
        max_bad_fraction = float("nan")
    if not math.isfinite(max_bad_fraction) or not 0.0 <= max_bad_fraction <= 1.0:
        report["ok"] = False
        report["warnings"].append("invalid UP_ELEV_SEAM_MAX_BAD_FRACTION")
        return report

    report["seam_stats"] = {
        "count": report["total_steps"],
        "total_jump_samples": int(total_jump_samples),
        "bad_fraction": float(bad_fraction),
        "max_bad_fraction": float(max_bad_fraction),
        "max_jump": float(max_jump),
        "p95_jump": float(p95_jump) if p95_jump is not None else None,
        "boundary_checks": len(all_boundary_jumps),
        "boundary_discontinuities": sum(
            jump > step_threshold_m for jump in all_boundary_jumps
        ),
        "max_boundary_jump": max(all_boundary_jumps, default=0.0),
    }
    report["elevation_stats"] = {
        "z_min": float(z_min) if z_min is not None else 0.0,
        "z_max": float(z_max) if z_max is not None else 0.0,
        "z_range": float((z_max - z_min)) if z_min is not None and z_max is not None else 0.0,
    }
    report["per_road"] = per_road

    offenders = sorted(
        per_road.values(),
        key=lambda r: (r.get("max_jump", 0.0), r.get("step_count", 0)),
        reverse=True,
    )
    report["top_offenders"] = offenders[:10]

    fail_max = max_jump > max_jump_m
    fail_freq = ((p95_jump or 0.0) > p95_threshold_m) and (bad_fraction > max_bad_fraction)
    fail_boundary = any(jump > step_threshold_m for jump in all_boundary_jumps)
    report["ok"] = not (
        fail_max or fail_freq or fail_boundary or report["invalid_roads"]
    )
    return report
