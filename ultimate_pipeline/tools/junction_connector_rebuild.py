from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ultimate_pipeline.topology.topology_repair import (
    _fit_arc_geometry,
    _replace_planview_with_arc,
    _replace_planview_with_direct_line,
    _road_end_heading_deg,
    _road_start_end,
)

Point = Tuple[float, float]


def _dist(a: Point, b: Point) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _format_float(value: float) -> str:
    return f"{float(value):.12f}".rstrip("0").rstrip(".")


def _road_length_attr(road: ET.Element, fallback: float = 0.0) -> float:
    try:
        value = float(road.get("length") or fallback)
    except Exception:
        return float(fallback)
    if math.isnan(value) or math.isinf(value):
        return float(fallback)
    return max(0.0, value)


def _road_id(road: ET.Element) -> str:
    return str(road.get("id") or "").strip()


def _is_junction_road(road: Optional[ET.Element]) -> bool:
    if road is None:
        return False
    return str(road.get("junction") or "").strip() not in ("", "-1")


def _roads_by_id(root: ET.Element) -> Dict[str, ET.Element]:
    return {
        _road_id(road): road
        for road in root.findall("./road")
        if _road_id(road)
    }


def _geometry_kind(road: ET.Element) -> str:
    geoms = list(road.findall("./planView/geometry"))
    if not geoms:
        return "missing"
    for geom in geoms:
        if geom.find("paramPoly3") is not None:
            return "paramPoly3"
    first = geoms[0]
    if first.find("line") is not None:
        return "line"
    if first.find("arc") is not None:
        return "arc"
    if first.find("spiral") is not None:
        return "spiral"
    if first.find("poly3") is not None:
        return "poly3"
    return "unknown"


def _connector_points(
    road: ET.Element, contact_point: str = "start"
) -> Optional[Tuple[Point, Point]]:
    endpoints = _road_start_end(road)
    if endpoints is None:
        return None
    start, end = endpoints
    if contact_point == "end":
        return end, start
    return start, end


def _nearest_endpoint(road: ET.Element, reference: Point) -> Optional[Tuple[str, Point, float]]:
    endpoints = _road_start_end(road)
    if endpoints is None:
        return None
    start, end = endpoints
    options = [
        ("start", start, _dist(start, reference)),
        ("end", end, _dist(end, reference)),
    ]
    return min(options, key=lambda item: item[2])


def _successor_road_id(connector_road: ET.Element, incoming_id: str) -> Optional[str]:
    link = connector_road.find("./link")
    if link is None:
        return None
    for successor in link.findall("./successor"):
        if str(successor.get("elementType") or "").strip() != "road":
            continue
        road_id = str(successor.get("elementId") or "").strip()
        if road_id and road_id != incoming_id:
            return road_id
    for predecessor in link.findall("./predecessor"):
        if str(predecessor.get("elementType") or "").strip() != "road":
            continue
        road_id = str(predecessor.get("elementId") or "").strip()
        if road_id and road_id != incoming_id:
            return road_id
    return None


def _iter_connections(root: ET.Element) -> Iterable[Tuple[str, ET.Element]]:
    for junction in root.findall("./junction"):
        junction_id = str(junction.get("id") or "").strip()
        for connection in junction.findall("./connection"):
            yield junction_id, connection


