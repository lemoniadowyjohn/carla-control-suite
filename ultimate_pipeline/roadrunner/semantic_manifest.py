from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .exceptions import RoadRunnerContractError
from .models import (
    AuthorityClass,
    SemanticDiffSummary,
    validate_identifier,
    validate_sha256,
)

_LANE_DIRECTIONS = frozenset({"forward", "backward", "all"})
_PLANVIEW_TYPES = frozenset({"line", "spiral", "arc", "poly3", "paramPoly3"})


@dataclass(frozen=True)
class LaneDiffEntry:
    road_id: str
    lane_section_s: float
    lane_id: int
    lane_type: str
    direction: str
    width: float | None
    status: str  # "unchanged", "added", "removed", "modified"


@dataclass(frozen=True)
class RoadDiffEntry:
    road_id: str
    junction_id: str | None
    status: str
    length_delta: float | None = None
    geometry_counts: Mapping[str, int] = field(default_factory=dict)
    geometry_delta: Mapping[str, int] = field(default_factory=dict)
    lane_changes: int = 0


@dataclass(frozen=True)
class JunctionDiffEntry:
    junction_id: str
    status: str
    connection_count_parent: int = 0
    connection_count_candidate: int = 0


@dataclass(frozen=True)
class SignalDiffEntry:
    signal_id: str
    status: str
    type_parent: str | None = None
    type_candidate: str | None = None


@dataclass(frozen=True)
class SemanticDiffDetail:
    parent_sha256: str
    candidate_sha256: str
    roads_identical: bool
    total_roads: int
    road_diffs: tuple[RoadDiffEntry, ...] = ()
    lane_diffs: tuple[LaneDiffEntry, ...] = ()
    junction_diffs: tuple[JunctionDiffEntry, ...] = ()
    signal_diffs: tuple[SignalDiffEntry, ...] = ()
    authority_escalation: bool = False
    authority_violations: tuple[str, ...] = ()

    def to_summary(self) -> SemanticDiffSummary:
        added_roads = sum(1 for r in self.road_diffs if r.status == "added")
        removed_roads = sum(1 for r in self.road_diffs if r.status == "removed")
        changed_roads = sum(1 for r in self.road_diffs if r.status == "modified")
        added_lanes = sum(1 for l in self.lane_diffs if l.status == "added")
        removed_lanes = sum(1 for l in self.lane_diffs if l.status == "removed")
        changed_lanes = sum(1 for l in self.lane_diffs if l.status == "modified")
        changed_elements = changed_roads + changed_lanes
        added_elements = added_roads + added_lanes
        removed_elements = removed_roads + removed_lanes
        changed_elements += sum(1 for j in self.junction_diffs if j.status == "modified")
        added_elements += sum(1 for j in self.junction_diffs if j.status == "added")
        removed_elements += sum(1 for j in self.junction_diffs if j.status == "removed")
        changed_elements += sum(1 for s in self.signal_diffs if s.status == "modified")
        added_elements += sum(1 for s in self.signal_diffs if s.status == "added")
        removed_elements += sum(1 for s in self.signal_diffs if s.status == "removed")
        critical = list(self.authority_violations)
        if self.authority_escalation:
            critical.append("authority_escalation_detected")
        metrics = {
            "total_roads_parent": self.total_roads,
            "total_roads_candidate": sum(
                1 for r in self.road_diffs if r.status != "removed"
            ),
            "road_diffs": len(self.road_diffs),
            "lane_diffs": len(self.lane_diffs),
            "junction_diffs": len(self.junction_diffs),
            "signal_diffs": len(self.signal_diffs),
        }
        return SemanticDiffSummary(
            parent_sha256=self.parent_sha256,
            candidate_sha256=self.candidate_sha256,
            changed_elements=changed_elements,
            added_elements=added_elements,
            removed_elements=removed_elements,
            critical_changes=tuple(critical),
            metrics=metrics,
        )


def _open_xodr(path: str | Path) -> ET.Element:
    tree = ET.parse(str(path))
    root = tree.getroot()
    if root.tag not in ("OpenDRIVE",):
        raise RoadRunnerContractError(f"not a valid OpenDRIVE XML: {path}")
    return root


