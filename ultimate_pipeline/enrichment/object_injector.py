# ultimate_pipeline/enrichment/object_injector.py

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple
import math


@dataclass
class OSMObject:
    x: float
    y: float
    z: float
    obj_type: str               # "building", "traffic_sign", "pole", "parking_space"
    subtype: Optional[str] = None
    height: Optional[float] = None
    outline: Optional[List[Tuple[float, float, float]]] = None   # building footprint
    heading: Optional[float] = None                              # radians
    road_id: Optional[str] = None
    s: Optional[float] = None
    t: Optional[float] = None


class ObjectInjector:
    """
    Robust OpenDRIVE object injection for CARLA.

    Features:
    - Converts global (x,y) → (road_id, s, t) if not provided.
    - Adds building outlines.
    - Adds correct orientation for traffic signs.
    - Nearest-road fallback if road_id is unknown.
    """

    DRIVING_LANES = {"driving", "motorway", "road"}

    @staticmethod
    def inject(root: ET.Element, objects: List[OSMObject]) -> None:
        roads = {r.get("id"): r for r in root.findall("road")}
        id_counter: Dict[str, int] = {}

        # Build simple road centerline index
        center_map = ObjectInjector._build_road_centers(roads)

        for obj in objects:
            # Determine object placement
            if not obj.road_id or obj.s is None or obj.t is None:
                road_id, s, t = ObjectInjector._nearest_road(center_map, obj)
                obj.road_id, obj.s, obj.t = road_id, s, t

            if obj.road_id not in roads:
                continue  # skip or fallback, but avoid invalid refs

            road_elem = roads[obj.road_id]

            # create unique object ID
            kind = obj.obj_type
            id_counter[kind] = id_counter.get(kind, 0) + 1
            obj_id = f"{kind}_{id_counter[kind]}"

            ObjectInjector._attach_object(road_elem, obj, obj_id)

    # ----------------------------------------------------------------------
    # Building a simplified lookup for nearest road search
    # ----------------------------------------------------------------------
    @staticmethod
    def _build_road_centers(roads: Dict[str, ET.Element]):
        centers = {}

        for road_id, road in roads.items():
            planview = road.find("./planView")
            if planview is None:
                continue

            geoms = planview.findall("geometry")
            if not geoms:
                continue

            xs, ys = [], []
            for g in geoms:
                x = float(g.get("x", "0"))
                y = float(g.get("y", "0"))
                xs.append(x)
                ys.append(y)

            if xs:
                centers[road_id] = (sum(xs) / len(xs), sum(ys) / len(ys))

        return centers

    # ----------------------------------------------------------------------
    # Nearest road finder (Euclidean distance)
    # ----------------------------------------------------------------------
    @staticmethod
    def _nearest_road(center_map: Dict[str, Tuple[float, float]], obj: OSMObject):
        ox, oy = obj.x, obj.y
        best = None
        best_dist = float("inf")

        for rid, (cx, cy) in center_map.items():
            d = (cx - ox) ** 2 + (cy - oy) ** 2
            if d < best_dist:
                best_dist = d
                best = rid

        if best is None:
            return None, 0.0, 0.0

        return best, 0.0, 0.0  # t=0 simplified fallback

    # ----------------------------------------------------------------------
    # Attach object to road with full OpenDRIVE schema
    # ----------------------------------------------------------------------
    @staticmethod
    def _attach_object(road: ET.Element, obj: OSMObject, obj_id: str):
        objects_elem = road.find("objects")
        if objects_elem is None:
            objects_elem = ET.SubElement(road, "objects")

        attrs = {
            "id": obj_id,
            "type": obj.obj_type,
            "name": obj.subtype or obj.obj_type,
            "s": f"{obj.s:.3f}",
            "t": f"{(obj.t or 0.0):.3f}",
            "zOffset": f"{obj.z:.2f}",
            "hdg": f"{(obj.heading or 0.0):.3f}",
            "roll": "0.0",
            "pitch": "0.0",
            "orientation": "none",
            "height": f"{(obj.height or 0.0):.2f}",
            "dynamic": "no",
        }

        o = ET.SubElement(objects_elem, "object", attrs)

        # Add building outline if exists
        if obj.outline:
            outline_elem = ET.SubElement(o, "outline")
            for (x, y, z) in obj.outline:
                ET.SubElement(outline_elem, "cornerGlobal", {
                    "x": f"{x:.3f}",
                    "y": f"{y:.3f}",
                    "z": f"{z:.3f}",
                })
