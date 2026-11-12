"""Read-only, fail-closed audit of explicit OpenDRIVE lane/road/junction links.

This is an ADDITIVE source checker, not an automatic map repair and not a
release certificate. It validates only links for which the XODR declares an
authoritative target. It intentionally does not invent a successor for an
unlinked lane or decide whether a disconnected road is a legitimate dead end.

The gate is self-contained and can be called on a verified snapshot; its
``input_sha256`` identifies bytes checked and its bounded XML parser rejects
DOCTYPE and entity declarations regardless of document encoding.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET
from xml.parsers import expat

DEFAULT_MAX_BYTES = 256 * 1024 * 1024


def _read_safe_xml(path: Path, max_bytes: int) -> tuple[ET.Element, str]:
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    # A bounded read on one open descriptor prevents stat/read TOCTOU and
    # unbounded allocation when the pathname is swapped during evaluation.
    with path.open("rb") as handle:
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("file exceeds admitted size")
    digest = hashlib.sha256(data).hexdigest()
    detector = expat.ParserCreate()

    def _reject(*_args: object) -> None:
        raise ValueError("DOCTYPE or entity declarations are forbidden")

    detector.StartDoctypeDeclHandler = _reject
    detector.EntityDeclHandler = _reject
    detector.ExternalEntityRefHandler = lambda *_args: 0
    detector.Parse(data, True)
    return ET.fromstring(data), digest


def _finite_float(value: str | None, *, field: str) -> float:
    if value is None:
        raise ValueError(f"missing {field}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"nonfinite {field}")
    return number


def _section_index(road: ET.Element, issues: list[dict[str, Any]]) -> list[ET.Element]:
    sections = road.findall("./lanes/laneSection")
    road_id = road.get("id", "")
    result: list[tuple[float, ET.Element]] = []
    try:
        length = _finite_float(road.get("length"), field="road.length")
        if length <= 0:
            raise ValueError("road.length must be greater than zero")
    except (ValueError, OverflowError) as exc:
        issues.append({"code": "INVALID_ROAD_LENGTH", "road": road_id, "detail": str(exc)})
        length = math.nan
    for section in sections:
        try:
            s = _finite_float(section.get("s"), field="laneSection.s")
            if s < 0 or (math.isfinite(length) and s >= length):
                raise ValueError("laneSection.s outside [0, road.length)")
        except (ValueError, OverflowError) as exc:
            issues.append({"code": "INVALID_LANE_SECTION", "road": road_id, "detail": str(exc)})
            continue
        if any(old_s == s for old_s, _ in result):
            issues.append({"code": "DUPLICATE_LANE_SECTION", "road": road_id, "detail": f"s={s}"})
        result.append((s, section))
    result.sort(key=lambda pair: pair[0])
    if not sections:
        issues.append({"code": "MISSING_LANE_SECTIONS", "road": road_id})
    if sections and result and result[0][0] != 0:
        issues.append({"code": "MISSING_ZERO_SECTION", "road": road_id})
    return [sec for _, sec in result]


def _lanes(section: ET.Element) -> dict[str, ET.Element]:
    return {lane.get("id", ""): lane for lane in section.findall("./left/lane") + section.findall("./right/lane")}


def check_road_boundary_links_strict(
    xodr_path: str | Path,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_issues: int = 10_000,
) -> dict[str, Any]:
    """Verify explicit target existence and correct boundary selection.

    Only established references are checked. A valid-looking standalone road
    may still be a source-level orphan; the report explicitly identifies its
    limited scope so release consumers cannot treat it as a topology proof.
    """
    path = Path(xodr_path)
    report: dict[str, Any] = {
        "gate": "road_boundary_links_strict",
        "scope": "declared_road_and_junction_link_targets_only",
        "status": "BLOCKED_INPUT",
        "ok": False,
        "input_sha256": None,
        "issues": [],
        "num_issues": 0,
        "issue_list_truncated": False,
        "checked_road_links": 0,
        "checked_lane_links": 0,
        "checked_junction_links": 0,
        "drivable_road_count": 0,
        "roads_scanned": 0,
    }
    if max_issues < 1:
        report["issues"] = [{"code": "INVALID_CONFIGURATION", "detail": "max_issues must be >=1"}]
        report["num_issues"] = 1
        return report
    try:
        root, digest = _read_safe_xml(path, max_bytes)
        report["input_sha256"] = digest
    except (OSError, ValueError, expat.ExpatError, ET.ParseError, OverflowError) as exc:
        report["issues"] = [{"code": "BLOCKED_XML_INPUT", "detail": str(exc)}]
        report["num_issues"] = 1
        return report

    issues: list[dict[str, Any]] = []
    if root.tag != "OpenDRIVE":
        issues.append({"code": "INVALID_ROOT", "detail": root.tag})
    roads: dict[str, ET.Element] = {}
    sections: dict[str, list[ET.Element]] = {}
    for road in root.findall("./road"):
        rid = road.get("id", "")
        if not rid:
            issues.append({"code": "MISSING_ROAD_ID"})
            continue
        if rid in roads:
            issues.append({"code": "DUPLICATE_ROAD_ID", "road": rid})
            continue
        roads[rid] = road
        sections[rid] = _section_index(road, issues)
    # Validate lane-ID side semantics without guessing topology. A missing or
    # ambiguous ID cannot be an authoritative predecessor/successor target.
    for rid, sec_list in sections.items():
        for section in sec_list:
            seen: set[str] = set()
            for side_name, sign in (("left", 1), ("right", -1)):
                for lane in section.findall(f"./{side_name}/lane"):
                    lid = lane.get("id", "")
                    try:
                        integer_id = int(lid)
                    except (TypeError, ValueError):
                        issues.append({"code": "INVALID_LANE_ID", "road": rid, "lane": lid})
                        continue
                    if integer_id * sign <= 0:
                        issues.append({"code": "LANE_SIDE_SIGN_MISMATCH", "road": rid, "lane": lid, "side": side_name})
                    if lid in seen:
                        issues.append({"code": "DUPLICATE_LANE_ID", "road": rid, "lane": lid})
                    seen.add(lid)
    report["roads_scanned"] = len(roads)
    if not roads:
        issues.append({"code": "NO_ROADS"})
    report["drivable_road_count"] = sum(
        bool(any(lane.get("type") == "driving" for sec in sections[rid] for lane in _lanes(sec).values()))
        for rid in roads
    )
    if not report["drivable_road_count"]:
        issues.append({"code": "NO_DRIVABLE_ROADS"})

    junction_ids: set[str] = set()
    for junction in root.findall("./junction"):
        jid = junction.get("id", "")
        if not jid:
            issues.append({"code": "MISSING_JUNCTION_ID"})
        elif jid in junction_ids:
            issues.append({"code": "DUPLICATE_JUNCTION_ID", "junction": jid})
        junction_ids.add(jid)
    for rid, road in roads.items():
        for direction in ("predecessor", "successor"):
            edge = road.find(f"./link/{direction}")
            if edge is None:
                continue
            kind, target = edge.get("elementType"), edge.get("elementId", "")
            if kind not in ("road", "junction"):
                issues.append({"code": "INVALID_ROAD_LINK_TYPE", "road": rid, "direction": direction, "type": kind})
            elif kind == "junction" and target not in junction_ids:
                issues.append({"code": "MISSING_TARGET_JUNCTION", "road": rid, "direction": direction, "junction": target})

    # Explicit ordinary road link: validate road, contactPoint, and the target
    # lane ID at the correct boundary. A lane can change sign if the target
    # road orientation is reversed, so neither sign nor exact lane ID matching
    # is inferred or forced.
    for rid, road in roads.items():
        sec_list = sections[rid]
        if not sec_list:
            continue
        link_node = road.find("./link")
        if link_node is None:
            continue
        for direction, source_sec in (("predecessor", sec_list[0]), ("successor", sec_list[-1])):
            edge = link_node.find(direction)
            if edge is None or edge.get("elementType") != "road":
                continue
            report["checked_road_links"] += 1
            tid = edge.get("elementId", "")
            target = roads.get(tid)
            cp = edge.get("contactPoint")
            if target is None:
                issues.append({"code": "MISSING_TARGET_ROAD", "road": rid, "direction": direction, "target": tid})
                continue
            if cp not in ("start", "end"):
                issues.append({"code": "MISSING_OR_INVALID_CONTACT_POINT", "road": rid, "direction": direction, "target": tid, "contactPoint": cp})
                continue
            target_secs = sections[tid]
            if not target_secs:
                issues.append({"code": "TARGET_HAS_NO_LANE_SECTIONS", "road": rid, "target": tid})
                continue
            target_lanes = _lanes(target_secs[0 if cp == "start" else -1])
            for lane in _lanes(source_sec).values():
                if lane.get("type") != "driving":
                    continue
                lane_link = lane.find(f"./link/{direction}")
                if lane_link is None:
                    continue  # Do not manufacture links or declare every lane terminal mandatory.
                report["checked_lane_links"] += 1
                lid = lane_link.get("id", "")
                target_lane = target_lanes.get(lid)
                if target_lane is None:
                    issues.append({"code": "MISSING_CROSSROAD_LANE", "road": rid, "lane": lane.get("id"), "target_road": tid, "target_lane": lid, "direction": direction, "contactPoint": cp})
                elif target_lane.get("type") != "driving":
                    issues.append({"code": "NONDRIVABLE_CROSSROAD_TARGET", "road": rid, "lane": lane.get("id"), "target_road": tid, "target_lane": lid, "target_type": target_lane.get("type"), "direction": direction})

    # Junction laneLink mappings use the incoming road's junction-contacting
    # boundary, and the connecting road's explicit connection contactPoint.
    for junction in root.findall("./junction"):
        jid = junction.get("id", "")
        for conn in junction.findall("./connection"):
            incoming_id, connecting_id = conn.get("incomingRoad", ""), conn.get("connectingRoad", "")
            incoming, connecting = roads.get(incoming_id), roads.get(connecting_id)
            cp = conn.get("contactPoint")
            report["checked_junction_links"] += 1
            if incoming is None or connecting is None:
                issues.append({"code": "MISSING_JUNCTION_ROAD", "junction": jid, "incoming": incoming_id, "connecting": connecting_id})
                continue
            if cp not in ("start", "end"):
                issues.append({"code": "INVALID_JUNCTION_CONTACT_POINT", "junction": jid, "connecting": connecting_id, "contactPoint": cp})
                continue
            sides = []
            incoming_link = incoming.find("./link")
            if incoming_link is not None:
                for direction in ("predecessor", "successor"):
                    edge = incoming_link.find(direction)
                    if edge is not None and edge.get("elementType") == "junction" and edge.get("elementId") == jid:
                        sides.append(direction)
            if len(sides) != 1:
                issues.append({"code": "UNVERIFIED_INCOMING_JUNCTION_SIDE", "junction": jid, "incoming": incoming_id, "side_candidates": sides})
                continue
            incoming_sections = sections[incoming_id]
            connecting_sections = sections[connecting_id]
            if not incoming_sections or not connecting_sections:
                issues.append({"code": "JUNCTION_ROAD_LANE_SECTIONS_MISSING", "junction": jid})
                continue
            source_lanes = _lanes(incoming_sections[0 if sides[0] == "predecessor" else -1])
            target_lanes = _lanes(connecting_sections[0 if cp == "start" else -1])
            for ll in conn.findall("./laneLink"):
                report["checked_lane_links"] += 1
                frm, to = ll.get("from", ""), ll.get("to", "")
                source_lane, target_lane = source_lanes.get(frm), target_lanes.get(to)
                if source_lane is None:
                    issues.append({"code": "MISSING_JUNCTION_FROM_LANE", "junction": jid, "incoming": incoming_id, "lane": frm})
                elif source_lane.get("type") != "driving":
                    issues.append({"code": "NONDRIVABLE_JUNCTION_FROM", "junction": jid, "incoming": incoming_id, "lane": frm})
                if target_lane is None:
                    issues.append({"code": "MISSING_JUNCTION_TO_LANE", "junction": jid, "connecting": connecting_id, "lane": to})
                elif target_lane.get("type") != "driving":
                    issues.append({"code": "NONDRIVABLE_JUNCTION_TO", "junction": jid, "connecting": connecting_id, "lane": to})

    report["num_issues"] = len(issues)
    report["issues"] = issues[:max_issues]
    report["issue_list_truncated"] = len(issues) > max_issues
    report["ok"] = not issues
    report["status"] = "PASS" if not issues else "FAIL"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xodr", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    args = parser.parse_args()
    report = check_road_boundary_links_strict(args.xodr, max_bytes=args.max_bytes)
    encoded = json.dumps(report, sort_keys=True, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded + "\n", encoding="utf-8")
    else:
        print(encoded)
    return 0 if report["ok"] is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