def _connection_metrics(
    root: ET.Element,
    roads: Dict[str, ET.Element],
    *,
    min_gap_m: float,
) -> Dict[str, Any]:
    total = 0
    start_mismatch = 0
    end_mismatch = 0
    lt_1m = 0
    junctions_with_issues = set()
    records: List[Dict[str, Any]] = []

    for junction_id, connection in _iter_connections(root):
        incoming_id = str(connection.get("incomingRoad") or "").strip()
        connector_id = str(connection.get("connectingRoad") or "").strip()
        contact_point = str(connection.get("contactPoint") or "start").strip() or "start"
        incoming = roads.get(incoming_id)
        connector = roads.get(connector_id)
        if incoming is None or connector is None or not _is_junction_road(connector):
            continue
        total += 1

        connector_pair = _connector_points(connector, contact_point)
        incoming_pair = _road_start_end(incoming)
        if connector_pair is None or incoming_pair is None:
            continue
        connector_attach, connector_opposite = connector_pair
        incoming_end = incoming_pair[1]

        outgoing_id = _successor_road_id(connector, incoming_id)
        outgoing = roads.get(outgoing_id or "")
        outgoing_nearest = _nearest_endpoint(outgoing, connector_opposite) if outgoing is not None else None
        end_gap = float("inf") if outgoing_nearest is None else float(outgoing_nearest[2])
        start_gap = _dist(connector_attach, incoming_end)
        length = _road_length_attr(
            connector,
            fallback=_dist(connector_attach, connector_opposite),
        )

        start_issue = start_gap > float(min_gap_m)
        end_issue = end_gap > float(min_gap_m)
        lt_issue = length < 1.0
        if start_issue:
            start_mismatch += 1
        if end_issue:
            end_mismatch += 1
        if lt_issue:
            lt_1m += 1
        if start_issue or end_issue or lt_issue:
            junctions_with_issues.add(junction_id)
        records.append(
            {
                "junction_id": junction_id,
                "incoming_road": incoming_id,
                "connecting_road": connector_id,
                "outgoing_road": outgoing_id,
                "contactPoint": contact_point,
                "start_gap_m": start_gap,
                "end_gap_m": end_gap,
                "length_m": length,
                "geometry": _geometry_kind(connector),
            }
        )

    return {
        "total_connectors_examined": total,
        "connector_start_mismatch": start_mismatch,
        "connector_end_mismatch": end_mismatch,
        "connectors_lt_1m": lt_1m,
        "junctions_with_issues": len(junctions_with_issues),
        "records": records,
    }


def _planview_backup(road: ET.Element) -> Tuple[Optional[str], Optional[ET.Element], Optional[int]]:
    old_length = road.get("length")
    old_plan = road.find("./planView")
    old_plan_copy = copy.deepcopy(old_plan) if old_plan is not None else None
    old_plan_index = list(road).index(old_plan) if old_plan is not None else None
    return old_length, old_plan_copy, old_plan_index


def _restore_planview(
    road: ET.Element,
    old_length: Optional[str],
    old_plan: Optional[ET.Element],
    old_plan_index: Optional[int],
) -> None:
    if old_length is None:
        road.attrib.pop("length", None)
    else:
        road.set("length", old_length)
    current = road.find("./planView")
    if current is not None:
        road.remove(current)
    if old_plan is not None:
        index = old_plan_index if old_plan_index is not None else len(list(road))
        road.insert(max(0, min(index, len(list(road)))), old_plan)


def _write_direct_line(road: ET.Element, start: Point, end: Point) -> bool:
    length = _replace_planview_with_direct_line(road, start, end)
    if length is None:
        return False
    road.set("length", _format_float(length))
    return True


def _write_rebuilt_geometry(
    road: ET.Element,
    *,
    original_kind: str,
    start: Point,
    end: Point,
    start_hdg_rad: float,
) -> Optional[str]:
    if original_kind == "paramPoly3":
        arc = _fit_arc_geometry(start, end, start_hdg_rad)
        if arc is not None:
            curvature, arc_length = arc
            if _replace_planview_with_arc(road, start, start_hdg_rad, curvature, arc_length):
                return "arc"
    if _write_direct_line(road, start, end):
        return "line"
    return None


def _write_degenerate_loop_arc(
    road: ET.Element,
    *,
    start: Point,
    start_hdg_rad: float,
    fallback_length_m: float,
) -> Optional[str]:
    arc_length = max(_road_length_attr(road, fallback=fallback_length_m), 1.0)
    if arc_length < 1.0:
        return None
    curvature = (2.0 * math.pi) / arc_length
    if _replace_planview_with_arc(road, start, start_hdg_rad, curvature, arc_length):
        return "arc"
    return None


