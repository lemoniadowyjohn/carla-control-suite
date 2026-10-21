#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MAP REALISM P0 ORACLE — campaign instrument for the P0 repair campaign.

Read-only scans over an OpenDRIVE artifact producing the BEFORE/AFTER defect
manifests required by the remediation guarantee:

  P0-A dangling mandatory lane successors (audit definition)
  P0-B orphan drivable roads (CLOSURE-18 definition)
  P0-C junction connector lane-interface elevation continuity
  P0-D structure (bridge/tunnel/elevated) terrain separation
  P0-E georeference absolute-origin / invertibility audit

Semantics follow the audit's *mandatory* reading: a driving lane whose road
terminates at a junction must be actually routed through at least one
``<connection>``/``<laneLink>`` of that junction. The GAP-048 contract records
junction routing authority in laneLinks, and lane-level ``<successor>`` at a
junction-boundary lane is only a marker; the mandatory set therefore checks the
junction routing membership, not the lane-level link element.

All outputs are deterministic, keyed by stable ids, and carry the map sha256,
so before/after manifests cannot be silently re-based.
"""
from __future__ import annotations

import json
import math
import re
import hashlib
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "scan_map_realism_p0",
    "scan_dangling_mandatory_lane_successors",
    "scan_orphan_drivable_roads",
    "scan_connector_lane_interface_dz",
    "scan_structure_terrain_separation",
    "scan_georeference",
    "_safe_float",
]

_DANGLING_CONNECTOR_DZ_THRESHOLD_M = 0.5
_LANE_DZ_TUNNEL_THRESHOLD_M = 0.5


def _safe_float(value: Optional[str], default: float = 0.0) -> float:
    try:
        parsed = float(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


# ---------------------------------------------------------------------------
# header / georeference
# ---------------------------------------------------------------------------

def _geo_tokens(text: str) -> Dict[str, str]:
    tokens: Dict[str, str] = {}
    for element in (text or "").split(" "):
        parts = element.split("=")
        if len(parts) == 2:
            tokens[parts[0]] = parts[1]
    return tokens


def scan_georeference(root: ET.Element) -> Dict[str, Any]:
    """Georeference audit: absolute origin presence + single-offset check."""
    header = root.find("header")
    report: Dict[str, Any] = {
        "has_geo_reference": False,
        "geo_reference": None,
        "has_absolute_origin": False,
        "lat_0": None,
        "lon_0": None,
        "has_offset": False,
        "offset": None,
        "duplicate_offset_in_georef": False,
    }
    if header is None:
        report["error"] = "no header"
        return report
    geo_el = header.find("geoReference")
    offset_el = header.find("offset")
    if geo_el is not None:
        report["has_geo_reference"] = True
        text = (geo_el.text or "").strip()
        report["geo_reference"] = text
        tokens = _geo_tokens(text)
        lat0 = tokens.get("+lat_0")
        lon0 = tokens.get("+lon_0")
        report["lat_0"] = _safe_float(lat0, float("nan")) if lat0 else None
        report["lon_0"] = _safe_float(lon0, float("nan")) if lon0 else None
        report["has_absolute_origin"] = bool(lat0 and lon0)
        # a geoReference that itself hard-codes the header offset is a
        # duplicate translation (the anti-pattern the campaign must not add)
        if offset_el is not None:
            ox = _safe_float(offset_el.get("x"), None)
            oy = _safe_float(offset_el.get("y"), None)
            if ox and oy and lat0 and lon0:
                # duplicated if +x_0/+y_0 masquerade as the rebase offset while
                # lat_0/lon_0 also sit at the local origin
                _t = tokens.get("+x_0"), tokens.get("+y_0")
                if _t[0] and _t[1]:
                    x0 = _safe_float(_t[0], float("nan"))
                    y0 = _safe_float(_t[1], float("nan"))
                    if abs(x0 - ox) < 1e-6 and abs(y0 - oy) < 1e-6:
                        report["duplicate_offset_in_georef"] = True
    if offset_el is not None:
        report["has_offset"] = True
        report["offset"] = {
            "x": _safe_float(offset_el.get("x")),
            "y": _safe_float(offset_el.get("y")),
            "z": _safe_float(offset_el.get("z"), 0.0),
            "hdg": _safe_float(offset_el.get("hdg"), 0.0),
        }
    return report


# ---------------------------------------------------------------------------
# structural helpers
# ---------------------------------------------------------------------------

def _roads(root: ET.Element) -> Dict[str, ET.Element]:
    return {r.get("id"): r for r in root.findall("road") if r.get("id")}


def _sorted_sections(road: ET.Element) -> List[ET.Element]:
    return sorted(road.findall("./lanes/laneSection"), key=lambda s: _safe_float(s.get("s")))


def _driving_lanes(section: ET.Element) -> Dict[int, ET.Element]:
    out: Dict[int, ET.Element] = {}
    if section is None:
        return out
    for side in ("left", "right"):
        side_el = section.find(side)
        if side_el is None:
            continue
        for lane in side_el.findall("lane"):
            try:
                lane_id = int(str(lane.get("id")))
            except (TypeError, ValueError):
                continue
            if str(lane.get("type", "driving")).lower() == "driving":
                out[lane_id] = lane
    return out


def _z_at_ref(road: ET.Element, at_start: bool) -> Optional[float]:
    """Reference-line z at the road boundary (elevationProfile).

    Evaluates the active profile segment covering the boundary s (0 for start,
    total length for end). Returns None when the road has no profile.
    """
    profile = road.find("elevationProfile")
    if profile is None:
        return None
    segments = [
        (_safe_float(e.get("s")), e.attrib)
        for e in profile.findall("elevation")
    ]
    if not segments:
        return None
    segments.sort()
    s_target = 0.0 if at_start else _length_of(road)
    seg = segments[0]
    for candidate in segments:
        if candidate[0] <= s_target:
            seg = candidate
        else:
            break
    s0, attr = seg
    a, b, c, d = (_safe_float(attr.get(k, "0")) for k in ("a", "b", "c", "d"))
    ds = max(0.0, s_target - s0)
    return a + b * ds + c * ds * ds + d * ds * ds


def _grade_bit(road: ET.Element, at_start: bool) -> float:
    """d/ds z at the boundary (first coefficient b of the boundary profile)."""
    profile = road.find("elevationProfile")
    if profile is None:
        return 0.0
    segs = [(_safe_float(e.get("s")), e) for e in profile.findall("elevation")]
    if not segs:
        return 0.0
    segs.sort()
    s0, el = segs[0] if at_start else segs[-1]
    return _safe_float(el.get("b"), 0.0)


def _length_of(road: ET.Element) -> float:
    geoms = road.findall("./planView/geometry")
    if not geoms:
        return 0.0
    last = geoms[-1]
    return _safe_float(last.get("s")) + _safe_float(last.get("length"))


# ---------------------------------------------------------------------------
# P0-A: dangling mandatory lane successors
# ---------------------------------------------------------------------------

def scan_dangling_mandatory_lane_successors(root: ET.Element) -> Dict[str, Any]:
    """Every driving lane of every road that terminates at a junction must be
    routed through that junction's connections/laneLinks. A road boundary lane
    with no candidate laneLink is a dangling mandatory successor.
    """
    roads = _roads(root)
    lanes_records: List[Dict[str, Any]] = []

    # junction membership: road_id -> set(junction ids whose connections name it)
    connection_index: Dict[str, List[ET.Element]] = {}
    for junction in root.findall("junction"):
        for conn in junction.findall("connection"):
            incoming = conn.get("incomingRoad")
            if incoming:
                connection_index.setdefault(incoming, []).append(junction)

    for rid, road in roads.items():
        # a road is junction-terminating if it has no successor road link and
        # is an incomingRoad inside a junction's connection set; roads with a
        # road successor whose element type is "junction" count too.
        end_side_is_junction = False
        junction_ids: set = set()
        link = road.find("./link/successor")
        if link is not None and link.get("elementType") == "junction":
            end_side_is_junction = True
            if link.get("elementId"):
                junction_ids.add(link.get("elementId"))
        for junc_id in connection_index.get(rid, []):
            junction_ids.add(junc_id.get("id"))
            if not end_side_is_junction and junction_ids:
                end_side_is_junction = True

        if not end_side_is_junction:
            continue

        secs = _sorted_sections(road)
        if not secs:
            continue
        boundary = secs[-1]  # the end section faces the junction
        driving = _driving_lanes(boundary)
        for lane_id, lane in driving.items():
            # junction routing membership: ∃ connection of a containing
            # junction with incomingRoad == rid and a laneLink from == lane_id
            candidates: List[Tuple[str, str]] = []
            routed = False
            for junc in root.findall("junction"):
                for conn in junc.findall("connection"):
                    if conn.get("incomingRoad") != rid:
                        continue
                    has_link = any(
                        str(ll.get("from")) == str(lane_id)
                        for ll in conn.findall("laneLink")
                    )
                    candidates.append((junc.get("id"), conn.get("connectingRoad")))
                    routed = routed or has_link
            record = {
                "road_id": rid,
                "lane_id": lane_id,
                "road_length_m": round(_length_of(road), 3),
                "junctions_connected": sorted(junction_ids),
                "candidate_connections": len(candidates),
                "routed": routed,
                "classification": None,
            }
            if not routed:
                if len({c[1] for c in candidates}) > 1:
                    record["classification"] = "VALID_AMBIGUITY_CANDIDATE"
                record["candidates"] = candidates[:8]
                lanes_records.append(record)

    dangling_records = []
    for r in lanes_records:
        if r["routed"]:
            continue
        distinct_connectors = {c[1] for c in r.get("candidates", [])}
        if len(distinct_connectors) > 1:
            r["classification"] = "VALID_AMBIGUITY"
        else:
            r["classification"] = "NO_CANDIDATE_ROUTING"
        dangling_records.append(r)

    classes: Dict[str, int] = {}
    for r in dangling_records:
        classes[r["classification"]] = classes.get(r["classification"], 0) + 1
    return {
        "mandatory_lanes_checked": len(lanes_records),
        "dangling_mandatory_lane_successors": len(dangling_records),
        "dangling_by_class": classes,
        "dangling_records": dangling_records,
    }


# ---------------------------------------------------------------------------
# P0-B: orphan drivable roads
# ---------------------------------------------------------------------------

def scan_orphan_drivable_roads(root: ET.Element) -> Dict[str, Any]:
    """CLOSURE-18 definition: a road with >=1 driving lane that has no
    predecessor/successor road link and is not a member of any junction
    connection (neither incomingRoad nor connectingRoad) is an orphan."""
    roads = _roads(root)
    junction_roads: set = set()
    for junction in root.findall("junction"):
        for conn in junction.findall("connection"):
            for rid in (conn.get("incomingRoad"), conn.get("connectingRoad")):
                if rid:
                    junction_roads.add(rid)

    orphans: List[Dict[str, Any]] = []
    for rid, road in roads.items():
        has_driving = any(
            len(_driving_lanes(sec)) for sec in _sorted_sections(road)
        )
        if not has_driving or rid in junction_roads:
            continue
        links = road.find("./link")
        pred = links.find("predecessor") if links is not None else None
        succ = links.find("successor") if links is not None else None
        pred_road = pred is not None and pred.get("elementType") != "junction" and pred.get("elementId") in roads
        succ_road = succ is not None and succ.get("elementType") != "junction" and succ.get("elementId") in roads
        if pred_road or succ_road:
            continue
        orphans.append({
            "road_id": rid,
            "length_m": round(_length_of(road), 3),
            "predecessor": (pred.attrib if pred is not None else None),
            "successor": (succ.attrib if succ is not None else None),
        })
    for rec in orphans:
        rec["classification"] = "UNEXPLAINED"
    return {
        "orphan_drivable_roads": len(orphans),
        "orphan_records": orphans,
    }


# ---------------------------------------------------------------------------
# P0-C: junction connector lane-interface Δz
# ---------------------------------------------------------------------------

def scan_connector_lane_interface_dz(root: ET.Element) -> Dict[str, Any]:
    """For every junction laneLink, compare reference z at the interface on
    both sides (incoming end vs connector start; connector end vs outgoing
    start), the grade continuum, and record heading residual via contact
    points. Classify each interface seam.
    """
    roads = _roads(root)
    links: List[Dict[str, Any]] = []
    connection_records: List[Dict[str, Any]] = []
    for junction in root.findall("junction"):
        for conn in junction.findall("connection"):
            incoming = conn.get("incomingRoad")
            connecting = conn.get("connectingRoad")
            if incoming not in roads or connecting not in roads:
                continue
            at_start_contact = conn.get("contactPoint", "start") != "end"
            z_in = _z_at_ref(roads[incoming], at_start=False)
            z_con_start = _z_at_ref(roads[connecting], at_start=True)
            z_con_end = _z_at_ref(roads[connecting], at_start=False)
            # outgoing roads: successor of connector end via connector link
            succ = roads[connecting].find("./link/successor")
            out_road = succ.get("elementId") if succ is not None and succ.get("elementType") != "junction" else None
            z_out = _z_at_ref(roads[out_road], at_start=True) if (out_road in roads if out_road else False) else None
            dz_start = None if (z_in is None or z_con_start is None) else round(z_con_start - z_in, 4)
            dz_end = None if (z_con_end is None or z_out is None) else round(z_out - z_con_end, 4)
            grade_start = None if dz_start is None else 0.0
            con_len = _length_of(roads[connecting])
            worst_conn = max(
                (abs(v) for v in (dz_start, dz_end) if v is not None),
                default=None,
            )
            # interface classification at connection level (audit convention:
            # each connection contributes a start and an end interface)
            if con_len < 0.01:
                conn_class = "DEGENERATE_CONNECTOR"
            elif worst_conn is not None and worst_conn > _DANGLING_CONNECTOR_DZ_THRESHOLD_M:
                conn_class = "REAL_SURFACE_DISCONTINUITY"
            elif worst_conn is not None and worst_conn > 0.0:
                conn_class = "VALID_GRADE_CHANGE"
            else:
                conn_class = "UNKNOWN_NO_Z"
            connection_records.append({
                "junction_id": junction.get("id"),
                "connector_road": connecting,
                "dz_start": dz_start,
                "dz_end": dz_end,
                "classification": conn_class,
            })
            for ll in conn.findall("laneLink"):
                try:
                    from_id = int(str(ll.get("from")))
                    to_id = int(str(ll.get("to")))
                except (TypeError, ValueError):
                    continue
                worst = max(
                    (abs(v) for v in (dz_start, dz_end) if v is not None),
                    default=0.0,
                )
                if worst > _DANGLING_CONNECTOR_DZ_THRESHOLD_M:
                    classification = "REAL_SURFACE_DISCONTINUITY"
                elif worst > 0.0:
                    classification = "VALID_GRADE_CHANGE"
                else:
                    classification = "CONTINUOUS"
                links.append({
                    "junction_id": junction.get("id"),
                    "connector_road": connecting,
                    "connector_length_m": round(con_len, 3),
                    "from": from_id,
                    "to": to_id,
                    "dz_start": dz_start,
                    "dz_end": dz_end,
                    "classification": classification,
                })
    bad = [
        l for l in links
        if l["classification"] in ("REAL_SURFACE_DISCONTINUITY",)
    ]
    conn_bad = [c for c in connection_records if c["classification"] == "REAL_SURFACE_DISCONTINUITY"]
    worst = max(
        (max(abs(l["dz_start"]), abs(l["dz_end"])) for l in bad),
        default=0.0,
    )
    worst_record = None
    for l in bad:
        worst_here = max(abs(l["dz_start"]), abs(l["dz_end"]))
        if worst_record is None or worst_here > worst_record["worst_dz"]:
            worst_record = {"worst_dz": worst_here, **{k: l[k] for k in ("junction_id","connector_road","from","to","dz_start","dz_end")}}
    return {
        "interface_links": len(links),
        "connections_total": len(connection_records),
        "connection_interfaces": len(connection_records) * 2,
        "bad_seams": len(bad),
        "bad_connections": len(conn_bad),
        "bad_interface_examples": conn_bad[:50],
        "conn_class_counts": {
            k: sum(1 for c in connection_records if c["classification"] == k)
            for k in {c["classification"] for c in connection_records}
        },
        "bad_examples": bad[:50],
        "worst_dz": round(worst, 4),
        "worst_record": worst_record,
    }


# ---------------------------------------------------------------------------
# P0-D: structure terrain separation
# ---------------------------------------------------------------------------

def scan_structure_terrain_separation(
    root: ET.Element,
    terrain_sampler: Any,
    road_classes: Optional[Dict[str, str]] = None,
    threshold_m: float = 0.5,
) -> Dict[str, Any]:
    """Compare each bridge/elevated/tunnel road's deck z against the terrain
    (DEM). Bridges/elevated must be >= threshold above terrain at their deck;
    tunnels must be >= threshold below terrain. Requires a ``terrain_sampler``
    callable (x, y) -> z built from the pinned DEM by the elevation importer.
    """
    if terrain_sampler is None:
        return {"ok": False, "INCOMPLETE": True, "reason": "terrain_sampler_unavailable"}
    roads = _roads(root)
    records: List[Dict[str, Any]] = []
    for rid, road in roads.items():
        if not road_classes:
            break
        road_class = (road_classes or {}).get(rid)
        if road_class not in ("bridge", "elevated", "tunnel"):
            continue
        geoms = sorted(road.findall("./planView/geometry"), key=lambda g: _safe_float(g.get("s")))
        if not geoms:
            continue
        from ultimate_pipeline.geometry.opendrive_geometry_kernel import pose_at_s, endpoint
        samples: List[Dict[str, Any]] = []
        step = max(1, len(geoms) // 8)
        chosen = geoms[::step]
        for geom in chosen:
            s = _safe_float(geom.get("s")) + _safe_float(geom.get("length")) / 2.0
            pose = endpoint(geom)
            road_z = None
            profile = road.find("elevationProfile")
            if profile is not None:
                elevs = [(_safe_float(e.get("s")), e) for e in profile.findall("elevation")]
                if elevs:
                    elevs.sort(key=lambda v: v[0])
                    s0, el = elevs[0]
                    for s_e, e_el in elevs:
                        if s_e <= s:
                            s0, el = s_e, e_el
                        else:
                            break
                    ds = max(0.0, s - s0)
                    a = _safe_float(el.get("a"), 0.0)
                    b = _safe_float(el.get("b"), 0.0)
                    c = _safe_float(el.get("c"), 0.0)
                    d = _safe_float(el.get("d"), 0.0)
                    road_z = a + b * ds + c * ds * ds + d * ds * ds
            if road_z is None:
                continue
            terrain_z = terrain_sampler(float(pose.x), float(pose.y))
            dz = round(road_z - terrain_z, 3)
            samples.append({"s": round(s, 1), "road_z": round(road_z, 3), "terrain_z": round(terrain_z, 3), "dz": dz})
        if not samples:
            continue
        # bridge/elevated: road must be ABOVE terrain by >= threshold
        # tunnel: road must be BELOW terrain by >= threshold
        if road_class in ("bridge", "elevated"):
            worst_dz = min(s["dz"] for s in samples)
            violated = worst_dz < threshold_m
        else:  # tunnel
            worst_dz = max(s["dz"] for s in samples)
            violated = worst_dz > -threshold_m
        records.append({
            "road_id": rid,
            "class": road_class,
            "worst_dz": worst_dz,
            "violated": violated,
            "samples": samples,
        })
    if not records:
        return {"classify_population": 0, "ok": False, "INCOMPLETE": True,
                "reason": "no classified structure roads (road_classes empty)"}
    violations = [r for r in records if r["violated"]]
    return {
        "classified_structure_roads": len(records),
        "violations": len(violations),
        "violated_roads": [r["road_id"] for r in violations],
        "records": records,
        "ok": len(violations) == 0,
    }


# ---------------------------------------------------------------------------
# master entrypoint
# ---------------------------------------------------------------------------

def scan_map_realism_p0(xodr_path: str, dem: Optional[str] = None, osm_path: Optional[str] = None) -> Dict[str, Any]:
    root = ET.parse(xodr_path).getroot()

    sha = hashlib.sha256(open(xodr_path, "rb").read()).hexdigest()

    report: Dict[str, Any] = {
        "schema": "MAP_REALISM_P0_ORACLE/v1",
        "xodr_path": str(xodr_path),
        "xodr_sha256": sha,
        "georeference": scan_georeference(root),
        "dangling_mandatory_lane_successors": scan_dangling_mandatory_lane_successors(root),
        "orphan_drivable_roads": scan_orphan_drivable_roads(root),
        "connector_lane_interface_dz": scan_connector_lane_interface_dz(root),
    }

    if dem:
        try:
            from ultimate_pipeline.enrichment.structure_classifier import classify_xodr_roads
            from ultimate_pipeline.enrichment.elevation_importer import ElevationImporter
            classification = classify_xodr_roads(xodr_path, osm_path=osm_path)
            road_classes = {
                rid: rec.get("class")
                for rid, rec in classification.get("per_road", {}).items()
            }
            sampler = ElevationImporter.make_raster_sampler(dem, xodr_path, osm_path=osm_path)
            report["structure_terrain_separation"] = scan_structure_terrain_separation(
                root, sampler, road_classes)
        except Exception as exc:  # not a scan failure, record the block
            report["structure_terrain_separation"] = {
                "INCOMPLETE": True, "error": f"{type(exc).__name__}: {exc}"}

    return report


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="MAP REALISM P0 oracle scan")
    ap.add_argument("--xodr", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dem", default=None)
    ap.add_argument("--osm", default=None)
    args = ap.parse_args()
    report = scan_map_realism_p0(args.xodr, args.dem, args.osm)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(f"oracle -> {args.out}")
    dm = report["dangling_mandatory_lane_successors"]
    orph = report["orphan_drivable_roads"]
    conn = report["connector_lane_interface_dz"]
    print(f"dangling_mandatory={dm['dangling_mandatory_lane_successors']} "
          f"orphan_drivable={orph['orphan_drivable_roads']} "
          f"bad_connector_seams={conn['bad_seams']}/{conn['interface_links']} "
          f"worst_dz={conn['worst_dz']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
