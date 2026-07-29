"""
junction_connector_snap.py
==========================
Snap displaced junction connector roads back to their incoming road endpoints.

This repair is intentionally narrow:
  - Only roads with ``junction != -1`` are touched.
  - Only ``planView/geometry`` element ``x``, ``y``, and ``hdg`` attributes are updated.
  - Geometry lengths, curvature, polynomial coefficients, lane links, lanes, and junction
    definitions are preserved.

Usage:
  python -m ultimate_pipeline.tools.junction_connector_snap \
      --input  path/to/input.xodr \
      --output path/to/output.xodr \
      [--max-gap 2.0]
"""
from __future__ import annotations

import argparse
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

from ultimate_pipeline.diagnostics.audit_xodr_visual_geometry import (
    _build_junction_rows,
    _road_endpoint_pose,
    _roads_by_id,
)
from ultimate_pipeline.quality.check_geometric_continuity import (
    Geometry,
    Pose,
    _pose_for_geometry,
)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _norm_angle(angle: float) -> float:
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle < -math.pi:
        angle += 2.0 * math.pi
    return angle


def _dist_xy(a: Pose, b: Pose) -> float:
    return math.hypot(float(a.x) - float(b.x), float(a.y) - float(b.y))


def _is_connector_road(road: Optional[ET.Element]) -> bool:
    if road is None:
        return False
    return str(road.get("junction") or "").strip() not in ("", "-1")


def _planview_geometry_elements(road: ET.Element) -> List[ET.Element]:
    plan = road.find("./planView")
    if plan is None:
        return []
    geoms = list(plan.findall("./geometry"))
    geoms.sort(key=lambda geom: _safe_float(geom.get("s"), 0.0))
    return geoms


def _geometry_model(geom_el: ET.Element) -> Geometry:
    kind = "unknown"
    curvature = 0.0
    curv_start = 0.0
    curv_end = 0.0
    poly_a = 0.0
    poly_b = 0.0
    poly_c = 0.0
    poly_d = 0.0
    param_a_u = 0.0
    param_b_u = 0.0
    param_c_u = 0.0
    param_d_u = 0.0
    param_a_v = 0.0
    param_b_v = 0.0
    param_c_v = 0.0
    param_d_v = 0.0
    param_p_range = "normalized"

    if geom_el.find("./line") is not None:
        kind = "line"
    elif (arc := geom_el.find("./arc")) is not None:
        kind = "arc"
        curvature = _safe_float(arc.get("curvature"))
    elif (spiral := geom_el.find("./spiral")) is not None:
        kind = "spiral"
        curv_start = _safe_float(spiral.get("curvStart"))
        curv_end = _safe_float(spiral.get("curvEnd"))
    elif (poly := geom_el.find("./poly3")) is not None:
        kind = "poly3"
        poly_a = _safe_float(poly.get("a"))
        poly_b = _safe_float(poly.get("b"))
        poly_c = _safe_float(poly.get("c"))
        poly_d = _safe_float(poly.get("d"))
    elif (param := geom_el.find("./paramPoly3")) is not None:
        kind = "paramPoly3"
        param_a_u = _safe_float(param.get("aU"))
        param_b_u = _safe_float(param.get("bU"))
        param_c_u = _safe_float(param.get("cU"))
        param_d_u = _safe_float(param.get("dU"))
        param_a_v = _safe_float(param.get("aV"))
        param_b_v = _safe_float(param.get("bV"))
        param_c_v = _safe_float(param.get("cV"))
        param_d_v = _safe_float(param.get("dV"))
        param_p_range = (param.get("pRange") or "normalized").strip() or "normalized"

    return Geometry(
        s0=_safe_float(geom_el.get("s"), 0.0),
        x0=_safe_float(geom_el.get("x"), 0.0),
        y0=_safe_float(geom_el.get("y"), 0.0),
        hdg0=_safe_float(geom_el.get("hdg"), 0.0),
        length=max(_safe_float(geom_el.get("length"), 0.0), 0.0),
        kind=kind,
        curvature=curvature,
        curv_start=curv_start,
        curv_end=curv_end,
        poly_a=poly_a,
        poly_b=poly_b,
        poly_c=poly_c,
        poly_d=poly_d,
        param_a_u=param_a_u,
        param_b_u=param_b_u,
        param_c_u=param_c_u,
        param_d_u=param_d_u,
        param_a_v=param_a_v,
        param_b_v=param_b_v,
        param_c_v=param_c_v,
        param_d_v=param_d_v,
        param_p_range=param_p_range,
    )


