"""XODR semantic diff engine for RoadRunner roundtrip validation.

Parses OpenDRIVE (.xodr) files into a normalized snapshot and computes
semantic differences between a parent (governed/candidate) XODR and a
RoadRunner-exported candidate XODR across all required comparison dimensions.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .validation import DiffClassification, DiffRecord, RoundtripConfig
from ultimate_pipeline.core.georef_utils import normalize_georeference, parse_georeference
from ultimate_pipeline.utils.file_hashing import sha256_file


def _float(value: str | None, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        v = float(value)
        if not math.isfinite(v):
            return default
        return v
    except (TypeError, ValueError):
        return default


def _stable(value: float | None, decimals: int = 6) -> float | None:
    if value is None:
        return None
    return float(f"{value:.{decimals}f}")


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


@dataclass(frozen=True)
class GeometrySegment:
    """Normalized representation of a single plan-view geometry segment."""

    s: float
    x: float
    y: float
    hdg: float
    length: float
    geom_type: str
    curvature_start: float
    curvature_end: float
    extra: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LaneWidth:
    """Normalized lane width polynomial."""

    s_offset: float
    a: float
    b: float
    c: float
    d: float


@dataclass(frozen=True)
class LaneLink:
    """Normalized lane predecessor/successor link."""

    element_type: str | None
    element_id: str | None
    contact_point: str | None


@dataclass(frozen=True)
class LaneInfo:
    """Normalized representation of a lane."""

    lane_id: int
    lane_type: str
    direction: str
    level: bool
    widths: tuple[LaneWidth, ...]
    predecessor: LaneLink | None
    successor: LaneLink | None


@dataclass(frozen=True)
class LaneSectionInfo:
    """Normalized representation of a lane section."""

    s: float
    left: tuple[LaneInfo, ...]
    center: tuple[LaneInfo, ...]
    right: tuple[LaneInfo, ...]


@dataclass(frozen=True)
class RoadLink:
    """Normalized road predecessor/successor link."""

    element_type: str | None
    element_id: str | None
    contact_point: str | None


@dataclass(frozen=True)
class ElevationSegment:
    """Normalized elevation polynomial segment."""

    s: float
    a: float
    b: float
    c: float
    d: float


@dataclass(frozen=True)
class SuperelevationSegment:
    """Normalized superelevation polynomial segment."""

    s: float
    a: float
    b: float
    c: float
    d: float


@dataclass(frozen=True)
class RoadMarkInfo:
    """Normalized road mark."""

    s_offset: float
    mark_type: str
    weight: str
    color: str
    width: float
    extra: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SignalInfo:
    """Normalized signal."""

    signal_id: str
    s: float
    t: float
    signal_type: str
    subtype: str
    name: str | None
    extra: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ObjectInfo:
    """Normalized object."""

    object_id: str
    s: float
    t: float
    object_type: str
    subtype: str
    name: str | None
    extra: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ControllerInfo:
    """Normalized controller."""

    controller_id: str
    name: str | None
    extra: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class JunctionConnection:
    """Normalized junction connection."""

    incoming_road: str
    connecting_road: str
    contact_point: str
    extra: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class JunctionInfo:
    """Normalized representation of a junction."""

    junction_id: str
    name: str | None
    connections: tuple[JunctionConnection, ...]


@dataclass(frozen=True)
class RoadInfo:
    """Normalized representation of a road."""

    road_id: str
    name: str | None
    length: float
    road_type: str | None
    junction: str | None
    predecessor: RoadLink | None
    successor: RoadLink | None
    geometry: tuple[GeometrySegment, ...]
    lane_sections: tuple[LaneSectionInfo, ...]
    elevation: tuple[ElevationSegment, ...]
    superelevation: tuple[SuperelevationSegment, ...]
    road_marks: tuple[RoadMarkInfo, ...]
    signals: tuple[SignalInfo, ...]
    objects: tuple[ObjectInfo, ...]


@dataclass(frozen=True)
class XodrSnapshot:
    """Normalized snapshot of an XODR file."""

    sha256: str
    georeference: str | None
    georeference_complete: bool
    header_bounds: Mapping[str, float | None]
    header_offset: Mapping[str, float | None]
    roads: Mapping[str, RoadInfo]
    junctions: Mapping[str, JunctionInfo]
    controllers: tuple[ControllerInfo, ...]
    signals: tuple[SignalInfo, ...]
    objects: tuple[ObjectInfo, ...]
    total_road_length: float
    road_count: int
    junction_count: int
    authority_class: str | None


def _parse_lane_link(link_elem: ET.Element | None) -> LaneLink | None:
    if link_elem is None:
        return None
    return LaneLink(
        element_type=link_elem.get("elementType"),
        element_id=link_elem.get("elementId"),
        contact_point=link_elem.get("contactPoint"),
    )


def _parse_road_link(link_elem: ET.Element | None) -> RoadLink | None:
    if link_elem is None:
        return None
    return RoadLink(
        element_type=link_elem.get("elementType"),
        element_id=link_elem.get("elementId"),
        contact_point=link_elem.get("contactPoint"),
    )


def _parse_geometry_segment(geom_elem: ET.Element) -> GeometrySegment:
    s = _float(geom_elem.get("s"))
    x = _float(geom_elem.get("x"))
    y = _float(geom_elem.get("y"))
    hdg = _float(geom_elem.get("hdg"))
    length = _float(geom_elem.get("length"))

    geom_type = "unknown"
    curvature_start = 0.0
    curvature_end = 0.0
    extra: dict[str, str] = {}

    for child in geom_elem:
        tag = _strip_ns(child.tag)
        if tag in ("line", "arc", "spiral", "poly3", "paramPoly3"):
            geom_type = tag
            if tag == "arc":
                curvature = _float(child.get("curvature"))
                curvature_start = curvature
                curvature_end = curvature
            elif tag == "spiral":
                curvature_start = _float(child.get("curvStart"))
                curvature_end = _float(child.get("curvEnd"))
            elif tag in ("poly3", "paramPoly3"):
                for attr in ("a", "b", "c", "d"):
                    val = child.get(attr)
                    if val is not None:
                        extra[attr] = val
            for attr, val in child.attrib.items():
                if attr not in ("a", "b", "c", "d"):
                    extra[attr] = val
            break

    return GeometrySegment(
        s=s, x=x, y=y, hdg=hdg, length=length,
        geom_type=geom_type,
        curvature_start=curvature_start,
        curvature_end=curvature_end,
        extra=extra,
    )


def _parse_lane_width(width_elem: ET.Element) -> LaneWidth:
    return LaneWidth(
        s_offset=_float(width_elem.get("sOffset")),
        a=_float(width_elem.get("a")),
        b=_float(width_elem.get("b")),
        c=_float(width_elem.get("c")),
        d=_float(width_elem.get("d")),
    )


def _parse_lane(lane_elem: ET.Element) -> LaneInfo:
    lane_id = int(_float(lane_elem.get("id"), 0))
    lane_type = lane_elem.get("type", "none")
    direction = lane_elem.get("direction", "same")
    level = lane_elem.get("level", "false").lower() == "true"

    widths: list[LaneWidth] = []
    for w in lane_elem.findall("width"):
        widths.append(_parse_lane_width(w))

    link_elem = lane_elem.find("link")
    predecessor = None
    successor = None
    if link_elem is not None:
        pred_elem = link_elem.find("predecessor")
        if pred_elem is not None:
            predecessor = _parse_lane_link(pred_elem)
        succ_elem = link_elem.find("successor")
        if succ_elem is not None:
            successor = _parse_lane_link(succ_elem)

    return LaneInfo(
        lane_id=lane_id,
        lane_type=lane_type,
        direction=direction,
        level=level,
        widths=tuple(widths),
        predecessor=predecessor,
        successor=successor,
    )


def _parse_lane_section(ls_elem: ET.Element) -> LaneSectionInfo:
    s = _float(ls_elem.get("s"))

    left: list[LaneInfo] = []
    center: list[LaneInfo] = []
    right: list[LaneInfo] = []

    left_elem = ls_elem.find("left")
    if left_elem is not None:
        for lane in left_elem.findall("lane"):
            left.append(_parse_lane(lane))

    center_elem = ls_elem.find("center")
    if center_elem is not None:
        for lane in center_elem.findall("lane"):
            center.append(_parse_lane(lane))

    right_elem = ls_elem.find("right")
    if right_elem is not None:
        for lane in right_elem.findall("lane"):
            right.append(_parse_lane(lane))

    return LaneSectionInfo(
        s=s,
        left=tuple(left),
        center=tuple(center),
        right=tuple(right),
    )


def _parse_elevation(el_elem: ET.Element) -> ElevationSegment:
    return ElevationSegment(
        s=_float(el_elem.get("s")),
        a=_float(el_elem.get("a")),
        b=_float(el_elem.get("b")),
        c=_float(el_elem.get("c")),
        d=_float(el_elem.get("d")),
    )


def _parse_superelevation(se_elem: ET.Element) -> SuperelevationSegment:
    return SuperelevationSegment(
        s=_float(se_elem.get("s")),
        a=_float(se_elem.get("a")),
        b=_float(se_elem.get("b")),
        c=_float(se_elem.get("c")),
        d=_float(se_elem.get("d")),
    )


def _parse_road_mark(rm_elem: ET.Element) -> RoadMarkInfo:
    return RoadMarkInfo(
        s_offset=_float(rm_elem.get("sOffset")),
        mark_type=rm_elem.get("type", "none"),
        weight=rm_elem.get("weight", "standard"),
        color=rm_elem.get("color", "white"),
        width=_float(rm_elem.get("width")),
        extra=dict(rm_elem.attrib),
    )


def _parse_signal(sig_elem: ET.Element) -> SignalInfo:
    return SignalInfo(
        signal_id=sig_elem.get("id", ""),
        s=_float(sig_elem.get("s")),
        t=_float(sig_elem.get("t")),
        signal_type=sig_elem.get("type", "none"),
        subtype=sig_elem.get("subtype", ""),
        name=sig_elem.get("name"),
        extra=dict(sig_elem.attrib),
    )


def _parse_object(obj_elem: ET.Element) -> ObjectInfo:
    return ObjectInfo(
        object_id=obj_elem.get("id", ""),
        s=_float(obj_elem.get("s")),
        t=_float(obj_elem.get("t")),
        object_type=obj_elem.get("type", "none"),
        subtype=obj_elem.get("subtype", ""),
        name=obj_elem.get("name"),
        extra=dict(obj_elem.attrib),
    )


def _parse_controller(ctrl_elem: ET.Element) -> ControllerInfo:
    return ControllerInfo(
        controller_id=ctrl_elem.get("id", ""),
        name=ctrl_elem.get("name"),
        extra=dict(ctrl_elem.attrib),
    )


def _parse_junction_connection(conn_elem: ET.Element) -> JunctionConnection:
    return JunctionConnection(
        incoming_road=conn_elem.get("incomingRoad", ""),
        connecting_road=conn_elem.get("connectingRoad", ""),
        contact_point=conn_elem.get("contactPoint", ""),
        extra=dict(conn_elem.attrib),
    )


def _parse_junction(junc_elem: ET.Element) -> JunctionInfo:
    connections: list[JunctionConnection] = []
    for conn in junc_elem.findall("connection"):
        connections.append(_parse_junction_connection(conn))
    return JunctionInfo(
        junction_id=junc_elem.get("id", ""),
        name=junc_elem.get("name"),
        connections=tuple(connections),
    )


def _parse_road(road_elem: ET.Element) -> RoadInfo:
    road_id = road_elem.get("id", "")
    name = road_elem.get("name")
    length = _float(road_elem.get("length"))
    road_type = road_elem.get("type")
    junction = road_elem.get("junction")

    link_elem = road_elem.find("link")
    predecessor = None
    successor = None
    if link_elem is not None:
        pred_elem = link_elem.find("predecessor")
        if pred_elem is not None:
            predecessor = _parse_road_link(pred_elem)
        succ_elem = link_elem.find("successor")
        if succ_elem is not None:
            successor = _parse_road_link(succ_elem)

    geometry: list[GeometrySegment] = []
    planview = road_elem.find("planView")
    if planview is not None:
        for geom in planview.findall("geometry"):
            geometry.append(_parse_geometry_segment(geom))

    lane_sections: list[LaneSectionInfo] = []
    lanes_elem = road_elem.find("lanes")
    if lanes_elem is not None:
        for ls in lanes_elem.findall("laneSection"):
            lane_sections.append(_parse_lane_section(ls))

    elevation: list[ElevationSegment] = []
    elev_elem = road_elem.find("elevationProfile")
    if elev_elem is not None:
        for el in elev_elem.findall("elevation"):
            elevation.append(_parse_elevation(el))

    superelevation: list[SuperelevationSegment] = []
    superelem = road_elem.find("lateralProfile")
    if superelem is not None:
        for se in superelem.findall("superelevation"):
            superelevation.append(_parse_superelevation(se))

    road_marks: list[RoadMarkInfo] = []
    for rm in road_elem.findall(".//roadMark"):
        road_marks.append(_parse_road_mark(rm))

    signals: list[SignalInfo] = []
    for sig in road_elem.findall("signal"):
        signals.append(_parse_signal(sig))

    objects: list[ObjectInfo] = []
    for obj in road_elem.findall("object"):
        objects.append(_parse_object(obj))

    return RoadInfo(
        road_id=road_id,
        name=name,
        length=length,
        road_type=road_type,
        junction=junction,
        predecessor=predecessor,
        successor=successor,
        geometry=tuple(geometry),
        lane_sections=tuple(lane_sections),
        elevation=tuple(elevation),
        superelevation=tuple(superelevation),
        road_marks=tuple(road_marks),
        signals=tuple(signals),
        objects=tuple(objects),
    )


def parse_xodr(path: str | Path) -> XodrSnapshot:
    """Parse an XODR file into a normalized snapshot.

    This function is read-only: it does not modify the input file.
    """
    path = Path(path)
    sha = sha256_file(path)

    raw = path.read_bytes()
    normalized_bytes = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    root = ET.fromstring(normalized_bytes)

    header = root.find("header")
    georef = None
    georef_complete = False
    bounds: dict[str, float | None] = {"north": None, "south": None, "east": None, "west": None}
    offset: dict[str, float | None] = {"x": None, "y": None, "z": None, "hdg": None}

    if header is not None:
        for key in ("north", "south", "east", "west"):
            bounds[key] = _stable(_float(header.get(key)))
        geo_elem = header.find("geoReference")
        if geo_elem is not None and geo_elem.text:
            valid, params_complete, norm = parse_georeference(geo_elem.text)
            georef = norm or None
            georef_complete = bool(params_complete)
        offset_elem = header.find("offset")
        if offset_elem is not None:
            for key in ("x", "y", "z", "hdg"):
                offset[key] = _stable(_float(offset_elem.get(key)))

    roads: dict[str, RoadInfo] = {}
    for road_elem in root.findall("road"):
        road = _parse_road(road_elem)
        roads[road.road_id] = road

    junctions: dict[str, JunctionInfo] = {}
    for junc_elem in root.findall("junction"):
        junc = _parse_junction(junc_elem)
        junctions[junc.junction_id] = junc

    controllers: list[ControllerInfo] = []
    for ctrl_elem in root.findall("controller"):
        controllers.append(_parse_controller(ctrl_elem))

    signals: list[SignalInfo] = []
    for sig_elem in root.findall("signal"):
        signals.append(_parse_signal(sig_elem))

    objects: list[ObjectInfo] = []
    for obj_elem in root.findall("object"):
        objects.append(_parse_object(obj_elem))

    total_length = sum(r.length for r in roads.values())

    authority_class = None
    meta_elem = root.find("meta")
    if meta_elem is not None:
        authority_class = meta_elem.get("authorityClass")

    return XodrSnapshot(
        sha256=sha,
        georeference=georef,
        georeference_complete=georef_complete,
        header_bounds=bounds,
        header_offset=offset,
        roads=roads,
        junctions=junctions,
        controllers=tuple(controllers),
        signals=tuple(signals),
        objects=tuple(objects),
        total_road_length=total_length,
        road_count=len(roads),
        junction_count=len(junctions),
        authority_class=authority_class,
    )


def _sample_centreline(road: RoadInfo, interval: float) -> list[tuple[float, float, float, float]]:
    """Sample plan-view centreline points: (s, x, y, hdg, curvature)."""
    samples: list[tuple[float, float, float, float]] = []
    for seg in road.geometry:
        if seg.length <= 0:
            continue
        n = max(1, int(seg.length / interval))
        for i in range(n + 1):
            t = i / n
            s = seg.s + t * seg.length
            x = seg.x + t * seg.length * math.cos(seg.hdg)
            y = seg.y + t * seg.length * math.sin(seg.hdg)
            hdg = seg.hdg
            curvature = seg.curvature_start + t * (seg.curvature_end - seg.curvature_start)
            samples.append((s, x, y, hdg, curvature))
    return samples


def _endpoint(road: RoadInfo) -> tuple[float, float, float]:
    """Compute endpoint position (x, y, hdg) of a road."""
    if not road.geometry:
        return (0.0, 0.0, 0.0)
    last = road.geometry[-1]
    end_s = last.s + last.length
    end_x = last.x + last.length * math.cos(last.hdg)
    end_y = last.y + last.length * math.sin(last.hdg)
    return (end_x, end_y, last.hdg)


def _classify_georeference(parent: XodrSnapshot, candidate: XodrSnapshot) -> DiffRecord:
    if parent.georeference is None and candidate.georeference is None:
        return DiffRecord(
            dimension="georeference",
            element_id=None,
            parent_value=None,
            candidate_value=None,
            classification=DiffClassification.IDENTICAL,
            message="Both parent and candidate lack georeference",
        )
    if parent.georeference is None:
        return DiffRecord(
            dimension="georeference",
            element_id=None,
            parent_value=None,
            candidate_value=candidate.georeference,
            classification=DiffClassification.APPROVED_IMPROVEMENT,
            message="Candidate adds georeference where parent had none",
        )
    if candidate.georeference is None:
        return DiffRecord(
            dimension="georeference",
            element_id=None,
            parent_value=parent.georeference,
            candidate_value=None,
            classification=DiffClassification.CRITICAL_REGRESSION,
            message="Candidate lost georeference present in parent",
        )
    if parent.georeference == candidate.georeference:
        return DiffRecord(
            dimension="georeference",
            element_id=None,
            parent_value=parent.georeference,
            candidate_value=candidate.georeference,
            classification=DiffClassification.IDENTICAL,
            message="Georeference identical",
        )
    return DiffRecord(
        dimension="georeference",
        element_id=None,
        parent_value=parent.georeference,
        candidate_value=candidate.georeference,
        classification=DiffClassification.POTENTIAL_LOSS,
        message="Georeference differs between parent and candidate",
    )


def _classify_header_bounds(parent: XodrSnapshot, candidate: XodrSnapshot) -> DiffRecord:
    p = parent.header_bounds
    c = candidate.header_bounds
    if p == c:
        return DiffRecord(
            dimension="header_bounds",
            element_id=None,
            parent_value=str(p),
            candidate_value=str(c),
            classification=DiffClassification.IDENTICAL,
            message="Header bounds identical",
        )
    return DiffRecord(
        dimension="header_bounds",
        element_id=None,
        parent_value=str(p),
        candidate_value=str(c),
        classification=DiffClassification.FORMAT_ONLY,
        message="Header bounds differ (format-only)",
    )


def _classify_road_count(parent: XodrSnapshot, candidate: XodrSnapshot) -> DiffRecord:
    p_count = parent.road_count
    c_count = candidate.road_count
    if p_count == c_count:
        return DiffRecord(
            dimension="road_count",
            element_id=None,
            parent_value=str(p_count),
            candidate_value=str(c_count),
            classification=DiffClassification.IDENTICAL,
            message=f"Road count identical: {p_count}",
        )
    if c_count < p_count:
        return DiffRecord(
            dimension="road_count",
            element_id=None,
            parent_value=str(p_count),
            candidate_value=str(c_count),
            classification=DiffClassification.CRITICAL_REGRESSION,
            message=f"Road count decreased: {p_count} -> {c_count}",
        )
    return DiffRecord(
        dimension="road_count",
        element_id=None,
        parent_value=str(p_count),
        candidate_value=str(c_count),
        classification=DiffClassification.APPROVED_IMPROVEMENT,
        message=f"Road count increased: {p_count} -> {c_count}",
    )


def _classify_junction_count(parent: XodrSnapshot, candidate: XodrSnapshot) -> DiffRecord:
    p_count = parent.junction_count
    c_count = candidate.junction_count
    if p_count == c_count:
        return DiffRecord(
            dimension="junction_count",
            element_id=None,
            parent_value=str(p_count),
            candidate_value=str(c_count),
            classification=DiffClassification.IDENTICAL,
            message=f"Junction count identical: {p_count}",
        )
    if c_count < p_count:
        return DiffRecord(
            dimension="junction_count",
            element_id=None,
            parent_value=str(p_count),
            candidate_value=str(c_count),
            classification=DiffClassification.CRITICAL_REGRESSION,
            message=f"Junction count decreased: {p_count} -> {c_count}",
        )
    return DiffRecord(
        dimension="junction_count",
        element_id=None,
        parent_value=str(p_count),
        candidate_value=str(c_count),
        classification=DiffClassification.APPROVED_IMPROVEMENT,
        message=f"Junction count increased: {p_count} -> {c_count}",
    )


def _classify_total_length(parent: XodrSnapshot, candidate: XodrSnapshot, config: RoundtripConfig) -> DiffRecord:
    p_len = parent.total_road_length
    c_len = candidate.total_road_length
    diff = abs(p_len - c_len)
    if diff <= config.length_tolerance_m:
        return DiffRecord(
            dimension="total_length",
            element_id=None,
            parent_value=f"{p_len:.6f}",
            candidate_value=f"{c_len:.6f}",
            classification=DiffClassification.IDENTICAL,
            message=f"Total road length within tolerance: {p_len:.3f} vs {c_len:.3f}",
        )
    if c_len < p_len:
        return DiffRecord(
            dimension="total_length",
            element_id=None,
            parent_value=f"{p_len:.6f}",
            candidate_value=f"{c_len:.6f}",
            classification=DiffClassification.POTENTIAL_LOSS,
            message=f"Total road length decreased: {p_len:.3f} -> {c_len:.3f}",
        )
    return DiffRecord(
        dimension="total_length",
        element_id=None,
        parent_value=f"{p_len:.6f}",
        candidate_value=f"{c_len:.6f}",
        classification=DiffClassification.APPROVED_IMPROVEMENT,
        message=f"Total road length increased: {p_len:.3f} -> {c_len:.3f}",
    )


def _classify_road_ids(parent: XodrSnapshot, candidate: XodrSnapshot) -> list[DiffRecord]:
    diffs: list[DiffRecord] = []
    p_ids = set(parent.roads.keys())
    c_ids = set(candidate.roads.keys())
    for rid in sorted(p_ids - c_ids):
        diffs.append(DiffRecord(
            dimension="road_id",
            element_id=rid,
            parent_value=rid,
            candidate_value=None,
            classification=DiffClassification.CRITICAL_REGRESSION,
            message=f"Road {rid} deleted in candidate",
        ))
    for rid in sorted(c_ids - p_ids):
        diffs.append(DiffRecord(
            dimension="road_id",
            element_id=rid,
            parent_value=None,
            candidate_value=rid,
            classification=DiffClassification.APPROVED_IMPROVEMENT,
            message=f"Road {rid} added in candidate",
        ))
    return diffs


def _classify_junction_ids(parent: XodrSnapshot, candidate: XodrSnapshot) -> list[DiffRecord]:
    diffs: list[DiffRecord] = []
    p_ids = set(parent.junctions.keys())
    c_ids = set(candidate.junctions.keys())
    for jid in sorted(p_ids - c_ids):
        diffs.append(DiffRecord(
            dimension="junction_id",
            element_id=jid,
            parent_value=jid,
            candidate_value=None,
            classification=DiffClassification.CRITICAL_REGRESSION,
            message=f"Junction {jid} deleted in candidate",
        ))
    for jid in sorted(c_ids - p_ids):
        diffs.append(DiffRecord(
            dimension="junction_id",
            element_id=jid,
            parent_value=None,
            candidate_value=jid,
            classification=DiffClassification.APPROVED_IMPROVEMENT,
            message=f"Junction {jid} added in candidate",
        ))
    return diffs


def _classify_geometry_types(
    parent: XodrSnapshot, candidate: XodrSnapshot, config: RoundtripConfig
) -> list[DiffRecord]:
    diffs: list[DiffRecord] = []
    for rid in sorted(set(parent.roads.keys()) & set(candidate.roads.keys())):
        p_road = parent.roads[rid]
        c_road = candidate.roads[rid]
        p_types = [seg.geom_type for seg in p_road.geometry]
        c_types = [seg.geom_type for seg in c_road.geometry]
        if p_types == c_types:
            continue
        if len(p_types) != len(c_types):
            diffs.append(DiffRecord(
                dimension="geometry_type",
                element_id=rid,
                parent_value=str(p_types),
                candidate_value=str(c_types),
                classification=DiffClassification.POTENTIAL_LOSS,
                message=f"Geometry sequence length differs for road {rid}",
            ))
            continue
        for i, (pt, ct) in enumerate(zip(p_types, c_types)):
            if pt != ct:
                classification = DiffClassification.POTENTIAL_LOSS
                if pt in ("poly3", "paramPoly3", "spiral") and ct == "line":
                    classification = DiffClassification.CRITICAL_REGRESSION
                diffs.append(DiffRecord(
                    dimension="geometry_type",
                    element_id=rid,
                    parent_value=pt,
                    candidate_value=ct,
                    classification=classification,
                    message=f"Geometry type changed at segment {i} of road {rid}: {pt} -> {ct}",
                ))
    return diffs


def _classify_sampled_centreline(
    parent: XodrSnapshot, candidate: XodrSnapshot, config: RoundtripConfig
) -> list[DiffRecord]:
    diffs: list[DiffRecord] = []
    for rid in sorted(set(parent.roads.keys()) & set(candidate.roads.keys())):
        p_road = parent.roads[rid]
        c_road = candidate.roads[rid]
        p_samples = _sample_centreline(p_road, config.sample_interval_m)
        c_samples = _sample_centreline(c_road, config.sample_interval_m)
        if not p_samples or not c_samples:
            continue
        min_len = min(len(p_samples), len(c_samples))
        max_pos_diff = 0.0
        max_hdg_diff = 0.0
        max_curv_diff = 0.0
        for i in range(min_len):
            p_s, p_x, p_y, p_hdg, p_curv = p_samples[i]
            c_s, c_x, c_y, c_hdg, c_curv = c_samples[i]
            pos_diff = math.sqrt((p_x - c_x) ** 2 + (p_y - c_y) ** 2)
            hdg_diff = abs(p_hdg - c_hdg)
            hdg_diff = min(hdg_diff, 2 * math.pi - hdg_diff)
            curv_diff = abs(p_curv - c_curv)
            max_pos_diff = max(max_pos_diff, pos_diff)
            max_hdg_diff = max(max_hdg_diff, hdg_diff)
            max_curv_diff = max(max_curv_diff, curv_diff)
        if max_pos_diff > config.position_tolerance_m:
            diffs.append(DiffRecord(
                dimension="sampled_centreline",
                element_id=rid,
                parent_value=f"max_pos_diff={max_pos_diff:.6f}",
                candidate_value=f"tolerance={config.position_tolerance_m:.6f}",
                classification=DiffClassification.POTENTIAL_LOSS,
                message=f"Centeline position drift on road {rid}: {max_pos_diff:.4f} m",
            ))
        if max_hdg_diff > math.radians(config.tangent_regression_threshold_deg):
            diffs.append(DiffRecord(
                dimension="sampled_centreline",
                element_id=rid,
                parent_value=f"max_hdg_diff={max_hdg_diff:.6f}",
                candidate_value=f"threshold={config.tangent_regression_threshold_deg} deg",
                classification=DiffClassification.POTENTIAL_LOSS,
                message=f"Centeline heading drift on road {rid}: {math.degrees(max_hdg_diff):.4f} deg",
            ))
        if max_curv_diff > config.curvature_tolerance:
            diffs.append(DiffRecord(
                dimension="sampled_centreline",
                element_id=rid,
                parent_value=f"max_curv_diff={max_curv_diff:.6f}",
                candidate_value=f"tolerance={config.curvature_tolerance:.6f}",
                classification=DiffClassification.POTENTIAL_LOSS,
                message=f"Centeline curvature drift on road {rid}: {max_curv_diff:.6f}",
            ))
    return diffs


def _classify_endpoints(
    parent: XodrSnapshot, candidate: XodrSnapshot, config: RoundtripConfig
) -> list[DiffRecord]:
    diffs: list[DiffRecord] = []
    for rid in sorted(set(parent.roads.keys()) & set(candidate.roads.keys())):
        p_road = parent.roads[rid]
        c_road = candidate.roads[rid]
        p_end = _endpoint(p_road)
        c_end = _endpoint(c_road)
        pos_diff = math.sqrt((p_end[0] - c_end[0]) ** 2 + (p_end[1] - c_end[1]) ** 2)
        hdg_diff = abs(p_end[2] - c_end[2])
        hdg_diff = min(hdg_diff, 2 * math.pi - hdg_diff)
        hdg_diff_deg = math.degrees(hdg_diff)
        if pos_diff > config.position_tolerance_m:
            diffs.append(DiffRecord(
                dimension="endpoint_position",
                element_id=rid,
                parent_value=f"({p_end[0]:.6f},{p_end[1]:.6f})",
                candidate_value=f"({c_end[0]:.6f},{c_end[1]:.6f})",
                classification=DiffClassification.POTENTIAL_LOSS,
                message=f"Endpoint position drift on road {rid}: {pos_diff:.4f} m",
            ))
        if hdg_diff_deg > config.tangent_regression_threshold_deg:
            diffs.append(DiffRecord(
                dimension="endpoint_tangent",
                element_id=rid,
                parent_value=f"{math.degrees(p_end[2]):.6f}",
                candidate_value=f"{math.degrees(c_end[2]):.6f}",
                classification=DiffClassification.CRITICAL_REGRESSION,
                message=f"Endpoint tangent regression on road {rid}: {hdg_diff_deg:.4f} deg",
            ))
    return diffs


def _classify_curvature(
    parent: XodrSnapshot, candidate: XodrSnapshot, config: RoundtripConfig
) -> list[DiffRecord]:
    diffs: list[DiffRecord] = []
    for rid in sorted(set(parent.roads.keys()) & set(candidate.roads.keys())):
        p_road = parent.roads[rid]
        c_road = candidate.roads[rid]
        p_max_curv = max((abs(seg.curvature_start) for seg in p_road.geometry), default=0.0)
        c_max_curv = max((abs(seg.curvature_start) for seg in c_road.geometry), default=0.0)
        if abs(p_max_curv - c_max_curv) > config.curvature_tolerance:
            diffs.append(DiffRecord(
                dimension="curvature",
                element_id=rid,
                parent_value=f"{p_max_curv:.6f}",
                candidate_value=f"{c_max_curv:.6f}",
                classification=DiffClassification.POTENTIAL_LOSS,
                message=f"Max curvature drift on road {rid}: {p_max_curv:.6f} -> {c_max_curv:.6f}",
            ))
    return diffs


def _classify_road_links(
    parent: XodrSnapshot, candidate: XodrSnapshot
) -> list[DiffRecord]:
    diffs: list[DiffRecord] = []
    for rid in sorted(set(parent.roads.keys()) & set(candidate.roads.keys())):
        p_road = parent.roads[rid]
        c_road = candidate.roads[rid]
        for link_type, p_link, c_link in (
            ("road_predecessor", p_road.predecessor, c_road.predecessor),
            ("road_successor", p_road.successor, c_road.successor),
        ):
            if p_link is None and c_link is None:
                continue
            if p_link is None and c_link is not None:
                diffs.append(DiffRecord(
                    dimension=link_type,
                    element_id=rid,
                    parent_value=None,
                    candidate_value=str(c_link),
                    classification=DiffClassification.APPROVED_IMPROVEMENT,
                    message=f"Road {rid} {link_type} added in candidate",
                ))
                continue
            if p_link is not None and c_link is None:
                diffs.append(DiffRecord(
                    dimension=link_type,
                    element_id=rid,
                    parent_value=str(p_link),
                    candidate_value=None,
                    classification=DiffClassification.CRITICAL_REGRESSION,
                    message=f"Road {rid} {link_type} removed in candidate",
                ))
                continue
            if p_link != c_link:
                diffs.append(DiffRecord(
                    dimension=link_type,
                    element_id=rid,
                    parent_value=str(p_link),
                    candidate_value=str(c_link),
                    classification=DiffClassification.POTENTIAL_LOSS,
                    message=f"Road {rid} {link_type} changed",
                ))
    return diffs


def _classify_junction_connections(
    parent: XodrSnapshot, candidate: XodrSnapshot
) -> list[DiffRecord]:
    diffs: list[DiffRecord] = []
    for jid in sorted(set(parent.junctions.keys()) & set(candidate.junctions.keys())):
        p_junc = parent.junctions[jid]
        c_junc = candidate.junctions[jid]
        p_conns = {(c.incoming_road, c.connecting_road, c.contact_point) for c in p_junc.connections}
        c_conns = {(c.incoming_road, c.connecting_road, c.contact_point) for c in c_junc.connections}
        for conn in sorted(p_conns - c_conns):
            diffs.append(DiffRecord(
                dimension="junction_connection",
                element_id=jid,
                parent_value=str(conn),
                candidate_value=None,
                classification=DiffClassification.CRITICAL_REGRESSION,
                message=f"Junction {jid} connection {conn} removed in candidate",
            ))
        for conn in sorted(c_conns - p_conns):
            diffs.append(DiffRecord(
                dimension="junction_connection",
                element_id=jid,
                parent_value=None,
                candidate_value=str(conn),
                classification=DiffClassification.APPROVED_IMPROVEMENT,
                message=f"Junction {jid} connection {conn} added in candidate",
            ))
    return diffs


def _classify_lane_sections(
    parent: XodrSnapshot, candidate: XodrSnapshot, config: RoundtripConfig
) -> list[DiffRecord]:
    diffs: list[DiffRecord] = []
    for rid in sorted(set(parent.roads.keys()) & set(candidate.roads.keys())):
        p_road = parent.roads[rid]
        c_road = candidate.roads[rid]
        p_starts = [ls.s for ls in p_road.lane_sections]
        c_starts = [ls.s for ls in c_road.lane_sections]
        if len(p_starts) != len(c_starts):
            diffs.append(DiffRecord(
                dimension="lane_section_start",
                element_id=rid,
                parent_value=str(p_starts),
                candidate_value=str(c_starts),
                classification=DiffClassification.POTENTIAL_LOSS,
                message=f"Lane section count differs for road {rid}: {len(p_starts)} -> {len(c_starts)}",
            ))
            continue
        for i, (ps, cs) in enumerate(zip(p_starts, c_starts)):
            if abs(ps - cs) > config.position_tolerance_m:
                diffs.append(DiffRecord(
                    dimension="lane_section_start",
                    element_id=rid,
                    parent_value=f"{ps:.6f}",
                    candidate_value=f"{cs:.6f}",
                    classification=DiffClassification.POTENTIAL_LOSS,
                    message=f"Lane section {i} start drift on road {rid}: {ps:.4f} -> {cs:.4f}",
                ))
    return diffs


def _classify_lane_ids(
    parent: XodrSnapshot, candidate: XodrSnapshot
) -> list[DiffRecord]:
    diffs: list[DiffRecord] = []
    for rid in sorted(set(parent.roads.keys()) & set(candidate.roads.keys())):
        p_road = parent.roads[rid]
        c_road = candidate.roads[rid]
        p_ids = set()
        c_ids = set()
        for ls in p_road.lane_sections:
            for lane in (*ls.left, *ls.center, *ls.right):
                p_ids.add(lane.lane_id)
        for ls in c_road.lane_sections:
            for lane in (*ls.left, *ls.center, *ls.right):
                c_ids.add(lane.lane_id)
        for lid in sorted(p_ids - c_ids):
            diffs.append(DiffRecord(
                dimension="lane_id",
                element_id=rid,
                parent_value=str(lid),
                candidate_value=None,
                classification=DiffClassification.CRITICAL_REGRESSION,
                message=f"Lane {lid} on road {rid} deleted in candidate",
            ))
        for lid in sorted(c_ids - p_ids):
            diffs.append(DiffRecord(
                dimension="lane_id",
                element_id=rid,
                parent_value=None,
                candidate_value=str(lid),
                classification=DiffClassification.APPROVED_IMPROVEMENT,
                message=f"Lane {lid} on road {rid} added in candidate",
            ))
    return diffs


def _classify_lane_types(
    parent: XodrSnapshot, candidate: XodrSnapshot
) -> list[DiffRecord]:
    diffs: list[DiffRecord] = []
    for rid in sorted(set(parent.roads.keys()) & set(candidate.roads.keys())):
        p_road = parent.roads[rid]
        c_road = candidate.roads[rid]
        for i, (p_ls, c_ls) in enumerate(zip(p_road.lane_sections, c_road.lane_sections)):
            p_lanes = {l.lane_id: l for l in (*p_ls.left, *p_ls.center, *p_ls.right)}
            c_lanes = {l.lane_id: l for l in (*c_ls.left, *c_ls.center, *c_ls.right)}
            for lid in sorted(set(p_lanes.keys()) & set(c_lanes.keys())):
                p_lane = p_lanes[lid]
                c_lane = c_lanes[lid]
                if p_lane.lane_type != c_lane.lane_type:
                    classification = DiffClassification.POTENTIAL_LOSS
                    if c_lane.lane_type.lower() == "driving" and lid == 0:
                        classification = DiffClassification.CRITICAL_REGRESSION
                    diffs.append(DiffRecord(
                        dimension="lane_type",
                        element_id=rid,
                        parent_value=p_lane.lane_type,
                        candidate_value=c_lane.lane_type,
                        classification=classification,
                        message=f"Lane {lid} type on road {rid} section {i}: {p_lane.lane_type} -> {c_lane.lane_type}",
                    ))
    return diffs


def _classify_lane_directions(
    parent: XodrSnapshot, candidate: XodrSnapshot
) -> list[DiffRecord]:
    diffs: list[DiffRecord] = []
    for rid in sorted(set(parent.roads.keys()) & set(candidate.roads.keys())):
        p_road = parent.roads[rid]
        c_road = candidate.roads[rid]
        for i, (p_ls, c_ls) in enumerate(zip(p_road.lane_sections, c_road.lane_sections)):
            p_lanes = {l.lane_id: l for l in (*p_ls.left, *p_ls.center, *p_ls.right)}
            c_lanes = {l.lane_id: l for l in (*c_ls.left, *c_ls.center, *c_ls.right)}
            for lid in sorted(set(p_lanes.keys()) & set(c_lanes.keys())):
                if p_lanes[lid].direction != c_lanes[lid].direction:
                    diffs.append(DiffRecord(
                        dimension="lane_direction",
                        element_id=rid,
                        parent_value=p_lanes[lid].direction,
                        candidate_value=c_lanes[lid].direction,
                        classification=DiffClassification.POTENTIAL_LOSS,
                        message=f"Lane {lid} direction on road {rid} section {i}: {p_lanes[lid].direction} -> {c_lanes[lid].direction}",
                    ))
    return diffs


def _classify_lane_widths(
    parent: XodrSnapshot, candidate: XodrSnapshot, config: RoundtripConfig
) -> list[DiffRecord]:
    diffs: list[DiffRecord] = []
    for rid in sorted(set(parent.roads.keys()) & set(candidate.roads.keys())):
        p_road = parent.roads[rid]
        c_road = candidate.roads[rid]
        for i, (p_ls, c_ls) in enumerate(zip(p_road.lane_sections, c_road.lane_sections)):
            p_lanes = {l.lane_id: l for l in (*p_ls.left, *p_ls.center, *p_ls.right)}
            c_lanes = {l.lane_id: l for l in (*c_ls.left, *c_ls.center, *c_ls.right)}
            for lid in sorted(set(p_lanes.keys()) & set(c_lanes.keys())):
                p_lane = p_lanes[lid]
                c_lane = c_lanes[lid]
                p_w = p_lane.widths[0].a if p_lane.widths else 0.0
                c_w = c_lane.widths[0].a if c_lane.widths else 0.0
                if c_w < 0:
                    diffs.append(DiffRecord(
                        dimension="lane_width",
                        element_id=rid,
                        parent_value=f"{p_w:.6f}",
                        candidate_value=f"{c_w:.6f}",
                        classification=DiffClassification.CRITICAL_REGRESSION,
                        message=f"Negative lane width on road {rid} lane {lid}: {c_w:.4f}",
                    ))
                elif abs(p_w - c_w) > config.width_tolerance_m:
                    diffs.append(DiffRecord(
                        dimension="lane_width",
                        element_id=rid,
                        parent_value=f"{p_w:.6f}",
                        candidate_value=f"{c_w:.6f}",
                        classification=DiffClassification.POTENTIAL_LOSS,
                        message=f"Lane {lid} width drift on road {rid} section {i}: {p_w:.4f} -> {c_w:.4f}",
                    ))
    return diffs


def _classify_lane_links(
    parent: XodrSnapshot, candidate: XodrSnapshot
) -> list[DiffRecord]:
    diffs: list[DiffRecord] = []
    for rid in sorted(set(parent.roads.keys()) & set(candidate.roads.keys())):
        p_road = parent.roads[rid]
        c_road = candidate.roads[rid]
        for i, (p_ls, c_ls) in enumerate(zip(p_road.lane_sections, c_road.lane_sections)):
            p_lanes = {l.lane_id: l for l in (*p_ls.left, *p_ls.center, *p_ls.right)}
            c_lanes = {l.lane_id: l for l in (*c_ls.left, *c_ls.center, *c_ls.right)}
            for lid in sorted(set(p_lanes.keys()) & set(c_lanes.keys())):
                p_lane = p_lanes[lid]
                c_lane = c_lanes[lid]
                for link_type, p_link, c_link in (
                    ("lane_predecessor", p_lane.predecessor, c_lane.predecessor),
                    ("lane_successor", p_lane.successor, c_lane.successor),
                ):
                    if p_link is None and c_link is None:
                        continue
                    if p_link is None and c_link is not None:
                        diffs.append(DiffRecord(
                            dimension=link_type,
                            element_id=rid,
                            parent_value=None,
                            candidate_value=str(c_link),
                            classification=DiffClassification.APPROVED_IMPROVEMENT,
                            message=f"Lane {lid} {link_type} on road {rid} section {i} added",
                        ))
                        continue
                    if p_link is not None and c_link is None:
                        diffs.append(DiffRecord(
                            dimension=link_type,
                            element_id=rid,
                            parent_value=str(p_link),
                            candidate_value=None,
                            classification=DiffClassification.CRITICAL_REGRESSION,
                            message=f"Lane {lid} {link_type} on road {rid} section {i} removed",
                        ))
                        continue
                    if p_link != c_link:
                        diffs.append(DiffRecord(
                            dimension=link_type,
                            element_id=rid,
                            parent_value=str(p_link),
                            candidate_value=str(c_link),
                            classification=DiffClassification.POTENTIAL_LOSS,
                            message=f"Lane {lid} {link_type} on road {rid} section {i} changed",
                        ))
    return diffs


def _classify_elevation(
    parent: XodrSnapshot, candidate: XodrSnapshot, config: RoundtripConfig
) -> list[DiffRecord]:
    diffs: list[DiffRecord] = []
    for rid in sorted(set(parent.roads.keys()) & set(candidate.roads.keys())):
        p_road = parent.roads[rid]
        c_road = candidate.roads[rid]
        p_a = p_road.elevation[0].a if p_road.elevation else 0.0
        c_a = c_road.elevation[0].a if c_road.elevation else 0.0
        if abs(p_a - c_a) > config.position_tolerance_m:
            diffs.append(DiffRecord(
                dimension="elevation",
                element_id=rid,
                parent_value=f"{p_a:.6f}",
                candidate_value=f"{c_a:.6f}",
                classification=DiffClassification.POTENTIAL_LOSS,
                message=f"Elevation drift on road {rid}: {p_a:.4f} -> {c_a:.4f}",
            ))
    return diffs


def _classify_superelevation(
    parent: XodrSnapshot, candidate: XodrSnapshot, config: RoundtripConfig
) -> list[DiffRecord]:
    diffs: list[DiffRecord] = []
    for rid in sorted(set(parent.roads.keys()) & set(candidate.roads.keys())):
        p_road = parent.roads[rid]
        c_road = candidate.roads[rid]
        p_a = p_road.superelevation[0].a if p_road.superelevation else 0.0
        c_a = c_road.superelevation[0].a if c_road.superelevation else 0.0
        if abs(p_a - c_a) > config.curvature_tolerance:
            diffs.append(DiffRecord(
                dimension="superelevation",
                element_id=rid,
                parent_value=f"{p_a:.6f}",
                candidate_value=f"{c_a:.6f}",
                classification=DiffClassification.POTENTIAL_LOSS,
                message=f"Superelevation drift on road {rid}: {p_a:.6f} -> {c_a:.6f}",
            ))
    return diffs


def _classify_markings(
    parent: XodrSnapshot, candidate: XodrSnapshot
) -> list[DiffRecord]:
    diffs: list[DiffRecord] = []
    for rid in sorted(set(parent.roads.keys()) & set(candidate.roads.keys())):
        p_road = parent.roads[rid]
        c_road = candidate.roads[rid]
        p_marks = {(rm.s_offset, rm.mark_type, rm.color) for rm in p_road.road_marks}
        c_marks = {(rm.s_offset, rm.mark_type, rm.color) for rm in c_road.road_marks}
        for mark in sorted(p_marks - c_marks):
            diffs.append(DiffRecord(
                dimension="marking",
                element_id=rid,
                parent_value=str(mark),
                candidate_value=None,
                classification=DiffClassification.CRITICAL_REGRESSION,
                message=f"Road mark {mark} on road {rid} removed in candidate",
            ))
        for mark in sorted(c_marks - p_marks):
            diffs.append(DiffRecord(
                dimension="marking",
                element_id=rid,
                parent_value=None,
                candidate_value=str(mark),
                classification=DiffClassification.APPROVED_IMPROVEMENT,
                message=f"Road mark {mark} on road {rid} added in candidate",
            ))
    return diffs


def _classify_signals(
    parent: XodrSnapshot, candidate: XodrSnapshot
) -> list[DiffRecord]:
    diffs: list[DiffRecord] = []
    p_ids = {s.signal_id for s in parent.signals}
    c_ids = {s.signal_id for s in candidate.signals}
    for sid in sorted(p_ids - c_ids):
        diffs.append(DiffRecord(
            dimension="signal",
            element_id=sid,
            parent_value=sid,
            candidate_value=None,
            classification=DiffClassification.CRITICAL_REGRESSION,
            message=f"Signal {sid} removed in candidate",
        ))
    for sid in sorted(c_ids - p_ids):
        diffs.append(DiffRecord(
            dimension="signal",
            element_id=sid,
            parent_value=None,
            candidate_value=sid,
            classification=DiffClassification.APPROVED_IMPROVEMENT,
            message=f"Signal {sid} added in candidate",
        ))
    return diffs


def _classify_controllers(
    parent: XodrSnapshot, candidate: XodrSnapshot
) -> list[DiffRecord]:
    diffs: list[DiffRecord] = []
    p_ids = {c.controller_id for c in parent.controllers}
    c_ids = {c.controller_id for c in candidate.controllers}
    for cid in sorted(p_ids - c_ids):
        diffs.append(DiffRecord(
            dimension="controller",
            element_id=cid,
            parent_value=cid,
            candidate_value=None,
            classification=DiffClassification.CRITICAL_REGRESSION,
            message=f"Controller {cid} removed in candidate",
        ))
    for cid in sorted(c_ids - p_ids):
        diffs.append(DiffRecord(
            dimension="controller",
            element_id=cid,
            parent_value=None,
            candidate_value=cid,
            classification=DiffClassification.APPROVED_IMPROVEMENT,
            message=f"Controller {cid} added in candidate",
        ))
    return diffs


def _classify_objects(
    parent: XodrSnapshot, candidate: XodrSnapshot
) -> list[DiffRecord]:
    diffs: list[DiffRecord] = []
    p_ids = {o.object_id for o in parent.objects}
    c_ids = {o.object_id for o in candidate.objects}
    for oid in sorted(p_ids - c_ids):
        diffs.append(DiffRecord(
            dimension="object",
            element_id=oid,
            parent_value=oid,
            candidate_value=None,
            classification=DiffClassification.POTENTIAL_LOSS,
            message=f"Object {oid} removed in candidate",
        ))
    for oid in sorted(c_ids - p_ids):
        diffs.append(DiffRecord(
            dimension="object",
            element_id=oid,
            parent_value=None,
            candidate_value=oid,
            classification=DiffClassification.APPROVED_IMPROVEMENT,
            message=f"Object {oid} added in candidate",
        ))
    return diffs


def _classify_authority(
    parent: XodrSnapshot, candidate: XodrSnapshot
) -> DiffRecord:
    if parent.authority_class is None and candidate.authority_class is None:
        return DiffRecord(
            dimension="authority_class",
            element_id=None,
            parent_value=None,
            candidate_value=None,
            classification=DiffClassification.IDENTICAL,
            message="No authority class in either file",
        )
    if parent.authority_class is None:
        return DiffRecord(
            dimension="authority_class",
            element_id=None,
            parent_value=None,
            candidate_value=candidate.authority_class,
            classification=DiffClassification.APPROVED_IMPROVEMENT,
            message="Candidate adds authority class",
        )
    if candidate.authority_class is None:
        return DiffRecord(
            dimension="authority_class",
            element_id=None,
            parent_value=parent.authority_class,
            candidate_value=None,
            classification=DiffClassification.CRITICAL_REGRESSION,
            message="Candidate lost authority class",
        )
    if parent.authority_class == candidate.authority_class:
        return DiffRecord(
            dimension="authority_class",
            element_id=None,
            parent_value=parent.authority_class,
            candidate_value=candidate.authority_class,
            classification=DiffClassification.IDENTICAL,
            message="Authority class identical",
        )
    return DiffRecord(
        dimension="authority_class",
        element_id=None,
        parent_value=parent.authority_class,
        candidate_value=candidate.authority_class,
        classification=DiffClassification.CRITICAL_REGRESSION,
        message=f"Authority class changed: {parent.authority_class} -> {candidate.authority_class}",
    )


def _classify_drivable_graph(
    parent: XodrSnapshot, candidate: XodrSnapshot
) -> list[DiffRecord]:
    diffs: list[DiffRecord] = []
    p_components = _graph_components(parent)
    c_components = _graph_components(candidate)
    if p_components != c_components:
        diffs.append(DiffRecord(
            dimension="drivable_graph",
            element_id=None,
            parent_value=str(p_components),
            candidate_value=str(c_components),
            classification=DiffClassification.POTENTIAL_LOSS,
            message=f"Drivable graph components changed: {p_components} -> {c_components}",
        ))
    return diffs


def _graph_components(snapshot: XodrSnapshot) -> dict[str, int]:
    roads = set(snapshot.roads.keys())
    adj: dict[str, set[str]] = {rid: set() for rid in roads}
    for rid, road in snapshot.roads.items():
        for link in (road.predecessor, road.successor):
            if link and link.element_id and link.element_id in roads:
                adj[rid].add(link.element_id)
                adj[link.element_id].add(rid)
    seen: set[str] = set()
    comp_sizes: list[int] = []
    for rid in roads:
        if rid in seen:
            continue
        stack = [rid]
        seen.add(rid)
        sz = 0
        while stack:
            u = stack.pop()
            sz += 1
            for v in adj.get(u, ()):
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        comp_sizes.append(sz)
    comp_sizes.sort(reverse=True)
    return {
        "components": len(comp_sizes),
        "largest": comp_sizes[0] if comp_sizes else 0,
    }


def compute_diffs(
    parent: XodrSnapshot,
    candidate: XodrSnapshot,
    config: RoundtripConfig | None = None,
) -> tuple[DiffRecord, ...]:
    """Compute all semantic differences between parent and candidate snapshots."""
    if config is None:
        config = RoundtripConfig()

    diffs: list[DiffRecord] = []

    diffs.append(_classify_georeference(parent, candidate))
    diffs.append(_classify_header_bounds(parent, candidate))
    diffs.append(_classify_road_count(parent, candidate))
    diffs.append(_classify_junction_count(parent, candidate))
    diffs.append(_classify_total_length(parent, candidate, config))
    diffs.append(_classify_authority(parent, candidate))

    diffs.extend(_classify_road_ids(parent, candidate))
    diffs.extend(_classify_junction_ids(parent, candidate))
    diffs.extend(_classify_geometry_types(parent, candidate, config))
    diffs.extend(_classify_sampled_centreline(parent, candidate, config))
    diffs.extend(_classify_endpoints(parent, candidate, config))
    diffs.extend(_classify_curvature(parent, candidate, config))
    diffs.extend(_classify_road_links(parent, candidate))
    diffs.extend(_classify_junction_connections(parent, candidate))
    diffs.extend(_classify_lane_sections(parent, candidate, config))
    diffs.extend(_classify_lane_ids(parent, candidate))
    diffs.extend(_classify_lane_types(parent, candidate))
    diffs.extend(_classify_lane_directions(parent, candidate))
    diffs.extend(_classify_lane_widths(parent, candidate, config))
    diffs.extend(_classify_lane_links(parent, candidate))
    diffs.extend(_classify_elevation(parent, candidate, config))
    diffs.extend(_classify_superelevation(parent, candidate, config))
    diffs.extend(_classify_markings(parent, candidate))
    diffs.extend(_classify_signals(parent, candidate))
    diffs.extend(_classify_controllers(parent, candidate))
    diffs.extend(_classify_objects(parent, candidate))
    diffs.extend(_classify_drivable_graph(parent, candidate))

    return tuple(diffs)


__all__ = [
    "ControllerInfo",
    "DiffRecord",
    "DiffClassification",
    "ElevationSegment",
    "GeometrySegment",
    "JunctionConnection",
    "JunctionInfo",
    "LaneInfo",
    "LaneLink",
    "LaneSectionInfo",
    "LaneWidth",
    "ObjectInfo",
    "RoadInfo",
    "RoadLink",
    "RoadMarkInfo",
    "RoundtripConfig",
    "SignalInfo",
    "SuperelevationSegment",
    "XodrSnapshot",
    "compute_diffs",
    "parse_xodr",
]
