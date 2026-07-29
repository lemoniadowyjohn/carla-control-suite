from __future__ import annotations
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True)
class LaneLink:
    from_lane: int
    to_lane: int

    @classmethod
    def from_xml(cls, elem: ET.Element) -> LaneLink:
        return cls(from_lane=int(elem.get("from", 0)), to_lane=int(elem.get("to", 0)))


@dataclass(frozen=True)
class ConnectingRoad:
    connection_id: str
    incoming_road: str
    connecting_road: str
    contact_point: str
    lane_links: tuple[LaneLink, ...] = ()

    @classmethod
    def from_xml(cls, elem: ET.Element) -> ConnectingRoad:
        lane_links = tuple(
            LaneLink.from_xml(le) for le in elem.findall("laneLink")
        )
        return cls(
            connection_id=elem.get("id", ""),
            incoming_road=elem.get("incomingRoad", ""),
            connecting_road=elem.get("connectingRoad", ""),
            contact_point=elem.get("contactPoint", ""),
            lane_links=lane_links,
        )


@dataclass(frozen=True)
class JunctionRef:
    junction_id: str
    incoming_roads: tuple[str, ...] = ()
    targets: tuple[str, ...] = ()


@dataclass
class JunctionModel:
    id: str
    name: str
    connections: dict[str, ConnectingRoad] = field(default_factory=dict)
    region: str = ""
    position: tuple[float, float] | None = None

    @property
    def connecting_road_ids(self) -> tuple[str, ...]:
        return tuple(c.connecting_road for c in self.connections.values())

    @property
    def incoming_road_ids(self) -> tuple[str, ...]:
        return tuple({c.incoming_road for c in self.connections.values()})

    def find_by_connecting_road(self, road_id: str) -> list[ConnectingRoad]:
        return [c for c in self.connections.values() if c.connecting_road == road_id]

    def find_by_incoming_road(self, road_id: str) -> list[ConnectingRoad]:
        return [c for c in self.connections.values() if c.incoming_road == road_id]

    @classmethod
    def from_xml(cls, elem: ET.Element) -> JunctionModel:
        j = cls(
            id=elem.get("id", ""),
            name=elem.get("name", ""),
        )
        for conn_elem in elem.findall("connection"):
            conn = ConnectingRoad.from_xml(conn_elem)
            j.connections[conn.connection_id] = conn
        return j

    @classmethod
    def from_xodr_file(cls, path: str) -> list[JunctionModel]:
        tree = ET.parse(path)
        root = tree.getroot()
        junctions: list[JunctionModel] = []
        for je in root.findall("junction"):
            junctions.append(cls.from_xml(je))
        return junctions

    @classmethod
    def from_xodr_string(cls, xml_str: str) -> list[JunctionModel]:
        root = ET.fromstring(xml_str)
        junctions: list[JunctionModel] = []
        for je in root.findall("junction"):
            junctions.append(cls.from_xml(je))
        return junctions

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "connections": [
                {
                    "connection_id": c.connection_id,
                    "incoming_road": c.incoming_road,
                    "connecting_road": c.connecting_road,
                    "contact_point": c.contact_point,
                    "lane_links": [{"from": ll.from_lane, "to": ll.to_lane} for ll in c.lane_links],
                }
                for c in self.connections.values()
            ],
        }


class JunctionValidator:
    def __init__(self, junctions: list[JunctionModel], road_ids: set[str]):
        self.junctions = junctions
        self.road_ids = road_ids

    def validate_connectivity(self) -> list[str]:
        errors: list[str] = []
        for j in self.junctions:
            for c in j.connections.values():
                if c.incoming_road not in self.road_ids:
                    errors.append(f"Junction {j.id}: incoming road {c.incoming_road} not found")
                if c.connecting_road not in self.road_ids:
                    errors.append(f"Junction {j.id}: connecting road {c.connecting_road} not found")
        return errors

    def validate_no_duplicate_connections(self) -> list[str]:
        errors: list[str] = []
        for j in self.junctions:
            seen: set[tuple[str, str, str]] = set()
            for c in j.connections.values():
                key = (c.incoming_road, c.connecting_road, c.contact_point)
                if key in seen:
                    errors.append(f"Junction {j.id}: duplicate connection {key}")
                seen.add(key)
        return errors

    def validate_lane_links(self, road_lane_counts: dict[str, int]) -> list[str]:
        errors: list[str] = []
        for j in self.junctions:
            for c in j.connections.values():
                for ll in c.lane_links:
                    road_id = c.incoming_road
                    lane_count = road_lane_counts.get(road_id, 0)
                    if abs(ll.from_lane) > lane_count and lane_count > 0:
                        errors.append(
                            f"Junction {j.id} connection {c.connection_id}: "
                            f"from_lane {ll.from_lane} exceeds lane count {lane_count} on road {road_id}"
                        )
        return errors

    def validate_all(self, road_lane_counts: dict[str, int] | None = None) -> list[str]:
        errors = []
        errors.extend(self.validate_connectivity())
        errors.extend(self.validate_no_duplicate_connections())
        if road_lane_counts:
            errors.extend(self.validate_lane_links(road_lane_counts))
        return errors


def summarize_junctions(junctions: list[JunctionModel]) -> dict:
    total = len(junctions)
    incoming_set: set[str] = set()
    connecting_set: set[str] = set()
    for j in junctions:
        incoming_set.update(j.incoming_road_ids)
        connecting_set.update(j.connecting_road_ids)
    return {
        "total_junctions": total,
        "unique_incoming_roads": len(incoming_set),
        "unique_connecting_roads": len(connecting_set),
        "junctions": [j.to_dict() for j in junctions],
    }
