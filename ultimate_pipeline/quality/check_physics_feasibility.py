# ultimate_pipeline/quality/check_physics_feasibility.py

from __future__ import annotations

import math
from typing import List, Dict, Any
from xml.etree.ElementTree import Element

from ultimate_pipeline.quality.check_elevation_smoothness import ElevationSmoothnessGate


class PhysicsFeasibilityChecker:
    """
    Very coarse physics sanity:

    - reuse elevation smoothness (slope)
    - check lane width not absurdly small or huge
    """

    MIN_LANE_WIDTH = 1.0
    MAX_LANE_WIDTH = 7.0

    # Lane types that must have reasonable widths for vehicle physics
    DRIVEABLE_LANE_TYPES = {"driving", "entry", "exit", "onRamp", "offRamp", "connectingRamp"}

    @staticmethod
    def validate(root: Element) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []

        # 1) elevation slope issues
        issues.extend(ElevationSmoothnessGate.validate(root))

        # 2) lane width extremes - only for driveable lanes
        # Non-driveable lanes (sidewalk, shoulder, parking, etc.) have different valid ranges
        for road in root.findall("road"):
            rid = road.get("id", "UNKNOWN")
            for lane in road.findall(".//lane"):
                lane_type = lane.get("type", "driving")
                # Only enforce width constraints on driveable lane types
                if lane_type not in PhysicsFeasibilityChecker.DRIVEABLE_LANE_TYPES:
                    continue
                for width in lane.findall("width"):
                    raw_a = width.get("a", "3.5")
                    try:
                        a = float(raw_a)
                    except (TypeError, ValueError):
                        a = float("nan")
                    # A bare float() only catches parse *exceptions* --
                    # float("nan") parses without error, and `nan < MIN` /
                    # `nan > MAX` are both always False in IEEE-754, so a
                    # corrupted width coefficient would silently produce zero
                    # issues instead of being flagged as physically
                    # infeasible/unverifiable.
                    if not math.isfinite(a):
                        issues.append(
                            {
                                "road_id": rid,
                                "lane_type": lane_type,
                                "type": "lane_width_non_finite",
                                "value": raw_a,
                            }
                        )
                        continue
                    if a < PhysicsFeasibilityChecker.MIN_LANE_WIDTH:
                        issues.append(
                            {
                                "road_id": rid,
                                "lane_type": lane_type,
                                "type": "lane_too_narrow",
                                "value": a,
                            }
                        )
                    elif a > PhysicsFeasibilityChecker.MAX_LANE_WIDTH:
                        issues.append(
                            {
                                "road_id": rid,
                                "lane_type": lane_type,
                                "type": "lane_too_wide",
                                "value": a,
                            }
                        )

        return issues
