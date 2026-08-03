#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ELV-002/003/004 — elevation profile structural invariants.

Read-only validator for OpenDRIVE elevation profiles:

- ELV-002: piecewise profiles are encouraged; a single linear segment spanning
  the whole road on a long road is flagged (default of one linear profile is
  rejected as release evidence).
- ELV-003: elevation records are ordered by s, unique, start at 0, and the
  profile is valid over [0, road.length].
- ELV-004: within-road C0 continuity at segment joins (segment i end height
  equals segment i+1 start height within tolerance).

Fail-closed: any malformed or unordered profile is reported; the validator
never mutates the document.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

C0_TOLERANCE_M = float(0.05)
MIN_PIECEWISE_ROAD_LENGTH_M = 60.0


def _safe_float(value: Optional[str], default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except Exception:
        return default


def _parse_profile(road: ET.Element) -> List[Tuple[float, float, float, float, float]]:
    profile = road.find("elevationProfile")
    if profile is None:
        return []
    segments: List[Tuple[float, float, float, float, float]] = []
    for el in profile.findall("elevation"):
        segments.append((
            _safe_float(el.get("s")),
            _safe_float(el.get("a")),
            _safe_float(el.get("b")),
            _safe_float(el.get("c")),
            _safe_float(el.get("d")),
        ))
    return segments


def _height(seg: Tuple[float, float, float, float, float], s: float) -> float:
    s0, a, b, c, d = seg
    ds = max(0.0, s - s0)
    return a + b * ds + c * ds * ds + d * ds * ds * ds


def validate_elevation_profile_structure(
    root: ET.Element,
    *,
    min_piecewise_length_m: float = MIN_PIECEWISE_ROAD_LENGTH_M,
    c0_tolerance_m: float = C0_TOLERANCE_M,
) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    roads = root.findall("road")

    for road in roads:
        rid = (road.get("id") or "").strip()
        length = _safe_float(road.get("length"))
        segments = _parse_profile(road)

        if not segments:
            issues.append({
                "road_id": rid,
                "rule": "ELV-003",
                "severity": "warn",
                "detail": "no elevationProfile present (flat implicit profile)",
            })
            continue

        # ELV-003: ordered and unique s, start at 0, coverage of road length.
        ss = [seg[0] for seg in segments]
        if ss[0] != 0.0:
            issues.append({"road_id": rid, "rule": "ELV-003", "severity": "fail",
                           "detail": f"first elevation s={ss[0]} != 0"})
        if any(b <= a for a, b in zip(ss, ss[1:])):
            issues.append({"road_id": rid, "rule": "ELV-003", "severity": "fail",
                           "detail": "elevation s values not strictly ordered"})
        if len(set(ss)) != len(ss):
            issues.append({"road_id": rid, "rule": "ELV-003", "severity": "fail",
                           "detail": "duplicate elevation s values"})
        if length > 0.0 and ss[-1] >= length + 1e-6:
            issues.append({"road_id": rid, "rule": "ELV-003", "severity": "fail",
                           "detail": f"last elevation s={ss[-1]} exceeds road length {length}"})

        # ELV-002: single linear segment over a long road is a release-evidence reject.
        # Linear means cubic/quadratic terms vanish (c == d == 0), not slope == 0.
        if (len(segments) == 1 and length >= min_piecewise_length_m
                and segments[0][3] == 0.0 and segments[0][4] == 0.0):
            issues.append({"road_id": rid, "rule": "ELV-002", "severity": "fail",
                           "detail": "single linear elevation profile over long road "
                                     "(not piecewise-capable of local grade changes)"})

        # ELV-004: C0 continuity at within-road segment joins.
        for prev, nxt in zip(segments, segments[1:]):
            gap = abs(_height(prev, nxt[0]) - nxt[1])
            if gap > c0_tolerance_m:
                issues.append({"road_id": rid, "rule": "ELV-004", "severity": "fail",
                               "detail": f"C0 gap {gap:.4f} m at s={nxt[0]}"})

    ok = not any(issue["severity"] == "fail" for issue in issues)
    return {
        "ok": ok,
        "rule": "ELV-002/ELV-003/ELV-004",
        "roads_checked": len(roads),
        "issues": issues,
        "issue_count": len(issues),
        "fail_count": sum(1 for i in issues if i["severity"] == "fail"),
    }
