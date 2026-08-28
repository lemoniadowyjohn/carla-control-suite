#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ELV-LAN-001 — elevation seam fixer (real implementation).

Aligns z-values at road/geometry boundaries to remove elevation seams without
re-sampling the DEM.  For every road-to-road link (A.end -> B.start) a bounded
corrective offset is applied to the START of the downstream road's elevation
profile and blended to zero over ``blend_length_m`` using a quadratic falloff
(C0 and C1 at the blend end).  Falls back to splitting the first elevation
segment when it is shorter than the blend length.

Fail-closed: if the profile is empty, the road is skipped with a warning
recorded (no invented data); if the offset exceeds ``max_snap_m`` the seam is
reported as NOT fixed (never silently forced).
"""
from __future__ import annotations

import math
import os
import shutil
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

BLEND_LENGTH_DEFAULT_M = 25.0


def _safe_float(value: Optional[str], default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except Exception:
        return default


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


def _road_end_z(road: ET.Element, contact_point: str) -> Optional[float]:
    length = _safe_float(road.get("length"))
    segments = _parse_elevation_profile(road)
    if not segments or length <= 0.0:
        return None
    s = length if contact_point == "end" else 0.0
    return _elevation_at_s(segments, s)


def _split_segment(profile: ET.Element, insert_at_s: float) -> bool:
    """Split the elevation segment covering ``insert_at_s`` in two (C0 match)."""
    for el in profile.findall("elevation"):
        s0 = _safe_float(el.get("s"))
        a, b, c, d = (_safe_float(el.get(k)) for k in ("a", "b", "c", "d"))
        # find next segment start to bound this segment
        others = [o for o in profile.findall("elevation")
                  if _safe_float(o.get("s")) > s0]
        s1 = min((_safe_float(o.get("s")) for o in others), default=math.inf)
        if s0 < insert_at_s < s1:
            ds = insert_at_s - s0
            z = a + b * ds + c * ds * ds + d * ds * ds * ds
            slope = b + 2.0 * c * ds + 3.0 * d * ds * ds
            new_el = ET.SubElement(profile, "elevation",
                                   s=f"{insert_at_s:.9f}", a=f"{z:.9f}",
                                   b=f"{slope:.9f}", c="0", d="0")
            profile.remove(el)
            profile.insert(0, el)  # re-append first so children order survives sort below
            profile.append(new_el)
            _resort_children(profile)
            return True
    return False


def _resort_children(profile: ET.Element) -> None:
    children = list(profile)
    children.sort(key=lambda e: _safe_float(e.get("s")))
    for c in children:
        profile.remove(c)
    for c in children:
        profile.append(c)


def _apply_correction(profile: ET.Element, dz: float, blend_m: float) -> bool:
    """Apply quadratic-falloff corrective offset to the first segment only.

    The first elevation segment is guaranteed to end at ``blend_m`` (split
    from the original profile if it spans further), so the corrective term
    delta(s) = dz*(1 - s/blend)^2 decays to zero AND its derivative vanishes
    at the blend end.  The remainder of the profile is untouched.
    """
    if dz == 0.0:
        return True
    segments = [(el, _safe_float(el.get("s"))) for el in profile.findall("elevation")]
    if not segments:
        return False
    segments.sort(key=lambda pair: pair[1])
    first_el, first_s = segments[0]
    next_s = segments[1][1] if len(segments) > 1 else math.inf
    first_len = next_s - first_s
    if first_len <= 1e-3:
        return False
    if first_len < blend_m:
        # segment ends before the blend: decay over the whole segment
        blend_m = first_len
    elif first_len > blend_m + 1e-6:
        # split at blend end so the falloff is confined to [0, blend_m]
        _split_segment(profile, first_s + blend_m)
    a = _safe_float(first_el.get("a"))
    b = _safe_float(first_el.get("b"))
    c = _safe_float(first_el.get("c"))
    d = _safe_float(first_el.get("d"))
    inv_blend = 1.0 / blend_m
    # delta(s) = dz*(1 - s/blend)^2 ; adding it to the cubic a+b s+c s^2+d s^3
    # yields: a+dz, b-2dz*inv_blend, c+dz*inv_blend^2, d
    first_el.set("a", f"{a + dz:.9f}")
    first_el.set("b", f"{b - 2.0 * dz * inv_blend:.9f}")
    first_el.set("c", f"{c + dz * inv_blend * inv_blend:.9f}")
    return True


def fix_elevation_seams(
    xodr_in: str,
    out_xodr: str,
    max_snap_m: float = 0.25,
    blend_length_m: float = BLEND_LENGTH_DEFAULT_M,
) -> Dict[str, Any]:
    """Align z-values at road/geometry boundaries to remove elevation seams.

    Does NOT re-sample the DEM.  Writes a NEW file (never mutates input).
    Returns stats: seams_checked, seams_fixed, max_delta.
    """
    stats: Dict[str, Any] = {
        "seams_checked": 0,
        "seams_fixed": 0,
        "seams_already_consistent": 0,
        "seams_skipped_empty_profile": 0,
        "seams_over_threshold": 0,
        "max_delta": 0.0,
        "roads": 0,
        "warnings": [],
        "out_xodr": out_xodr,
    }
    try:
        tree = ET.parse(xodr_in)
        root = tree.getroot()
    except Exception as exc:
        stats["warnings"].append(f"failed to parse input xodr: {exc}")
        return stats

    roads = {r.get("id"): r for r in root.findall("road")}
    stats["roads"] = len(roads)
    fixed_ids: List[str] = []

    for rid, road in roads.items():
        link = road.find("link")
        if link is None:
            continue
        for direction in ("predecessor", "successor"):
            el = link.find(direction)
            if el is None or el.get("elementType") != "road":
                continue
            other = roads.get(el.get("elementId"))
            if other is None:
                continue
            # A.end -> B.start for predecessor; A.end -> B.start for successor
            # too (road's OWN end connects to the successor's start) -- in both
            # branches z_a is the fixed anchor (target) and z_b is the current
            # value of `downstream`'s shared boundary, so delta = z_a - z_b is
            # the correction to apply to `downstream` in either case.
            if direction == "predecessor":
                z_a = _road_end_z(other, "end")
                z_b = _road_end_z(road, "start")
                downstream = road
            else:
                z_a = _road_end_z(road, "end")
                z_b = _road_end_z(other, "start")
                downstream = other
            if z_a is None or z_b is None:
                stats["seams_skipped_empty_profile"] += 1
                continue
            delta = z_a - z_b
            stats["seams_checked"] += 1
            stats["max_delta"] = max(stats["max_delta"], abs(delta))
            if abs(delta) < 1e-9:
                stats["seams_already_consistent"] += 1
                continue
            if abs(delta) > max_snap_m:
                stats["seams_over_threshold"] += 1
                stats["warnings"].append(
                    f"road {rid}: boundary delta {abs(delta):.3f} m exceeds max_snap_m "
                    f"({max_snap_m} m) - not forced")
                continue
            profile = downstream.find("elevationProfile")
            if profile is None or not profile.findall("elevation"):
                stats["seams_skipped_empty_profile"] += 1
                continue
            if _apply_correction(profile, delta, blend_length_m):
                stats["seams_fixed"] += 1
                fixed_ids.append(rid)

    if stats["seams_fixed"] > 0:
        os.makedirs(os.path.dirname(os.path.abspath(out_xodr)) or ".", exist_ok=True)
        tree.write(out_xodr, encoding="utf-8", xml_declaration=True)
    stats["fixed_road_ids"] = fixed_ids
    return stats