def _geometry_end_pose(geom_el: ET.Element) -> Pose:
    geom = _geometry_model(geom_el)
    return _pose_for_geometry(geom, float(geom.length))


def _set_geometry_pose(geom_el: ET.Element, pose: Pose) -> None:
    geom_el.set("x", f"{float(pose.x):.12f}")
    geom_el.set("y", f"{float(pose.y):.12f}")
    geom_el.set("hdg", f"{_norm_angle(float(pose.hdg)):.12f}")


def _count_junction_issues(root: ET.Element) -> Dict[str, Any]:
    roads = _roads_by_id(root)
    rows = _build_junction_rows(root, roads)
    start_count = 0
    end_count = 0
    junction_ids_with_issues = set()
    for row in rows:
        junction_id = str(row.get("junction_id") or "")
        if junction_id:
            junction_ids_with_issues.add(junction_id)
        issue = str(row.get("issue") or "")
        if issue == "connector_start_pose_mismatch":
            start_count += 1
        elif issue == "connector_end_pose_mismatch":
            end_count += 1
    return {
        "rows_total": len(rows),
        "connector_start_mismatch": start_count,
        "connector_end_mismatch": end_count,
        "junctions_total": len(root.findall("./junction")),
        "junctions_with_issues": len(junction_ids_with_issues),
    }


def snap_junction_connectors(
    root: ET.Element,
    max_gap_m: float = 2.0,
    rechain_guard_m: float = 50.0,
) -> Dict[str, int]:
    """
    Snap displaced connector-road start poses to the nearest incoming-road endpoint.

    ``rechain_guard_m`` is accepted for API/documentation parity with prior repair tools but
    intentionally unused here. Connector roads are rechained unconditionally after a snap.
    """
    del rechain_guard_m

    roads = _roads_by_id(root)
    connectors_snapped = 0
    geometries_rechained = 0
    connectors_examined = 0
    skipped_missing_incoming = 0
    skipped_missing_connecting = 0
    skipped_missing_geometries = 0
    skipped_missing_pose = 0

    for junction in root.findall("./junction"):
        for connection in junction.findall("./connection"):
            incoming_id = str(connection.get("incomingRoad") or "")
            connecting_id = str(connection.get("connectingRoad") or "")
            incoming = roads.get(incoming_id)
            connecting = roads.get(connecting_id)

            if incoming is None:
                skipped_missing_incoming += 1
                continue
            if connecting is None:
                skipped_missing_connecting += 1
                continue
            if not _is_connector_road(connecting):
                continue

            connectors_examined += 1
            conn_start = _road_endpoint_pose(connecting, "start")
            incoming_start = _road_endpoint_pose(incoming, "start")
            incoming_end = _road_endpoint_pose(incoming, "end")
            if conn_start is None or incoming_start is None or incoming_end is None:
                skipped_missing_pose += 1
                continue

            gap_to_start = _dist_xy(conn_start, incoming_start)
            gap_to_end = _dist_xy(conn_start, incoming_end)
            target_pose = incoming_start if gap_to_start <= gap_to_end else incoming_end
            nearest_gap = min(gap_to_start, gap_to_end)
            if nearest_gap <= max_gap_m:
                continue

            geoms = _planview_geometry_elements(connecting)
            if not geoms:
                skipped_missing_geometries += 1
                continue

            _set_geometry_pose(geoms[0], target_pose)
            prev_end = _geometry_end_pose(geoms[0])
            local_rechains = 0
            for geom_el in geoms[1:]:
                _set_geometry_pose(geom_el, prev_end)
                prev_end = _geometry_end_pose(geom_el)
                local_rechains += 1

            connectors_snapped += 1
            geometries_rechained += local_rechains

    return {
        "connectors_examined": connectors_examined,
        "connectors_snapped": connectors_snapped,
        "geometries_rechained": geometries_rechained,
        "skipped_missing_incoming": skipped_missing_incoming,
        "skipped_missing_connecting": skipped_missing_connecting,
        "skipped_missing_geometries": skipped_missing_geometries,
        "skipped_missing_pose": skipped_missing_pose,
    }


