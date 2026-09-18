#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Optional post-prune elevation re-projection using DEM samples.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

from ultimate_pipeline.enrichment.elevation_importer import ElevationImporter


def _safe_float(x: Optional[str], default: float = 0.0) -> float:
    try:
        return float(x) if x is not None else default
    except Exception:
        return default


class _Geometry:
    def __init__(
        self,
        s0: float,
        x0: float,
        y0: float,
        hdg0: float,
        length: float,
        kind: str,
        curvature: float = 0.0,
        curv_start: float = 0.0,
        curv_end: float = 0.0,
    ) -> None:
        self.s0 = s0
        self.x0 = x0
        self.y0 = y0
        self.hdg0 = hdg0
        self.length = length
        self.kind = kind
        self.curvature = curvature
        self.curv_start = curv_start
        self.curv_end = curv_end


def _parse_geometries(road_el: ET.Element) -> List[_Geometry]:
    plan = road_el.find("planView")
    if plan is None:
        return []
    geoms: List[_Geometry] = []
    for geom_el in plan.findall("geometry"):
        s0 = _safe_float(geom_el.get("s"))
        x0 = _safe_float(geom_el.get("x"))
        y0 = _safe_float(geom_el.get("y"))
        hdg0 = _safe_float(geom_el.get("hdg"))
        length = _safe_float(geom_el.get("length"))

        kind = "line"
        curvature = 0.0
        curv_start = 0.0
        curv_end = 0.0

        if geom_el.find("line") is not None:
            kind = "line"
        elif (arc := geom_el.find("arc")) is not None:
            kind = "arc"
            curvature = _safe_float(arc.get("curvature"))
        elif (spiral := geom_el.find("spiral")) is not None:
            kind = "spiral"
            curv_start = _safe_float(spiral.get("curvStart"))
            curv_end = _safe_float(spiral.get("curvEnd"))

        geoms.append(_Geometry(s0, x0, y0, hdg0, length, kind, curvature, curv_start, curv_end))

    geoms.sort(key=lambda g: g.s0)
    return geoms


def _pose_line(g: _Geometry, s_local: float) -> Tuple[float, float]:
    x = g.x0 + math.cos(g.hdg0) * s_local
    y = g.y0 + math.sin(g.hdg0) * s_local
    return x, y


def _pose_arc(g: _Geometry, s_local: float) -> Tuple[float, float]:
    k = g.curvature
    if abs(k) < 1e-12:
        return _pose_line(g, s_local)
    dx_local = math.sin(k * s_local) / k
    dy_local = (1.0 - math.cos(k * s_local)) / k
    cos0 = math.cos(g.hdg0)
    sin0 = math.sin(g.hdg0)
    x = g.x0 + cos0 * dx_local - sin0 * dy_local
    y = g.y0 + sin0 * dx_local + cos0 * dy_local
    return x, y


def _pose_spiral(g: _Geometry, s_local: float, ds: float = 0.5) -> Tuple[float, float]:
    L = max(g.length, 1e-9)
    s_local = max(0.0, min(s_local, L))
    x = g.x0
    y = g.y0
    hdg = g.hdg0

    k0 = g.curv_start
    k1 = g.curv_end

    s = 0.0
    while s < s_local - 1e-12:
        step = min(ds, s_local - s)
        smid = s + 0.5 * step
        k_mid = k0 + (k1 - k0) * (smid / L)
        hdg_mid = hdg + k_mid * step
        x += math.cos(hdg) * step
        y += math.sin(hdg) * step
        hdg = hdg_mid
        s += step

    return x, y


def _pose_for_geometry(g: _Geometry, s_local: float) -> Tuple[float, float]:
    if g.kind == "arc":
        return _pose_arc(g, s_local)
    if g.kind == "spiral":
        return _pose_spiral(g, s_local)
    return _pose_line(g, s_local)


def _sample_xy_along_road(geoms: List[_Geometry], s_abs: float) -> Tuple[float, float]:
    if not geoms:
        return 0.0, 0.0
    g_sel = geoms[0]
    for g in geoms:
        if s_abs >= g.s0:
            g_sel = g
        else:
            break
    s_local = max(0.0, min(s_abs - g_sel.s0, g_sel.length))
    return _pose_for_geometry(g_sel, s_local)


def apply_postprune_elevation_autofix(
    xodr_in: str,
    dem_path: str,
    out_xodr: str,
    *,
    sample_step_m: float = 10.0,
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "xodr_in": xodr_in,
        "out_xodr": out_xodr,
        "dem_path": dem_path,
        "sample_step_m": sample_step_m,
        "roads_total": 0,
        "roads_updated": 0,
        "samples_total": 0,
        "samples_valid": 0,
        "warnings": [],
    }

    try:
        tree = ET.parse(xodr_in)
        root = tree.getroot()
    except Exception as e:
        report["warnings"].append(f"failed to parse xodr: {e}")
        return report

    try:
        sampler = ElevationImporter.make_raster_sampler(dem_path, xodr_path=xodr_in)
    except Exception as e:
        report["warnings"].append(f"failed to create DEM sampler: {e}")
        return report

    for road in root.findall("road"):
        report["roads_total"] += 1
        rid = (road.get("id") or "").strip()
        length = _safe_float(road.get("length"))
        if length <= 0:
            continue
        geoms = _parse_geometries(road)
        if not geoms:
            continue

        samples: List[Tuple[float, float]] = []
        s = 0.0
        while s <= length:
            x, y = _sample_xy_along_road(geoms, s)
            z, valid = sampler(x, y)
            report["samples_total"] += 1
            if valid and z is not None and math.isfinite(float(z)):
                samples.append((s, float(z)))
                report["samples_valid"] += 1
            s += sample_step_m

        if len(samples) < 2:
            continue

        profile = road.find("elevationProfile")
        if profile is None:
            profile = ET.SubElement(road, "elevationProfile")
        for el in list(profile.findall("elevation")):
            profile.remove(el)

        for idx, (s0, z0) in enumerate(samples):
            if idx + 1 < len(samples):
                s1, z1 = samples[idx + 1]
                ds = max(1e-3, s1 - s0)
                b = (z1 - z0) / ds
            else:
                b = 0.0
            ET.SubElement(
                profile,
                "elevation",
                {
                    "s": f"{s0:.3f}",
                    "a": f"{z0:.3f}",
                    "b": f"{b:.6f}",
                    "c": "0.0",
                    "d": "0.0",
                },
            )

        report["roads_updated"] += 1

    tree.write(out_xodr, encoding="utf-8", xml_declaration=True)
    return report
