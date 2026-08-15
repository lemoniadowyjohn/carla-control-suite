#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F1 — CRS contract for the frozen horizontal candidate.

Establishes, with evidence, the geographic frame of the candidate XODR
geometry before any DEM sampling is allowed:

- The frozen candidate was produced by CARLA Osm2Odr from the authoritative
  Ingolstadt OSM extract.  Osm2Odr's native output frame is
  ``tmerc(lat_0=0, lon_0=0, k=1, x_0=0, y_0=0, datum=WGS84)`` (proven by the
  WP1 wheel probe, reports/ingolstadt_map_quality_v2 PHASE_1A_DIAGNOSIS.md).
- The header geoReference of the pinned candidate claims EPSG:32632
  (``+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0``).  That pin
  is metadata-only: the geometry was never reprojected, so interpreting the
  geometry in the claimed CRS places the map ~162 km east / ~59 km north of
  true Ingolstadt (13.6E/49.3N instead of 11.43E/48.77N).
- WP1 coordinate truth (candidate_actual_reprojection.xodr) re-projected the
  candidate through inverse-tmerc(0,0) -> WGS84 -> EPSG:32632 with 0.0 m
  round-trip error, so the native frame is the verified ground truth.

``verify_crs_contract`` decides, per candidate:

- CLAIMED_CRS_VERIFIED   — the header claim is geographically plausible
  (header bounds in the claimed CRS fall inside the OSM source bounds).
- OSM2ODR_NATIVE_VERIFIED — the header claim is disproven (it would place the
  map far outside the OSM source bounds) and the Osm2Odr native frame places
  the header bounds inside the OSM source bounds.
- UNRESOLVED            — neither frame can be established.  Fail closed:
  DEM sampling must not proceed.

