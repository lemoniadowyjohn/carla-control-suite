from __future__ import annotations

import argparse
import copy
import json
import math
import shutil
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ultimate_pipeline.quality.check_geometric_continuity import (
    Pose,
    _norm_angle,
    _parse_geometries,
    _pose_at_s,
)


Point = Tuple[float, float]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        out = float(value)
    except Exception:
        return float(default)
    if math.isnan(out) or math.isinf(out):
        return float(default)
    return out


def _safe_id_sort(value: str) -> Tuple[int, Any]:
    try:
        return (0, int(str(value)))
    except Exception:
        return (1, str(value))


def _dist(a: Pose, b: Pose) -> float:
    return math.hypot(float(a.x) - float(b.x), float(a.y) - float(b.y))


def _road_planview_length(road: ET.Element) -> float:
    declared = _safe_float(road.get("length"), 0.0)
    geoms, _warnings = _parse_geometries(road)
    if not geoms:
        return max(0.0, declared)
    geom_extent = max(float(g.s0) + max(float(g.length), 0.0) for g in geoms)
    return max(declared, geom_extent)


def _road_pose(road: ET.Element, contact_point: str) -> Optional[Pose]:
    geoms, _warnings = _parse_geometries(road)
    if not geoms:
        return None
    s_abs = 0.0 if str(contact_point).strip() == "start" else _road_planview_length(road)
    pose, _eval_warnings = _pose_at_s(geoms, s_abs)
    return Pose(float(pose.x), float(pose.y), float(_norm_angle(pose.hdg)))


def _road_endpoints(road: ET.Element) -> Optional[Dict[str, Pose]]:
    start = _road_pose(road, "start")
    end = _road_pose(road, "end")
    if start is None or end is None:
        return None
    return {"start": start, "end": end}


def _nearest_endpoint(road: ET.Element, reference: Pose) -> Optional[Tuple[str, Pose, float]]:
    endpoints = _road_endpoints(road)
    if endpoints is None:
        return None
    items = [
        ("start", endpoints["start"], _dist(reference, endpoints["start"])),
        ("end", endpoints["end"], _dist(reference, endpoints["end"])),
    ]
    return min(items, key=lambda item: item[2])


def _connector_geometry_kind(road: ET.Element) -> str:
    plan = road.find("planView")
    if plan is None:
        return "missing"
    kinds: List[str] = []
    for geom in plan.findall("geometry"):
        if geom.find("paramPoly3") is not None:
            kinds.append("paramPoly3")
        elif geom.find("arc") is not None:
            kinds.append("arc")
        elif geom.find("line") is not None:
            kinds.append("line")
        elif geom.find("poly3") is not None:
            kinds.append("poly3")
        elif geom.find("spiral") is not None:
            kinds.append("spiral")
        else:
            kinds.append("unknown")
    if "paramPoly3" in kinds:
        return "paramPoly3"
    if kinds:
        return kinds[0]
    return "empty"


def _find_incoming_anchor(
    *,
    junction_id: str,
    incoming_road: ET.Element,
    connector_attach_pose: Pose,
) -> Tuple[Optional[Pose], str]:
    link = incoming_road.find("link")
    if link is not None:
        for successor in link.findall("successor"):
            if (
                str(successor.get("elementType") or "").strip() == "junction"
                and str(successor.get("elementId") or "").strip() == str(junction_id)
            ):
                return _road_pose(incoming_road, "end"), "incoming_successor_junction"
        for predecessor in link.findall("predecessor"):
            if (
                str(predecessor.get("elementType") or "").strip() == "junction"
                and str(predecessor.get("elementId") or "").strip() == str(junction_id)
            ):
                return _road_pose(incoming_road, "start"), "incoming_predecessor_junction"

    nearest = _nearest_endpoint(incoming_road, connector_attach_pose)
    if nearest is None:
        return None, "incoming_no_planview"
    contact, pose, _gap = nearest
    return pose, f"incoming_nearest_{contact}"