def _parse_road_element(road: ET.Element) -> dict[str, Any]:
    road_id = road.attrib.get("id", "")
    junction = road.attrib.get("junction", "-1")
    length_str = road.attrib.get("length", "0")
    try:
        length = float(length_str)
    except ValueError:
        length = 0.0
    junction_id = None if junction in ("-1", "") else junction
    geometry_types: dict[str, int] = {}
    plan_view = road.find("planView")
    if plan_view is not None:
        for geo in plan_view:
            t = geo.tag
            geo_type = geo.attrib.get("type", t)
            geometry_types[geo_type] = geometry_types.get(geo_type, 0) + 1
    lane_sections: list[dict[str, Any]] = []
    lanes_elem = road.find("lanes")
    if lanes_elem is not None:
        for ls in lanes_elem.findall("laneSection"):
            s_str = ls.attrib.get("s", "0")
            try:
                s_val = float(s_str)
            except ValueError:
                s_val = 0.0
            lanes_in_section: list[dict[str, Any]] = []
            for side in ("left", "center", "right"):
                side_elem = ls.find(side)
                if side_elem is None:
                    continue
                for lane in side_elem:
                    lane_id_str = lane.attrib.get("id", "0")
                    lane_type = lane.attrib.get("type", "none")
                    level_str = lane.attrib.get("level", "0")
                    direction = lane.attrib.get("direction", "forward")
                    try:
                        lane_id = int(lane_id_str)
                    except ValueError:
                        lane_id = 0
                    width_val: float | None = None
                    width_elem = lane.find("width")
                    if width_elem is not None:
                        try:
                            width_val = float(width_elem.attrib.get("a", "0"))
                        except ValueError:
                            width_val = None
                    lanes_in_section.append(
                        {
                            "id": lane_id,
                            "type": lane_type,
                            "level": level_str == "1",
                            "width": width_val,
                            "direction": direction,
                        }
                    )
            lane_sections.append({"s": s_val, "lanes": lanes_in_section})
    return {
        "id": road_id,
        "junction": junction_id,
        "length": length,
        "geometry_types": geometry_types,
        "lane_sections": lane_sections,
    }


def _parse_junction_element(junction: ET.Element) -> dict[str, Any]:
    jid = junction.attrib.get("id", "")
    connections = junction.findall("connection")
    return {"id": jid, "connections": len(connections)}


def _parse_signal_element(signal: ET.Element) -> dict[str, Any]:
    sid = signal.attrib.get("id", "")
    stype = signal.attrib.get("type", "")
    dynamic = signal.attrib.get("dynamic", "no")
    return {"id": sid, "type": stype, "dynamic": dynamic}


def _parse_xodr(root: ET.Element) -> dict[str, Any]:
    roads: dict[str, dict[str, Any]] = {}
    junctions: dict[str, dict[str, Any]] = {}
    signals: dict[str, dict[str, Any]] = {}

    for child in root:
        if child.tag == "road":
            info = _parse_road_element(child)
            roads[info["id"]] = info
        elif child.tag == "junction":
            info = _parse_junction_element(child)
            junctions[info["id"]] = info
        elif child.tag == "signal" or child.tag == "controller":
            pass

    for child in root:
        if child.tag == "signal":
            info = _parse_signal_element(child)
            signals[info["id"]] = info

    for road_elem in root.findall("road"):
        for obj in road_elem.findall(".//signal"):
            sid = obj.attrib.get("id", "")
            stype = obj.attrib.get("type", "")
            dynamic = obj.attrib.get("dynamic", "no")
            if sid and sid not in signals:
                signals[sid] = {"id": sid, "type": stype, "dynamic": dynamic}

    return {"roads": roads, "junctions": junctions, "signals": signals}


def _compare_lanes(
    parent_lanes: list[dict[str, Any]],
    candidate_lanes: list[dict[str, Any]],
    road_id: str,
) -> list[LaneDiffEntry]:
    diffs: list[LaneDiffEntry] = []
    parent_by_id: dict[int, dict[str, Any]] = {}
    candidate_by_id: dict[int, dict[str, Any]] = {}
    for lane in parent_lanes:
        parent_by_id[lane["id"]] = lane
    for lane in candidate_lanes:
        candidate_by_id[lane["id"]] = lane

    all_ids = set(parent_by_id) | set(candidate_by_id)
    for lid in sorted(all_ids):
        p = parent_by_id.get(lid)
        c = candidate_by_id.get(lid)
        if p is not None and c is None:
            diffs.append(
                LaneDiffEntry(
                    road_id=road_id,
                    lane_section_s=0.0,
                    lane_id=lid,
                    lane_type=p["type"],
                    direction=p["direction"],
                    width=p["width"],
                    status="removed",
                )
            )
        elif p is None and c is not None:
            diffs.append(
                LaneDiffEntry(
                    road_id=road_id,
                    lane_section_s=0.0,
                    lane_id=lid,
                    lane_type=c["type"],
                    direction=c["direction"],
                    width=c["width"],
                    status="added",
                )
            )
        elif p is not None and c is not None:
            modified = False
            if p["type"] != c["type"]:
                modified = True
            if p["direction"] != c["direction"]:
                modified = True
            if p["width"] != c["width"]:
                modified = True
            if modified:
                diffs.append(
                    LaneDiffEntry(
                        road_id=road_id,
                        lane_section_s=0.0,
                        lane_id=lid,
                        lane_type=c["type"],
                        direction=c["direction"],
                        width=c["width"],
                        status="modified",
                    )
                )
    return diffs


