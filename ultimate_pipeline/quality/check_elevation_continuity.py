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
        value = float(x) if x is not None else default
    except Exception:
        return default
    # float("nan")/float("inf") parse without raising; a non-finite elevation
    # coefficient must fail closed to `default` rather than silently poison
    # every downstream comparison (NaN comparisons are always False, so a
    # discontinuity gate would otherwise never fire for that road).
    return value if math.isfinite(value) else default


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


def _normalize_contact_point(value: Optional[str]) -> Optional[str]:
    raw = str(value or "").strip().lower()
    if raw in {"start", "end"}:
        return raw
    return None


def _road_links(road_el: ET.Element) -> List[Tuple[str, str, str, Optional[str]]]:
    """Return list of (link_kind, elementType, elementId, contactPoint) for predecessor/successor."""
    out: List[Tuple[str, str, str, Optional[str]]] = []
    link_el = road_el.find("link")
    if link_el is None:
        return out

    for kind in ("predecessor", "successor"):
        el = link_el.find(kind)
        if el is None:
            continue
        etype = (el.get("elementType") or "").strip()
        eid = (el.get("elementId") or "").strip()
        cp = _normalize_contact_point(el.get("contactPoint"))
        if etype and eid:
            out.append((kind, etype, eid, cp))
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

    Endpoint selection mirrors the geometric-continuity checker
    (check_geometric_continuity.py): the source endpoint is implied by the
    link kind (predecessor -> source road START, successor -> source road
    END), while the TARGET endpoint is taken from the link's declared
    ``contactPoint`` attribute (defaulting to "start" only when
    contactPoint is absent/invalid) rather than being hardcoded per link
    kind. This avoids silently comparing the wrong end of the linked road
    when contactPoint="end".

    Links where either the source or target road belongs to a junction
    (junction != "-1") are reported separately under
    ``junction_connector_issues`` / ``num_junction_connector_issues``, since
    junction connector roads join at lane centers (governed by
    <junction><connection><laneLink> semantics and per-lane offsets) rather
    than at the plain road reference-line elevation, and mixing them into
    ``issues`` would dilute genuine ordinary-road z-steps with expected
    junction-lane-offset artifacts.

    Returns
    -------
    dict
        {
            "ok": bool,
            "eps_z": float,
            "num_roads": int,
            "num_links_checked": int,
            "num_junction_connector_links_checked": int,
            "num_issues": int,
            "num_junction_connector_issues": int,
            "issues": [
                {
                    "from_road": str,
                    "to_road": str,
                    "link_kind": str,
                    "contact_point": Optional[str],
                    "z_from_end": float,
                    "z_to_start": float,
                    "dz": float,
                    "warnings": [str]
                }, ...
            ],
            "junction_connector_issues": [...same shape as issues...],
            "warnings": [str]
        }
    """
    report: Dict[str, Any] = {
        "ok": True,
        "eps_z": eps_z,
        "num_roads": 0,
        "num_links_checked": 0,
        "num_junction_connector_links_checked": 0,
        "num_issues": 0,
        "num_junction_connector_issues": 0,
        "issues": [],
        "junction_connector_issues": [],
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
    junction_connector_issues: List[Dict[str, Any]] = []

    for r in roads:
        rid = (r.get("id") or "").strip()
        if not rid:
            continue

        road_len = _road_length(r)
        links = _road_links(r)
        source_is_junction_connector = str(r.get("junction") or "-1").strip() != "-1"

        for link_kind, etype, eid, contact_point in links:
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

            linked_road = road_by_id[eid]
            linked_len = _road_length(linked_road)
            target_is_junction_connector = str(linked_road.get("junction") or "-1").strip() != "-1"
            is_junction_connector_link = source_is_junction_connector or target_is_junction_connector

            if is_junction_connector_link:
                report["num_junction_connector_links_checked"] += 1
            else:
                report["num_links_checked"] += 1

            # Target endpoint is selected by the link's declared
            # contactPoint (default "start" when absent), NOT hardcoded by
            # link kind -- a successor link with contactPoint="end" must be
            # evaluated at the linked road's END, not its start.
            target_endpoint = contact_point or "start"
            target_s = 0.0 if target_endpoint == "start" else linked_len

            # Successor: current end -> linked target endpoint
            # Predecessor: current start -> linked target endpoint
            if link_kind == "successor":
                z_from, warn_from = _get_elevation_at_s(r, road_len)
                from_label = "z_from_end"
            else:
                z_from, warn_from = _get_elevation_at_s(r, 0.0)
                from_label = "z_from_start"

            z_to, warn_to = _get_elevation_at_s(linked_road, target_s)
            to_label = "z_to_start" if target_endpoint == "start" else "z_to_end"

            dz = abs(z_from - z_to)

            warn = warn_from + warn_to

            if dz > eps_z:
                record = {
                    "from_road": rid,
                    "to_road": eid,
                    "link_kind": link_kind,
                    "contact_point": contact_point,
                    from_label: z_from,
                    to_label: z_to,
                    "dz": dz,
                    "warnings": warn,
                }
                if is_junction_connector_link:
                    junction_connector_issues.append(record)
                else:
                    issues.append(record)

    report["issues"] = issues
    report["junction_connector_issues"] = junction_connector_issues
    report["num_issues"] = len(issues)
    report["num_junction_connector_issues"] = len(junction_connector_issues)
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
