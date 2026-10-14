#!/usr/bin/env python3
"""Reusable XODR index - parse XODR once, query many times."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from lxml import etree
    HAS_LXML = True
except ImportError:
    import xml.etree.ElementTree as etree
    HAS_LXML = False


@dataclass
class Geometry:
    """OpenDRIVE geometry element."""
    s: float
    x: float
    y: float
    hdg: float
    length: float
    type: str  # line, arc, spiral, poly3
    params: dict[str, float] = field(default_factory=dict)


@dataclass
class Lane:
    """OpenDRIVE lane."""
    id: int
    type: str
    level: bool
    predecessor: Optional[int] = None
    successor: Optional[int] = None
    width_coeffs: list[float] = field(default_factory=list)  # a, b, c, d
    offset_coeffs: list[float] = field(default_factory=list)


@dataclass
class LaneSection:
    """OpenDRIVE lane section."""
    s0: float
    lanes: dict[int, Lane] = field(default_factory=dict)  # lane_id -> Lane


@dataclass
class Road:
    """OpenDRIVE road."""
    id: str
    name: str
    length: float
    junction_id: str = ""
    geometries: list[Geometry] = field(default_factory=list)
    lane_sections: list[LaneSection] = field(default_factory=list)
    elevation: dict = field(default_factory=dict)
    lateral_profile: dict = field(default_factory=dict)


@dataclass
class Junction:
    """OpenDRIVE junction."""
    id: str
    name: str
    connections: list[dict] = field(default_factory=list)
    controllers: list[dict] = field(default_factory=list)


@dataclass
class XodrIndex:
    """Indexed XODR document for fast queries."""
    roads: dict[str, Road] = field(default_factory=dict)  # road_id -> Road
    junctions: dict[str, Junction] = field(default_factory=dict)  # junction_id -> Junction
    total_length: float = 0.0
    header: dict = field(default_factory=dict)

    @classmethod
    def from_file(cls, xodr_path: Path) -> "XodrIndex":
        """Parse XODR file and build index."""
        if HAS_LXML:
            parser = etree.XMLParser(remove_blank_text=True)
            tree = etree.parse(str(xodr_path), parser)
        else:
            tree = etree.parse(str(xodr_path))
        root = tree.getroot()

        index = cls()

        # Parse header
        header = root.find("header")
        if header is not None:
            index.header = {
                "revMajor": header.get("revMajor"),
                "revMinor": header.get("revMinor"),
                "name": header.get("name"),
                "version": header.get("version"),
                "date": header.get("date"),
                "north": header.get("north"),
                "south": header.get("south"),
                "east": header.get("east"),
                "west": header.get("west"),
                "vendor": header.get("vendor"),
            }
            # Geo reference
            geo = header.find("geoReference")
            if geo is not None and geo.text:
                index.header["geoReference"] = geo.text.strip()

        # Parse roads
        for road_elem in root.findall("road"):
            road = cls._parse_road(road_elem)
            index.roads[road.id] = road
            index.total_length += road.length

        # Parse junctions
        for junction_elem in root.findall("junction"):
            junction = cls._parse_junction(junction_elem)
            index.junctions[junction.id] = junction

        return index

    @classmethod
    def _parse_road(cls, elem) -> Road:
        road = Road(
            id=elem.get("id"),
            name=elem.get("name", ""),
            length=float(elem.get("length", 0)),
            junction_id=elem.get("junction", ""),
        )

        # Parse planView geometries
        planview = elem.find("planView")
        if planview is not None:
            for geo_elem in planview.findall("geometry"):
                s = float(geo_elem.get("s", 0))
                x = float(geo_elem.get("x", 0))
                y = float(geo_elem.get("y", 0))
                hdg = float(geo_elem.get("hdg", 0))
                length = float(geo_elem.get("length", 0))

                geo = Geometry(s=s, x=x, y=y, hdg=hdg, length=length, type="")

                # Parse geometry type
                for child in geo_elem:
                    if child.tag == "line":
                        geo.type = "line"
                    elif child.tag == "arc":
                        geo.type = "arc"
                        geo.params["curvature"] = float(child.get("curvature", 0))
                    elif child.tag == "spiral":
                        geo.type = "spiral"
                        geo.params["curvStart"] = float(child.get("curvStart", 0))
                        geo.params["curvEnd"] = float(child.get("curvEnd", 0))
                    elif child.tag == "poly3":
                        geo.type = "poly3"
                        geo.params["a"] = float(child.get("a", 0))
                        geo.params["b"] = float(child.get("b", 0))
                        geo.params["c"] = float(child.get("c", 0))
                        geo.params["d"] = float(child.get("d", 0))

                road.geometries.append(geo)

        # Parse lanes
        lanes_elem = elem.find("lanes")
        if lanes_elem is not None:
            # Lane offset
            lane_offset = lanes_elem.find("laneOffset")
            if lane_offset is not None:
                road.lateral_profile["laneOffset"] = lane_offset.get("a", "0")

            for ls_elem in lanes_elem.findall("laneSection"):
                s0 = float(ls_elem.get("s", 0))
                ls = LaneSection(s0=s0)

                # Center lanes
                center = ls_elem.find("center")
                if center is not None:
                    for lane_elem in center.findall("lane"):
                        lane = cls._parse_lane(lane_elem)
                        ls.lanes[lane.id] = lane

                # Right lanes
                right = ls_elem.find("right")
                if right is not None:
                    for lane_elem in right.findall("lane"):
                        lane = cls._parse_lane(lane_elem)
                        ls.lanes[lane.id] = lane

                # Left lanes
                left = ls_elem.find("left")
                if left is not None:
                    for lane_elem in left.findall("lane"):
                        lane = cls._parse_lane(lane_elem)
                        ls.lanes[lane.id] = lane

                road.lane_sections.append(ls)

        # Parse elevation profile
        elevation = elem.find("elevationProfile")
        if elevation is not None:
            road.elevation = {"elevations": []}
            for elev in elevation.findall("elevation"):
                road.elevation["elevations"].append({
                    "s": float(elev.get("s", 0)),
                    "a": float(elev.get("a", 0)),
                    "b": float(elev.get("b", 0)),
                    "c": float(elev.get("c", 0)),
                    "d": float(elev.get("d", 0)),
                })

        # Parse lateral profile
        lateral = elem.find("lateralProfile")
        if lateral is not None:
            road.lateral_profile["superelevations"] = []
            for sup in lateral.findall("superelevation"):
                road.lateral_profile["superelevations"].append({
                    "s": float(sup.get("s", 0)),
                    "a": float(sup.get("a", 0)),
                    "b": float(sup.get("b", 0)),
                    "c": float(sup.get("c", 0)),
                    "d": float(sup.get("d", 0)),
                })

        return road

    @classmethod
    def _parse_lane(cls, elem) -> Lane:
        lane = Lane(
            id=int(elem.get("id", 0)),
            type=elem.get("type", "driving"),
            level=elem.get("level", "false").lower() == "true",
        )

        link = elem.find("link")
        if link is not None:
            pred = link.find("predecessor")
            if pred is not None:
                lane.predecessor = int(pred.get("id", 0))
            succ = link.find("successor")
            if succ is not None:
                lane.successor = int(succ.get("id", 0))

        # Width
        width = elem.find("width")
        if width is not None:
            lane.width_coeffs = [
                float(width.get("a", 0)),
                float(width.get("b", 0)),
                float(width.get("c", 0)),
                float(width.get("d", 0)),
            ]

        # Lane offset
        offset = elem.find("offset")
        if offset is not None:
            lane.offset_coeffs = [
                float(offset.get("a", 0)),
                float(offset.get("b", 0)),
                float(offset.get("c", 0)),
                float(offset.get("d", 0)),
            ]

        return lane

    @classmethod
    def _parse_junction(cls, elem) -> Junction:
        junction = Junction(
            id=elem.get("id"),
            name=elem.get("name", ""),
        )

        for conn in elem.findall("connection"):
            junction.connections.append({
                "id": conn.get("id"),
                "incomingRoad": conn.get("incomingRoad"),
                "connectingRoad": conn.get("connectingRoad"),
                "contactPoint": conn.get("contactPoint"),
            })
            for lane_link in conn.findall("laneLink"):
                junction.connections[-1].setdefault("laneLinks", []).append({
                    "from": lane_link.get("from"),
                    "to": lane_link.get("to"),
                })

        for ctrl in elem.findall("controller"):
            junction.controllers.append({
                "id": ctrl.get("id"),
                "type": ctrl.get("type"),
                "sequence": ctrl.get("sequence"),
            })

        return junction

    # Query methods
    def get_road(self, road_id: str) -> Optional[Road]:
        return self.roads.get(road_id)

    def get_junction(self, junction_id: str) -> Optional[Junction]:
        return self.junctions.get(junction_id)

    def get_roads_in_junction(self, junction_id: str) -> list[str]:
        junction = self.get_junction(junction_id)
        if not junction:
            return []
        return list(set(c["connectingRoad"] for c in junction.connections))

    def sample_road_centerline(self, road_id: str, ds: float = 1.0) -> list[dict]:
        """Sample road centerline at interval ds (meters)."""
        road = self.get_road(road_id)
        if not road:
            return []

        points = []
        for geo in road.geometries:
            s = geo.s
            while s < geo.s + geo.length:
                pt = self._eval_geometry(geo, s)
                if pt:
                    points.append(pt)
                s += ds

        return points

    def _eval_geometry(self, geo: Geometry, s: float) -> Optional[dict]:
        """Evaluate geometry at position s (relative to road start)."""
        t = s - geo.s
        if t < 0 or t > geo.length:
            return None

        if geo.type == "line":
            x = geo.x + t * math.cos(geo.hdg)
            y = geo.y + t * math.sin(geo.hdg)
            hdg = geo.hdg
        elif geo.type == "arc":
            curv = geo.params.get("curvature", 0)
            if abs(curv) < 1e-10:
                x = geo.x + t * math.cos(geo.hdg)
                y = geo.y + t * math.sin(geo.hdg)
                hdg = geo.hdg
            else:
                r = 1.0 / curv
                theta = curv * t
                x = geo.x + r * (math.sin(geo.hdg + theta) - math.sin(geo.hdg))
                y = geo.y - r * (math.cos(geo.hdg + theta) - math.cos(geo.hdg))
                hdg = geo.hdg + theta
        elif geo.type == "spiral":
            # Approximate with small line segments
            curv_start = geo.params.get("curvStart", 0)
            curv_end = geo.params.get("curvEnd", 0)
            if abs(curv_end - curv_start) < 1e-10:
                curv = curv_start
                r = 1.0 / curv if abs(curv) > 1e-10 else float('inf')
                if r == float('inf'):
                    x = geo.x + t * math.cos(geo.hdg)
                    y = geo.y + t * math.sin(geo.hdg)
                    hdg = geo.hdg
                else:
                    theta = curv * t
                    x = geo.x + r * (math.sin(geo.hdg + theta) - math.sin(geo.hdg))
                    y = geo.y - r * (math.cos(geo.hdg + theta) - math.cos(geo.hdg))
                    hdg = geo.hdg + theta
            else:
                # Linear curvature change
                curv = curv_start + (curv_end - curv_start) * (t / geo.length)
                r = 1.0 / curv if abs(curv) > 1e-10 else float('inf')
                if r == float('inf'):
                    x = geo.x + t * math.cos(geo.hdg)
                    y = geo.y + t * math.sin(geo.hdg)
                    hdg = geo.hdg
                else:
                    theta = curv * t
                    x = geo.x + r * (math.sin(geo.hdg + theta) - math.sin(geo.hdg))
                    y = geo.y - r * (math.cos(geo.hdg + theta) - math.cos(geo.hdg))
                    hdg = geo.hdg + theta
        else:
            # poly3 or unknown - approximate
            x = geo.x + t * math.cos(geo.hdg)
            y = geo.y + t * math.sin(geo.hdg)
            hdg = geo.hdg

        return {"s": s, "x": x, "y": y, "hdg": hdg, "road_id": geo.type}

    def save(self, path: Path):
        """Save index to JSON for fast reloading."""
        data = {
            "schema": "xodr_index/v1",
            "roads": {rid: self._road_to_dict(r) for rid, r in self.roads.items()},
            "junctions": {jid: self._junction_to_dict(j) for jid, j in self.junctions.items()},
            "total_length": self.total_length,
            "header": self.header,
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "XodrIndex":
        """Load index from JSON."""
        data = json.loads(path.read_text(encoding="utf-8"))
        index = cls()
        index.roads = {rid: cls._dict_to_road(d) for rid, d in data["roads"].items()}
        index.junctions = {jid: cls._dict_to_junction(d) for jid, d in data["junctions"].items()}
        index.total_length = data["total_length"]
        index.header = data.get("header", {})
        return index

    def _road_to_dict(self, road: Road) -> dict:
        return {
            "id": road.id,
            "name": road.name,
            "length": road.length,
            "junction_id": road.junction_id,
            "geometries": [
                {
                    "s": g.s, "x": g.x, "y": g.y,
                    "hdg": g.hdg, "length": g.length,
                    "type": g.type, "params": g.params,
                } for g in road.geometries
            ],
            "lane_sections": [
                {
                    "s0": ls.s0,
                    "lanes": {str(lid): self._lane_to_dict(l) for lid, l in ls.lanes.items()},
                } for ls in road.lane_sections
            ],
            "elevation": road.elevation,
            "lateral_profile": road.lateral_profile,
        }

    def _lane_to_dict(self, lane: Lane) -> dict:
        return {
            "id": lane.id,
            "type": lane.type,
            "level": lane.level,
            "predecessor": lane.predecessor,
            "successor": lane.successor,
            "width_coeffs": lane.width_coeffs,
            "offset_coeffs": lane.offset_coeffs,
        }

    def _junction_to_dict(self, junction: Junction) -> dict:
        return {
            "id": junction.id,
            "name": junction.name,
            "connections": junction.connections,
            "controllers": junction.controllers,
        }

    @classmethod
    def _dict_to_road(cls, data: dict) -> Road:
        road = Road(
            id=data["id"],
            name=data["name"],
            length=data["length"],
            junction_id=data["junction_id"],
        )
        road.geometries = [
            Geometry(
                s=g["s"], x=g["x"], y=g["y"],
                hdg=g["hdg"], length=g["length"],
                type=g["type"], params=g["params"],
            ) for g in data["geometries"]
        ]
        road.lane_sections = [
            LaneSection(
                s0=ls["s0"],
                lanes={int(lid): cls._dict_to_lane(l) for lid, l in ls["lanes"].items()},
            ) for ls in data["lane_sections"]
        ]
        road.elevation = data.get("elevation", {})
        road.lateral_profile = data.get("lateral_profile", {})
        return road

    @classmethod
    def _dict_to_lane(cls, data: dict) -> Lane:
        return Lane(
            id=data["id"],
            type=data["type"],
            level=data["level"],
            predecessor=data.get("predecessor"),
            successor=data.get("successor"),
            width_coeffs=data.get("width_coeffs", []),
            offset_coeffs=data.get("offset_coeffs", []),
        )

    @classmethod
    def _dict_to_junction(cls, data: dict) -> Junction:
        return Junction(
            id=data["id"],
            name=data["name"],
            connections=data.get("connections", []),
            controllers=data.get("controllers", []),
        )


# Add missing imports
import math
from typing import Optional