def _iter_connector_road_links(connector_road: ET.Element) -> Iterable[Tuple[str, ET.Element]]:
    link = connector_road.find("link")
    if link is None:
        return []
    out: List[Tuple[str, ET.Element]] = []
    for tag in ("successor", "predecessor"):
        for el in link.findall(tag):
            out.append((tag, el))
    return out


def _find_outgoing_anchor(
    *,
    roads_by_id: Dict[str, ET.Element],
    incoming_id: str,
    connector_road: ET.Element,
    connector_contact_point: str,
    connector_opposite_pose: Pose,
) -> Tuple[Optional[Pose], str, Optional[str]]:
    preferred_tags = (
        ("successor", "predecessor")
        if connector_contact_point == "start"
        else ("predecessor", "successor")
    )
    road_links = [
        (tag, el)
        for tag, el in _iter_connector_road_links(connector_road)
        if str(el.get("elementType") or "").strip() == "road"
        and str(el.get("elementId") or "").strip()
        and str(el.get("elementId") or "").strip() in roads_by_id
        and str(el.get("elementId") or "").strip() != str(incoming_id)
    ]
    road_links.sort(
        key=lambda item: (
            preferred_tags.index(item[0]) if item[0] in preferred_tags else 99,
            _safe_id_sort(str(item[1].get("elementId") or "")),
        )
    )
    if not road_links:
        return None, "outgoing_road_link_missing", None

    tag, el = road_links[0]
    target_id = str(el.get("elementId") or "").strip()
    target_road = roads_by_id[target_id]

    nearest = _nearest_endpoint(target_road, connector_opposite_pose)
    if nearest is None:
        return None, "outgoing_no_planview", target_id
    nearest_contact, nearest_pose, nearest_gap = nearest

    link_contact = str(el.get("contactPoint") or "").strip()
    if link_contact in ("start", "end"):
        linked_pose = _road_pose(target_road, link_contact)
        if linked_pose is not None:
            linked_gap = _dist(connector_opposite_pose, linked_pose)
            if linked_gap <= nearest_gap + 0.5:
                return linked_pose, f"outgoing_{tag}_link_{link_contact}", target_id

    return nearest_pose, f"outgoing_{tag}_nearest_{nearest_contact}", target_id


def _replace_planview_with_direct_line(road: ET.Element, start: Pose, end: Pose) -> None:
    dx = float(end.x) - float(start.x)
    dy = float(end.y) - float(start.y)
    length = math.hypot(dx, dy)
    hdg = math.atan2(dy, dx) if length > 1e-12 else float(start.hdg)

    plan = road.find("planView")
    if plan is None:
        plan = ET.SubElement(road, "planView")
    plan.clear()

    geom = ET.SubElement(
        plan,
        "geometry",
        {
            "s": "0.000000000000",
            "x": f"{float(start.x):.12f}",
            "y": f"{float(start.y):.12f}",
            "hdg": f"{float(_norm_angle(hdg)):.12f}",
            "length": f"{float(length):.12f}",
        },
    )
    ET.SubElement(geom, "line")
    road.set("length", f"{float(length):.12f}")


def _arc_endpoint(start: Pose, curvature: float, length: float) -> Pose:
    k = float(curvature)
    l = float(length)
    if abs(k) < 1e-12:
        return Pose(
            float(start.x) + l * math.cos(float(start.hdg)),
            float(start.y) + l * math.sin(float(start.hdg)),
            float(_norm_angle(start.hdg)),
        )
    hdg = float(start.hdg)
    dx_local = math.sin(k * l) / k
    dy_local = (1.0 - math.cos(k * l)) / k
    x = float(start.x) + math.cos(hdg) * dx_local - math.sin(hdg) * dy_local
    y = float(start.y) + math.sin(hdg) * dx_local + math.cos(hdg) * dy_local
    return Pose(float(x), float(y), float(_norm_angle(hdg + k * l)))


