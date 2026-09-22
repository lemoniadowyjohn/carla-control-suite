"""Canonical Topology Index for OpenDRIVE."""
from __future__ import annotations
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

@dataclass
class RoadIndex:
    id: str
    predecessors: List[Tuple[str, str]] = field(default_factory=list) # (elementType, elementId)
    successors: List[Tuple[str, str]] = field(default_factory=list)
    lane_sections: List[LaneSectionIndex] = field(default_factory=list)

@dataclass
class LaneSectionIndex:
    s: float
    lanes: Dict[int, str] = field(default_factory=dict) # laneId -> type

@dataclass
class JunctionIndex:
    id: str
    connections: Dict[str, ConnectionIndex] = field(default_factory=dict)

@dataclass
class ConnectionIndex:
    id: str
    incoming_road: str
    connecting_road: str
    contact_point: str
    lane_links: List[Tuple[int, int]] = field(default_factory=list) # from, to

class TopologyIndex:
    def __init__(self, xodr_path: Path):
        self.roads: Dict[str, RoadIndex] = {}
        self.junctions: Dict[str, JunctionIndex] = {}
        self._parse(xodr_path)

    def _parse(self, xodr_path: Path):
        tree = ET.parse(xodr_path)
        root = tree.getroot()

        for road in root.findall("road"):
            r_id = road.get("id", "")
            r_idx = RoadIndex(id=r_id)
            link = road.find("link")
            if link is not None:
                for pred in link.findall("predecessor"):
                    r_idx.predecessors.append((pred.get("elementType", ""), pred.get("elementId", "")))
                for succ in link.findall("successor"):
                    r_idx.successors.append((succ.get("elementType", ""), succ.get("elementId", "")))
            
            for ls in road.findall(".//laneSection"):
                ls_idx = LaneSectionIndex(s=float(ls.get("s", 0.0)))
                for lane in ls.findall(".//lane"):
                    ls_idx.lanes[int(lane.get("id", 0))] = lane.get("type", "")
                r_idx.lane_sections.append(ls_idx)
            self.roads[r_id] = r_idx

        for jun in root.findall("junction"):
            j_id = jun.get("id", "")
            j_idx = JunctionIndex(id=j_id)
            for conn in jun.findall("connection"):
                c_idx = ConnectionIndex(
                    id=conn.get("id", ""),
                    incoming_road=conn.get("incomingRoad", ""),
                    connecting_road=conn.get("connectingRoad", ""),
                    contact_point=conn.get("contactPoint", "")
                )
                for ll in conn.findall("laneLink"):
                    c_idx.lane_links.append((int(ll.get("from", 0)), int(ll.get("to", 0))))
                j_idx.connections[c_idx.id] = c_idx
            self.junctions[j_id] = j_idx
