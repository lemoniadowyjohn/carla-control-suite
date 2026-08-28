#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F3 — road structure classification from authoritative OSM, before DEM application.

Classification set (F3 spec):
    terrain-following, bridge, tunnel, underpass, covered, embankment,
    cutting, elevated, unknown

Sources:
- `bridge=*` ways  -> bridge (bridge=covered -> covered)
- `tunnel=*` ways  -> tunnel (tunnel=building_passage -> underpass,
                                 tunnel=covered -> covered)
- `covered=yes`    -> covered
- `embankment=yes` -> embankment
- `cutting=yes`    -> cutting
- bridge with a `layer` tag -> elevated

XODR road ids are NOT OSM way ids (ids are lost during conversion), so roads are
matched SPATIALLY: OSM structure ways are projected into the verified
Osm2Odr native frame (F1) and buffered; each XODR road's planView centreline is
sampled and the covered fraction per structure category is computed.

Fail-closed: any inability to establish structure identity (unparsable OSM,
zero structure ways, zero matched node coordinates, transform failure) raises,
so DEM application cannot silently treat a bridge as terrain.

The module never mutates the XODR document.
"""
from __future__ import annotations

import math
import os
import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from pyproj import CRS, Transformer

    _PYPROJ_OK = True
except Exception:  # pragma: no cover
    CRS = None
    Transformer = None
    _PYPROJ_OK = False

from ultimate_pipeline.dem.dem_crs_contract import (
    OSM2ODR_NATIVE_PROJ4,
    resolve_sampling_crs,
    verify_crs_contract,
)

TERRAIN_FOLLOWING = "terrain_following"
BRIDGE = "bridge"
TUNNEL = "tunnel"
UNDERPASS = "underpass"
COVERED = "covered"
EMBANKMENT = "embankment"
CUTTING = "cutting"
ELEVATED = "elevated"
UNKNOWN = "unknown"

STRUCTURE_CLASSES = {
    BRIDGE,
    TUNNEL,
    UNDERPASS,
    COVERED,
    EMBANKMENT,
    CUTTING,
    ELEVATED,
}

# fraction of road centreline length that must fall inside buffered structure
# geometry for the road to be classified as that structure
DEFAULT_CLASS_FRACTION = 0.60
# structure way buffer half-width (m) around the OSM centreline
DEFAULT_BUFFER_M = 12.0
# sample spacing for road centreline (m)
DEFAULT_SAMPLE_SPACING_M = 4.0
# minimum bridge/tunnel way node count required to trust geometry
MIN_STRUCTURE_NODES = 2


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _safe_float(value: Optional[str], default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except Exception:
        return default


def _wgs84_to_native_transformer(xodr_path: str, osm_path: str) -> Tuple[Any, Dict[str, Any]]:
    """WGS84 -> verified Osm2Odr native frame transformer (F1 contract)."""
    record = verify_crs_contract(xodr_path, osm_path=osm_path)
    verdict = str(record.get("verdict", ""))
    if verdict != "OSM2ODR_NATIVE_VERIFIED":
        raise RuntimeError(
            f"[F3] cannot classify: F1 CRS contract not verified "
            f"(verdict={verdict!r})"
        )
    native = record.get("native_frame") or OSM2ODR_NATIVE_PROJ4
    if not _PYPROJ_OK:
        raise RuntimeError("[F3] pyproj unavailable; cannot project OSM structures")
    src = CRS.from_epsg(4326)
    dst = CRS.from_proj4(native)
    tf = Transformer.from_crs(src, dst, always_xy=True)
    return tf, record


def load_osm_structures(
    osm_path: str,
    *,
    xodr_path: str,
    buffer_m: float = DEFAULT_BUFFER_M,
) -> Dict[str, Any]:
    """Parse OSM and return structure ways projected into the native frame.

    Returns a record with:
        structures: list of {way_id, class, tags, layer, polyline_m}
        nodes_total, structure_ways_total, counts_per_class
        buffer_m
    Fail-closed: raises on unparsable OSM, empty node set, or empty structure set.
    """
    if not os.path.exists(osm_path):
        raise FileNotFoundError(f"[F3] OSM source missing: {osm_path}")
    tf, _record = _wgs84_to_native_transformer(xodr_path, osm_path)

    # Pass 1: all node coordinates (Overpass dumps may list ways before nodes).
    nodes: Dict[str, Tuple[float, float]] = {}
    try:
        for _ev, el in ET.iterparse(osm_path, events=("end",)):
            if _localname(el.tag) == "node":
                try:
                    nodes[el.get("id")] = (
                        float(el.get("lat")),
                        float(el.get("lon")),
                    )
                except Exception:
                    pass
                el.clear()
    except ET.ParseError as exc:
        raise RuntimeError(f"[F3] OSM parse failed: {exc}") from exc
    if not nodes:
        raise RuntimeError("[F3] OSM contains no node coordinates; cannot classify")

    # Pass 2: structure ways resolved against the node table.
    structures: List[Dict[str, Any]] = []
    try:
        for _ev, el in ET.iterparse(osm_path, events=("end",)):
            if _localname(el.tag) != "way":
                continue
            tags: Dict[str, str] = {}
            for tag in el.findall("tag"):
                tags.setdefault(tag.get("k"), tag.get("v"))
            cls = _classify_tags(tags)
            if cls is None:
                el.clear()
                continue
            nds = [n.get("ref") for n in el.findall("nd")]
            pts: List[Tuple[float, float]] = []
            for ref in nds:
                if ref in nodes:
                    lat, lon = nodes[ref]
                    try:
                        x, y = tf.transform(float(lon), float(lat))
                        pts.append((float(x), float(y)))
                    except Exception:
                        continue
            if len(pts) >= MIN_STRUCTURE_NODES:
                structures.append({
                    "way_id": str(el.get("id")),
                    "class": cls,
                    "tags": dict(tags),
                    "layer": _safe_float(tags.get("layer"), 0.0),
                    "polyline_m": pts,
                })
            el.clear()
    except ET.ParseError as exc:
        raise RuntimeError(f"[F3] OSM parse failed: {exc}") from exc

    if not structures:
        raise RuntimeError("[F3] OSM contains no bridge/tunnel/covered/embankment/cutting ways")

    counts: Dict[str, int] = {}
    for s in structures:
        counts[s["class"]] = counts.get(s["class"], 0) + 1
    return {
        "structures": structures,
        "nodes_total": len(nodes),
        "structure_ways_total": len(structures),
        "counts_per_class": counts,
        "buffer_m": float(buffer_m),
    }


def _classify_tags(tags: Dict[str, str]) -> Optional[str]:
    bridge = tags.get("bridge")
    tunnel = tags.get("tunnel")
    if bridge is not None:
        if bridge == "covered":
            return COVERED
        if tags.get("layer") is not None:
            return ELEVATED
        return BRIDGE
    if tunnel is not None:
        if tunnel == "building_passage":
            return UNDERPASS
        if tunnel == "covered":
            return COVERED
        return TUNNEL
    if tags.get("covered") in ("yes", "1"):
        return COVERED
    if tags.get("embankment") in ("yes", "1"):
        return EMBANKMENT
    if tags.get("cutting") in ("yes", "1"):
        return CUTTING
    return None


def _geometry_polyline(geom: ET.Element, spacing_m: float) -> List[Tuple[float, float]]:
    """Densified polyline of one planView geometry primitive."""
    try:
        x = float(geom.get("x"))
        y = float(geom.get("y"))
        hdg = float(geom.get("hdg"))
        length = float(geom.get("length"))
    except Exception:
        return []
    prim = None
    for child in list(geom):
        lname = _localname(child.tag)
        if lname in ("line", "arc", "paramPoly3", "poly3", "spiral"):
            prim = child
            break
    pts: List[Tuple[float, float]] = []
    if prim is None:
        return []
    lname = _localname(prim.tag)
    n = max(2, int(math.ceil(length / spacing_m)) + 1)
    if lname == "line":
        pts = [(x + t * length * math.cos(hdg), y + t * length * math.sin(hdg))
               for t in (i / (n - 1) for i in range(n))]
    elif lname == "arc":
        k = _safe_float(prim.get("curvature"), 0.0)
        if not math.isfinite(k) or abs(k) < 1e-12:
            pts = [(x + t * length * math.cos(hdg), y + t * length * math.sin(hdg))
                   for t in (i / (n - 1) for i in range(n))]
        else:
            pts = []
            for i in range(n):
                t = i / (n - 1)
                s = t * length
                px = x + (math.sin(hdg + k * s) - math.sin(hdg)) / k
                py = y + (-math.cos(hdg + k * s) + math.cos(hdg)) / k
                pts.append((px, py))
    elif lname == "paramPoly3":
        p_range = str(prim.get("pRange", "arcLength"))
        p_max = length if p_range == "arcLength" else 1.0
        a_u = _safe_float(prim.get("aU"))
        b_u = _safe_float(prim.get("bU"))
        c_u = _safe_float(prim.get("cU"))
        d_u = _safe_float(prim.get("dU"))
        a_v = _safe_float(prim.get("aV"))
        b_v = _safe_float(prim.get("bV"))
        c_v = _safe_float(prim.get("cV"))
        d_v = _safe_float(prim.get("dV"))
        cos_h = math.cos(hdg)
        sin_h = math.sin(hdg)
        pts = []
        for i in range(n):
            t = i / (n - 1)
            p = t * p_max
            u = a_u + b_u * p + c_u * p * p + d_u * p * p * p
            v = a_v + b_v * p + c_v * p * p + d_v * p * p * p
            pts.append((x + u * cos_h - v * sin_h, y + u * sin_h + v * cos_h))
    else:
        # poly3 / spiral: coarse straight-segment approximation
        pts = [(x + t * length * math.cos(hdg), y + t * length * math.sin(hdg))
               for t in (i / (n - 1) for i in range(n))]
    return pts


def road_centerline_polyline(
    road: ET.Element, spacing_m: float = DEFAULT_SAMPLE_SPACING_M
) -> List[Tuple[float, float]]:
    """Densified centreline of one road (concatenated geometry primitives)."""
    plan = road.find("planView")
    if plan is None:
        return []
    pts: List[Tuple[float, float]] = []
    for geom in plan.findall("geometry"):
        seg = _geometry_polyline(geom, spacing_m)
        if not seg:
            continue
        if pts and seg:
            last = pts[-1]
            first = seg[0]
            if (last[0] - first[0]) ** 2 + (last[1] - first[1]) ** 2 < 1e-6:
                seg = seg[1:]
        pts.extend(seg)
    return pts


def _point_segment_dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx = bx - ax
    dy = by - ay
    denom = dx * dx + dy * dy
    if denom < 1e-12:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / denom
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _point_polyline_dist(px: float, py: float, poly: List[Tuple[float, float]]) -> float:
    best = math.inf
    for a, b in zip(poly, poly[1:]):
        best = min(best, _point_segment_dist(px, py, a[0], a[1], b[0], b[1]))
    if len(poly) == 1:
        return math.hypot(px - poly[0][0], py - poly[0][1])
    return best


def _polyline_length(poly: List[Tuple[float, float]]) -> float:
    return sum(
        math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(poly, poly[1:])
    )


def _classify_road_centreline(
    pts: List[Tuple[float, float]],
    structures: List[Dict[str, Any]],
    buffer_m: float,
    class_fraction: float,
) -> Dict[str, Any]:
    """Return dominant structure class + covered length fractions per class."""
    if not pts:
        return {
            "class": UNKNOWN,
            "matched_length_m": 0.0,
            "total_length_m": 0.0,
            "coverage_fraction": 0.0,
            "coverage_by_class": {},
            "matched_structures": [],
        }
    total = _polyline_length(pts)
    covered_by_class: Dict[str, float] = {}
    matched_ids: List[str] = []
    for pt in pts:
        hit_class: Optional[str] = None
        for s in structures:
            if _point_polyline_dist(pt[0], pt[1], s["polyline_m"]) <= buffer_m:
                hit_class = s["class"]
                if s["way_id"] not in matched_ids:
                    matched_ids.append(s["way_id"])
                break
        if hit_class is not None:
            covered_by_class[hit_class] = covered_by_class.get(hit_class, 0.0) + 1.0
    matched = sum(covered_by_class.values())
    dominant = max(covered_by_class, key=covered_by_class.get) if covered_by_class else None
    if dominant is None:
        cls = TERRAIN_FOLLOWING
    elif (matched / max(1, len(pts))) >= class_fraction:
        cls = dominant
    else:
        cls = UNKNOWN
    return {
        "class": cls,
        "matched_length_m": matched * (total / max(1, len(pts))),
        "total_length_m": total,
        "coverage_fraction": matched / max(1, len(pts)),
        "coverage_by_class": covered_by_class,
        "matched_structures": matched_ids,
    }


def classify_xodr_roads(
    xodr_path: str,
    *,
    osm_path: str,
    buffer_m: float = DEFAULT_BUFFER_M,
    class_fraction: float = DEFAULT_CLASS_FRACTION,
    sample_spacing_m: float = DEFAULT_SAMPLE_SPACING_M,
) -> Dict[str, Any]:
    """Classify every road of the XODR document. Never mutates the document.

    Returns:
        classification record with per-road {class, coverage_fraction, ...},
        structure summary, and verdict. Raises (fail-closed) when identity
        cannot be established.
    """
    structures_record = load_osm_structures(
        osm_path, xodr_path=xodr_path, buffer_m=buffer_m
    )
    structures = structures_record["structures"]

    if not os.path.exists(xodr_path):
        raise FileNotFoundError(f"[F3] XODR missing: {xodr_path}")
    tree = ET.parse(xodr_path)
    root = tree.getroot()

    per_road: Dict[str, Dict[str, Any]] = {}
    counts: Dict[str, int] = {}
    total_length_m = 0.0
    matched_length_m = 0.0
    for road in root.findall("road"):
        rid = str(road.get("id", "UNKNOWN"))
        pts = road_centerline_polyline(road, spacing_m=sample_spacing_m)
        result = _classify_road_centreline(
            pts, structures, buffer_m=buffer_m, class_fraction=class_fraction
        )
        cls = result["class"]
        counts[cls] = counts.get(cls, 0) + 1
        total_length_m += result["total_length_m"]
        matched_length_m += result["matched_length_m"]
        per_road[rid] = {
            "class": cls,
            "coverage_fraction": round(result["coverage_fraction"], 6),
            "matched_length_m": round(result["matched_length_m"], 3),
            "total_length_m": round(result["total_length_m"], 3),
            "matched_structure_way_ids": result["matched_structures"][:20],
        }

    structure_classes = {cls for cls in counts if cls in STRUCTURE_CLASSES}
    ok = bool(structure_classes) or bool(
        counts.get(TERRAIN_FOLLOWING, 0) and counts.get(UNKNOWN, 0)
    )
    return {
        "verdict": "STRUCTURE_CLASSIFICATION_OK" if ok else "STRUCTURE_CLASSIFICATION_EMPTY",
        "ok": ok,
        "roads_total": len(per_road),
        "class_counts": counts,
        "structure_ways": structures_record,
        "structure_way_ids_matched": sorted(
            {wid for r in per_road.values() for wid in r["matched_structure_way_ids"]}
        ),
        "matched_length_m": round(matched_length_m, 3),
        "total_length_m": round(total_length_m, 3),
        "matched_fraction": round(
            matched_length_m / total_length_m if total_length_m > 0 else 0.0, 6
        ),
        "per_road": per_road,
        "buffer_m": buffer_m,
        "class_fraction": class_fraction,
        "sample_spacing_m": sample_spacing_m,
    }


# ---------------------------------------------------------------------------
# structure-aware elevation policy (F3: never force bridges/tunnels onto DEM)
# ---------------------------------------------------------------------------

STRUCTURE_PROFILE_POLICY = {
    BRIDGE: "deck_linear",
    ELEVATED: "deck_linear",
    TUNNEL: "deck_linear",
    UNDERPASS: "deck_linear",
    COVERED: "terrain_checked",
    EMBANKMENT: "terrain_following",
    CUTTING: "terrain_following",
    TERRAIN_FOLLOWING: "terrain_following",
    UNKNOWN: "fail_closed",
}


def structure_profile_policy(road_class: str) -> str:
    """Elevation policy for a road class (F3 spec: no ground-DEM forcing)."""
    return STRUCTURE_PROFILE_POLICY.get(road_class, "fail_closed")


def structure_road_ids(classification: Dict[str, Any]) -> List[str]:
    """Road ids whose profile must NOT follow ground DEM (deck_linear policy)."""
    return [
        rid
        for rid, rec in classification.get("per_road", {}).items()
        if structure_profile_policy(rec.get("class", UNKNOWN)) == "deck_linear"
    ]


def apply_dem_structure_gate(
    classification: Dict[str, Any],
    *,
    strict: bool = True,
) -> Dict[str, Any]:
    """Gate DEM application on classification identity (fail-closed)."""
    if not isinstance(classification, dict) or not classification.get("ok"):
        if strict:
            raise RuntimeError("[F3] structure classification identity not established")
        return {"gate": "SKIPPED", "reason": "identity_not_established"}
    policy_report: Dict[str, Any] = {}
    for cls, count in classification.get("class_counts", {}).items():
        policy_report[cls] = {
            "roads": count,
            "profile_policy": structure_profile_policy(cls),
        }
    return {
        "gate": "PASS",
        "reason": "structure identity established",
        "policy_report": policy_report,
        "structure_road_count": len(structure_road_ids(classification)),
    }