def rebuild_junction_connectors(
    root: ET.Element,
    *,
    min_gap_m: float = 2.0,
    verify_gap_m: float = 0.5,
    max_rebuild_length_m: float = 300.0,
    repair_degenerate_loops: bool = False,
) -> Dict[str, Any]:
    roads = _roads_by_id(root)
    before = _connection_metrics(root, roads, min_gap_m=min_gap_m)
    before_by_connector = {
        str(rec["connecting_road"]): rec for rec in before["records"]
    }

    rebuilt_line = 0
    rebuilt_arc = 0
    skipped_degenerate = 0
    skipped_no_outgoing = 0
    skipped_verify_failed = 0
    skipped_too_long = 0
    warnings: List[Dict[str, Any]] = []

    for junction_id, connection in _iter_connections(root):
        incoming_id = str(connection.get("incomingRoad") or "").strip()
        connector_id = str(connection.get("connectingRoad") or "").strip()
        contact_point = str(connection.get("contactPoint") or "start").strip() or "start"
        rec = before_by_connector.get(connector_id)
        if rec is None or float(rec.get("start_gap_m", 0.0)) <= float(min_gap_m):
            continue

        incoming = roads.get(incoming_id)
        connector = roads.get(connector_id)
        if incoming is None or connector is None or not _is_junction_road(connector):
            continue
        incoming_endpoints = _road_start_end(incoming)
        connector_pair = _connector_points(connector, contact_point)
        if incoming_endpoints is None or connector_pair is None:
            skipped_verify_failed += 1
            continue

        incoming_end = incoming_endpoints[1]
        start_hdg_rad = math.radians(_road_end_heading_deg(incoming))
        connector_attach_before, connector_opposite_before = connector_pair
        outgoing_id = _successor_road_id(connector, incoming_id)
        outgoing = roads.get(outgoing_id or "")
        outgoing_nearest = (
            _nearest_endpoint(outgoing, connector_opposite_before)
            if outgoing is not None
            else None
        )
        if outgoing_nearest is None:
            skipped_no_outgoing += 1
            continue
        _out_contact, outgoing_target, _out_gap = outgoing_nearest

        if contact_point == "end":
            rebuild_start = outgoing_target
            rebuild_end = incoming_end
            start_hdg = start_hdg_rad
        else:
            rebuild_start = incoming_end
            rebuild_end = outgoing_target
            start_hdg = start_hdg_rad

        rebuild_length = _dist(rebuild_start, rebuild_end)
        old_length, old_plan, old_plan_index = _planview_backup(connector)
        original_kind = str(rec.get("geometry") or _geometry_kind(connector))
        if rebuild_length < 0.5:
            if not repair_degenerate_loops:
                skipped_degenerate += 1
                continue
            written_kind = _write_degenerate_loop_arc(
                connector,
                start=rebuild_start,
                start_hdg_rad=start_hdg,
                fallback_length_m=max(float(rec.get("length_m", 0.0) or 0.0), 1.0),
            )
            if written_kind is None:
                _restore_planview(connector, old_length, old_plan, old_plan_index)
                skipped_degenerate += 1
                continue
        else:
            if rebuild_length < 1.0:
                skipped_degenerate += 1
                continue
            if rebuild_length > float(max_rebuild_length_m):
                skipped_too_long += 1
                warnings.append(
                    {
                        "junction_id": junction_id,
                        "connecting_road": connector_id,
                        "reason": "rebuild_length_gt_max",
                        "rebuild_length_m": rebuild_length,
                    }
                )
                continue
            written_kind = _write_rebuilt_geometry(
                connector,
                original_kind=original_kind,
                start=rebuild_start,
                end=rebuild_end,
                start_hdg_rad=start_hdg,
            )
        if written_kind is None:
            _restore_planview(connector, old_length, old_plan, old_plan_index)
            skipped_verify_failed += 1
            continue

        connector_after = _connector_points(connector, contact_point)
        if connector_after is None:
            start_gap_after = float("inf")
            end_gap_after = float("inf")
        else:
            connector_attach_after, connector_opposite_after = connector_after
            start_gap_after = _dist(connector_attach_after, incoming_end)
            end_gap_after = _dist(connector_opposite_after, outgoing_target)

        if start_gap_after < float(verify_gap_m) and end_gap_after < float(verify_gap_m):
            if written_kind == "arc":
                rebuilt_arc += 1
            else:
                rebuilt_line += 1
        else:
            _restore_planview(connector, old_length, old_plan, old_plan_index)
            skipped_verify_failed += 1

    after = _connection_metrics(root, _roads_by_id(root), min_gap_m=min_gap_m)
    return {
        "total_connectors_examined": before["total_connectors_examined"],
        "connectors_rebuilt_line": rebuilt_line,
        "connectors_rebuilt_arc": rebuilt_arc,
        "connectors_skipped_degenerate": skipped_degenerate,
        "connectors_skipped_no_outgoing": skipped_no_outgoing,
        "connectors_skipped_verify_failed": skipped_verify_failed,
        "connectors_skipped_too_long": skipped_too_long,
        "connector_start_mismatch_before": before["connector_start_mismatch"],
        "connector_start_mismatch_after": after["connector_start_mismatch"],
        "connector_end_mismatch_before": before["connector_end_mismatch"],
        "connector_end_mismatch_after": after["connector_end_mismatch"],
        "connectors_lt_1m_before": before["connectors_lt_1m"],
        "connectors_lt_1m_after": after["connectors_lt_1m"],
        "junctions_with_issues_before": before["junctions_with_issues"],
        "junctions_with_issues_after": after["junctions_with_issues"],
        "warnings": warnings,
    }


