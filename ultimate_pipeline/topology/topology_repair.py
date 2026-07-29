# ultimate_pipeline/topology/topology_repair.py

from __future__ import annotations

from collections import defaultdict
import math
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Set, Tuple

from ultimate_pipeline.core.xodr_sanitizer import _safe_float
from ultimate_pipeline.core.repair_diff import diff_log
from ultimate_pipeline.geometry.geometry_math import sample_parampoly3_points


Point = Tuple[float, float]
Bucket = Tuple[int, int]


def _road_id(road: ET.Element) -> str:
    return str(road.get("id") or "").strip()


def _road_length(road: ET.Element) -> float:
    return max(0.0, _safe_float(road.get("length"), 0.0))


def _roads_by_id(root: ET.Element) -> Dict[str, ET.Element]:
    return {
        _road_id(road): road
        for road in root.findall("./road")
        if _road_id(road)
    }


def _road_successor_exit_road(road: Optional[ET.Element]) -> Optional[str]:
    if road is None:
        return None
    link = road.find("link")
    if link is None:
        return None
    for succ in link.findall("successor"):
        if str(succ.get("elementType") or "").strip() == "road":
            exit_road = str(succ.get("elementId") or "").strip()
            return exit_road or None
    return None


def _format_float(value: float) -> str:
    return f"{float(value):.6f}"


def _geometry_endpoint(geom: ET.Element) -> Point:
    x0 = _safe_float(geom.get("x"), 0.0)
    y0 = _safe_float(geom.get("y"), 0.0)
    hdg = _safe_float(geom.get("hdg"), 0.0)
    length = max(0.0, _safe_float(geom.get("length"), 0.0))

    arc = geom.find("arc")
    if arc is not None:
        curvature = _safe_float(arc.get("curvature"), 0.0)
        if abs(curvature) > 1e-12:
            hdg_new = hdg + curvature * length
            return (
                x0 + (math.sin(hdg_new) - math.sin(hdg)) / curvature,
                y0 - (math.cos(hdg_new) - math.cos(hdg)) / curvature,
            )

    if geom.find("paramPoly3") is not None:
        pts = sample_parampoly3_points(geom, x0, y0, hdg, length, [1.0])
        if pts:
            return pts[-1]

    return (
        x0 + length * math.cos(hdg),
        y0 + length * math.sin(hdg),
    )


def _road_start_end(road: ET.Element) -> Optional[Tuple[Point, Point]]:
    geoms = sorted(
        list(road.findall("./planView/geometry")),
        key=lambda item: _safe_float(item.get("s"), 0.0),
    )
    if not geoms:
        return None
    first = geoms[0]
    last = geoms[-1]
    start = (
        _safe_float(first.get("x"), 0.0),
        _safe_float(first.get("y"), 0.0),
    )
    return start, _geometry_endpoint(last)


def _anchor_bucket(point: Point, bucket_m: float = 0.5) -> Bucket:
    scale = max(float(bucket_m), 1e-6)
    return (int(round(point[0] / scale)), int(round(point[1] / scale)))


def _road_start_heading_deg(road: ET.Element) -> float:
    geoms = sorted(
        list(road.findall("./planView/geometry")),
        key=lambda item: _safe_float(item.get("s"), 0.0),
    )
    if not geoms:
        return 0.0
    return math.degrees(_safe_float(geoms[0].get("hdg"), 0.0)) % 360.0


def _angle_delta_deg(left: float, right: float) -> float:
    raw = abs(float(left) - float(right)) % 360.0
    return raw if raw <= 180.0 else 360.0 - raw


def _signed_angle_delta_deg(source_deg: float, target_deg: float) -> float:
    return (float(target_deg) - float(source_deg) + 180.0) % 360.0 - 180.0


def _heading_spread_deg(headings: List[float]) -> float:
    if len(headings) < 2:
        return 0.0
    return max(
        _angle_delta_deg(left, right)
        for idx, left in enumerate(headings)
        for right in headings[idx + 1 :]
    )


def _road_end_heading_deg(road: ET.Element) -> float:
    geoms = sorted(
        list(road.findall("./planView/geometry")),
        key=lambda item: _safe_float(item.get("s"), 0.0),
    )
    if not geoms:
        return 0.0
    geom = geoms[-1]
    hdg = _safe_float(geom.get("hdg"), 0.0)
    length = max(0.0, _safe_float(geom.get("length"), 0.0))
    arc = geom.find("arc")
    if arc is not None:
        hdg += _safe_float(arc.get("curvature"), 0.0) * length
    return math.degrees(hdg) % 360.0