def _report_path(output_path: Path) -> Path:
    if output_path.suffix:
        return output_path.with_suffix("").with_name(
            f"{output_path.with_suffix('').name}.snap_report.json"
        )
    return output_path.with_name(f"{output_path.name}.snap_report.json")


def run_snap(input_path: Path, output_path: Path, max_gap_m: float) -> Dict[str, Any]:
    input_path = Path(input_path).expanduser().resolve()
    output_path = Path(output_path).expanduser().resolve()
    report_path = _report_path(output_path)

    tree = ET.parse(input_path)
    root = tree.getroot()

    before = _count_junction_issues(root)
    repair = snap_junction_connectors(root, max_gap_m=max_gap_m)
    after = _count_junction_issues(root)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_path, encoding="unicode", xml_declaration=True)

    report = {
        "input": str(input_path),
        "output": str(output_path),
        "max_gap_m": float(max_gap_m),
        "connector_start_mismatch_before": before["connector_start_mismatch"],
        "connector_start_mismatch_after": after["connector_start_mismatch"],
        "connector_end_mismatch_before": before["connector_end_mismatch"],
        "connector_end_mismatch_after": after["connector_end_mismatch"],
        "connectors_snapped": repair["connectors_snapped"],
        "geometries_rechained": repair["geometries_rechained"],
        "junctions_total": before["junctions_total"],
        "junctions_with_issues_before": before["junctions_with_issues"],
        "junctions_with_issues_after": after["junctions_with_issues"],
        "connectors_examined": repair["connectors_examined"],
        "skipped_missing_incoming": repair["skipped_missing_incoming"],
        "skipped_missing_connecting": repair["skipped_missing_connecting"],
        "skipped_missing_geometries": repair["skipped_missing_geometries"],
        "skipped_missing_pose": repair["skipped_missing_pose"],
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Snap displaced junction connector roads in an OpenDRIVE XODR file."
    )
    parser.add_argument("--input", required=True, help="Input XODR path.")
    parser.add_argument("--output", required=True, help="Output repaired XODR path.")
    parser.add_argument(
        "--max-gap",
        type=float,
        default=2.0,
        help="Only snap connector starts when the nearest incoming-road endpoint gap exceeds this value in meters.",
    )
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    report = run_snap(
        input_path=Path(args.input),
        output_path=Path(args.output),
        max_gap_m=float(args.max_gap),
    )

    print("junction_connector_snap summary")
    print(f"  input: {report['input']}")
    print(f"  output: {report['output']}")
    print(f"  max_gap_m: {report['max_gap_m']}")
    print(
        "  connector_start_mismatch: "
        f"{report['connector_start_mismatch_before']} -> {report['connector_start_mismatch_after']}"
    )
    print(
        "  connector_end_mismatch: "
        f"{report['connector_end_mismatch_before']} -> {report['connector_end_mismatch_after']}"
    )
    print(f"  connectors_snapped: {report['connectors_snapped']}")
    print(f"  geometries_rechained: {report['geometries_rechained']}")
    print(
        "  junctions_with_issues: "
        f"{report['junctions_with_issues_before']} -> {report['junctions_with_issues_after']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
