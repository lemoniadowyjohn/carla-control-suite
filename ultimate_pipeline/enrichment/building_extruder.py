# ultimate_pipeline/enrichment/building_extruder.py

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
    """

    @staticmethod
    def _ensure_objects_parent(root: ET.Element) -> ET.Element:
        objs = root.find("objects")
        if objs is None:
            objs = ET.SubElement(root, "objects")
        return objs

    @staticmethod
    def add_buildings(root: ET.Element, buildings: List[BuildingFootprint]) -> int:
        objs_parent = BuildingExtruder._ensure_objects_parent(root)

        inserted = 0

        for idx, b in enumerate(buildings):
            # Defensive checks
            if not b.footprint or len(b.footprint) < 3:
                continue

            fp_bytes = (";".join([f"{x:.3f},{y:.3f}" for x,y in b.footprint]) + f"|h={b.height:.2f}").encode('utf-8')
            bid = b.id or ("bld_" + hashlib.md5(fp_bytes).hexdigest()[:12])


            obj = ET.SubElement(objs_parent, "object", {
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
                "fillType": "concrete"
            })

            pts = b.footprint
            if pts[0] != pts[-1]:
                pts = pts + [pts[0]]

            for x, y in pts:
                ET.SubElement(outline, "cornerGlobal", {
                    "x": f"{x:.3f}",
                    "y": f"{y:.3f}",
                    "z": "0.0"
                })

            inserted += 1

        return inserted

    # -----------------------------------------------------------------
    # Legacy API – your pipeline still calls insert_buildings()
    # -----------------------------------------------------------------
    @staticmethod
    def insert_buildings(root: ET.Element, buildings: List[BuildingFootprint]) -> int:
        return BuildingExtruder.add_buildings(root, buildings)