def _heading_between_points(start: Point, end: Point) -> float:
    return (
        math.degrees(
            math.atan2(
                float(end[1]) - float(start[1]),
                float(end[0]) - float(start[0]),
            )
        )
        % 360.0
    )


def _turn_class(delta_deg: float) -> str:
    if delta_deg <= -135.0 or delta_deg >= 135.0:
        return "uturn"
    if delta_deg < -35.0:
        return "right"
    if delta_deg > 35.0:
        return "left"
    return "straight"


def _lane_link_signature(conn: ET.Element) -> Tuple[Tuple[str, str], ...]:
    return tuple(
        sorted(
            (
                str(link.get("from") or "").strip(),
                str(link.get("to") or "").strip(),
            )
            for link in conn.findall("laneLink")
        )
    )


def _lane_side_bucket(signature: Tuple[Tuple[str, str], ...]) -> str:
    lane_ids: List[int] = []
    for from_lane, _to_lane in signature:
        try:
            lane_ids.append(int(from_lane))
        except Exception:
            continue
    if not lane_ids:
        return "none"
    if all(lane_id < 0 for lane_id in lane_ids):
        return "right"
    if all(lane_id > 0 for lane_id in lane_ids):
        return "left"
    return "mixed"


def _fit_arc_geometry(
    start: Point, end: Point, start_hdg_rad: float
) -> Optional[Tuple[float, float]]:
    """Compute (curvature_rad_per_m, arc_length_m) for a circular arc that:
    - starts at *start* with heading *start_hdg_rad*
    - passes exactly through *end*

    Positive curvature = counterclockwise (left-turn) per OpenDRIVE convention.
    Returns None if the arc would be degenerate, nearly straight, or require
    more than a 270° sweep (pathological geometry).
    """
    dx = float(end[0]) - float(start[0])
    dy = float(end[1]) - float(start[1])
    d_sq = dx * dx + dy * dy
    if d_sq < 1e-12:
        return None
    # Unique curvature for arc from (start, h) through end:
    #   k = -2*(dx·sin(h) - dy·cos(h)) / (dx²+dy²)
    k = -2.0 * (dx * math.sin(start_hdg_rad) - dy * math.cos(start_hdg_rad)) / d_sq
    if abs(k) < 1e-6:
        return None  # nearly straight; caller falls back to direct line
    inv_k = 1.0 / k
    # Arc centre
    cx = float(start[0]) - math.sin(start_hdg_rad) * inv_k
    cy = float(start[1]) + math.cos(start_hdg_rad) * inv_k
    # Sweep angle
    alpha_s = math.atan2(float(start[1]) - cy, float(start[0]) - cx)
    alpha_e = math.atan2(float(end[1]) - cy, float(end[0]) - cx)
    if k > 0.0:  # counterclockwise
        theta = (alpha_e - alpha_s) % (2.0 * math.pi)
        if theta < 1e-9:
            theta = 2.0 * math.pi
    else:  # clockwise
        theta = (alpha_s - alpha_e) % (2.0 * math.pi)
        if theta < 1e-9:
            theta = 2.0 * math.pi
    if theta > 1.5 * math.pi:
        return None  # > 270°: degenerate junction geometry; skip
    arc_length = theta * abs(inv_k)
    if arc_length < 1.0:
        return None
    return k, arc_length


def _replace_planview_with_arc(
    road: ET.Element,
    start: Point,
    start_hdg_rad: float,
    curvature: float,
    arc_length: float,
) -> bool:
    """Replace road planView with a single arc geometry and update the road length attribute.

    Updating the road length is safe for connector roads (junction != -1) because
    they have a single laneSection at s=0 and no internal s-referenced sub-elements.
    """
    plan_view = road.find("planView")
    if plan_view is None:
        plan_view = ET.Element("planView")
        road.insert(0, plan_view)
    for child in list(plan_view):
        plan_view.remove(child)
    geom = ET.SubElement(
        plan_view,
        "geometry",
        {
            "s": "0.000000",
            "x": _format_float(start[0]),
            "y": _format_float(start[1]),
            "hdg": _format_float(start_hdg_rad),
            "length": _format_float(arc_length),
        },
    )
    ET.SubElement(geom, "arc", {"curvature": _format_float(curvature)})
    road.set("length", _format_float(arc_length))
    return True


