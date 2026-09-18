# ultimate_pipeline/enrichment/building_extruder.py
from __future__ import annotations

import xml.etree.ElementTree as ET
import hashlib
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class BuildingFootprint:
    """
    Building polygon in *projected map coordinates* (meters).
    """
    footprint: List[Tuple[float, float]]
    height: float = 10.0
    id: str | None = None
    name: str | None = None

    def __init__(self, footprint, height=10.0, id=None, name=None):
        self.footprint = footprint
        self.height = height
        self.id = id
        self.name = name


class BuildingExtruder:
    """
    Insert <object type="building"> into the XODR file.

    Buildings are attached inside individual <road><objects> elements (correct
    OpenDRIVE schema placement).  Each building is assigned to its nearest road
    by centroid distance; absolute cornerGlobal coordinates are used so CARLA
    can place the mesh regardless of the chosen road's local (s,t) frame.
    """

    @staticmethod
    def _road_centroid_map(root: ET.Element) -> dict:
        """Return {road_id: (cx, cy)} using planView geometry start-points."""
        centroids: dict = {}
        for road in root.findall("road"):
            rid = road.get("id")
            planview = road.find("planView")
            if planview is None:
                continue
            geoms = planview.findall("geometry")
            if not geoms:
                continue
            xs = [float(g.get("x", "0")) for g in geoms]
            ys = [float(g.get("y", "0")) for g in geoms]
            if xs:
                centroids[rid] = (sum(xs) / len(xs), sum(ys) / len(ys))
        return centroids

    @staticmethod
    def _nearest_road_id(centroids: dict, bx: float, by: float):
        best_id = None
        best_d = float("inf")
        for rid, (cx, cy) in centroids.items():
            d = (cx - bx) ** 2 + (cy - by) ** 2
            if d < best_d:
                best_d = d
                best_id = rid
        return best_id

    @staticmethod
    def add_buildings(root: ET.Element, buildings: List[BuildingFootprint]) -> int:
        centroids = BuildingExtruder._road_centroid_map(root)
        roads = {r.get("id"): r for r in root.findall("road")}

        inserted = 0

        for b in buildings:
            # Defensive checks
            if not b.footprint or len(b.footprint) < 3:
                continue

            pts = b.footprint

            # Compute building centroid for road assignment
            bx = sum(p[0] for p in pts) / len(pts)
            by = sum(p[1] for p in pts) / len(pts)

            rid = BuildingExtruder._nearest_road_id(centroids, bx, by)
            if rid is None or rid not in roads:
                continue

            road_elem = roads[rid]
            objects_elem = road_elem.find("objects")
            if objects_elem is None:
                objects_elem = ET.SubElement(road_elem, "objects")

            fp_bytes = (";".join([f"{x:.3f},{y:.3f}" for x, y in pts]) + f"|h={b.height:.2f}").encode("utf-8")
            bid = b.id or ("bld_" + hashlib.md5(fp_bytes).hexdigest()[:12])

            obj = ET.SubElement(objects_elem, "object", {
                "id": bid,
                "name": b.name or bid,
                "type": "building",
                "s": "0.0",
                "t": "0.0",
                "zOffset": "0.0",
                "orientation": "absolute",
                "height": f"{b.height:.2f}",
                "hdg": "0.0",
                "length": "0.0",
                "width": "0.0",
            })

            outline = ET.SubElement(obj, "outline", {
                "id": "0",
                "fillType": "concrete",
            })

            if pts[0] != pts[-1]:
                pts = pts + [pts[0]]

            for x, y in pts:
                ET.SubElement(outline, "cornerGlobal", {
                    "x": f"{x:.3f}",
                    "y": f"{y:.3f}",
                    "z": "0.0",
                })

            inserted += 1

        return inserted

    # -----------------------------------------------------------------
    # Legacy API – your pipeline still calls insert_buildings()
    # -----------------------------------------------------------------
    @staticmethod
    def insert_buildings(root: ET.Element, buildings: List[BuildingFootprint]) -> int:
        return BuildingExtruder.add_buildings(root, buildings)