def _compare_roads(
    parent: dict[str, Any],
    candidate: dict[str, Any],
) -> tuple[list[RoadDiffEntry], list[LaneDiffEntry]]:
    road_diffs: list[RoadDiffEntry] = []
    lane_diffs: list[LaneDiffEntry] = []

    parent_roads: dict[str, dict[str, Any]] = parent.get("roads", {})
    candidate_roads: dict[str, dict[str, Any]] = candidate.get("roads", {})
    all_road_ids = set(parent_roads) | set(candidate_roads)

    for rid in sorted(all_road_ids):
        p = parent_roads.get(rid)
        c = candidate_roads.get(rid)
        if p is not None and c is None:
            road_diffs.append(
                RoadDiffEntry(
                    road_id=rid,
                    junction_id=p.get("junction"),
                    status="removed",
                )
            )
        elif p is None and c is not None:
            road_diffs.append(
                RoadDiffEntry(
                    road_id=rid,
                    junction_id=c.get("junction"),
                    status="added",
                )
            )
        elif p is not None and c is not None:
            length_delta = c["length"] - p["length"]
            p_geo = p.get("geometry_types", {})
            c_geo = c.get("geometry_types", {})
            all_geo_types = set(p_geo) | set(c_geo)
            geo_delta: dict[str, int] = {}
            for gt in sorted(all_geo_types):
                diff = c_geo.get(gt, 0) - p_geo.get(gt, 0)
                if diff != 0:
                    geo_delta[gt] = diff
            p_lanes: list[dict[str, Any]] = []
            c_lanes: list[dict[str, Any]] = []
            for ls in p.get("lane_sections", []):
                p_lanes.extend(ls.get("lanes", []))
            for ls in c.get("lane_sections", []):
                c_lanes.extend(ls.get("lanes", []))
            current_lane_diffs = _compare_lanes(p_lanes, c_lanes, rid)
            lane_diffs.extend(current_lane_diffs)
            modified = (
                abs(length_delta) > 0.001
                or bool(geo_delta)
                or len(current_lane_diffs) > 0
            )
            if modified:
                road_diffs.append(
                    RoadDiffEntry(
                        road_id=rid,
                        junction_id=p.get("junction"),
                        status="modified",
                        length_delta=round(length_delta, 6),
                        geometry_counts=dict(p_geo),
                        geometry_delta=geo_delta,
                        lane_changes=len(current_lane_diffs),
                    )
                )

    return road_diffs, lane_diffs


def _compare_junctions(
    parent: dict[str, Any],
    candidate: dict[str, Any],
) -> list[JunctionDiffEntry]:
    diffs: list[JunctionDiffEntry] = []
    p_juncs: dict[str, dict[str, Any]] = parent.get("junctions", {})
    c_juncs: dict[str, dict[str, Any]] = candidate.get("junctions", {})
    all_ids = set(p_juncs) | set(c_juncs)
    for jid in sorted(all_ids):
        p = p_juncs.get(jid)
        c = c_juncs.get(jid)
        if p is not None and c is None:
            diffs.append(JunctionDiffEntry(junction_id=jid, status="removed"))
        elif p is None and c is not None:
            diffs.append(JunctionDiffEntry(junction_id=jid, status="added"))
        elif p is not None and c is not None:
            pc = p.get("connections", 0)
            cc = c.get("connections", 0)
            if pc != cc:
                diffs.append(
                    JunctionDiffEntry(
                        junction_id=jid,
                        status="modified",
                        connection_count_parent=pc,
                        connection_count_candidate=cc,
                    )
                )
    return diffs


def _compare_signals(
    parent: dict[str, Any],
    candidate: dict[str, Any],
) -> list[SignalDiffEntry]:
    diffs: list[SignalDiffEntry] = []
    p_sigs: dict[str, dict[str, Any]] = parent.get("signals", {})
    c_sigs: dict[str, dict[str, Any]] = candidate.get("signals", {})
    all_ids = set(p_sigs) | set(c_sigs)
    for sid in sorted(all_ids):
        p = p_sigs.get(sid)
        c = c_sigs.get(sid)
        if p is not None and c is None:
            diffs.append(SignalDiffEntry(signal_id=sid, status="removed"))
        elif p is None and c is not None:
            diffs.append(
                SignalDiffEntry(
                    signal_id=sid,
                    status="added",
                    type_candidate=c.get("type"),
                )
            )
        elif p is not None and c is not None:
            if p.get("type") != c.get("type"):
                diffs.append(
                    SignalDiffEntry(
                        signal_id=sid,
                        status="modified",
                        type_parent=p.get("type"),
                        type_candidate=c.get("type"),
                    )
                )
    return diffs


