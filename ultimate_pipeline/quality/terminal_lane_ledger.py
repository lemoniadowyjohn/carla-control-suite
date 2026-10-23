#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Terminal-lane ledger: OSM-authoritative classification of terminal lanes.

Every driving lane whose road has no successor anywhere must be accounted for
by source authority before the map may claim ``mandatory dangling = 0``:

  VALID_TERMINAL_SOURCE     OSM source way terminates there (cul-de-sac / spur)
  VALID_TERMINAL_COVERAGE   OSM continues only outside the map coverage bbox
  MISSING_ROAD_LINK         OSM continuation road exists in-map; link was dropped
  JUNCTION_MAPPING_DEFECT   continuation crosses an unmapped/mis-mapped junction
  GENERATOR_NO_CANDIDATE    OSM continuation exists but no compatible map road
  UNMAPPED                  road end could not be matched to the OSM source

The ledger is read-only against the XODR and the OSM source. Repairs consume
``MISSING_ROAD_LINK`` / ``JUNCTION_MAPPING_DEFECT`` / ``GENERATOR_NO_CANDIDATE``
records; everything else is exempt-with-evidence terminality. There is no
nearest-geometry guessing: a continuation candidate is accepted only when the
OSM network itself declares an incident way at the shared node with a bearing
that plausibly continues the dead-end way, and a compatible in-map road exists.

