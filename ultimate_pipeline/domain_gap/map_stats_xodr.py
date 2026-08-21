# ultimate_pipeline/domain_gap/map_stats_xodr.py

from __future__ import annotations

import math
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple, Any

from ultimate_pipeline.core.xodr_sanitizer import _safe_float
from opendrive_geometry.primitives import param_poly3_curvature_at
from opendrive_geometry.errors import ParamPoly3Error


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

    # Interior arc-length fractions at which paramPoly3/spiral curvature is sampled.
    # Interior points avoid endpoint tangent degeneracies (s=0 cusps).
    CURVATURE_SAMPLE_FRACTIONS = (0.25, 0.5, 0.75)

    # Physical upper bound on |curvature| (1/m); radius >= 1 m. Values above this arise from
    # degenerate/ill-conditioned paramPoly3 segments (near-cusp tangent), not real road
    # centerlines, and are excluded so a handful of spikes cannot dominate downstream
    # histograms (a single kappa=37 outlier otherwise stretches the L1-hist range).
    MAX_PHYSICAL_CURVATURE = 1.0

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
                "curvature_sampling": (
                    "arc + spiral + paramPoly3 (sampled at interior arc-length "
                    "fractions 0.25/0.5/0.75); <line> excluded; |curvature|<=1.0 1/m "
                    "physical bound (degenerate segments dropped)"
                ),
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
        Collect curvature values from curved planView geometry.

        Handles the three OpenDRIVE curvature-bearing primitives:
          - <arc curvature="k">          -> constant curvature k
          - <spiral curvStart curvEnd>   -> curvature is linear in s (clothoid)
          - <paramPoly3 ...>             -> curvature sampled at interior arc-length points
        <line> segments carry no curvature and contribute nothing.

        paramPoly3 is the dominant format emitted by both Osm2Odr/SUMO (auto) and
        RoadRunner (manual); collecting arc-only (the previous behaviour) yielded empty
        or near-empty samples and made the RQ1 curvature gap a measurement artifact.
        """
        curv: List[float] = []

        for geom in road.findall("./planView/geometry"):
            arc = geom.find("arc")
            if arc is not None:
                curv.append(_safe_float(arc.get("curvature", "0"), 0.0))
                continue

            spiral = geom.find("spiral")
            if spiral is not None:
                cs = _safe_float(spiral.get("curvStart", "0"), 0.0)
                ce = _safe_float(spiral.get("curvEnd", "0"), 0.0)
                # Clothoid curvature is linear in the arc-length fraction.
                curv.extend(
                    cs + (ce - cs) * f
                    for f in XODRMapStatsExtractor.CURVATURE_SAMPLE_FRACTIONS
                )
                continue

            ppoly = geom.find("paramPoly3")
            if ppoly is not None:
                length = _safe_float(geom.get("length", "0"), 0.0)
                if length <= 0.0:
                    continue
                p_range = ppoly.get("pRange")  # "normalized" | "arcLength" | None
                coeffs = [
                    _safe_float(ppoly.get(name, "0"), 0.0)
                    for name in ("aU", "bU", "cU", "dU", "aV", "bV", "cV", "dV")
                ]
                for f in XODRMapStatsExtractor.CURVATURE_SAMPLE_FRACTIONS:
                    s = length * f
                    try:
                        k = param_poly3_curvature_at(*coeffs, p_range, length, s)
                    except (ParamPoly3Error, ValueError, ArithmeticError):
                        continue
                    if math.isfinite(k):
                        curv.append(k)

        # Exclude non-physical curvature from degenerate/ill-conditioned segments so it
        # cannot dominate downstream distribution comparisons.
        bound = XODRMapStatsExtractor.MAX_PHYSICAL_CURVATURE
        return [k for k in curv if abs(k) <= bound]
