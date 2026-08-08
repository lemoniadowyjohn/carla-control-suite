# ultimate_pipeline/enrichment/object_injector.py

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple


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


# --------------------------------------------------------------------------
# Crosswalk authoring (Stage I). Reuses the canonical <object> + <outline>
# schema defined above. Additive only: inserts <object type="crosswalk"> under
# <road><objects>; never mutates roads/junctions/geometries/signals.
# --------------------------------------------------------------------------
CROSSWALK_DEFAULT_DEPTH_M = 4.0  # along-road marking extent


def _crossing_subtype(crossing_type: Optional[str]) -> str:
    ct = (crossing_type or "").lower()
    if ct == "zebra":
        return "crosswalk_zebra"
    if ct == "marked":
        return "crosswalk_marked"
    if ct in ("traffic_signals", "uncontrolled", "island"):
        return "crosswalk_signals"
    return "crosswalk"


def _bearing(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    return math.degrees(math.atan2(dy, dx))


def _crosswalk_outline(start: Tuple[float, float],
                       end: Tuple[float, float],
                       depth: float = CROSSWALK_DEFAULT_DEPTH_M) -> List[Tuple[float, float, float]]:
    """Closed quad for a crosswalk marking.

    start->end is the curb-to-curb centerline (across-road); `depth` is the
    along-road extent, applied perpendicular to the centerline on its road-side.
    Returns 5 vertices (first == last for a closed polygon), CCW in the +Y-forward
    local frame used by OpenDRIVE.
    """
    cx = (end[0] - start[0]) / 2.0
    cy = (end[1] - start[1]) / 2.0
    seg = math.hypot(cx, cy)
    if seg < 1e-6:
        nx, ny = depth / 2.0, 0.0
    else:
        nx = -(cy / seg) * (depth / 2.0)
        ny = (cx / seg) * (depth / 2.0)
    s_left = (start[0] - nx, start[1] - ny, 0.0)
    s_right = (start[0] + nx, start[1] + ny, 0.0)
    e_right = (end[0] + nx, end[1] + ny, 0.0)
    e_left = (end[0] - nx, end[1] - ny, 0.0)
    return [s_left, s_right, e_right, e_left, s_left]


@dataclass
class CrosswalkSpec:
    """One authoritative crosswalk to author. Sourced from the Stage H ledger."""
    osm_id: str
    crossing_type: Optional[str]
    start_m: Tuple[float, float]
    end_m: Tuple[float, float]
    road_id: str
    s: float
    t: float
    road_ids_all: Tuple[str, ...] = ()
    disposition: str = "INSERTED"
    reason: str = ""


class CrosswalkInjector:
    """Deterministic, idempotent crosswalk <object> injector.

    Reuses ObjectInjector._attach_object (canonical OpenDRIVE object schema).
    Idempotent across runs: an object id `crosswalk_{osm_id}` is unique and
    skipped if already present in the target XODR.
    """

    @staticmethod
    def existing_ids(root: ET.Element) -> set:
        ids = set()
        for obj in root.iter("object"):
            if (obj.get("type") or "").lower() == "crosswalk":
                oid = obj.get("id")
                if oid:
                    ids.add(oid)
        return ids

    @staticmethod
    def inject(root: ET.Element, specs: List["CrosswalkSpec"]) -> Dict[str, int]:
        roads_by_id = {r.get("id"): r for r in root.findall("road")}
        existing = CrosswalkInjector.existing_ids(root)
        stats = {"written": 0, "skipped_existing": 0, "skipped_no_road": 0}
        for spec in specs:
            obj_id = f"crosswalk_{spec.osm_id}"
            if obj_id in existing:
                stats["skipped_existing"] += 1
                continue
            road = roads_by_id.get(spec.road_id)
            if road is None:
                stats["skipped_no_road"] += 1
                continue
            start, end = spec.start_m, spec.end_m
            obj = OSMObject(
                x=(start[0] + end[0]) / 2.0,
                y=(start[1] + end[1]) / 2.0,
                z=0.0,
                obj_type="crosswalk",
                subtype=_crossing_subtype(spec.crossing_type),
                height=0.0,
                outline=_crosswalk_outline(start, end),
                heading=math.radians(_bearing(start, end)),
                road_id=spec.road_id,
                s=spec.s,
                t=spec.t,
            )
            ObjectInjector._attach_object(road, obj, obj_id)
            existing.add(obj_id)
            stats["written"] += 1
        return stats