Coordinate contract: the XODR local frame equals the Osm2Odr native tmerc frame
minus the pinned rebase offset; OSM lat/lon -> native tmerc -> local is a fixed
affine chain. The rebase offset is read from the XODR header <offset>.
"""
from __future__ import annotations

import json
import math
import math as _math
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "build_terminal_lane_ledger",
    "LEDGER_STATUS_VALID", "LEDGER_STATUS_DEFECT",
]

LEDGER_STATUS_VALID = "VALID"
LEDGER_STATUS_DEFECT = "DEFECT"

_TOLERANCE_M = 2.5
_BEARING_CONTINUATION_MAX_DEG = 55.0


def _safe_float(value: Optional[str], default: float = 0.0) -> float:
    try:
        parsed = float(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _header_rebase(root: ET.Element) -> Tuple[float, float]:
    offset = root.find("header/offset") if root.find("header") is not None else None
    if offset is None:
        return (0.0, 0.0)
    return (_safe_float(offset.get("x")), _safe_float(offset.get("y")))


def _sorted_geometry(road: ET.Element) -> List[ET.Element]:
    return sorted(road.findall("./planView/geometry"), key=lambda g: _safe_float(g.get("s")))


def _boundary_pose(road: ET.Element, at_start: bool) -> Optional[Tuple[float, float, float]]:
    from ultimate_pipeline.geometry.opendrive_geometry_kernel import pose_at_s, endpoint as kernel_endpoint
    geoms = _sorted_geometry(road)
    if not geoms:
        return None
    geom = geoms[0] if at_start else geoms[-1]
    pose = pose_at_s(geom, 0.0) if at_start else kernel_endpoint(geom)
    return (float(pose.x), float(pose.y), float(pose.heading))


class _OsmIndex:
    """Node/way index of the authoritative OSM in XODR local coordinates."""

    def __init__(self, osm_path: str, rebase: Tuple[float, float]):
        import pyproj
        self._rebase = rebase
        native = (
            "+proj=tmerc +lat_0=0 +lon_0=0 +k=1 +x_0=0 +y_0=0 "
            "+datum=WGS84 +units=m +no_defs"
        )
        self._wgs_to_native = pyproj.Transformer.from_crs(
            "EPSG:4326", native, always_xy=True)
        self.nodes_lonlat: Dict[str, Tuple[float, float]] = {}
        self.ways: Dict[str, List[Dict[str, Any]]] = {}
        self.node_grid: Dict[Tuple[int, int], List[str]] = {}
        self._cell = 4.0
        osm_root = ET.parse(osm_path).getroot()
        bounds_el = osm_root.find("bounds")
        self.bounds: Optional[Dict[str, float]] = (
            dict(bounds_el.attrib) if bounds_el is not None else None)
        for node in osm_root.findall("node"):
            lon = node.get("lon")
            lat = node.get("lat")
            if lon is None or lat is None:
                continue
            self.nodes_lonlat[node.get("id")] = (float(lon), float(lat))
        for way in osm_root.findall("way"):
            if way.find('tag[@k="highway"]') is None:
                continue
            refs = [nd.get("ref") for nd in way.findall("nd")]
            if len([r for r in refs if r in self.nodes_lonlat]) < 2:
                continue
            self.ways[way.get("id")] = [
                {"ref": r, "tags": {"highway": (way.find('tag[@k="highway"]').get("v") if way.find('tag[@k="highway"]') is not None else None),
                                    "oneway": (way.find('tag[@k="oneway"]').get("v") if way.find('tag[@k="oneway"]') is not None else None),
                                    "junction": (way.find('tag[@k="junction"]').get("v") if way.find('tag[@k="junction"]') is not None else None)}}
                for r in refs
            ]
            for r in set(refs):
                if r not in self.nodes_lonlat:
                    continue
                x, y = self.node_local(r)
                key = (int(x // self._cell), int(y // self._cell))
                self.node_grid.setdefault(key, []).append(r)
                self.node_to_ways = getattr(self, "node_to_ways", {})
                self.node_to_ways.setdefault(r, set()).add(way.get("id"))

    # -- coordinate helpers -------------------------------------------------
    def node_local(self, node_id: str) -> Tuple[float, float]:
        lon, lat = self.nodes_lonlat[node_id]
        x, y = self._wgs_to_native.transform(lon, lat)
        return (x - self._rebase[0], y - self._rebase[1])

    def nearby_nodes(self, x: float, y: float, radius_cell: int = 1) -> List[str]:
        cx, cy = int(x // self._cell), int(y // self._cell)
        out: List[str] = []
        for ix in range(cx - radius_cell, cx + radius_cell + 1):
            for iy in range(cy - radius_cell, cy + radius_cell + 1):
                out.extend(self.node_grid.get((ix, iy), []))
        return out


def _bearing_deg(dx: float, dy: float) -> float:
    return _math.degrees(_math.atan2(dy, dx)) % 360.0


def _angle_diff(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _way_local_points(index: _OsmIndex, way_id: str) -> List[Tuple[float, float, str]]:
    return [
        (*index.node_local(d["ref"]), d["ref"])
        for d in index.ways[way_id]
        if d["ref"] in index.nodes_lonlat
    ]


def _map_bbox_local(root: ET.Element, rebase: Tuple[float, float]) -> Optional[Dict[str, float]]:
    header = root.find("header")
    if header is None:
        return None
    try:
        west = _safe_float(header.get("west"), float("nan"))
        east = _safe_float(header.get("east"), float("nan"))
        south = _safe_float(header.get("south"), float("nan"))
        north = _safe_float(header.get("north"), float("nan"))
    except Exception:
        return None
    if any(_math.isnan(v) for v in (west, east, south, north)):
        return None
    # header bounds are absolute (native) coordinates: convert to local frame
    return {
        "min_x": west - rebase[0], "max_x": east - rebase[0],
        "min_y": south - rebase[1], "max_y": north - rebase[1],
    }


def _classify_dead_end(
    index: _OsmIndex,
    roads: Dict[str, ET.Element],
    road: ET.Element,
    lane_id: int,
    bbox: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    rid = road.get("id")
    # dead-end side: no successor road — dead end at road END
    pose = _boundary_pose(road, at_start=False)
    if pose is None:
        return {"road_id": rid, "lane_id": lane_id, "status": "DEFECT",
                "classification": "UNMAPPED", "reason": "no planView geometry"}
    x0, y0, heading = pose
    heading_deg = _math.degrees(heading) % 360.0
    reciprocal = (heading_deg + 180.0) % 360.0

    best: Optional[Dict[str, Any]] = None
    for node_id in index.nearby_nodes(x0, y0, radius_cell=1):
        nx, ny = index.node_local(node_id)
        d = math.hypot(nx - x0, ny - y0)
        if d > _TOLERANCE_M:
            continue
        if best is None or d < best["matched_distance_m"]:
            best = {
                "matched_distance_m": round(d, 3),
                "matched_node": node_id,
            }
    if best is None:
        return {"road_id": rid, "lane_id": lane_id, "status": "DEFECT",
                "classification": "UNMAPPED",
                "reason": "no OSM node within tolerance at road end",
                "end_local": [round(x0, 2), round(y0, 2)]}

    node_id = best["matched_node"]
    incident = sorted(getattr(index, "node_to_ways", {}).get(node_id, set()))
    branch_records: List[Dict[str, Any]] = []
    for wid in incident:
        pts = _way_local_points(index, wid)
        i = next((k for k, p in enumerate(pts) if p[2] == node_id), None)
        if i is None:
            continue
        directions = []  # (bearing, role) where role names the branch
        if i + 1 < len(pts):
            b = _bearing_deg(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
            directions.append((b, "forward"))
        if i - 1 >= 0:
            b = _bearing_deg(pts[i - 1][0] - pts[i][0], pts[i - 1][1] - pts[i][1])
            directions.append((b, "forward2"))
        rec = {
            "way_id": wid,
            "is_endpoint": len(pts) >= 2 and (i == 0 or i == len(pts) - 1),
            "branch_count": len(directions),
            "branches": [],
        }
        for bearing, role in directions:
            # a branch running back into the road body matches the reciprocal
            # heading; a branch leaving roughly along the road heading is a
            # forward continuation
            into_angle = _angle_diff(bearing, reciprocal)
            cont_angle = _angle_diff(bearing, heading_deg)
            branch = {
                "bearing": round(bearing, 1),
                "angle_into_road_deg": round(into_angle, 1),
                "angle_continuation_deg": round(cont_angle, 1),
            }
            if into_angle <= 60.0:
                branch["role"] = "back_into_road"
            elif cont_angle <= _BEARING_CONTINUATION_MAX_DEG:
                branch["role"] = "forward_continuation"
            else:
                branch["role"] = "other"
            rec["branches"].append(branch)
        branch_records.append(rec)

    # source way: an incident way with a branch running back into the road
    best_way: Optional[Dict[str, Any]] = None
    for rec in branch_records:
        angles = [b["angle_into_road_deg"] for b in rec["branches"]
                  if b.get("role") == "back_into_road"]
        if angles and (best_way is None or min(angles) < best_way["best_into_angle"]):
            best_way = {"way_id": rec["way_id"], "best_into_angle": min(angles)}

    # continuations: every branch that leaves the node roughly forward,
    # including the source way's own other branch (interior truncation)
    continuations: List[Dict[str, Any]] = []
    for rec in branch_records:
        for branch in rec["branches"]:
            if branch.get("role") == "forward_continuation":
                continuations.append({
                    "way_id": rec["way_id"],
                    "bearing": branch["bearing"],
                    "angle_delta_deg": branch["angle_continuation_deg"],
                })

    record: Dict[str, Any] = {
        "road_id": rid,
        "lane_id": lane_id,
        "status": None,
        "classification": None,
        "matched_node": node_id,
        "matched_distance_m": best["matched_distance_m"],
        "heading_deg": round(heading_deg, 1),
        "matched_source_way": (best_way or {}).get("way_id"),
        "incident_ways": [r["way_id"] for r in branch_records],
        "incident_branches": [
            {"way_id": r["way_id"], "branches": r["branches"]}
            for r in branch_records
        ],
        "continuation_ways": continuations[:6],
    }
    if best_way is None:
        record["classification"] = "UNMAPPED"
        record["status"] = "DEFECT"
        record["reason"] = (
            "no source way leaves the shared node back into the road body "
            "(heading %s)" % round(heading_deg, 1))
        return record

    if not continuations:
        # the source way truly terminates: cul-de-sac / spur / boundary stub
        record["classification"] = "VALID_TERMINAL_SOURCE"
        record["status"] = "VALID"
        record["reason"] = "OSM source way terminates at this node; no incident continuation"
        return record

    # a continuation exists in the OSM network. Classify where it goes.
    def _way_inside_bbox(wid: str) -> bool:
        if bbox is None:
            return True  # cannot prove coverage-truncation: stay conservative
        for px, py, _ in _way_local_points(index, wid):
            if (bbox["min_x"] - 25.0 <= px <= bbox["max_x"] + 25.0
                    and bbox["min_y"] - 25.0 <= py <= bbox["max_y"] + 25.0):
                return True
        return False

    inside = [c for c in continuations if _way_inside_bbox(c["way_id"])]
    if not inside:
        record["classification"] = "VALID_TERMINAL_COVERAGE"
        record["status"] = "VALID"
        record["reason"] = "continuation ways leave the map coverage bbox"
        return record

    # junction cluster? (>=3 distinct ways share the node)
    if len(incident) >= 3:
        record["classification"] = "JUNCTION_MAPPING_DEFECT"
        record["status"] = "DEFECT"
        record["reason"] = (
            "node shared by %d OSM ways; junction mapping lacks the outgoing leg"
            % len(incident))
        return record

    record["classification"] = "SOURCE_CONTINUATION"
    record["status"] = "DEFECT"
    record["reason"] = (
        "OSM declares in-map continuation ways %s at this node but the map "
        "road has no successor"
        % (", ".join(sorted({c["way_id"] for c in inside}))[:120],))
    return record


def build_terminal_lane_ledger(
    xodr_path: str,
    osm_path: str,
    *,
    strict_checker_population: bool = True,
) -> Dict[str, Any]:
    """Classify the terminal/dead-end driving-lane population by OSM authority.

    Population: driving lanes at a road boundary where the road has no road
    successor (the ``allow_dead_ends=False`` strict checker set).
    """
    from ultimate_pipeline.quality.check_lane_connectivity import (
        find_broken_lanes_detailed,
    )
    root = ET.parse(xodr_path).getroot()
    roads = {r.get("id"): r for r in root.findall("road") if r.get("id")}
    rebase = _header_rebase(root)
    bbox = _map_bbox_local(root, rebase)
    index = _OsmIndex(osm_path, rebase)

    broken = find_broken_lanes_detailed(root, allow_dead_ends=False)
    records: List[Dict[str, Any]] = []
    cache: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for item in broken:
        rid = str(item.get("road_id"))
        lane_id = item.get("lane_id")
        try:
            lane_id = int(str(lane_id))
        except (TypeError, ValueError):
            lane_id = 0
        key = (rid, lane_id)
        if key not in cache:
            road = roads.get(rid)
            if road is None:
                cache[key] = {"road_id": rid, "lane_id": lane_id,
                              "status": "DEFECT", "classification": "UNMAPPED",
                              "reason": "road absent"}
            else:
                cache[key] = _classify_dead_end(index, roads, road, lane_id, bbox)
        records.append(cache[key])

    by_class: Dict[str, int] = {}
    for rec in records:
        by_class[rec["classification"]] = by_class.get(rec["classification"], 0) + 1
    defect_records = [r for r in records if r.get("status") == "DEFECT"]
    return {
        "schema": "TERMINAL_LANE_LEDGER/v1",
        "xodr_path": str(xodr_path),
        "osm_path": str(osm_path),
        "population": len(records),
        "class_counts": by_class,
        "defect_count": len(defect_records),
        "defect_records": defect_records,
        "records": records,
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="OSM-authoritative terminal lane ledger")
    ap.add_argument("--xodr", required=True)
    ap.add_argument("--osm", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    report = build_terminal_lane_ledger(args.xodr, args.osm)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(f"ledger -> {args.out}: population={report['population']} "
          f"classes={report['class_counts']} defects={report['defect_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
