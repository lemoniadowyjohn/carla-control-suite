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


def _stationary_points(
    segments: List[Tuple[float, float, float, float, float]],
    length: float,
) -> List[float]:
    """All interior extrema of the exact cubic elevation polynomials.

    Looking only at evenly spaced samples misses a high peak or deep valley
    whose values at BOTH surrounding sample points are equal. Every cubic's
    derivative is quadratic, so at most two stationary points occur per
    segment. This is deterministic and bounded by the number of segments.
    """
    extrema: List[float] = []
    for idx, (s0, _a, b, c, d) in enumerate(segments):
        end = segments[idx + 1][0] if idx + 1 < len(segments) else length
        local_length = end - s0
        roots: List[float] = []
        if d:
            qa, qb, qc = 3.0 * d, 2.0 * c, b
            discriminant = qb * qb - 4.0 * qa * qc
            if not math.isfinite(discriminant):
                raise ValueError("non-finite derivative discriminant")
            if discriminant >= 0.0:
                radical = math.sqrt(discriminant)
                roots = [(-qb - radical) / (2.0 * qa), (-qb + radical) / (2.0 * qa)]
        elif c:
            roots = [-b / (2.0 * c)]
        for local_s in roots:
            if not math.isfinite(local_s):
                raise ValueError("non-finite derivative root")
            if 0.0 < local_s < local_length:
                absolute_s = s0 + local_s
                if not math.isfinite(absolute_s):
                    raise ValueError("non-finite stationary position")
                extrema.append(absolute_s)
    return extrema


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

            # Include *both* nominal sample points and every actual piecewise
            # polynomial boundary. Otherwise a continuous triangular hill at
            # s=2.5 m can be invisible at the 0/5/10 m nominal samples.
            regular_positions = [0.0]
            s = 0.0
            while s < length:
                next_s = min(length, s + sample_step_m)
                if next_s <= s:
                    raise ValueError("sampling interval cannot advance at road precision")
                s = next_s
                regular_positions.append(s)
            boundary_indices = {segment[0]: idx for idx, segment in enumerate(segments) if idx}
            extrema = _stationary_points(segments, length)
            base_positions = set(regular_positions) | set(boundary_indices)
            extra_extrema = set(extrema) - base_positions
            positions = sorted(base_positions | set(extrema))
            if len(positions) - 1 > max_samples_per_road:
                raise ValueError("sampling requires more than 1000000 intervals")

            prev_z = _poly_z(segments[0], 0.0) if segments else 0.0
            road_jumps: List[float] = []
            boundary_jumps: List[float] = []
            steps = 0
            active_index = 0

            z_min = prev_z if z_min is None else min(z_min, prev_z)
            z_max = prev_z if z_max is None else max(z_max, prev_z)

            for position in positions[1:]:
                # Evaluate just BEFORE a boundary using its preceding segment.
                # After accounting for the continuous interval, evaluate the
                # right-hand segment. This prevents a discontinuity from being
                # double-counted as an interval jump.
                left_z = _poly_z(segments[active_index], position) if segments else 0.0
                interval_jump = abs(left_z - prev_z)
                road_jumps.append(interval_jump)
                all_jumps.append(interval_jump)
                if interval_jump > step_threshold_m:
                    steps += 1
                z_min = min(z_min, left_z)
                z_max = max(z_max, left_z)
                if position in boundary_indices:
                    active_index = boundary_indices[position]
                    right_z = _poly_z(segments[active_index], position)
                    boundary_jumps.append(abs(right_z - left_z))
                    z_min = min(z_min, right_z)
                    z_max = max(z_max, right_z)
                    prev_z = right_z
                else:
                    prev_z = left_z

            all_boundary_jumps.extend(boundary_jumps)
            per_road[rid] = {
                "road_id": rid,
                "samples": len(road_jumps) + 1,
                "extrema_samples": len(extra_extrema),
                "boundary_samples": len(boundary_indices),
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