def _offset_point(point: Point, heading_deg: float, lateral_offset_m: float) -> Point:
    theta = math.radians(float(heading_deg) + 90.0)
    return (
        float(point[0]) + float(lateral_offset_m) * math.cos(theta),
        float(point[1]) + float(lateral_offset_m) * math.sin(theta),
    )


def _centered_offsets(count: int, spacing_m: float) -> List[float]:
    if count <= 1:
        return [0.0] * max(0, count)
    center = (count - 1) / 2.0
    return [(idx - center) * float(spacing_m) for idx in range(count)]


def _replace_planview_with_direct_line(
    road: ET.Element, start: Point, end: Point
) -> Optional[float]:
    dx = float(end[0]) - float(start[0])
    dy = float(end[1]) - float(start[1])
    direct_length = math.hypot(dx, dy)
    if direct_length <= 1e-9:
        return None

    hdg = math.atan2(dy, dx)
    plan_view = road.find("planView")
    if plan_view is None:
        plan_view = ET.Element("planView")
        road.insert(0, plan_view)
    for child in list(plan_view):
        plan_view.remove(child)

    geom = ET.SubElement(
        plan_view,
        "geometry",
        {
            "s": "0.000000",
            "x": _format_float(start[0]),
            "y": _format_float(start[1]),
            "hdg": _format_float(hdg),
            "length": _format_float(direct_length),
        },
    )
    ET.SubElement(geom, "line")
    return direct_length


def _valid_incoming_connection_counts(root: ET.Element) -> Dict[Tuple[str, str], int]:
    roads = _roads_by_id(root)
    counts: Dict[Tuple[str, str], int] = defaultdict(int)
    for junction in root.findall("./junction"):
        junction_id = str(junction.get("id") or "").strip()
        if not junction_id:
            continue
        for conn in junction.findall("./connection"):
            incoming = str(conn.get("incomingRoad") or "").strip()
            connecting = str(conn.get("connectingRoad") or "").strip()
            if not incoming or not connecting:
                continue
            if incoming not in roads:
                continue
            if _road_successor_exit_road(roads.get(connecting)):
                counts[(junction_id, incoming)] += 1
    return dict(counts)


def _remove_roads(root: ET.Element, road_ids: Set[str]) -> int:
    removed = 0
    for road in list(root.findall("./road")):
        if _road_id(road) in road_ids:
            root.remove(road)
            removed += 1
    return removed


def _remove_duplicate_connections(root: ET.Element, road_ids: Set[str]) -> int:
    removed = 0
    for junction in root.findall("./junction"):
        for conn in list(junction.findall("./connection")):
            if str(conn.get("connectingRoad") or "").strip() in road_ids:
                junction.remove(conn)
                removed += 1
    return removed


def _enforce_canonical_invariants(
    root: ET.Element,
    before_incoming_counts: Dict[Tuple[str, str], int],
) -> None:
    roads = _roads_by_id(root)
    seen_families: Set[Tuple[str, str, str]] = set()
    after_counts: Dict[Tuple[str, str], int] = defaultdict(int)

    for junction in root.findall("./junction"):
        junction_id = str(junction.get("id") or "").strip()
        if not junction_id:
            continue
        for conn in junction.findall("./connection"):
            incoming = str(conn.get("incomingRoad") or "").strip()
            connecting = str(conn.get("connectingRoad") or "").strip()
            exit_road = _road_successor_exit_road(roads.get(connecting))
            if not incoming or not connecting or not exit_road:
                continue
            key = (junction_id, incoming, exit_road)
            if key in seen_families:
                raise RuntimeError(
                    "junction connector canonicalization invariant failed: "
                    f"duplicate family remains for junction={junction_id}, "
                    f"incomingRoad={incoming}, exitRoad={exit_road}"
                )
            seen_families.add(key)
            after_counts[(junction_id, incoming)] += 1

    for key, before_count in before_incoming_counts.items():
        if before_count > 0 and after_counts.get(key, 0) <= 0:
            junction_id, incoming = key
            raise RuntimeError(
                "junction connector canonicalization invariant failed: "
                f"incomingRoad={incoming} in junction={junction_id} lost all valid "
                "connections"
            )


