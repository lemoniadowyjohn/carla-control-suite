#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Origin sanity check for OpenDRIVE map coordinates.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional, Tuple


def _safe_float(x: Optional[str], default: float = 0.0) -> float:
    try:
        return float(x) if x is not None else default
    except Exception:
        return default


def check_origin_sanity(
    xodr_path: str,
    *,
    warn_distance_m: float = 50_000.0,
    fail_distance_m: float = 500_000.0,
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "ok": True,
        "xodr_path": xodr_path,
        "warn_distance_m": warn_distance_m,
        "fail_distance_m": fail_distance_m,
        "bbox": None,
        "centroid": None,
        "centroid_distance_m": None,
        "warnings": [],
    }

    try:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
    except Exception as e:
        report["ok"] = False
        report["warnings"].append(f"failed to parse xodr: {e}")
        return report

    min_x = None
    min_y = None
    max_x = None
    max_y = None

    for road in root.findall("road"):
        plan = road.find("planView")
        if plan is None:
            continue
        for geom in plan.findall("geometry"):
            x = _safe_float(geom.get("x"))
            y = _safe_float(geom.get("y"))
            min_x = x if min_x is None else min(min_x, x)
            min_y = y if min_y is None else min(min_y, y)
            max_x = x if max_x is None else max(max_x, x)
            max_y = y if max_y is None else max(max_y, y)

    if min_x is None or min_y is None or max_x is None or max_y is None:
        report["warnings"].append("no planView geometry found")
        return report

    cx = (min_x + max_x) / 2.0
    cy = (min_y + max_y) / 2.0
    dist = math.hypot(cx, cy)

    report["bbox"] = {"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y}
    report["centroid"] = {"x": cx, "y": cy}
    report["centroid_distance_m"] = dist

    # NaN/Inf from a corrupt planView x/y makes `dist` non-finite; a magnitude
    # comparison against NaN is always False in IEEE-754 (`nan > fail_distance_m`
    # is False), so the checks below would silently never fire without an
    # explicit guard.
    if not math.isfinite(dist):
        report["ok"] = False
        report["warnings"].append(f"centroid distance is non-finite ({dist!r}) -- corrupt planView x/y coordinate")
    elif dist > fail_distance_m:
        report["ok"] = False
        report["warnings"].append(f"centroid distance {dist:.1f}m exceeds fail threshold")
    elif dist > warn_distance_m:
        report["warnings"].append(f"centroid distance {dist:.1f}m exceeds warn threshold")

    return report
