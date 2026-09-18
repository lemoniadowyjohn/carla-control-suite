# ultimate_pipeline/domain_gap/map_stats_osm.py

from __future__ import annotations

import math
import json
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple, Optional


XY = Tuple[float, float]


# ============================================================
# Data containers
# ============================================================

@dataclass
class OSMRoad:
    polyline: List[XY]
    highway: str
    lanes: Optional[int]
    maxspeed: Optional[float]
    turn_lanes: Optional[str] = None    # OSM turn:lanes e.g. "left|straight|right"
    traffic_sign: Optional[str] = None  # OSM traffic_sign e.g. "de:206", "de:274-50"


@dataclass
class OSMMapStats:
    """
    Coarse geometric + semantic statistics extracted from OSM.
    All values are deterministic and reproducible.
    """

    total_road_length: float
    num_roads: int

    avg_lane_width: float                  # inferred (meters)
    curvature_samples: List[float]
    maxspeed_samples: List[float]

    road_type_counts: Dict[str, int]
    road_type_lengths: Dict[str, float]

    assumptions: Dict[str, str]

    def to_dict(self) -> Dict:
        d = asdict(self)

        # cap large vectors for JSON readability
        d["curvature_samples"] = self.curvature_samples[:5000]
        d["maxspeed_samples"] = self.maxspeed_samples[:5000]

        return d


# ============================================================
# Extractor
# ============================================================

class OSMMapStatsExtractor:
    """
    Compute geometry + semantics from an OSM road network.

    This module is intentionally:
        - CARLA-free
        - XODR-free
        - deterministic
    """

    DEFAULT_LANE_WIDTH_M = 3.0
    MAX_CURVATURE_SAMPLES = 100_000

    @staticmethod
    def from_osm_roads(osm_roads: List[OSMRoad]) -> OSMMapStats:
        total_len = 0.0
        curvatures: List[float] = []
        maxspeeds: List[float] = []

        type_counts: Dict[str, int] = {}
        type_lengths: Dict[str, float] = {}

        inferred_lane_widths: List[float] = []

        for r in osm_roads:
            length = OSMMapStatsExtractor._polyline_length(r.polyline)
            total_len += length

            # ---------------------------
            # Road type stats
            # ---------------------------
            if r.highway:
                type_counts[r.highway] = type_counts.get(r.highway, 0) + 1
                type_lengths[r.highway] = type_lengths.get(r.highway, 0.0) + length

            # ---------------------------
            # Speed stats
            # ---------------------------
            if r.maxspeed is not None:
                maxspeeds.append(r.maxspeed)

            # ---------------------------
            # Lane width inference
            # ---------------------------
            if r.lanes and r.lanes > 0:
                inferred_lane_widths.append(
                    r.lanes * OSMMapStatsExtractor.DEFAULT_LANE_WIDTH_M
                )

            # ---------------------------
            # Curvature sampling
            # ---------------------------
            curvatures.extend(
                OSMMapStatsExtractor._approximate_polyline_curvature(r.polyline)
            )

        # deterministic downsampling (important!)
        if len(curvatures) > OSMMapStatsExtractor.MAX_CURVATURE_SAMPLES:
            step = len(curvatures) // OSMMapStatsExtractor.MAX_CURVATURE_SAMPLES
            curvatures = curvatures[::step]

        avg_lane_width = (
            sum(inferred_lane_widths) / len(inferred_lane_widths)
            if inferred_lane_widths
            else OSMMapStatsExtractor.DEFAULT_LANE_WIDTH_M
        )

        return OSMMapStats(
            total_road_length=total_len,
            num_roads=len(osm_roads),
            avg_lane_width=avg_lane_width,
            curvature_samples=curvatures,
            maxspeed_samples=maxspeeds,
            road_type_counts=type_counts,
            road_type_lengths=type_lengths,
            assumptions={
                "lane_width_model": "lanes × 3.0m (fallback: 3.0m)",
                "curvature_model": "angle change per segment / segment length",
                "coordinate_system": "projected OSM coordinates (meters)",
                "sampling_cap": str(OSMMapStatsExtractor.MAX_CURVATURE_SAMPLES),
            },
        )

    @staticmethod
    def save_json(stats: OSMMapStats, out_path: str) -> None:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(stats.to_dict(), f, indent=2)

    # ========================================================
    # Helpers
    # ========================================================

    @staticmethod
    def _polyline_length(poly: List[XY]) -> float:
        length = 0.0
        for (x1, y1), (x2, y2) in zip(poly, poly[1:]):
            length += math.hypot(x2 - x1, y2 - y1)
        return length

    @staticmethod
    def _approximate_polyline_curvature(poly: List[XY]) -> List[float]:
        """
        Approximate curvature as turning angle per unit length.
        """
        if len(poly) < 3:
            return []

        curv: List[float] = []

        for i in range(1, len(poly) - 1):
            x0, y0 = poly[i - 1]
            x1, y1 = poly[i]
            x2, y2 = poly[i + 1]

            v1x, v1y = x1 - x0, y1 - y0
            v2x, v2y = x2 - x1, y2 - y1

            n1 = math.hypot(v1x, v1y)
            n2 = math.hypot(v2x, v2y)
            if n1 == 0 or n2 == 0:
                continue

            dot = v1x * v2x + v1y * v2y
            cos_angle = max(-1.0, min(1.0, dot / (n1 * n2)))
            angle = math.acos(cos_angle)

            seg_len = 0.5 * (n1 + n2)
            if seg_len > 0:
                curv.append(angle / seg_len)

        return curv