def _fit_arc_geometry(
    start: Pose,
    end: Pose,
    start_hdg_rad: float,
    *,
    max_abs_curvature: float = 1.0,
) -> Optional[Tuple[float, float]]:
    dx = float(end.x) - float(start.x)
    dy = float(end.y) - float(start.y)
    chord = math.hypot(dx, dy)
    if chord <= 1e-6:
        return None

    cos_h = math.cos(float(start_hdg_rad))
    sin_h = math.sin(float(start_hdg_rad))
    x_local = cos_h * dx + sin_h * dy
    y_local = -sin_h * dx + cos_h * dy
    if abs(y_local) <= 1e-6:
        return None

    curvature = 2.0 * y_local / max((x_local * x_local + y_local * y_local), 1e-12)
    if abs(curvature) <= 1e-12 or abs(curvature) > float(max_abs_curvature):
        return None

    phi = math.atan2(curvature * x_local, 1.0 - curvature * y_local)
    length = phi / curvature
    if length <= 1e-6:
        phi = phi + (2.0 * math.pi if curvature > 0.0 else -2.0 * math.pi)
        length = phi / curvature
    if length <= 1e-6:
        return None

    # Reject long-way-around arcs for connector roads; a line fallback is safer.
    if length > max(chord * 3.0, chord + 25.0):
        return None

    endpoint = _arc_endpoint(
        Pose(float(start.x), float(start.y), float(start_hdg_rad)),
        curvature,
        length,
    )
    if math.hypot(float(endpoint.x) - float(end.x), float(endpoint.y) - float(end.y)) > 1e-5:
        return None
    return float(curvature), float(length)


def _replace_planview_with_arc(
    road: ET.Element,
    start: Pose,
    hdg: float,
    curvature: float,
    length: float,
) -> None:
    plan = road.find("planView")
    if plan is None:
        plan = ET.SubElement(road, "planView")
    plan.clear()
    geom = ET.SubElement(
        plan,
        "geometry",
        {
            "s": "0.000000000000",
            "x": f"{float(start.x):.12f}",
            "y": f"{float(start.y):.12f}",
            "hdg": f"{float(_norm_angle(hdg)):.12f}",
            "length": f"{float(length):.12f}",
        },
    )
    ET.SubElement(geom, "arc", {"curvature": f"{float(curvature):.12f}"})
    road.set("length", f"{float(length):.12f}")


def _restore_road_planview(
    road: ET.Element,
    *,
    old_length: Optional[str],
    old_plan: Optional[ET.Element],
    old_plan_index: Optional[int],
) -> None:
    if old_length is None:
        road.attrib.pop("length", None)
    else:
        road.set("length", old_length)

    current_plan = road.find("planView")
    if current_plan is not None:
        road.remove(current_plan)
    if old_plan is not None:
        idx = old_plan_index if old_plan_index is not None else len(list(road))
        road.insert(max(0, min(idx, len(list(road)))), old_plan)


def _connector_endpoint_poses(
    connector_road: ET.Element,
    connector_contact_point: str,
) -> Optional[Tuple[Pose, Pose]]:
    endpoints = _road_endpoints(connector_road)
    if endpoints is None:
        return None
    if connector_contact_point == "end":
        return endpoints["end"], endpoints["start"]
    return endpoints["start"], endpoints["end"]


def _write_rebuild_geometry(
    *,
    connector_road: ET.Element,
    original_kind: str,
    plan_start: Pose,
    plan_end: Pose,
    start_hdg: float,
    max_abs_curvature: float,
) -> str:
    if original_kind == "paramPoly3":
        arc = _fit_arc_geometry(
            plan_start,
            plan_end,
            start_hdg,
            max_abs_curvature=max_abs_curvature,
        )
        if arc is not None:
            curvature, length = arc
            _replace_planview_with_arc(
                connector_road, plan_start, start_hdg, curvature, length
            )
            return "arc"

    _replace_planview_with_direct_line(connector_road, plan_start, plan_end)
    return "line"