The decision is recorded with the transforms used so elevation evidence can
show exactly which frame the DEM was sampled in.
"""
from __future__ import annotations

import math
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

try:
    from pyproj import CRS, Transformer
except Exception:  # pragma: no cover - pyproj is required for DEM phases
    CRS = None
    Transformer = None

#: Osm2Odr native output frame (verified against WP1 reprojection, 0.0 m).
OSM2ODR_NATIVE_PROJ4 = (
    "+proj=tmerc +lat_0=0 +lon_0=0 +k=1 +x_0=0 +y_0=0 +datum=WGS84 "
    "+units=m +no_defs"
)

#: Pinned-candidate control point and its verified WGS84 location.
#: Pinned XODR geometry start of road 39830 == WP1 candidate_actual_reprojection
#: road 39830 start (678942.92, 5402201.68) via
#: inverse-tmerc(0,0) -> WGS84 -> EPSG:32632 (round-trip max error 0.0 m).
WP1_CONTROL_POINT = {
    "xodr_x": 840138.71778614,
    "xodr_y": 5464923.98146263,
    "wgs84_lon": 11.434291,
    "wgs84_lat": 48.747103,
    "utm32n_x": 678942.92,
    "utm32n_y": 5402201.68,
    "source": "WP1 candidate_actual_reprojection.xodr, road 39830 (0.0 m verified)",
}

#: Tolerance applied to the OSM source bounds when judging plausibility
#: (road extents are smaller than node extents; keep a generous margin).
PLAUSIBILITY_MARGIN_DEG = 0.15


def _localname(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def claimed_crs_from_xodr(xodr_path: str) -> Tuple[Optional[Any], Optional[str], Optional[str]]:
    """Return (CRS object, raw proj4 text, reason) for the header geoReference."""
    if CRS is None:
        return None, None, "pyproj_unavailable"
    try:
        tree = ET.parse(xodr_path)
    except Exception as exc:
        return None, None, f"parse_error:{exc}"
    root = tree.getroot()
    header = root.find("header")
    if header is None:
        return None, None, "no_header"
    geo = header.find("geoReference")
    if geo is None or not (geo.text or "").strip():
        return None, None, "no_geoReference"
    raw = str(geo.text or "").strip()
    try:
        crs = CRS.from_user_input(raw)
        return crs, raw, "parsed"
    except Exception as exc:
        return None, raw, f"crs_parse_failed:{exc}"


def header_bounds_from_xodr(xodr_path: str) -> Optional[Dict[str, float]]:
    try:
        tree = ET.parse(xodr_path)
    except Exception:
        return None
    root = tree.getroot()
    header = root.find("header")
    if header is None:
        return None
    try:
        return {
            "west": float(header.get("west")),
            "east": float(header.get("east")),
            "south": float(header.get("south")),
            "north": float(header.get("north")),
        }
    except Exception:
        return None


def _default_header_offset() -> Dict[str, float]:
    return {"x": 0.0, "y": 0.0, "z": 0.0, "hdg": 0.0}


def header_offset_from_xodr(xodr_path: str) -> Dict[str, float]:
    try:
        tree = ET.parse(xodr_path)
    except Exception:
        return _default_header_offset()
    root = tree.getroot()
    header = root.find("header")
    if header is None:
        return _default_header_offset()
    off = header.find("offset")
    if off is None:
        return _default_header_offset()
    out = _default_header_offset()
    for key in ("x", "y", "z", "hdg"):
        try:
            out[key] = float(off.get(key, out[key]))
        except Exception:
            out[key] = 0.0
    return out


def _apply_header_offset_to_point(
    x: float, y: float, offset: Dict[str, float]
) -> Tuple[float, float]:
    hdg = float(offset.get("hdg", 0.0))
    ox = float(offset.get("x", 0.0))
    oy = float(offset.get("y", 0.0))
    cos_h = math.cos(hdg)
    sin_h = math.sin(hdg)
    return (float(x) * cos_h - float(y) * sin_h + ox, float(x) * sin_h + float(y) * cos_h + oy)


def _bounds_with_header_offset(
    bounds: Optional[Dict[str, float]], offset: Dict[str, float]
) -> Optional[Dict[str, float]]:
    if bounds is None:
        return None
    corners = (
        (float(bounds["west"]), float(bounds["south"])),
        (float(bounds["west"]), float(bounds["north"])),
        (float(bounds["east"]), float(bounds["south"])),
        (float(bounds["east"]), float(bounds["north"])),
    )
    xs = []
    ys = []
    for x, y in corners:
        xx, yy = _apply_header_offset_to_point(x, y, offset)
        xs.append(xx)
        ys.append(yy)
    return {"west": min(xs), "east": max(xs), "south": min(ys), "north": max(ys)}


def _geometry_endpoint(
    x: float, y: float, hdg: float, length: float, prim: ET.Element
) -> tuple:
    """Exact endpoint for line/arc/paramPoly3 primitives (bbox purposes)."""
    lname = _localname(prim.tag)
    if lname == "line":
        return (x + length * math.cos(hdg), y + length * math.sin(hdg))
    if lname == "arc":
        try:
            k = float(prim.get("curvature", "0.0"))
        except Exception:
            k = 0.0
        if abs(k) < 1e-9:
            return (x + length * math.cos(hdg), y + length * math.sin(hdg))
        return (
            x + (math.sin(hdg + k * length) - math.sin(hdg)) / k,
            y + (-math.cos(hdg + k * length) + math.cos(hdg)) / k,
        )
    if lname == "paramPoly3":
        try:
            p_range = str(prim.get("pRange", "arcLength"))
            p_max = float(length) if p_range == "arcLength" else 1.0
            a_u = float(prim.get("aU", "0"))
            b_u = float(prim.get("bU", "0"))
            c_u = float(prim.get("cU", "0"))
            d_u = float(prim.get("dU", "0"))
            a_v = float(prim.get("aV", "0"))
            b_v = float(prim.get("bV", "0"))
            c_v = float(prim.get("cV", "0"))
            d_v = float(prim.get("dV", "0"))
        except Exception:
            return (x + length * math.cos(hdg), y + length * math.sin(hdg))
        p = p_max
        u = a_u + b_u * p + c_u * p * p + d_u * p * p * p
        v = a_v + b_v * p + c_v * p * p + d_v * p * p * p
        cos_h = math.cos(hdg)
        sin_h = math.sin(hdg)
        return (x + u * cos_h - v * sin_h, y + u * sin_h + v * cos_h)
    return (x + length * math.cos(hdg), y + length * math.sin(hdg))


def _planview_bbox(xodr_path: str) -> Optional[Dict[str, float]]:
    """Bbox of ALL planView geometry: starts AND exact endpoints."""
    minx = miny = math.inf
    maxx = maxy = -math.inf
    found = False
    try:
        for ev, el in ET.iterparse(xodr_path, events=("start", "end")):
            if _localname(el.tag) == "planView" and ev == "end":
                el.clear()
                continue
            if _localname(el.tag) == "geometry" and ev == "end":
                try:
                    x = float(el.get("x"))
                    y = float(el.get("y"))
                    hdg = float(el.get("hdg"))
                    length = float(el.get("length"))
                except Exception:
                    el.clear()
                    continue
                prim = None
                for child in list(el):
                    if _localname(child.tag) in ("line", "arc", "paramPoly3"):
                        prim = child
                        break
                if prim is None:
                    el.clear()
                    continue
                ex, ey = _geometry_endpoint(x, y, hdg, length, prim)
                found = True
                minx = min(minx, x, ex)
                maxx = max(maxx, x, ex)
                miny = min(miny, y, ey)
                maxy = max(maxy, y, ey)
                el.clear()
    except Exception:
        return None
    if not found:
        return None
    return {"west": minx, "east": maxx, "south": miny, "north": maxy}


def osm_source_bounds(osm_path: str) -> Optional[Dict[str, float]]:
    """Stream the OSM extract and compute node bounds (WGS84)."""
    node_re = re.compile(r'<node .*?lat="(-?[\d.]+)" lon="(-?[\d.]+)"')
    min_lat = min_lon = math.inf
    max_lat = max_lon = -math.inf
    count = 0
    try:
        with open(osm_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = node_re.search(line)
                if m:
                    lat, lon = float(m.group(1)), float(m.group(2))
                    count += 1
                    min_lat = min(min_lat, lat)
                    max_lat = max(max_lat, lat)
                    min_lon = min(min_lon, lon)
                    max_lon = max(max_lon, lon)
    except Exception:
        return None
    if count == 0:
        return None
    return {
        "lat_min": min_lat,
        "lat_max": max_lat,
        "lon_min": min_lon,
        "lon_max": max_lon,
    }


def _bbox_to_wgs84(
    bbox: Dict[str, float], src_crs: Any
) -> Optional[Dict[str, float]]:
    if CRS is None or Transformer is None:
        return None
    try:
        tf = Transformer.from_crs(src_crs, CRS.from_epsg(4326), always_xy=True)
    except Exception:
        return None
    try:
        corners = (
            (float(bbox["west"]), float(bbox["south"])),
            (float(bbox["west"]), float(bbox["north"])),
            (float(bbox["east"]), float(bbox["south"])),
            (float(bbox["east"]), float(bbox["north"])),
        )
        tx: List[float] = []
        ty: List[float] = []
        for x, y in corners:
            xx, yy = tf.transform(x, y)
            tx.append(float(xx))
            ty.append(float(yy))
    except Exception:
        return None
    return {"lon_min": min(tx), "lat_min": min(ty), "lon_max": max(tx), "lat_max": max(ty)}


def _expanded(bounds: Dict[str, float], margin_deg: float) -> Dict[str, float]:
    return {
        "lat_min": bounds["lat_min"] - margin_deg,
        "lat_max": bounds["lat_max"] + margin_deg,
        "lon_min": bounds["lon_min"] - margin_deg,
        "lon_max": bounds["lon_max"] + margin_deg,
    }


def _inside(bounds: Dict[str, float], expanded: Dict[str, float]) -> bool:
    return bool(
        bounds.get("lat_min") is not None
        and bounds["lat_min"] >= expanded["lat_min"]
        and bounds["lat_max"] <= expanded["lat_max"]
        and bounds["lon_min"] >= expanded["lon_min"]
        and bounds["lon_max"] <= expanded["lon_max"]
    )


def osm2odr_native_crs() -> Optional[Any]:
    if CRS is None:
        return None
    try:
        return CRS.from_proj4(OSM2ODR_NATIVE_PROJ4)
    except Exception:
        return None


def verify_crs_contract(
    xodr_path: str, osm_bounds: Optional[Dict[str, float]] = None, *, osm_path: Optional[str] = None
) -> Dict[str, Any]:
    """Decide which geographic frame the candidate geometry is in.

    Fail-closed: returns verdict UNRESOLVED unless one frame is established.
    """
    if osm_bounds is None and osm_path is not None:
        osm_bounds = osm_source_bounds(osm_path)
    if osm_bounds is None:
        return {
            "verdict": "UNRESOLVED",
            "reason": "osm_source_unavailable",
            "osm_bounds": None,
        }
    header_bounds_raw = header_bounds_from_xodr(xodr_path)
    geometry_bounds = _planview_bbox(xodr_path)
    bounds_source = "header"
    if header_bounds_raw is None:
        header_bounds_raw = geometry_bounds
        bounds_source = "planView"
    if header_bounds_raw is None:
        return {
            "verdict": "UNRESOLVED",
            "reason": "no_geometry_bounds",
            "osm_bounds": osm_bounds,
        }
    header_offset = header_offset_from_xodr(xodr_path)
    header_bounds = _bounds_with_header_offset(header_bounds_raw, header_offset)
    geometry_bounds_with_offset = _bounds_with_header_offset(
        geometry_bounds, header_offset
    )

    expanded = _expanded(osm_bounds, PLAUSIBILITY_MARGIN_DEG)

    claimed_crs, claimed_raw, claimed_reason = claimed_crs_from_xodr(xodr_path)
    claimed_wgs84 = (
        _bbox_to_wgs84(header_bounds, claimed_crs)
        if claimed_crs is not None
        else None
    )
    claimed_plausible = bool(
        claimed_wgs84 is not None and _inside(claimed_wgs84, expanded)
    )

    native_crs = osm2odr_native_crs()
    native_wgs84 = (
        _bbox_to_wgs84(header_bounds, native_crs)
        if native_crs is not None
        else None
    )
    native_plausible = bool(
        native_wgs84 is not None and _inside(native_wgs84, expanded)
    )

    if claimed_plausible and not native_plausible:
        verdict = "CLAIMED_CRS_VERIFIED"
        reason = "claimed_geoReference_plausible_against_osm"
    elif native_plausible and not claimed_plausible:
        verdict = "OSM2ODR_NATIVE_VERIFIED"
        reason = "claimed_geoReference_disproven;osm2odr_native_frame_matches_osm"
    elif claimed_plausible and native_plausible:
        verdict = "AMBIGUOUS"
        reason = "both_frames_plausible;prefer_claimed_with_warning"
    else:
        verdict = "UNRESOLVED"
        reason = "no_frame_matches_osm_source"

    control = WP1_CONTROL_POINT
    control_error_m = None
    if native_crs is not None and claimed_crs is not None and Transformer is not None:
        try:
            tf = Transformer.from_crs(
                claimed_crs, CRS.from_epsg(4326), always_xy=True
            )
            lon, lat = tf.transform(control["xodr_x"], control["xodr_y"])
            control_error_m = math.hypot(
                (lon - control["wgs84_lon"]) * 111320.0 * math.cos(math.radians(lat)),
                (lat - control["wgs84_lat"]) * 110540.0,
            )
        except Exception:
            control_error_m = None

    return {
        "verdict": verdict,
        "reason": reason,
        "osm_bounds": osm_bounds,
        "osm_bounds_expanded_deg": PLAUSIBILITY_MARGIN_DEG,
        "bounds_source": bounds_source,
        "header_bounds": header_bounds_raw,
        "header_offset": header_offset,
        "header_bounds_with_offset": header_bounds,
        "geometry_bounds": geometry_bounds,
        "geometry_bounds_with_offset": geometry_bounds_with_offset,
        "claimed_crs": str(claimed_crs) if claimed_crs is not None else None,
        "claimed_proj4": claimed_raw,
        "claimed_crs_reason": claimed_reason,
        "claimed_crs_header_bounds_wgs84": claimed_wgs84,
        "claimed_plausible": claimed_plausible,
        "native_frame": OSM2ODR_NATIVE_PROJ4,
        "native_frame_header_bounds_wgs84": native_wgs84,
        "native_plausible": native_plausible,
        "wp1_control_point": control,
        "wp1_control_point_error_m_if_claimed_crs": control_error_m,
    }


def resolve_sampling_crs(
    xodr_path: str,
    *,
    osm_bounds: Optional[Dict[str, float]] = None,
    osm_path: Optional[str] = None,
    strict: bool = True,
) -> Tuple[Optional[Any], str, Dict[str, Any]]:
    """Return (CRS for DEM sampling, source label, verification record).

    Raises RuntimeError (fail closed) when the frame cannot be established and
    strict is True.  In non-strict mode returns (None, "unverified", record).
    """
    record = verify_crs_contract(xodr_path, osm_bounds, osm_path=osm_path)
    verdict = record["verdict"]
    if verdict == "OSM2ODR_NATIVE_VERIFIED":
        return osm2odr_native_crs(), "osm2odr_native_verified", record
    if verdict == "CLAIMED_CRS_VERIFIED":
        claimed, _, _ = claimed_crs_from_xodr(xodr_path)
        return claimed, "claimed_geoReference_verified", record
    if verdict == "AMBIGUOUS":
        claimed, _, _ = claimed_crs_from_xodr(xodr_path)
        if claimed is not None:
            return claimed, "claimed_geoReference_ambiguous", record
    if strict:
        raise RuntimeError(
            "F1 CRS contract unresolved: cannot establish the geographic "
            f"frame of {xodr_path} (verdict={verdict}, reason={record.get('reason')}). "
            "DEM sampling fails closed. Provide the OSM source or a resolvable "
            "geoReference."
        )
    return None, "unverified", record


def map_wgs84_extent(
    xodr_path: str,
    *,
    osm_bounds: Optional[Dict[str, float]] = None,
    osm_path: Optional[str] = None,
    strict: bool = True,
) -> Dict[str, Any]:
    """True WGS84 extent of the candidate geometry (from planView)."""
    crs, source, record = resolve_sampling_crs(
        xodr_path, osm_bounds=osm_bounds, osm_path=osm_path, strict=strict
    )
    bbox = _planview_bbox(xodr_path)
    extent = _bbox_to_wgs84(bbox, crs) if bbox is not None and crs is not None else None
    return {
        "extent_wgs84": extent,
        "bbox_in_xodr_frame": bbox,
        "sampling_crs": str(crs) if crs is not None else None,
        "sampling_crs_source": source,
        "verification": record,
    }
