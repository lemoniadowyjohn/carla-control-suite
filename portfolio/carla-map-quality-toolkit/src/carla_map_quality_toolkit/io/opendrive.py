from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class GeometrySegment:
    s: float
    x: float
    y: float
    hdg: float
    length: float
    kind: str
    curvature: float = 0.0


@dataclass(frozen=True)
class PolynomialRecord:
    s_offset: float
    a: float
    b: float
    c: float
    d: float

    def value(self, ds: float) -> float:
        return self.a + self.b * ds + self.c * ds**2 + self.d * ds**3


@dataclass(frozen=True)
class Lane:
    lane_id: int
    lane_type: str
    widths: tuple[PolynomialRecord, ...] = ()
    predecessor: int | None = None
    successor: int | None = None


@dataclass(frozen=True)
class LaneSection:
    s: float
    lanes: dict[int, Lane]


@dataclass(frozen=True)
class RoadLink:
    element_type: str
    element_id: str
    contact_point: str | None = None


@dataclass(frozen=True)
class Road:
    road_id: str
    length: float
    junction_id: str
    geometries: tuple[GeometrySegment, ...]
    lane_offsets: tuple[PolynomialRecord, ...]
    lane_sections: tuple[LaneSection, ...]
    predecessor: RoadLink | None = None
    successor: RoadLink | None = None

    @property
    def lane_ids(self) -> set[int]:
        return {lane_id for section in self.lane_sections for lane_id in section.lanes}


@dataclass(frozen=True)
class JunctionLaneLink:
    from_lane: int
    to_lane: int


@dataclass(frozen=True)
class JunctionConnection:
    connection_id: str
    incoming_road: str
    connecting_road: str
    contact_point: str
    lane_links: tuple[JunctionLaneLink, ...]


@dataclass(frozen=True)
class Junction:
    junction_id: str
    connections: tuple[JunctionConnection, ...]


@dataclass(frozen=True)
class OpenDriveMap:
    roads: dict[str, Road] = field(default_factory=dict)
    junctions: dict[str, Junction] = field(default_factory=dict)
    geo_reference: str | None = None


def _float(node: ET.Element, name: str, default: float = 0.0) -> float:
    return float(node.attrib.get(name, default))


def _parse_poly(node: ET.Element, offset_name: str) -> PolynomialRecord:
    return PolynomialRecord(
        s_offset=_float(node, offset_name),
        a=_float(node, "a"),
        b=_float(node, "b"),
        c=_float(node, "c"),
        d=_float(node, "d"),
    )


def _parse_lane(lane_node: ET.Element) -> Lane:
    widths = tuple(
        sorted(
            (_parse_poly(width, "sOffset") for width in lane_node.findall("width")),
            key=lambda rec: rec.s_offset,
        )
    )
    link_node = lane_node.find("link")
    pred = succ = None
    if link_node is not None:
        pred_node = link_node.find("predecessor")
        succ_node = link_node.find("successor")
        if pred_node is not None:
            pred = int(pred_node.attrib["id"])
        if succ_node is not None:
            succ = int(succ_node.attrib["id"])
    return Lane(
        lane_id=int(lane_node.attrib["id"]),
        lane_type=lane_node.attrib.get("type", "none"),
        widths=widths,
        predecessor=pred,
        successor=succ,
    )


def _parse_road_link(link_node: ET.Element | None, tag: str) -> RoadLink | None:
    if link_node is None:
        return None
    node = link_node.find(tag)
    if node is None:
        return None
    return RoadLink(
        element_type=node.attrib.get("elementType", "road"),
        element_id=node.attrib["elementId"],
        contact_point=node.attrib.get("contactPoint"),
    )


def parse_opendrive(path: str | Path) -> OpenDriveMap:
    """Parse a pragmatic OpenDRIVE subset needed by the quality checks.

    Supported plan-view primitives are ``line`` and ``arc``. Lane width and
    laneOffset cubic polynomials are retained for downstream geometry checks.
    """
    tree = ET.parse(Path(path))
    root = tree.getroot()

    header = root.find("header")
    geo_reference = None
    if header is not None:
        geo = header.find("geoReference")
        if geo is not None and geo.text:
            geo_reference = geo.text.strip()

    roads: dict[str, Road] = {}
    for road_node in root.findall("road"):
        geometries: list[GeometrySegment] = []
        plan_view = road_node.find("planView")
        if plan_view is not None:
            for geom in plan_view.findall("geometry"):
                if geom.find("line") is not None:
                    kind, curvature = "line", 0.0
                elif (arc := geom.find("arc")) is not None:
                    kind, curvature = "arc", float(arc.attrib["curvature"])
                else:
                    raise ValueError("Only OpenDRIVE line and arc geometries are supported")
                geometries.append(
                    GeometrySegment(
                        s=_float(geom, "s"),
                        x=_float(geom, "x"),
                        y=_float(geom, "y"),
                        hdg=_float(geom, "hdg"),
                        length=_float(geom, "length"),
                        kind=kind,
                        curvature=curvature,
                    )
                )

        lanes_node = road_node.find("lanes")
        lane_offsets: tuple[PolynomialRecord, ...] = ()
        lane_sections: list[LaneSection] = []
        if lanes_node is not None:
            lane_offsets = tuple(
                sorted(
                    (_parse_poly(node, "s") for node in lanes_node.findall("laneOffset")),
                    key=lambda rec: rec.s_offset,
                )
            )
            for section_node in lanes_node.findall("laneSection"):
                lanes: dict[int, Lane] = {}
                for side in ("left", "center", "right"):
                    side_node = section_node.find(side)
                    if side_node is not None:
                        for lane_node in side_node.findall("lane"):
                            lane = _parse_lane(lane_node)
                            lanes[lane.lane_id] = lane
                lane_sections.append(LaneSection(s=_float(section_node, "s"), lanes=lanes))

        link_node = road_node.find("link")
        road = Road(
            road_id=road_node.attrib["id"],
            length=float(road_node.attrib["length"]),
            junction_id=road_node.attrib.get("junction", "-1"),
            geometries=tuple(sorted(geometries, key=lambda g: g.s)),
            lane_offsets=lane_offsets,
            lane_sections=tuple(sorted(lane_sections, key=lambda s: s.s)),
            predecessor=_parse_road_link(link_node, "predecessor"),
            successor=_parse_road_link(link_node, "successor"),
        )
        roads[road.road_id] = road

    junctions: dict[str, Junction] = {}
    for j_node in root.findall("junction"):
        connections: list[JunctionConnection] = []
        for c_node in j_node.findall("connection"):
            lane_links = tuple(
                JunctionLaneLink(
                    from_lane=int(ll.attrib["from"]),
                    to_lane=int(ll.attrib["to"]),
                )
                for ll in c_node.findall("laneLink")
            )
            connections.append(
                JunctionConnection(
                    connection_id=c_node.attrib["id"],
                    incoming_road=c_node.attrib["incomingRoad"],
                    connecting_road=c_node.attrib["connectingRoad"],
                    contact_point=c_node.attrib.get("contactPoint", "start"),
                    lane_links=lane_links,
                )
            )
        jid = j_node.attrib["id"]
        junctions[jid] = Junction(junction_id=jid, connections=tuple(connections))

    return OpenDriveMap(roads=roads, junctions=junctions, geo_reference=geo_reference)
