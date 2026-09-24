"""Generate deterministic topology-derived runtime validation routes (O9)."""
from __future__ import annotations

import argparse
import json
import math
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map
from ultimate_pipeline.geometry.opendrive_geometry_kernel import endpoint, pose_at_s


def _f(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _poses(road: ET.Element) -> tuple[dict[str, Any], dict[str, Any]]:
    geoms = sorted(road.findall("./planView/geometry"), key=lambda g: _f(g.get("s")))
    if not geoms:
        return {}, {}
    try:
        start = pose_at_s(geoms[0], 0.0)
        end = endpoint(geoms[-1])
    except Exception:
        return {}, {}
    return {"x": start.x, "y": start.y, "z": start.heading}, {"x": end.x, "y": end.y, "z": end.heading}


def _lane_count(road: ET.Element) -> int:
    return len(road.findall(".//lane[@type='driving']"))


def generate_routes(map_path: Path, map_sha: str) -> dict[str, Any]:
    root = ET.parse(map_path).getroot()
    roads = {str(r.get("id")): r for r in root.findall("road") if r.get("id")}
    junctions = {str(j.get("id")): j for j in root.findall("junction") if j.get("id")}
    routes: list[dict[str, Any]] = []
    missing: list[str] = []

    def add(route_id: str, category: str, road_ids: list[str], diagnostic: bool = False) -> None:
        if not all(road_id in roads for road_id in road_ids):
            missing.append(route_id)
            return
        points = []
        for road_id in road_ids:
            road = roads[road_id]
            start, end = _poses(road)
            points.append({"road_id": road_id, "start": start, "end": end, "length_m": _f(road.get("length")), "driving_lanes": _lane_count(road)})
        routes.append({"route_id": route_id, "category": category, "source_map_sha256": map_sha, "diagnostic_only": diagnostic, "points": points, "deterministic": True})

    ordinary = sorted((int(rid) for rid, road in roads.items() if road.get("junction", "-1") == "-1" and _f(road.get("length")) > 0), key=lambda rid: (len(roads[str(rid)].findall(".//lane[@type='driving']")), rid))
    if ordinary:
        add("straight_urban_0001", "straight_urban_segment", [str(ordinary[0])])
    simple = sorted((str(jid) for jid, junction in junctions.items() if len(junction.findall("connection")) <= 4), key=lambda x: (len(junctions[x].findall("connection")), int(x) if x.isdigit() else x))
    if simple:
        jid = simple[0]
        conn = junctions[jid].find("connection")
        if conn is not None:
            add("simple_intersection_" + jid, "simple_intersection", [str(conn.get("incomingRoad"))], diagnostic=True)
    multi = sorted((str(jid) for jid, junction in junctions.items() if any(_lane_count(roads.get(str(c.get("incomingRoad")), ET.Element("road"))) >= 2 for c in junction.findall("connection"))), key=lambda x: int(x) if x.isdigit() else x)
    if multi:
        jid = multi[0]
        conn = junctions[jid].find("connection")
        if conn is not None:
            add("multilane_junction_" + jid, "multi_lane_junction", [str(conn.get("incomingRoad")), str(conn.get("connectingRoad"))], diagnostic=True)
    roundabouts = sorted(str(jid) for jid, junction in junctions.items() if (junction.get("type") or "").lower() == "roundabout")
    if roundabouts:
        add("roundabout_" + roundabouts[0], "roundabout", [], diagnostic=True)
    else:
        missing.append("roundabout")
    bridges = sorted(str(rid) for rid, road in roads.items() if (road.get("type") or "").lower() in {"bridge", "motorway"} or road.find("./bridge") is not None)
    if bridges:
        add("bridge_or_grade_" + bridges[0], "bridge_or_grade_separated", [bridges[0]], diagnostic=True)
    else:
        missing.append("bridge_or_grade_separated")
    merge_roads = sorted(str(rid) for rid, road in roads.items() if len(road.findall("./link/successor")) > 1)
    if merge_roads:
        add("lane_merge_" + merge_roads[0], "lane_merge", [merge_roads[0]], diagnostic=True)
    else:
        missing.append("lane_merge")
    split_roads = sorted(str(rid) for rid, road in roads.items() if len(road.findall("./link/predecessor")) > 1)
    if split_roads:
        add("lane_split_" + split_roads[0], "lane_split", [split_roads[0]], diagnostic=True)
    else:
        missing.append("lane_split")
    # Fixed GAP-026 diagnostic fixtures, reference IDs from validated current pin.
    add("gap026_0_25_0_5_j12_c3", "gap026_severe_candidate", ["47383", "54435"], diagnostic=True)
    add("gap026_3_5_j1_c3", "gap026_severe_candidate", ["42486", "52027"], diagnostic=True)
    add("gap026_10_j3470_c0", "gap026_severe_candidate", ["49561", "69981"], diagnostic=True)
    return {"schema": "runtime_validation_routes/v1", "status": "INCOMPLETE" if missing else "PASS", "generated_at_utc": datetime.now(timezone.utc).isoformat(), "source_map_path": str(map_path), "source_map_sha256": map_sha, "route_seed": None, "routes": routes, "missing_categories": sorted(set(missing)), "claim_boundary": "Offline deterministic route definitions only; no CARLA runtime validation or production-ready claim."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("runtime_validation_routes.json"))
    args = parser.parse_args()
    pin = verify_pinned_map("auto_map_of_record")
    report = generate_routes(Path(pin["resolved_path"]), pin["sha256"])
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "routes": len(report["routes"]), "missing_categories": report["missing_categories"]}, indent=2))
    return 0 if report["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