def canonicalize_junction_connectors(root: ET.Element) -> Dict[str, Any]:
    """Canonicalize Stage 3 junction connectors before geometry freeze.

    Policy A removes true duplicate connector roads for the same
    (incomingRoad, exitRoad) family. Policy B keeps semantically distinct exits
    but simplifies crowded same-start connector geometry to direct lines.
    """

    roads = _roads_by_id(root)
    before_incoming_counts = _valid_incoming_connection_counts(root)
    duplicate_families: List[Dict[str, Any]] = []
    removed_ids: Set[str] = set()
    removed_connections = 0

    for junction in root.findall("./junction"):
        junction_id = str(junction.get("id") or "").strip()
        if not junction_id:
            continue
        families: Dict[Tuple[str, str], List[Tuple[str, ET.Element]]] = defaultdict(list)
        for conn in junction.findall("./connection"):
            incoming = str(conn.get("incomingRoad") or "").strip()
            connecting = str(conn.get("connectingRoad") or "").strip()
            exit_road = _road_successor_exit_road(roads.get(connecting))
            if not incoming or not connecting or not exit_road:
                continue
            families[(incoming, exit_road)].append((connecting, conn))

        for (incoming, exit_road), members in families.items():
            unique_members = []
            seen = set()
            for connecting, conn in members:
                if connecting in seen or connecting not in roads:
                    continue
                unique_members.append((connecting, conn))
                seen.add(connecting)
            if len(unique_members) <= 1:
                continue

            sorted_members = sorted(
                unique_members,
                key=lambda item: (_road_length(roads[item[0]]), item[0]),
            )
            keep_id = sorted_members[len(sorted_members) // 2][0]
            remove_family_ids = [item[0] for item in sorted_members if item[0] != keep_id]
            removed_ids.update(remove_family_ids)
            duplicate_families.append(
                {
                    "junction_id": junction_id,
                    "incomingRoad": incoming,
                    "exitRoad": exit_road,
                    "kept_connectingRoad": keep_id,
                    "removed_connectingRoads": remove_family_ids,
                    "family_size": len(sorted_members),
                }
            )

    if removed_ids:
        removed_connections = _remove_duplicate_connections(root, removed_ids)
        roads_removed = _remove_roads(root, removed_ids)
    else:
        roads_removed = 0

    roads = _roads_by_id(root)
    normalized: List[Dict[str, Any]] = []
    touched_junctions: Set[str] = set()  # junctions touched by any policy (B, D, or E)
    policy_d_junctions: Set[str] = set()  # only junctions handled by Policy D (4×3 matrix)
    for junction in root.findall("./junction"):
        junction_id = str(junction.get("id") or "").strip()
        if not junction_id:
            continue
        groups: Dict[Bucket, List[Tuple[str, Point, Point, float]]] = defaultdict(list)
        for conn in junction.findall("./connection"):
            connecting = str(conn.get("connectingRoad") or "").strip()
            road = roads.get(connecting)
            if road is None:
                continue
            endpoints = _road_start_end(road)
            if endpoints is None:
                continue
            start, end = endpoints
            groups[_anchor_bucket(start)].append(
                (connecting, start, end, _road_start_heading_deg(road))
            )

        for bucket, members in groups.items():
            if len(members) < 3:
                continue
            heading_spread = _heading_spread_deg([item[3] for item in members])
            if heading_spread < 20.0:
                continue
            for connecting, start, end, _heading in members:
                road = roads.get(connecting)
                if road is None:
                    continue
                old_geometry_count = len(road.findall("./planView/geometry"))
                old_length = _road_length(road)
                direct_length = _replace_planview_with_direct_line(road, start, end)
                if direct_length is None:
                    continue
                touched_junctions.add(junction_id)
                normalized.append(
                    {
                        "junction_id": junction_id,
                        "connectingRoad": connecting,
                        "start_bucket": list(bucket),
                        "old_geometry_count": old_geometry_count,
                        "start_heading_spread_deg": round(heading_spread, 6),
                        "road_length_preserved_m": round(old_length, 6),
                        "direct_geometry_length_m": round(direct_length, 6),
                    }
                )

    roads = _roads_by_id(root)
    turn_family_adjusted: List[Dict[str, Any]] = []
    turn_family_groups: List[Dict[str, Any]] = []
    turn_offset_m = 0.85
    for junction in root.findall("./junction"):
        junction_id = str(junction.get("id") or "").strip()
        if not junction_id:
            continue

        records: List[Dict[str, Any]] = []
        for conn in junction.findall("./connection"):
            incoming = str(conn.get("incomingRoad") or "").strip()
            connecting = str(conn.get("connectingRoad") or "").strip()
            road = roads.get(connecting)
            exit_road = _road_successor_exit_road(road)
            incoming_road = roads.get(incoming)
            exit_road_element = roads.get(exit_road or "")
            if (
                not incoming
                or not connecting
                or road is None
                or not exit_road
                or incoming_road is None
                or exit_road_element is None
            ):
                continue
            endpoints = _road_start_end(road)
            if endpoints is None:
                continue
            start, end = endpoints
            incoming_heading = _road_end_heading_deg(incoming_road)
            exit_heading = _road_start_heading_deg(exit_road_element)
            connector_heading = _heading_between_points(start, end)
            signed_delta = _signed_angle_delta_deg(incoming_heading, connector_heading)
            lane_signature = _lane_link_signature(conn)
            lane_side = _lane_side_bucket(lane_signature)
            records.append(
                {
                    "junction_id": junction_id,
                    "incoming": incoming,
                    "connecting": connecting,
                    "exit": exit_road,
                    "road": road,
                    "start": start,
                    "end": end,
                    "start_bucket": _anchor_bucket(start),
                    "end_bucket": _anchor_bucket(end),
                    "incoming_heading": incoming_heading,
                    "exit_heading": exit_heading,
                    "signed_delta": signed_delta,
                    "turn_class": _turn_class(signed_delta),
                    "lane_side": lane_side,
                    "lane_signature": lane_signature,
                }
            )

        start_offsets: Dict[str, float] = {}
        end_offsets: Dict[str, float] = {}
        start_groups: Dict[Tuple[str, Bucket], List[Dict[str, Any]]] = defaultdict(list)
        end_groups: Dict[Tuple[str, Bucket], List[Dict[str, Any]]] = defaultdict(list)
        for record in records:
            start_groups[(record["incoming"], record["start_bucket"])].append(record)
            end_groups[(record["exit"], record["end_bucket"])].append(record)

        regular_turn_matrix = (
            len(records) == 12
            and len(start_groups) == 4
            and len(end_groups) == 4
            and all(len(members) == 3 for members in start_groups.values())
            and all(len(members) == 3 for members in end_groups.values())
        )
        if not regular_turn_matrix:
            continue

        for (incoming, bucket), members in start_groups.items():
            distinct_exits = {str(member["exit"]) for member in members}
            if len(members) < 3 or len(distinct_exits) < 3:
                continue
            ordered = sorted(
                members,
                key=lambda item: (
                    float(item["signed_delta"]),
                    str(item["exit"]),
                    str(item["connecting"]),
                ),
            )
            for member, offset in zip(ordered, _centered_offsets(len(ordered), turn_offset_m)):
                start_offsets[str(member["connecting"])] = offset
            turn_family_groups.append(
                {
                    "junction_id": junction_id,
                    "anchor": "start",
                    "incomingRoad": incoming,
                    "start_bucket": list(bucket),
                    "member_count": len(ordered),
                    "semantic_families": [
                        {
                            "connectingRoad": str(member["connecting"]),
                            "exitRoad": str(member["exit"]),
                            "lane_side": str(member["lane_side"]),
                            "turn_class": str(member["turn_class"]),
                            "signed_delta_deg": round(float(member["signed_delta"]), 6),
                        }
                        for member in ordered
                    ],
                }
            )

        for (exit_road, bucket), members in end_groups.items():
            distinct_incoming = {str(member["incoming"]) for member in members}
            if len(members) < 3 or len(distinct_incoming) < 3:
                continue
            ordered = sorted(
                members,
                key=lambda item: (
                    float(item["signed_delta"]),
                    str(item["incoming"]),
                    str(item["connecting"]),
                ),
            )
            for member, offset in zip(ordered, _centered_offsets(len(ordered), turn_offset_m)):
                end_offsets[str(member["connecting"])] = offset
            turn_family_groups.append(
                {
                    "junction_id": junction_id,
                    "anchor": "end",
                    "exitRoad": exit_road,
                    "end_bucket": list(bucket),
                    "member_count": len(ordered),
                    "semantic_families": [
                        {
                            "connectingRoad": str(member["connecting"]),
                            "incomingRoad": str(member["incoming"]),
                            "lane_side": str(member["lane_side"]),
                            "turn_class": str(member["turn_class"]),
                            "signed_delta_deg": round(float(member["signed_delta"]), 6),
                        }
                        for member in ordered
                    ],
                }
            )

        records_by_id = {str(record["connecting"]): record for record in records}
        for connecting in sorted(
            set(start_offsets) | set(end_offsets),
            key=lambda item: (len(item), item),
        ):
            record = records_by_id.get(connecting)
            if record is None:
                continue
            road = record["road"]
            old_start_bucket = record["start_bucket"]
            old_end_bucket = record["end_bucket"]
            start_offset = float(start_offsets.get(connecting, 0.0))
            end_offset = float(end_offsets.get(connecting, 0.0))
            new_start = _offset_point(
                record["start"],
                float(record["incoming_heading"]),
                start_offset,
            )
            new_end = _offset_point(
                record["end"],
                float(record["exit_heading"]),
                end_offset,
            )
            direct_length = _replace_planview_with_direct_line(road, new_start, new_end)
            if direct_length is None:
                continue
            touched_junctions.add(junction_id)
            policy_d_junctions.add(junction_id)
            turn_family_adjusted.append(
                {
                    "junction_id": junction_id,
                    "connectingRoad": connecting,
                    "incomingRoad": str(record["incoming"]),
                    "exitRoad": str(record["exit"]),
                    "lane_side": str(record["lane_side"]),
                    "turn_class": str(record["turn_class"]),
                    "start_offset_m": round(start_offset, 6),
                    "end_offset_m": round(end_offset, 6),
                    "old_start_bucket": list(old_start_bucket),
                    "new_start_bucket": list(_anchor_bucket(new_start)),
                    "old_end_bucket": list(old_end_bucket),
                    "new_end_bucket": list(_anchor_bucket(new_end)),
                    "direct_geometry_length_m": round(direct_length, 6),
                }
            )

    # Policy E: generalized fan-out lateral spread for irregular junctions.
    # Applies to any junction NOT already handled by Policy D (4×3 regular matrix).
    # For each start-anchor bucket shared by ≥2 connectors from the same incoming
    # road with DISTINCT exit roads, offset each connector's start laterally so they
    # no longer share an anchor bucket.  Likewise for shared end-anchor groups.
    # Replaces planView with a single direct line (start→end) after offsetting.
    # Safety guard: only applies when all exits in the group are distinct (semantic
    # dups would have been removed by Policy A; if not, skip rather than risk info loss).
    roads = _roads_by_id(root)
    policy_e_adjusted: List[Dict[str, Any]] = []
    policy_e_groups: List[Dict[str, Any]] = []

    for junction in root.findall("./junction"):
        junction_id = str(junction.get("id") or "").strip()
        if not junction_id:
            continue
        if junction_id in policy_d_junctions:
            continue  # Policy D (4×3 regular matrix) already optimally placed connectors

        records_e: List[Dict[str, Any]] = []
        for conn in junction.findall("./connection"):
            incoming = str(conn.get("incomingRoad") or "").strip()
            connecting = str(conn.get("connectingRoad") or "").strip()
            road = roads.get(connecting)
            exit_road = _road_successor_exit_road(road)
            incoming_road = roads.get(incoming)
            exit_road_element = roads.get(exit_road or "")
            if (
                not incoming
                or not connecting
                or road is None
                or not exit_road
                or incoming_road is None
                or exit_road_element is None
            ):
                continue
            endpoints = _road_start_end(road)
            if endpoints is None:
                continue
            start, end = endpoints
            incoming_heading = _road_end_heading_deg(incoming_road)
            exit_heading = _road_start_heading_deg(exit_road_element)
            connector_heading = _heading_between_points(start, end)
            signed_delta = _signed_angle_delta_deg(incoming_heading, connector_heading)
            lane_signature = _lane_link_signature(conn)
            lane_side = _lane_side_bucket(lane_signature)
            records_e.append(
                {
                    "junction_id": junction_id,
                    "incoming": incoming,
                    "connecting": connecting,
                    "exit": exit_road,
                    "road": road,
                    "start": start,
                    "end": end,
                    "start_bucket": _anchor_bucket(start),
                    "end_bucket": _anchor_bucket(end),
                    "incoming_heading": incoming_heading,
                    "exit_heading": exit_heading,
                    "signed_delta": signed_delta,
                    "turn_class": _turn_class(signed_delta),
                    "lane_side": lane_side,
                    "lane_signature": lane_signature,
                }
            )

        start_offsets_e: Dict[str, float] = {}
        end_offsets_e: Dict[str, float] = {}
        start_groups_e: Dict[Tuple[str, Bucket], List[Dict[str, Any]]] = defaultdict(list)
        end_groups_e: Dict[Tuple[str, Bucket], List[Dict[str, Any]]] = defaultdict(list)
        for record in records_e:
            start_groups_e[(record["incoming"], record["start_bucket"])].append(record)
            end_groups_e[(record["exit"], record["end_bucket"])].append(record)

        for (incoming, bucket), members in start_groups_e.items():
            if len(members) < 2:
                continue
            distinct_exits = {str(m["exit"]) for m in members}
            if len(distinct_exits) < len(members):
                # Semantic dups remain in this group; skip to avoid unsafe removal.
                continue
            ordered = sorted(
                members,
                key=lambda item: (float(item["signed_delta"]), str(item["exit"]), str(item["connecting"])),
            )
            for member, offset in zip(ordered, _centered_offsets(len(ordered), turn_offset_m)):
                start_offsets_e[str(member["connecting"])] = offset
            policy_e_groups.append(
                {
                    "junction_id": junction_id,
                    "anchor": "start",
                    "incomingRoad": incoming,
                    "start_bucket": list(bucket),
                    "member_count": len(ordered),
                    "semantic_families": [
                        {
                            "connectingRoad": str(m["connecting"]),
                            "exitRoad": str(m["exit"]),
                            "lane_side": str(m["lane_side"]),
                            "turn_class": str(m["turn_class"]),
                            "signed_delta_deg": round(float(m["signed_delta"]), 6),
                        }
                        for m in ordered
                    ],
                }
            )

        for (exit_road_key, bucket), members in end_groups_e.items():
            if len(members) < 2:
                continue
            distinct_incoming = {str(m["incoming"]) for m in members}
            if len(distinct_incoming) < len(members):
                continue
            ordered = sorted(
                members,
                key=lambda item: (float(item["signed_delta"]), str(item["incoming"]), str(item["connecting"])),
            )
            for member, offset in zip(ordered, _centered_offsets(len(ordered), turn_offset_m)):
                end_offsets_e[str(member["connecting"])] = offset
            policy_e_groups.append(
                {
                    "junction_id": junction_id,
                    "anchor": "end",
                    "exitRoad": exit_road_key,
                    "end_bucket": list(bucket),
                    "member_count": len(ordered),
                    "semantic_families": [
                        {
                            "connectingRoad": str(m["connecting"]),
                            "incomingRoad": str(m["incoming"]),
                            "lane_side": str(m["lane_side"]),
                            "turn_class": str(m["turn_class"]),
                            "signed_delta_deg": round(float(m["signed_delta"]), 6),
                        }
                        for m in ordered
                    ],
                }
            )

        if not start_offsets_e and not end_offsets_e:
            continue

        records_e_by_id = {str(r["connecting"]): r for r in records_e}
        for connecting in sorted(
            set(start_offsets_e) | set(end_offsets_e),
            key=lambda item: (len(item), item),
        ):
            record = records_e_by_id.get(connecting)
            if record is None:
                continue
            road = record["road"]
            old_start_bucket = record["start_bucket"]
            old_end_bucket = record["end_bucket"]
            start_offset = float(start_offsets_e.get(connecting, 0.0))
            end_offset = float(end_offsets_e.get(connecting, 0.0))
            new_start = _offset_point(
                record["start"], float(record["incoming_heading"]), start_offset
            )
            new_end = _offset_point(
                record["end"], float(record["exit_heading"]), end_offset
            )
            direct_length = _replace_planview_with_direct_line(road, new_start, new_end)
            if direct_length is None:
                continue
            touched_junctions.add(junction_id)
            policy_e_adjusted.append(
                {
                    "junction_id": junction_id,
                    "connectingRoad": connecting,
                    "incomingRoad": str(record["incoming"]),
                    "exitRoad": str(record["exit"]),
                    "lane_side": str(record["lane_side"]),
                    "turn_class": str(record["turn_class"]),
                    "start_offset_m": round(start_offset, 6),
                    "end_offset_m": round(end_offset, 6),
                    "old_start_bucket": list(old_start_bucket),
                    "new_start_bucket": list(_anchor_bucket(new_start)),
                    "old_end_bucket": list(old_end_bucket),
                    "new_end_bucket": list(_anchor_bucket(new_end)),
                    "direct_geometry_length_m": round(direct_length, 6),
                }
            )

    _enforce_canonical_invariants(root, before_incoming_counts)
    return {
        "schema": "junction_connector_canonicalization_v2",
        "ok": True,
        "duplicate_family_count": len(duplicate_families),
        "duplicate_families": duplicate_families,
        "connectors_removed_policy_a": len(removed_ids),
        "removed_connectingRoad_ids": sorted(removed_ids, key=lambda item: (len(item), item)),
        "removed_connections_policy_a": int(removed_connections),
        "removed_roads_policy_a": int(roads_removed),
        "connectors_geometry_normalized_policy_b": len(normalized),
        "normalized_connectors": normalized,
        "turn_family_anchor_groups_policy_d": turn_family_groups,
        "connectors_turn_family_adjusted_policy_d": len(turn_family_adjusted),
        "turn_family_adjusted_connectors": turn_family_adjusted,
        "irregular_fan_anchor_groups_policy_e": policy_e_groups,
        "connectors_irregular_fan_adjusted_policy_e": len(policy_e_adjusted),
        "irregular_fan_adjusted_connectors": policy_e_adjusted,
        "worst_junctions_touched": sorted(touched_junctions, key=lambda item: (len(item), item))[:20],
        "invariants": {
            "max_one_connector_per_incoming_exit": True,
            "no_incoming_road_lost_all_valid_connections": True,
            "distinct_turn_family_connectors_preserved": True,
        },
    }


class TopologyRepair:
    """
    Conservative topology repair:
    - removes invalid link references
    - removes invalid junction connections
    - ensures each road does not reference itself
    """

    @staticmethod
    def _fix_links(root: ET.Element):
        all_ids: Set[str] = {r.get("id") for r in root.findall("road") if r.get("id")}
        junction_ids: Set[str] = {
            j.get("id") for j in root.findall("junction") if j.get("id")
        }
        for road in root.findall("road"):
            rid = road.get("id", "")
            link = road.find("link")
            if link is None:
                continue
            seen = set()
            for tag in ("predecessor", "successor"):
                for e in list(link.findall(tag)):
                    etype = e.get("elementType")
                    eid = e.get("elementId")
                    cpt = e.get("contactPoint", "")
                    if etype == "road":
                        bad = (not eid) or (eid not in all_ids) or (eid == rid)
                    elif etype == "junction":
                        bad = (not eid) or (eid not in junction_ids)
                    else:
                        bad = True
                    key = (tag, etype, eid, cpt)
                    if bad or key in seen:
                        link.remove(e)
                        diff_log.add(
                            "topology_repair",
                            rid,
                            {
                                "fix": "removed_link",
                                "tag": tag,
                                "etype": etype,
                                "eid": eid,
                                "contactPoint": cpt,
                                "reason": "invalid_or_duplicate",
                            },
                        )
                    else:
                        seen.add(key)


    @staticmethod
    def _fix_junctions(root: ET.Element):
        all_ids: Set[str] = {r.get("id") for r in root.findall("road") if r.get("id")}
        for j in root.findall("junction"):
            seen = set()
            for conn in list(j.findall("connection")):
                inc = conn.get("incomingRoad")
                con = conn.get("connectingRoad")
                cpt = conn.get("contactPoint", "")
                bad = (not inc) or (not con) or (inc == con) or (inc not in all_ids) or (con not in all_ids)
                key = (inc, con, cpt)
                if bad or key in seen:
                    j.remove(conn)
                    diff_log.add(
                        "topology_repair",
                        f"junction_{j.get('id', 'UNKNOWN')}",
                        {
                            "fix": "removed_connection",
                            "incomingRoad": inc,
                            "connectingRoad": con,
                            "contactPoint": cpt,
                            "reason": "invalid_or_duplicate",
                        },
                    )
                else:
                    seen.add(key)


    @staticmethod
    def _remove_empty_junctions(root: ET.Element):
        for j in list(root.findall("junction")):
            if not list(j.findall("connection")):
                root.remove(j)

    @staticmethod
    def run(root: ET.Element) -> None:
        TopologyRepair._fix_links(root)
        TopologyRepair._fix_junctions(root)
        TopologyRepair._remove_empty_junctions(root)
        print("✓ TopologyRepair: basic link/junction cleanup applied.")
