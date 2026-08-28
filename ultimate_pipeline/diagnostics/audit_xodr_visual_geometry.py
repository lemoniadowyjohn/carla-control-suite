#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ultimate_pipeline.quality.check_geometric_continuity import (
    _angle_diff,
    _parse_geometries,
    _pose_for_geometry,
)
from ultimate_pipeline.quality.check_junction_integrity import JunctionIntegrityGate


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _is_finite(*values: float) -> bool:
    return all(math.isfinite(v) for v in values)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True),
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _roads_by_id(root: ET.Element) -> Dict[str, ET.Element]:
    return {
        str(road.get("id")): road
        for road in root.findall("./road")
        if road.get("id") is not None
    }


def _plan_geometries(road: ET.Element):
    geoms, warnings = _parse_geometries(road)
    return sorted(geoms, key=lambda geom: float(geom.s0)), warnings


def _road_endpoint_pose(road: ET.Element, contact_point: str):
    geoms, _warnings = _plan_geometries(road)
    if not geoms:
        return None
    if str(contact_point or "start").strip().lower() == "end":
        geom = geoms[-1]
        return _pose_for_geometry(geom, float(geom.length))
    geom = geoms[0]
    return _pose_for_geometry(geom, 0.0)


def _road_length(road: ET.Element) -> float:
    return _safe_float(road.get("length"), 0.0)


def _elevation_segments(
    road: ET.Element,
) -> List[Tuple[float, float, float, float, float]]:
    out: List[Tuple[float, float, float, float, float]] = []
    for elev in road.findall("./elevationProfile/elevation"):
        out.append(
            (
                _safe_float(elev.get("s"), 0.0),
                _safe_float(elev.get("a"), 0.0),
                _safe_float(elev.get("b"), 0.0),
                _safe_float(elev.get("c"), 0.0),
                _safe_float(elev.get("d"), 0.0),
            )
        )
    out.sort(key=lambda item: item[0])
    return out


def _eval_elevation(road: ET.Element, s_value: float) -> Optional[float]:
    segments = _elevation_segments(road)
    if not segments:
        return None
    active = segments[0]
    for segment in segments:
        if segment[0] <= s_value + 1e-9:
            active = segment
        else:
            break
    s0, a, b, c, d = active
    ds = max(0.0, float(s_value) - s0)
    return a + b * ds + c * ds * ds + d * ds * ds * ds


def _road_z_range(road: ET.Element) -> Tuple[Optional[float], Optional[float]]:
    length = max(0.0, _road_length(road))
    return _eval_elevation(road, 0.0), _eval_elevation(road, length)


def _header_info(root: ET.Element) -> Dict[str, Any]:
    header = root.find("./header")
    geo = header.find("geoReference") if header is not None else None
    offset = header.find("offset") if header is not None else None
    return {
        "geoReference_present": bool(
            geo is not None and str(geo.text or "").strip()
        ),
        "geoReference_text": str(geo.text or "").strip() if geo is not None else "",
        "offset_x": _safe_float(offset.get("x"), 0.0) if offset is not None else 0.0,
        "offset_y": _safe_float(offset.get("y"), 0.0) if offset is not None else 0.0,
        "offset_z": _safe_float(offset.get("z"), 0.0) if offset is not None else 0.0,
        "offset_hdg": _safe_float(offset.get("hdg"), 0.0) if offset is not None else 0.0,
    }


def _signal_count(root: ET.Element) -> int:
    return len(root.findall(".//signal"))


def _object_count(root: ET.Element) -> int:
    return len(root.findall(".//object"))


def _max_planview_abs(root: ET.Element) -> Dict[str, float]:
    max_abs_x = 0.0
    max_abs_y = 0.0
    for road in root.findall("./road"):
        geoms, _warnings = _plan_geometries(road)
        for geom in geoms:
            start = _pose_for_geometry(geom, 0.0)
            end = _pose_for_geometry(geom, float(geom.length))
            max_abs_x = max(
                max_abs_x,
                abs(float(start.x)),
                abs(float(end.x)),
            )
            max_abs_y = max(
                max_abs_y,
                abs(float(start.y)),
                abs(float(end.y)),
            )
    return {"max_abs_x": max_abs_x, "max_abs_y": max_abs_y}


