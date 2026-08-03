# ultimate_pipeline/quality/check_elevation_continuity.py
# -*- coding: utf-8 -*-

"""
Elevation continuity check for OpenDRIVE road-to-road successor joins.

Why:
- Even if topology is correct, Z mismatches at road boundaries cause visible
  seams and physics artifacts in CARLA.
- DEM import can introduce discontinuities if roads are sampled independently.

What it checks:
- For each road with a successor/predecessor link of elementType="road",
  compare the elevation (z) at the end of road A to the start of road B.
- Flag if |z_A_end - z_B_start| > eps_z (meters).

Outputs:
- A dict report suitable for JSON writing with ok, issues, warnings.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple


def _safe_float(x: Optional[str], default: float = 0.0) -> float:
    try:
        return float(x) if x is not None else default
    except Exception:
        return default


def _eval_elevation_poly(a: float, b: float, c: float, d: float, s_local: float) -> float:
    """Evaluate elevation polynomial: z = a + b*s + c*s^2 + d*s^3."""
    return a + b * s_local + c * s_local**2 + d * s_local**3


def _get_elevation_at_s(road_el: ET.Element, s_abs: float) -> Tuple[float, List[str]]:
    """Get elevation at a given s-coordinate along the road."""
    warnings: List[str] = []
    elev_profile = road_el.find("elevationProfile")
    if elev_profile is None:
        return 0.0, ["no elevationProfile"]

    elevations = elev_profile.findall("elevation")
    if not elevations:
        return 0.0, ["no elevation elements"]

    # Sort by s and find the segment containing s_abs
    elev_data = []
    for el in elevations:
        s = _safe_float(el.get("s"))
        a = _safe_float(el.get("a"))
        b = _safe_float(el.get("b"))
        c = _safe_float(el.get("c"))
        d = _safe_float(el.get("d"))
        elev_data.append((s, a, b, c, d))

    elev_data.sort(key=lambda x: x[0])

    # Find the applicable segment
    selected = elev_data[0]
    for ed in elev_data:
        if ed[0] <= s_abs + 1e-9:
            selected = ed
        else:
            break

    s_start, a, b, c, d = selected
    s_local = max(0.0, s_abs - s_start)
    z = _eval_elevation_poly(a, b, c, d, s_local)

    return z, warnings


def _road_length(road_el: ET.Element) -> float:
    return _safe_float(road_el.get("length"))


def _road_links(road_el: ET.Element) -> List[Tuple[str, str, str]]:
    """Return list of (link_kind, elementType, elementId) for predecessor/successor."""
    out: List[Tuple[str, str, str]] = []
    link_el = road_el.find("link")
    if link_el is None:
        return out

    for kind in ("predecessor", "successor"):
        el = link_el.find(kind)
        if el is None:
            continue
        etype = (el.get("elementType") or "").strip()
        eid = (el.get("elementId") or "").strip()
        if etype and eid:
            out.append((kind, etype, eid))
    return out


def check_elevation_continuity(
    xodr_path: str,
    eps_z: float = 0.5,
) -> Dict[str, Any]:
    """
    Check elevation continuity at road boundaries for road-to-road links.

    Parameters
    ----------
    xodr_path : str
        Path to the OpenDRIVE file.
    eps_z : float
        Maximum allowed Z difference at road joins (meters).

    Returns
    -------
    dict
        {
            "ok": bool,
            "eps_z": float,
            "num_roads": int,
            "num_links_checked": int,
            "num_issues": int,
            "issues": [
                {
                    "from_road": str,
                    "to_road": str,
                    "link_kind": str,
                    "z_from_end": float,
                    "z_to_start": float,
                    "dz": float,
                    "warnings": [str]
                }, ...
            ],
            "warnings": [str]
        }
    """
    report: Dict[str, Any] = {
        "ok": True,
        "eps_z": eps_z,
        "num_roads": 0,
        "num_links_checked": 0,
        "num_issues": 0,
        "issues": [],
        "warnings": [],
    }

    try:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
    except Exception as e:
        report["ok"] = False
        report["warnings"].append(f"failed to parse xodr: {e}")
        return report

    roads = root.findall("road")
    report["num_roads"] = len(roads)

    road_by_id: Dict[str, ET.Element] = {}
    for r in roads:
        rid = (r.get("id") or "").strip()
        if rid:
            road_by_id[rid] = r

    issues: List[Dict[str, Any]] = []

    for r in roads:
        rid = (r.get("id") or "").strip()
        if not rid:
            continue

        road_len = _road_length(r)
        links = _road_links(r)

        for link_kind, etype, eid in links:
            if etype != "road":
                continue
            if eid not in road_by_id:
                issues.append({
                    "from_road": rid,
                    "to_road": eid,
                    "link_kind": link_kind,
                    "error": f"linked road id not found: {eid}",
                    "warnings": [],
                })
                continue

            report["num_links_checked"] += 1

            linked_road = road_by_id[eid]
            linked_len = _road_length(linked_road)

            # Successor: current end -> linked start
            # Predecessor: current start -> linked end
            if link_kind == "successor":
                z_from, warn_from = _get_elevation_at_s(r, road_len)
                z_to, warn_to = _get_elevation_at_s(linked_road, 0.0)
                from_label = "z_from_end"
                to_label = "z_to_start"
            else:
                z_from, warn_from = _get_elevation_at_s(r, 0.0)
                z_to, warn_to = _get_elevation_at_s(linked_road, linked_len)
                from_label = "z_from_start"
                to_label = "z_to_end"

            dz = abs(z_from - z_to)

            warn = warn_from + warn_to

            if dz > eps_z:
                issues.append({
                    "from_road": rid,
                    "to_road": eid,
                    "link_kind": link_kind,
                    from_label: z_from,
                    to_label: z_to,
                    "dz": dz,
                    "warnings": warn,
                })

    report["issues"] = issues
    report["num_issues"] = len(issues)
    report["ok"] = len(issues) == 0

    return report


if __name__ == "__main__":
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser()
    ap.add_argument("xodr_path")
    ap.add_argument("--eps-z", type=float, default=0.5)
    args = ap.parse_args()

    rep = check_elevation_continuity(args.xodr_path, eps_z=args.eps_z)
    print(json.dumps(rep, indent=2))
    sys.exit(0 if rep.get("ok", False) else 2)
