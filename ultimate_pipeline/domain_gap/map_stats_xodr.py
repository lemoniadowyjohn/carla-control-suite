# ultimate_pipeline/domain_gap/map_stats_xodr.py

from __future__ import annotations

import math
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple, Any

from ultimate_pipeline.core.xodr_sanitizer import _safe_float


# ============================================================
# Data container
# ============================================================

@dataclass
class XODRMapStats:
    """
    Summary statistics extracted from an OpenDRIVE map.

    All values are *aggregated* and deterministic.
    No CARLA runtime assumptions.
    """

    total_road_length: float
    num_roads: int

    avg_lane_width: float
    lane_width_samples: List[float]

    curvature_samples: List[float]

    num_junctions: int
    num_roundabouts: int

    num_traffic_lights: int
    num_buildings: int

    object_counts: Dict[str, int]

    assumptions: Dict[str, str]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)

        # Cap large vectors for JSON usability
        d["lane_width_samples"] = self.lane_width_samples[:5000]
        d["curvature_samples"] = self.curvature_samples[:5000]

        return d


# ============================================================
# Extractor
# ============================================================

class XODRMapStatsExtractor:
    """
    Extract geometric + semantic statistics from an OpenDRIVE map.

    Design goals:
      - deterministic
      - CARLA-free
      - robust to malformed XODR
    """

    MAX_CURVATURE_SAMPLES = 100_000

    # -----------------------------
    # Public API
    # -----------------------------

    @staticmethod
    def from_file(path: str) -> XODRMapStats:
        tree = ET.parse(path)
        root = tree.getroot()
        return XODRMapStatsExtractor.from_root(root)

    @staticmethod
    def from_root(root: ET.Element) -> XODRMapStats:
        roads = root.findall("road")

        total_len = 0.0
        lane_widths: List[float] = []
        curvatures: List[float] = []
        object_counts: Dict[str, int] = {}

        num_roundabouts = 0

        # -----------------------------
        # Per-road aggregation
        # -----------------------------
        for road in roads:
            length = _safe_float(road.get("length", "0"), 0.0)
            total_len += length

            if XODRMapStatsExtractor._is_roundabout(road):
                num_roundabouts += 1

            lane_widths.extend(
                XODRMapStatsExtractor._collect_lane_widths(road)
            )
            curvatures.extend(
                XODRMapStatsExtractor._collect_curvatures(road)
            )

            # Road-scoped objects
            for obj in road.findall(".//object"):
                t = obj.get("type", "unknown")
                object_counts[t] = object_counts.get(t, 0) + 1

        # -----------------------------
        # Root-level objects
        # -----------------------------
        for obj in root.findall("object"):
            t = obj.get("type", "unknown")
            object_counts[t] = object_counts.get(t, 0) + 1

        # -----------------------------
        # Post-processing
        # -----------------------------
        num_junctions = len(root.findall("junction"))
        num_traffic_lights = object_counts.get("traffic_light", 0)
        num_buildings = object_counts.get("building", 0)

        # Deterministic downsampling of curvature
        if len(curvatures) > XODRMapStatsExtractor.MAX_CURVATURE_SAMPLES:
            step = len(curvatures) // XODRMapStatsExtractor.MAX_CURVATURE_SAMPLES
            curvatures = curvatures[::step]

        avg_lane_width = (
            sum(lane_widths) / len(lane_widths)
            if lane_widths else 0.0
        )

        return XODRMapStats(
            total_road_length=total_len,
            num_roads=len(roads),
            avg_lane_width=avg_lane_width,
            lane_width_samples=lane_widths,
            curvature_samples=curvatures,
            num_junctions=num_junctions,
            num_roundabouts=num_roundabouts,
            num_traffic_lights=num_traffic_lights,
            num_buildings=num_buildings,
            object_counts=object_counts,
            assumptions={
                "lane_width_sampling": "width polynomial coefficient a at sOffset=0",
                "curvature_sampling": "arc curvature values only",
                "roundabout_detection": "road type=roundabout OR short road with arc geometry",
                "units": "meters, radians",
                "curvature_cap": str(XODRMapStatsExtractor.MAX_CURVATURE_SAMPLES),
            },
        )

    @staticmethod
    def save_json(stats: XODRMapStats, out_path: str) -> None:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(stats.to_dict(), f, indent=2)

    # ========================================================
    # Helpers
    # ========================================================

    @staticmethod
    def _is_roundabout(road: ET.Element) -> bool:
        """
        Robust roundabout detection.

        Priority:
          1) explicit <type type="roundabout">
          2) fallback heuristic (short road + arc geometry)
        """
        typ = road.find("type")
        if typ is not None and typ.get("type") == "roundabout":
            return True

        length = _safe_float(road.get("length", "0"), 0.0)
        if length > 150.0:
            return False

        return road.find(".//arc") is not None

    @staticmethod
    def _collect_lane_widths(road: ET.Element) -> List[float]:
        widths: List[float] = []

        for ls in road.findall("./lanes/laneSection"):
            for side_name in ("left", "right"):
                side = ls.find(side_name)
                if side is None:
                    continue

                for lane in side.findall("lane"):
                    if lane.get("type") != "driving":
                        continue

                    for w in lane.findall("width"):
                        a = _safe_float(w.get("a", "0"), 0.0)
                        widths.append(abs(a))

        return widths

    @staticmethod
    def _collect_curvatures(road: ET.Element) -> List[float]:
        """
        Collect curvature values from arc geometries.
        """
        curv: List[float] = []

        for geom in road.findall("./planView/geometry"):
            arc = geom.find("arc")
            if arc is not None:
                k = _safe_float(arc.get("curvature", "0"), 0.0)
                curv.append(k)

        return curv
