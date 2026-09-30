from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OSMNode:
    node_id: str
    lon: float
    lat: float


@dataclass(frozen=True)
class OSMWay:
    way_id: str
    node_ids: tuple[str, ...]
    tags: dict[str, str]


@dataclass(frozen=True)
class OSMHighwayMap:
    nodes: dict[str, OSMNode]
    highways: tuple[OSMWay, ...]


def parse_osm_highways(path: str | Path) -> OSMHighwayMap:
    """Parse OSM XML and retain nodes plus ways carrying a ``highway`` tag."""
    root = ET.parse(Path(path)).getroot()
    nodes = {
        node.attrib["id"]: OSMNode(
            node_id=node.attrib["id"],
            lon=float(node.attrib["lon"]),
            lat=float(node.attrib["lat"]),
        )
        for node in root.findall("node")
    }

    highways: list[OSMWay] = []
    for way in root.findall("way"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in way.findall("tag")}
        if "highway" not in tags:
            continue
        node_ids = tuple(nd.attrib["ref"] for nd in way.findall("nd"))
        missing = tuple(node_id for node_id in node_ids if node_id not in nodes)
        if missing:
            raise ValueError(f"OSM way {way.attrib['id']} references missing nodes: {missing}")
        highways.append(OSMWay(way_id=way.attrib["id"], node_ids=node_ids, tags=tags))

    return OSMHighwayMap(nodes=nodes, highways=tuple(highways))