def _report_path(output_path: Path) -> Path:
    stem = output_path.with_suffix("")
    return stem.with_name(f"{stem.name}_rebuild_report.json")


def rebuild_file(
    input_path: Path,
    output_path: Path,
    *,
    min_gap_m: float = 2.0,
    dry_run: bool = False,
    repair_degenerate_loops: bool = False,
) -> Dict[str, Any]:
    input_path = Path(input_path)
    output_path = Path(output_path)
    report_path = _report_path(output_path)
    tree = ET.parse(input_path)
    root = tree.getroot()

    stats = rebuild_junction_connectors(
        root,
        min_gap_m=min_gap_m,
        repair_degenerate_loops=repair_degenerate_loops,
    )
    fix_effective = (
        int(stats["connector_start_mismatch_after"])
        < int(stats["connector_start_mismatch_before"])
    )

    report: Dict[str, Any] = {
        "input": str(input_path),
        "output": str(output_path),
        "min_gap_m": float(min_gap_m),
        **stats,
        "fix_effective": fix_effective,
        "dry_run": bool(dry_run),
        "repair_degenerate_loops": bool(repair_degenerate_loops),
        "input_sha256": _sha256(input_path),
        "output_sha256": None,
    }

    if not dry_run and fix_effective:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tree.write(output_path, encoding="UTF-8", xml_declaration=True)
        report["output_sha256"] = _sha256(output_path)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rebuild displaced OpenDRIVE junction connector planViews."
    )
    parser.add_argument("--input", required=True, type=Path, help="Input XODR path.")
    parser.add_argument("--output", required=True, type=Path, help="Output XODR path.")
    parser.add_argument(
        "--min-gap",
        type=float,
        default=2.0,
        help="Only rebuild connector starts with a gap larger than this many meters.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write only the rebuild report; do not write the output XODR.",
    )
    parser.add_argument(
        "--skip-degenerate-loops",
        action="store_true",
        help=(
            "Skip co-located incoming/outgoing connector endpoints instead of "
            "rewriting them as closed loop arcs."
        ),
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    report = rebuild_file(
        args.input,
        args.output,
        min_gap_m=float(args.min_gap),
        dry_run=bool(args.dry_run),
        repair_degenerate_loops=not bool(args.skip_degenerate_loops),
    )
    print("junction_connector_rebuild summary")
    print(f"  input: {report['input']}")
    print(f"  output: {report['output']}")
    print(
        "  start_mismatch: "
        f"{report['connector_start_mismatch_before']} -> "
        f"{report['connector_start_mismatch_after']}"
    )
    print(
        "  end_mismatch: "
        f"{report['connector_end_mismatch_before']} -> "
        f"{report['connector_end_mismatch_after']}"
    )
    print(f"  rebuilt_line: {report['connectors_rebuilt_line']}")
    print(f"  rebuilt_arc: {report['connectors_rebuilt_arc']}")
    print(f"  fix_effective: {report['fix_effective']}")
    if not bool(report["fix_effective"]):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