def _check_authority_escalation(
    parent: dict[str, Any],
    candidate: dict[str, Any],
) -> tuple[bool, tuple[str, ...]]:
    violations: list[str] = []
    p_roads: dict[str, dict[str, Any]] = parent.get("roads", {})
    c_roads: dict[str, dict[str, Any]] = candidate.get("roads", {})
    for rid, c_road in c_roads.items():
        p_road = p_roads.get(rid)
        if p_road is None:
            continue
        p_lanes: list[dict[str, Any]] = []
        c_lanes: list[dict[str, Any]] = []
        for ls in p_road.get("lane_sections", []):
            p_lanes.extend(ls.get("lanes", []))
        for ls in c_road.get("lane_sections", []):
            c_lanes.extend(ls.get("lanes", []))
        p_lane_count = len(p_lanes)
        c_lane_count = len(c_lanes)
        if c_lane_count > p_lane_count:
            violations.append(f"lane_addition_road_{rid}")
        c_junction = c_road.get("junction")
        p_junction = p_road.get("junction")
        if c_junction is None and p_junction is not None:
            violations.append(f"junction_removal_road_{rid}")
        c_length = c_road.get("length", 0)
        p_length = p_road.get("length", 0)
        if c_length > p_length * 1.05:
            violations.append(f"length_increase_road_{rid}")
    c_juncs: dict[str, dict[str, Any]] = candidate.get("junctions", {})
    p_juncs: dict[str, dict[str, Any]] = parent.get("junctions", {})
    for jid, c_junc in c_juncs.items():
        p_junc = p_juncs.get(jid)
        if p_junc is not None:
            cc = c_junc.get("connections", 0)
            pc = p_junc.get("connections", 0)
            if cc > pc:
                violations.append(f"connection_addition_junction_{jid}")
    return (len(violations) > 0, tuple(violations))


def compute_xodr_file_hash(path: str | Path) -> str:
    with open(str(path), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def compare_xodr_semantic(
    parent_path: str | Path,
    candidate_path: str | Path,
    parent_sha256: str | None = None,
    candidate_sha256: str | None = None,
    *,
    detect_authority_escalation: bool = True,
) -> SemanticDiffDetail:
    parent_sha = parent_sha256 or compute_xodr_file_hash(parent_path)
    candidate_sha = candidate_sha256 or compute_xodr_file_hash(candidate_path)
    parent_sha = validate_sha256(parent_sha, "parent_sha256")
    candidate_sha = validate_sha256(candidate_sha, "candidate_sha256")
    parent_root = _open_xodr(parent_path)
    candidate_root = _open_xodr(candidate_path)
    parent_data = _parse_xodr(parent_root)
    candidate_data = _parse_xodr(candidate_root)
    road_diffs, lane_diffs = _compare_roads(parent_data, candidate_data)
    junction_diffs = _compare_junctions(parent_data, candidate_data)
    signal_diffs = _compare_signals(parent_data, candidate_data)
    authority_escalation: bool = False
    authority_violations: tuple[str, ...] = ()
    if detect_authority_escalation:
        authority_escalation, authority_violations = _check_authority_escalation(
            parent_data, candidate_data
        )
    total_roads = max(
        len(parent_data.get("roads", {})),
        len(candidate_data.get("roads", {})),
    )
    roads_identical = (
        len(road_diffs) == 0
        and len(lane_diffs) == 0
        and len(junction_diffs) == 0
        and len(signal_diffs) == 0
    )
    return SemanticDiffDetail(
        parent_sha256=parent_sha,
        candidate_sha256=candidate_sha,
        roads_identical=roads_identical,
        total_roads=total_roads,
        road_diffs=tuple(road_diffs),
        lane_diffs=tuple(lane_diffs),
        junction_diffs=tuple(junction_diffs),
        signal_diffs=tuple(signal_diffs),
        authority_escalation=authority_escalation,
        authority_violations=authority_violations,
    )


def compare_xodr_files(
    parent_path: str | Path,
    candidate_path: str | Path,
    *,
    detect_authority_escalation: bool = True,
) -> SemanticDiffSummary:
    detail = compare_xodr_semantic(
        parent_path,
        candidate_path,
        detect_authority_escalation=detect_authority_escalation,
    )
    return detail.to_summary()


__all__ = [
    "LaneDiffEntry",
    "RoadDiffEntry",
    "JunctionDiffEntry",
    "SignalDiffEntry",
    "SemanticDiffDetail",
    "SemanticDiffSummary",
    "compare_xodr_semantic",
    "compare_xodr_files",
]