def _summarize_worst_junctions(records: List[Dict[str, Any]], limit: int = 10) -> List[Dict[str, Any]]:
    by_junction: Dict[str, Dict[str, Any]] = {}
    for rec in records:
        jid = str(rec.get("junction_id") or "")
        item = by_junction.setdefault(
            jid,
            {
                "junction_id": jid,
                "connections": 0,
                "start_gap_issues": 0,
                "end_gap_issues": 0,
                "max_start_gap_m": 0.0,
                "max_end_gap_m": 0.0,
            },
        )
        item["connections"] += 1
        start_gap = float(rec.get("start_gap_m", 0.0) or 0.0)
        end_gap = float(rec.get("end_gap_m", 0.0) or 0.0)
        if bool(rec.get("start_gap_issue", False)):
            item["start_gap_issues"] += 1
        if bool(rec.get("end_gap_issue", False)):
            item["end_gap_issues"] += 1
        item["max_start_gap_m"] = max(float(item["max_start_gap_m"]), start_gap)
        item["max_end_gap_m"] = max(float(item["max_end_gap_m"]), end_gap)
    rows = list(by_junction.values())
    rows.sort(
        key=lambda item: (
            int(item["start_gap_issues"]) + int(item["end_gap_issues"]),
            float(item["max_start_gap_m"]),
            float(item["max_end_gap_m"]),
            _safe_id_sort(str(item["junction_id"])),
        ),
        reverse=True,
    )
    return rows[:limit]