def _build_link_rows(root: ET.Element, roads: Dict[str, ET.Element]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for road in root.findall("./road"):
        road_id = str(road.get("id") or "")
        link_el = road.find("./link")
        if link_el is None:
            continue
        for rel_name in ("predecessor", "successor"):
            rel = link_el.find(f"./{rel_name}")
            if rel is None:
                continue
            element_type = str(rel.get("elementType") or "")
            element_id = str(rel.get("elementId") or "")
            contact_point = str(rel.get("contactPoint") or "")
            source_contact = "start" if rel_name == "predecessor" else "end"
            row: Dict[str, Any] = {
                "road_id": road_id,
                "relation": rel_name,
                "elementType": element_type,
                "elementId": element_id,
                "source_contact": source_contact,
                "target_contact": contact_point,
                "xy_gap_m": "",
                "hdg_gap_deg": "",
                "z_gap_m": "",
                "issue": "",
            }
            if element_type != "road":
                row["issue"] = "non_road_link"
                rows.append(row)
                continue
            if contact_point not in {"start", "end"}:
                row["issue"] = "invalid_contactPoint"
                rows.append(row)
                continue
            other = roads.get(element_id)
            if other is None:
                row["issue"] = "missing_linked_road"
                rows.append(row)
                continue
            source_pose = _road_endpoint_pose(road, source_contact)
            target_pose = _road_endpoint_pose(other, contact_point)
            if source_pose is None or target_pose is None:
                row["issue"] = "missing_pose"
                rows.append(row)
                continue
            dx = float(source_pose.x) - float(target_pose.x)
            dy = float(source_pose.y) - float(target_pose.y)
            row["xy_gap_m"] = round(math.hypot(dx, dy), 6)
            row["hdg_gap_deg"] = round(
                abs(
                    math.degrees(
                        _angle_diff(float(source_pose.hdg), float(target_pose.hdg))
                    )
                ),
                6,
            )
            source_s = 0.0 if source_contact == "start" else _road_length(road)
            target_s = 0.0 if contact_point == "start" else _road_length(other)
            source_z = _eval_elevation(road, source_s)
            target_z = _eval_elevation(other, target_s)
            if source_z is not None and target_z is not None:
                row["z_gap_m"] = round(abs(float(source_z) - float(target_z)), 6)
            rows.append(row)
    return rows


def _build_planview_rows(root: ET.Element) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for road in root.findall("./road"):
        road_id = str(road.get("id") or "")
        road_length = _road_length(road)
        if road_length <= 0.0 or not math.isfinite(road_length):
            rows.append(
                {
                    "road_id": road_id,
                    "issue": "invalid_road_length",
                    "detail": road_length,
                }
            )
        geoms, warnings = _plan_geometries(road)
        if not geoms:
            rows.append(
                {
                    "road_id": road_id,
                    "issue": "missing_planview_geometry",
                    "detail": "; ".join(warnings),
                }
            )
            continue
        prev = None
        for index, geom in enumerate(geoms):
            values = [
                float(geom.s0),
                float(geom.x0),
                float(geom.y0),
                float(geom.hdg0),
                float(geom.length),
            ]
            if not _is_finite(*values):
                rows.append(
                    {
                        "road_id": road_id,
                        "issue": "nonfinite_geometry_value",
                        "detail": index,
                    }
                )
            if float(geom.length) <= 1e-9:
                rows.append(
                    {
                        "road_id": road_id,
                        "issue": "zero_length_geometry",
                        "detail": index,
                    }
                )
            if geom.kind == "arc" and abs(float(geom.curvature)) > 1.0:
                rows.append(
                    {
                        "road_id": road_id,
                        "issue": "extreme_arc_curvature",
                        "detail": round(float(geom.curvature), 6),
                    }
                )
            if geom.kind == "spiral" and max(
                abs(float(geom.curv_start)),
                abs(float(geom.curv_end)),
            ) > 1.0:
                rows.append(
                    {
                        "road_id": road_id,
                        "issue": "extreme_spiral_curvature",
                        "detail": f"{geom.curv_start}/{geom.curv_end}",
                    }
                )
            if prev is not None:
                if float(geom.s0) + 1e-9 < float(prev.s0):
                    rows.append(
                        {
                            "road_id": road_id,
                            "issue": "geometry_s_nonmonotonic",
                            "detail": f"{prev.s0}->{geom.s0}",
                        }
                    )
                expected_s = float(prev.s0) + float(prev.length)
                if abs(float(geom.s0) - expected_s) > 1e-4:
                    rows.append(
                        {
                            "road_id": road_id,
                            "issue": "geometry_s_gap",
                            "detail": round(float(geom.s0) - expected_s, 6),
                        }
                    )
                prev_end = _pose_for_geometry(prev, float(prev.length))
                curr_start = _pose_for_geometry(geom, 0.0)
                xy_gap = math.hypot(
                    float(prev_end.x) - float(curr_start.x),
                    float(prev_end.y) - float(curr_start.y),
                )
                hdg_gap = abs(
                    math.degrees(
                        _angle_diff(float(prev_end.hdg), float(curr_start.hdg))
                    )
                )
                if xy_gap > 0.25 or hdg_gap > 5.0:
                    rows.append(
                        {
                            "road_id": road_id,
                            "issue": "internal_geometry_discontinuity",
                            "detail": json.dumps(
                                {
                                    "xy_gap_m": round(xy_gap, 6),
                                    "hdg_gap_deg": round(hdg_gap, 6),
                                    "segment_index": index,
                                }
                            ),
                        }
                    )
            prev = geom
    return rows


def _build_junction_rows(root: ET.Element, roads: Dict[str, ET.Element]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    gate_report = JunctionIntegrityGate.validate(root)
    for issue in gate_report.get("issues", []):
        rows.append(
            {
                "junction_id": issue.get("junction_id", issue.get("junction", "")),
                "connection_id": issue.get("connection_id", ""),
                "issue": issue.get("type", "unknown"),
                "detail": json.dumps(issue, sort_keys=True),
            }
        )
    for junction in root.findall("./junction"):
        junction_id = str(junction.get("id") or "")
        connections = junction.findall("./connection")
        if len(connections) > 20:
            rows.append(
                {
                    "junction_id": junction_id,
                    "connection_id": "",
                    "issue": "high_connection_count",
                    "detail": len(connections),
                }
            )
        for connection in connections:
            connection_id = str(connection.get("id") or "")
            lane_links = connection.findall("./laneLink")
            if not lane_links:
                rows.append(
                    {
                        "junction_id": junction_id,
                        "connection_id": connection_id,
                        "issue": "connector_without_laneLinks",
                        "detail": "",
                    }
                )
            incoming_id = str(connection.get("incomingRoad") or "")
            connecting_id = str(connection.get("connectingRoad") or "")
            incoming = roads.get(incoming_id)
            connecting = roads.get(connecting_id)
            if incoming is None or connecting is None:
                continue
            conn_start = _road_endpoint_pose(connecting, "start")
            incoming_start = _road_endpoint_pose(incoming, "start")
            incoming_end = _road_endpoint_pose(incoming, "end")
            if (
                conn_start is not None
                and incoming_start is not None
                and incoming_end is not None
            ):
                gap_start = math.hypot(
                    float(conn_start.x) - float(incoming_start.x),
                    float(conn_start.y) - float(incoming_start.y),
                )
                gap_end = math.hypot(
                    float(conn_start.x) - float(incoming_end.x),
                    float(conn_start.y) - float(incoming_end.y),
                )
                nearest = min(gap_start, gap_end)
                if nearest > 2.0:
                    rows.append(
                        {
                            "junction_id": junction_id,
                            "connection_id": connection_id,
                            "issue": "connector_start_pose_mismatch",
                            "detail": round(nearest, 6),
                        }
                    )
            link_el = connecting.find("./link")
            if link_el is None:
                continue
            succ = link_el.find("./successor")
            if succ is None or str(succ.get("elementType") or "") != "road":
                continue
            outgoing = roads.get(str(succ.get("elementId") or ""))
            if outgoing is None:
                continue
            conn_end = _road_endpoint_pose(connecting, "end")
            out_start = _road_endpoint_pose(outgoing, "start")
            out_end = _road_endpoint_pose(outgoing, "end")
            if conn_end is not None and out_start is not None and out_end is not None:
                nearest = min(
                    math.hypot(
                        float(conn_end.x) - float(out_start.x),
                        float(conn_end.y) - float(out_start.y),
                    ),
                    math.hypot(
                        float(conn_end.x) - float(out_end.x),
                        float(conn_end.y) - float(out_end.y),
                    ),
                )
                if nearest > 2.0:
                    rows.append(
                        {
                            "junction_id": junction_id,
                            "connection_id": connection_id,
                            "issue": "connector_end_pose_mismatch",
                            "detail": round(nearest, 6),
                        }
                    )
    return rows


def _build_lane_rows(root: ET.Element) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for road in root.findall("./road"):
        road_id = str(road.get("id") or "")
        lanes = road.find("./lanes")
        if lanes is None:
            rows.append(
                {
                    "road_id": road_id,
                    "lane_section_s": "",
                    "lane_id": "",
                    "issue": "missing_lanes_block",
                    "detail": "",
                }
            )
            continue
        sections = lanes.findall("./laneSection")
        if not sections:
            rows.append(
                {
                    "road_id": road_id,
                    "lane_section_s": "",
                    "lane_id": "",
                    "issue": "missing_lane_sections",
                    "detail": "",
                }
            )
            continue
        prev_s = None
        for lane_offset in lanes.findall("./laneOffset"):
            coeff = max(
                abs(_safe_float(lane_offset.get(k), 0.0)) for k in ("a", "b", "c", "d")
            )
            if not math.isfinite(coeff) or coeff > 10.0:
                rows.append(
                    {
                        "road_id": road_id,
                        "lane_section_s": lane_offset.get("s", "0"),
                        "lane_id": "",
                        "issue": "extreme_lane_offset",
                        "detail": round(coeff, 6),
                    }
                )
        for section in sections:
            section_s = _safe_float(section.get("s"), 0.0)
            if prev_s is not None and section_s + 1e-9 < prev_s:
                rows.append(
                    {
                        "road_id": road_id,
                        "lane_section_s": section.get("s", "0"),
                        "lane_id": "",
                        "issue": "laneSection_s_nonmonotonic",
                        "detail": f"{prev_s}->{section_s}",
                    }
                )
            prev_s = section_s
            for lane in section.findall(".//lane"):
                lane_id = str(lane.get("id") or "")
                lane_type = str(lane.get("type") or "")
                try:
                    int(lane_id)
                except Exception:
                    rows.append(
                        {
                            "road_id": road_id,
                            "lane_section_s": section.get("s", "0"),
                            "lane_id": lane_id,
                            "issue": "invalid_lane_id",
                            "detail": lane_type,
                        }
                    )
                widths = lane.findall("./width")
                if not widths and lane_id != "0":
                    rows.append(
                        {
                            "road_id": road_id,
                            "lane_section_s": section.get("s", "0"),
                            "lane_id": lane_id,
                            "issue": "missing_width",
                            "detail": lane_type,
                        }
                    )
                for width in widths:
                    a_val = _safe_float(width.get("a"), 0.0)
                    if not math.isfinite(a_val):
                        rows.append(
                            {
                                "road_id": road_id,
                                "lane_section_s": section.get("s", "0"),
                                "lane_id": lane_id,
                                "issue": "nonfinite_lane_width",
                                "detail": lane_type,
                            }
                        )
                    elif a_val < 0.0:
                        rows.append(
                            {
                                "road_id": road_id,
                                "lane_section_s": section.get("s", "0"),
                                "lane_id": lane_id,
                                "issue": "negative_lane_width",
                                "detail": round(a_val, 6),
                            }
                        )
                    elif (
                        abs(a_val) < 1e-9
                        and lane_type not in {"none", "restricted"}
                        and lane_id != "0"
                    ):
                        rows.append(
                            {
                                "road_id": road_id,
                                "lane_section_s": section.get("s", "0"),
                                "lane_id": lane_id,
                                "issue": "zero_lane_width",
                                "detail": lane_type,
                            }
                        )
                    elif a_val > 20.0:
                        rows.append(
                            {
                                "road_id": road_id,
                                "lane_section_s": section.get("s", "0"),
                                "lane_id": lane_id,
                                "issue": "extreme_lane_width",
                                "detail": round(a_val, 6),
                            }
                        )
    return rows


def _build_elevation_rows(
    root: ET.Element,
    roads: Dict[str, ET.Element],
    link_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    road_adjacency: Dict[str, Set[str]] = defaultdict(set)
    for row in link_rows:
        if row.get("elementType") != "road" or row.get("issue") == "missing_linked_road":
            continue
        road_id = str(row.get("road_id") or "")
        other = str(row.get("elementId") or "")
        if road_id and other and other in roads:
            road_adjacency[road_id].add(other)
            road_adjacency[other].add(road_id)
            z_gap = row.get("z_gap_m")
            if z_gap not in ("", None):
                rows.append(
                    {
                        "road_id": road_id,
                        "neighbor_road_id": other,
                        "issue": "linked_endpoint_z_gap",
                        "detail": z_gap,
                    }
                )
    z_samples: List[float] = []
    for road_id, road in roads.items():
        z_start, z_end = _road_z_range(road)
        has_elev = bool(_elevation_segments(road))
        rows.append(
            {
                "road_id": road_id,
                "neighbor_road_id": "",
                "issue": "road_endpoint_z",
                "detail": json.dumps(
                    {"z_start": z_start, "z_end": z_end, "has_elevation": has_elev}
                ),
            }
        )
        for value in (z_start, z_end):
            if value is not None:
                z_samples.append(float(value))
    median_abs = statistics.median([abs(v) for v in z_samples]) if z_samples else 0.0
    for road_id, road in roads.items():
        segments = _elevation_segments(road)
        neighbors = road_adjacency.get(road_id, set())
        if not segments and any(_elevation_segments(roads[n]) for n in neighbors if n in roads):
            rows.append(
                {
                    "road_id": road_id,
                    "neighbor_road_id": ",".join(sorted(neighbors)[:8]),
                    "issue": "missing_elevation_with_elevated_neighbors",
                    "detail": "",
                }
            )
        z_start, z_end = _road_z_range(road)
        if median_abs > 50.0 and any(abs(v or 0.0) < 1e-6 for v in (z_start, z_end)):
            rows.append(
                {
                    "road_id": road_id,
                    "neighbor_road_id": "",
                    "issue": "suspicious_zero_elevation_road",
                    "detail": json.dumps(
                        {
                            "z_start": z_start,
                            "z_end": z_end,
                            "median_abs_map_z": median_abs,
                        }
                    ),
                }
            )
    return rows


def _graph_components(root: ET.Element, roads: Dict[str, ET.Element]) -> Dict[str, Any]:
    adjacency: Dict[str, Set[str]] = {road_id: set() for road_id in roads}
    for road in root.findall("./road"):
        road_id = str(road.get("id") or "")
        link_el = road.find("./link")
        if link_el is None:
            continue
        for rel_name in ("predecessor", "successor"):
            rel = link_el.find(f"./{rel_name}")
            if rel is None or str(rel.get("elementType") or "") != "road":
                continue
            other = str(rel.get("elementId") or "")
            if other in roads:
                adjacency[road_id].add(other)
                adjacency[other].add(road_id)
    for junction in root.findall("./junction"):
        for connection in junction.findall("./connection"):
            incoming = str(connection.get("incomingRoad") or "")
            connecting = str(connection.get("connectingRoad") or "")
            if incoming in roads and connecting in roads:
                adjacency[incoming].add(connecting)
                adjacency[connecting].add(incoming)
            if connecting in roads:
                link_el = roads[connecting].find("./link")
                if link_el is not None:
                    succ = link_el.find("./successor")
                    if succ is not None and str(succ.get("elementType") or "") == "road":
                        outgoing = str(succ.get("elementId") or "")
                        if outgoing in roads:
                            adjacency[connecting].add(outgoing)
                            adjacency[outgoing].add(connecting)
    visited: Set[str] = set()
    components: List[List[str]] = []
    for road_id in roads:
        if road_id in visited:
            continue
        queue: deque[str] = deque([road_id])
        visited.add(road_id)
        component: List[str] = []
        while queue:
            current = queue.popleft()
            component.append(current)
            for neighbor in adjacency[current]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        components.append(sorted(component))
    components.sort(key=len, reverse=True)
    return {
        "component_count": len(components),
        "largest_component_size": len(components[0]) if components else 0,
        "isolated_roads": [component[0] for component in components if len(component) == 1][:200],
        "components": [
            {"size": len(component), "sample_roads": component[:25]}
            for component in components[:25]
        ],
        "dangling_road_ids": sorted(
            [road_id for road_id, neighbors in adjacency.items() if not neighbors]
        )[:200],
    }


def audit_xodr(xodr_path: Path, out_dir: Path) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    tree = ET.parse(xodr_path)
    root = tree.getroot()
    roads = _roads_by_id(root)
    header = _header_info(root)
    extents = _max_planview_abs(root)
    link_rows = _build_link_rows(root, roads)
    planview_rows = _build_planview_rows(root)
    junction_rows = _build_junction_rows(root, roads)
    lane_rows = _build_lane_rows(root)
    elevation_rows = _build_elevation_rows(root, roads, link_rows)
    graph_report = _graph_components(root, roads)

    z_samples = [
        value
        for road in roads.values()
        for value in _road_z_range(road)
        if value is not None
    ]
    elevation_min = min(z_samples) if z_samples else None
    elevation_max = max(z_samples) if z_samples else None
    superelevations = root.findall(".//lateralProfile/superelevation")
    lateral_profiles = root.findall("./road/lateralProfile")
    elevation_elements = root.findall(".//elevationProfile/elevation")

    coordinate_audit = {
        "header": header,
        "max_abs_planview": extents,
        "appears_centered_near_origin": bool(
            max(extents["max_abs_x"], extents["max_abs_y"]) <= 10000.0
        ),
        "huge_coordinate_threshold_m": 100000.0,
        "huge_coordinate_suspected": bool(
            max(extents["max_abs_x"], extents["max_abs_y"]) > 100000.0
        ),
    }
    planview_audit = {
        "issue_count": len(planview_rows),
        "issues_by_type": {
            key: sum(1 for row in planview_rows if row["issue"] == key)
            for key in sorted({row["issue"] for row in planview_rows})
        },
        "max_abs_planview": extents,
    }
    top_link_gaps = sorted(
        [row for row in link_rows if row.get("xy_gap_m") not in ("", None)],
        key=lambda row: float(row.get("xy_gap_m") or 0.0),
        reverse=True,
    )[:50]

    audit_summary = {
        "schema": "audit_xodr_visual_geometry_v1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "xodr_path": str(xodr_path.resolve()),
        "sha256": _sha256_file(xodr_path),
        "file_size_bytes": int(xodr_path.stat().st_size),
        "road_count": len(roads),
        "junction_count": len(root.findall("./junction")),
        "signal_count": _signal_count(root),
        "object_count": _object_count(root),
        "elevationProfile_entry_count": len(elevation_elements),
        "superelevation_entry_count": len(superelevations),
        "lateralProfile_entry_count": len(lateral_profiles),
        "header_offset": {
            "x": header["offset_x"],
            "y": header["offset_y"],
            "z": header["offset_z"],
        },
        "geoReference_present": header["geoReference_present"],
        "min_sampled_elevation": elevation_min,
        "max_sampled_elevation": elevation_max,
        "max_abs_planview_x": extents["max_abs_x"],
        "max_abs_planview_y": extents["max_abs_y"],
        "appears_centered_near_carla_origin": coordinate_audit["appears_centered_near_origin"],
        "planview_issue_count": len(planview_rows),
        "link_gap_issue_count": len(
            [row for row in link_rows if row.get("issue") not in ("", None)]
        ),
        "junction_issue_count": len(junction_rows),
        "lane_issue_count": len(lane_rows),
        "elevation_issue_count": len(elevation_rows),
        "graph_component_count": graph_report["component_count"],
        "largest_component_size": graph_report["largest_component_size"],
        "top_50_largest_endpoint_gaps": top_link_gaps,
    }

    _write_json(out_dir / "audit_summary.json", audit_summary)
    _write_json(out_dir / "coordinate_audit.json", coordinate_audit)
    _write_json(out_dir / "planview_audit.json", planview_audit)
    _write_json(out_dir / "graph_components.json", graph_report)

    _write_csv(
        out_dir / "link_gap_report.csv",
        link_rows,
        [
            "road_id",
            "relation",
            "elementType",
            "elementId",
            "source_contact",
            "target_contact",
            "xy_gap_m",
            "hdg_gap_deg",
            "z_gap_m",
            "issue",
        ],
    )
    _write_csv(
        out_dir / "junction_integrity_report.csv",
        junction_rows,
        ["junction_id", "connection_id", "issue", "detail"],
    )
    _write_csv(
        out_dir / "lane_sanity_report.csv",
        lane_rows,
        ["road_id", "lane_section_s", "lane_id", "issue", "detail"],
    )
    _write_csv(
        out_dir / "elevation_gap_report.csv",
        elevation_rows,
        ["road_id", "neighbor_road_id", "issue", "detail"],
    )
    return audit_summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit OpenDRIVE geometry/topology issues that can surface visually in CARLA."
    )
    parser.add_argument("--xodr", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    summary = audit_xodr(args.xodr, args.out)
    print(
        "[audit_xodr_visual_geometry] "
        f"roads={summary['road_count']} junctions={summary['junction_count']} "
        f"planview_issues={summary['planview_issue_count']} lane_issues={summary['lane_issue_count']} "
        f"junction_issues={summary['junction_issue_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
