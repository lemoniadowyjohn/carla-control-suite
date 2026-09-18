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
        return float(value) if value is not None else default
    except Exception:
        return default


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


def _parse_elevation_profile(road: ET.Element) -> List[Tuple[float, float, float, float, float]]:
    profile = road.find("elevationProfile")
    if profile is None:
        return []
    segments: List[Tuple[float, float, float, float, float]] = []
    for el in profile.findall("elevation"):
        s = _safe_float(el.get("s"))
        a = _safe_float(el.get("a"))
        b = _safe_float(el.get("b"))
        c = _safe_float(el.get("c"))
        d = _safe_float(el.get("d"))
        segments.append((s, a, b, c, d))
    segments.sort(key=lambda v: v[0])
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
    s0, a, b, c, d = seg
    ds = max(0.0, s - s0)
    return a + b * ds + c * ds * ds + d * ds * ds * ds


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
    }

    try:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
    except Exception as exc:
        report["ok"] = False
        report["warnings"].append(f"failed to parse xodr: {exc}")
        return report

    roads = root.findall("road")
    report["num_roads"] = len(roads)

    all_jumps: List[float] = []
    z_min = None
    z_max = None
    per_road: Dict[str, Any] = {}

    for road in roads:
        rid = (road.get("id") or "").strip()
        length = _safe_float(road.get("length"))
        if length <= 0:
            continue
        segments = _parse_elevation_profile(road)
        s = 0.0
        prev_z = _elevation_at_s(segments, s)
        road_jumps: List[float] = []
        steps = 0

        z_min = prev_z if z_min is None else min(z_min, prev_z)
        z_max = prev_z if z_max is None else max(z_max, prev_z)

        while s + sample_step_m <= length:
            s += sample_step_m
            z = _elevation_at_s(segments, s)
            dz = abs(z - prev_z)
            road_jumps.append(dz)
            all_jumps.append(dz)
            if dz > step_threshold_m:
                steps += 1
            prev_z = z
            z_min = z if z_min is None else min(z_min, z)
            z_max = z if z_max is None else max(z_max, z)

        if road_jumps:
            per_road[rid] = {
                "road_id": rid,
                "samples": len(road_jumps) + 1,
                "step_count": steps,
                "max_jump": max(road_jumps),
                "p95_jump": _percentile(road_jumps, 95.0),
            }
            report["total_samples"] += len(road_jumps) + 1
            report["total_steps"] += steps

    max_jump = max(all_jumps) if all_jumps else 0.0
    p95_jump = _percentile(all_jumps, 95.0) if all_jumps else 0.0
    total_jump_samples = len(all_jumps)
    bad_fraction = (report["total_steps"] / float(total_jump_samples)) if total_jump_samples else 0.0

    # Threshold scaling: for large maps, absolute seam-step counts scale with map size.
    # Use a fraction-based threshold to keep the gate comparable across areas.
    try:
        max_bad_fraction = float(os.getenv("UP_ELEV_SEAM_MAX_BAD_FRACTION", "0.002") or "0.002")
    except Exception:
        max_bad_fraction = 0.002

    report["seam_stats"] = {
        "count": report["total_steps"],
        "total_jump_samples": int(total_jump_samples),
        "bad_fraction": float(bad_fraction),
        "max_bad_fraction": float(max_bad_fraction),
        "max_jump": float(max_jump),
        "p95_jump": float(p95_jump) if p95_jump is not None else None,
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
    report["ok"] = not (fail_max or fail_freq)
    return report