def rebuild_displaced_junction_connectors_on_root(
    root: ET.Element,
    *,
    start_gap_threshold_m: float = 2.0,
    max_after_gap_m: float = 0.5,
    max_abs_curvature: float = 1.0,
    max_examples: int = 25,
) -> Dict[str, Any]:
    roads_by_id: Dict[str, ET.Element] = {
        str(road.get("id") or "").strip(): road
        for road in root.findall("road")
        if str(road.get("id") or "").strip()
    }
    processed_connectors: set[str] = set()
    before_records: List[Dict[str, Any]] = []
    after_records: List[Dict[str, Any]] = []
    examples: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    stats: Dict[str, Any] = {
        "schema": "junction_connector_rebuild_v1",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "start_gap_threshold_m": float(start_gap_threshold_m),
        "max_after_gap_m": float(max_after_gap_m),
        "max_abs_curvature": float(max_abs_curvature),
        "total_connectors": 0,
        "duplicate_connector_refs": 0,
        "start_gap_over_threshold_before": 0,
        "end_gap_over_tolerance_before": 0,
        "start_gap_over_threshold_after": 0,
        "end_gap_over_tolerance_after": 0,
        "attempted": 0,
        "rebuilt": 0,
        "reverted": 0,
        "skipped": 0,
        "missing_anchor": 0,
        "geometry_before": {},
        "geometry_written": {},
        "examples": examples,
        "errors": errors,
    }

    for junction in sorted(root.findall("junction"), key=lambda j: _safe_id_sort(str(j.get("id") or ""))):
        junction_id = str(junction.get("id") or "").strip()
        connections = sorted(
            junction.findall("connection"),
            key=lambda c: (
                _safe_id_sort(str(c.get("connectingRoad") or "")),
                _safe_id_sort(str(c.get("incomingRoad") or "")),
                str(c.get("id") or ""),
            ),
        )
        for conn in connections:
            incoming_id = str(conn.get("incomingRoad") or "").strip()
            connector_id = str(conn.get("connectingRoad") or "").strip()
            connector_contact_point = str(conn.get("contactPoint") or "start").strip()
            if connector_contact_point not in ("start", "end"):
                connector_contact_point = "start"

            if not incoming_id or not connector_id:
                stats["skipped"] += 1
                stats["missing_anchor"] += 1
                errors.append(
                    {
                        "junction_id": junction_id,
                        "incoming_road": incoming_id,
                        "connecting_road": connector_id,
                        "reason": "missing_connection_road_id",
                    }
                )
                continue
            if connector_id in processed_connectors:
                stats["duplicate_connector_refs"] += 1
                continue
            processed_connectors.add(connector_id)
            stats["total_connectors"] += 1

            incoming_road = roads_by_id.get(incoming_id)
            connector_road = roads_by_id.get(connector_id)
            if incoming_road is None or connector_road is None:
                stats["skipped"] += 1
                stats["missing_anchor"] += 1
                errors.append(
                    {
                        "junction_id": junction_id,
                        "incoming_road": incoming_id,
                        "connecting_road": connector_id,
                        "reason": "missing_incoming_or_connector_road",
                    }
                )
                continue

            connector_poses = _connector_endpoint_poses(
                connector_road, connector_contact_point
            )
            if connector_poses is None:
                stats["skipped"] += 1
                stats["missing_anchor"] += 1
                errors.append(
                    {
                        "junction_id": junction_id,
                        "incoming_road": incoming_id,
                        "connecting_road": connector_id,
                        "reason": "connector_missing_planview",
                    }
                )
                continue
            connector_attach_before, connector_opposite_before = connector_poses

            incoming_anchor, incoming_anchor_source = _find_incoming_anchor(
                junction_id=junction_id,
                incoming_road=incoming_road,
                connector_attach_pose=connector_attach_before,
            )
            outgoing_anchor, outgoing_anchor_source, outgoing_id = _find_outgoing_anchor(
                roads_by_id=roads_by_id,
                incoming_id=incoming_id,
                connector_road=connector_road,
                connector_contact_point=connector_contact_point,
                connector_opposite_pose=connector_opposite_before,
            )
            if incoming_anchor is None or outgoing_anchor is None:
                stats["skipped"] += 1
                stats["missing_anchor"] += 1
                errors.append(
                    {
                        "junction_id": junction_id,
                        "incoming_road": incoming_id,
                        "connecting_road": connector_id,
                        "reason": (
                            "missing_anchor:"
                            f"incoming={incoming_anchor_source},"
                            f"outgoing={outgoing_anchor_source}"
                        ),
                    }
                )
                continue

            start_gap_before = _dist(connector_attach_before, incoming_anchor)
            end_gap_before = _dist(connector_opposite_before, outgoing_anchor)
            original_kind = _connector_geometry_kind(connector_road)
            stats["geometry_before"][original_kind] = (
                int(stats["geometry_before"].get(original_kind, 0)) + 1
            )
            before_record = {
                "junction_id": junction_id,
                "incoming_road": incoming_id,
                "connecting_road": connector_id,
                "outgoing_road": outgoing_id,
                "contactPoint": connector_contact_point,
                "start_gap_m": float(start_gap_before),
                "end_gap_m": float(end_gap_before),
                "start_gap_issue": bool(start_gap_before > float(start_gap_threshold_m)),
                "end_gap_issue": bool(end_gap_before > float(max_after_gap_m)),
                "geometry_before": original_kind,
                "incoming_anchor_source": incoming_anchor_source,
                "outgoing_anchor_source": outgoing_anchor_source,
            }
            before_records.append(before_record)
            if before_record["start_gap_issue"]:
                stats["start_gap_over_threshold_before"] += 1
            if before_record["end_gap_issue"]:
                stats["end_gap_over_tolerance_before"] += 1

            if start_gap_before <= float(start_gap_threshold_m):
                stats["skipped"] += 1
                after_records.append(before_record)
                continue

            stats["attempted"] += 1
            old_length = connector_road.get("length")
            old_plan = connector_road.find("planView")
            old_plan_copy = copy.deepcopy(old_plan) if old_plan is not None else None
            old_plan_index = (
                list(connector_road).index(old_plan) if old_plan is not None else None
            )

            if connector_contact_point == "end":
                plan_start = outgoing_anchor
                plan_end = incoming_anchor
                start_hdg = float(outgoing_anchor.hdg)
            else:
                plan_start = incoming_anchor
                plan_end = outgoing_anchor
                start_hdg = float(incoming_anchor.hdg)

            written_kind = _write_rebuild_geometry(
                connector_road=connector_road,
                original_kind=original_kind,
                plan_start=plan_start,
                plan_end=plan_end,
                start_hdg=start_hdg,
                max_abs_curvature=float(max_abs_curvature),
            )
            stats["geometry_written"][written_kind] = (
                int(stats["geometry_written"].get(written_kind, 0)) + 1
            )

            connector_after = _connector_endpoint_poses(
                connector_road, connector_contact_point
            )
            if connector_after is None:
                start_gap_after = float("inf")
                end_gap_after = float("inf")
            else:
                connector_attach_after, connector_opposite_after = connector_after
                start_gap_after = _dist(connector_attach_after, incoming_anchor)
                end_gap_after = _dist(connector_opposite_after, outgoing_anchor)

            verified = (
                start_gap_after <= float(max_after_gap_m)
                and end_gap_after <= float(max_after_gap_m)
            )
            if verified:
                stats["rebuilt"] += 1
                after_record = dict(before_record)
                after_record.update(
                    {
                        "start_gap_m": float(start_gap_after),
                        "end_gap_m": float(end_gap_after),
                        "start_gap_issue": bool(
                            start_gap_after > float(start_gap_threshold_m)
                        ),
                        "end_gap_issue": bool(end_gap_after > float(max_after_gap_m)),
                        "geometry_written": written_kind,
                        "action": "rebuilt",
                    }
                )
                after_records.append(after_record)
                if len(examples) < int(max_examples):
                    examples.append(
                        {
                            "junction_id": junction_id,
                            "incoming_road": incoming_id,
                            "connecting_road": connector_id,
                            "outgoing_road": outgoing_id,
                            "geometry_before": original_kind,
                            "geometry_written": written_kind,
                            "start_gap_before_m": float(start_gap_before),
                            "end_gap_before_m": float(end_gap_before),
                            "start_gap_after_m": float(start_gap_after),
                            "end_gap_after_m": float(end_gap_after),
                        }
                    )
            else:
                _restore_road_planview(
                    connector_road,
                    old_length=old_length,
                    old_plan=old_plan_copy,
                    old_plan_index=old_plan_index,
                )
                stats["reverted"] += 1
                after_record = dict(before_record)
                after_record["action"] = "reverted"
                after_record["attempted_start_gap_after_m"] = float(start_gap_after)
                after_record["attempted_end_gap_after_m"] = float(end_gap_after)
                after_records.append(after_record)

    for rec in after_records:
        if float(rec.get("start_gap_m", 0.0) or 0.0) > float(start_gap_threshold_m):
            stats["start_gap_over_threshold_after"] += 1
        if float(rec.get("end_gap_m", 0.0) or 0.0) > float(max_after_gap_m):
            stats["end_gap_over_tolerance_after"] += 1

    before_sorted = sorted(
        before_records,
        key=lambda item: (
            float(item.get("start_gap_m", 0.0) or 0.0),
            float(item.get("end_gap_m", 0.0) or 0.0),
        ),
        reverse=True,
    )
    after_sorted = sorted(
        after_records,
        key=lambda item: (
            float(item.get("start_gap_m", 0.0) or 0.0),
            float(item.get("end_gap_m", 0.0) or 0.0),
        ),
        reverse=True,
    )
    stats["worst_before"] = before_sorted[: int(max_examples)]
    stats["worst_after"] = after_sorted[: int(max_examples)]
    stats["worst_junctions_before"] = _summarize_worst_junctions(before_records)
    stats["worst_junctions_after"] = _summarize_worst_junctions(after_records)
    stats["ok"] = bool(
        int(stats["reverted"]) == 0
        and int(stats["missing_anchor"]) == 0
        and int(stats["start_gap_over_threshold_after"]) == 0
    )
    return stats


def _risk_payload_from_rebuild(report: Dict[str, Any]) -> Dict[str, Any]:
    failed = int(report.get("start_gap_over_threshold_after", 0) or 0) + int(
        report.get("end_gap_over_tolerance_after", 0) or 0
    )
    return {
        "schema": "junction_connector_risk_v1",
        "source": "junction_connector_rebuild",
        "ok": failed == 0,
        "failed_check_count": failed,
        "n_failed_checks": failed,
        "overlap_pair_count": 0,
        "start_gap_over_threshold_after": int(
            report.get("start_gap_over_threshold_after", 0) or 0
        ),
        "end_gap_over_tolerance_after": int(
            report.get("end_gap_over_tolerance_after", 0) or 0
        ),
        "rebuilt": int(report.get("rebuilt", 0) or 0),
        "reverted": int(report.get("reverted", 0) or 0),
        "worst_junction_sample": report.get("worst_junctions_after", [])[:10],
    }


def rebuild_displaced_junction_connectors_in_file(
    input_xodr: str | Path,
    output_xodr: str | Path,
    *,
    report_path: str | Path | None = None,
    risk_report_path: str | Path | None = None,
    start_gap_threshold_m: float = 2.0,
    max_after_gap_m: float = 0.5,
    max_abs_curvature: float = 1.0,
) -> Dict[str, Any]:
    input_path = Path(input_xodr)
    output_path = Path(output_xodr)
    tree = ET.parse(input_path)
    root = tree.getroot()
    report = rebuild_displaced_junction_connectors_on_root(
        root,
        start_gap_threshold_m=start_gap_threshold_m,
        max_after_gap_m=max_after_gap_m,
        max_abs_curvature=max_abs_curvature,
    )
    report["input_xodr"] = str(input_path)
    report["output_xodr"] = str(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if int(report.get("rebuilt", 0) or 0) > 0 or input_path.resolve() == output_path.resolve():
        tree.write(output_path, encoding="UTF-8", xml_declaration=True)
    else:
        shutil.copy2(input_path, output_path)

    rp = Path(report_path) if report_path is not None else None
    risk_path = Path(risk_report_path) if risk_report_path is not None else None
    if rp is not None:
        report["report_path"] = str(rp)
    if risk_path is not None:
        report["risk_report_path"] = str(risk_path)

    if rp is not None:
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(
            json.dumps(report, indent=2, ensure_ascii=True, sort_keys=True),
            encoding="utf-8",
        )

    if risk_path is not None:
        risk = _risk_payload_from_rebuild(report)
        risk_path.parent.mkdir(parents=True, exist_ok=True)
        risk_path.write_text(
            json.dumps(risk, indent=2, ensure_ascii=True, sort_keys=True),
            encoding="utf-8",
        )
    return report


def _parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild displaced OpenDRIVE junction connector planViews by resetting "
            "both connector endpoints in one operation."
        )
    )
    parser.add_argument("--input", required=True, type=Path, help="Input XODR path")
    parser.add_argument("--output", required=True, type=Path, help="Output XODR path")
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="JSON rebuild report path",
    )
    parser.add_argument(
        "--risk-report",
        type=Path,
        default=None,
        help="Optional junction_connector_risk.json-compatible report path",
    )
    parser.add_argument(
        "--start-gap-threshold-m",
        type=float,
        default=2.0,
        help="Only rebuild connectors whose incoming/start gap exceeds this threshold",
    )
    parser.add_argument(
        "--max-after-gap-m",
        type=float,
        default=0.5,
        help="Revert a rebuilt connector unless both endpoint gaps verify below this value",
    )
    parser.add_argument(
        "--max-abs-curvature",
        type=float,
        default=1.0,
        help="Maximum absolute curvature accepted for paramPoly3-to-arc rebuilds",
    )
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    report = rebuild_displaced_junction_connectors_in_file(
        args.input,
        args.output,
        report_path=args.report,
        risk_report_path=args.risk_report,
        start_gap_threshold_m=args.start_gap_threshold_m,
        max_after_gap_m=args.max_after_gap_m,
        max_abs_curvature=args.max_abs_curvature,
    )
    print(
        "[junction_connector_rebuild] "
        f"connectors={report['total_connectors']} "
        f"attempted={report['attempted']} "
        f"rebuilt={report['rebuilt']} "
        f"reverted={report['reverted']} "
        f"start_gap_before={report['start_gap_over_threshold_before']} "
        f"start_gap_after={report['start_gap_over_threshold_after']}"
    )
    return 0 if bool(report.get("ok", False)) else 2


if __name__ == "__main__":
    raise SystemExit(main())
