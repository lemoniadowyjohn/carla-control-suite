# ultimate_pipeline/quality/check_physics_feasibility.py

from __future__ import annotations

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

    @staticmethod
    def validate(root: Element) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []

        # 1) elevation slope issues
        issues.extend(ElevationSmoothnessGate.validate(root))

        # 2) lane width extremes
        for road in root.findall("road"):
            rid = road.get("id", "UNKNOWN")
            for width in road.findall(".//lane/width"):
                a = float(width.get("a", "3.5"))
                if a < PhysicsFeasibilityChecker.MIN_LANE_WIDTH:
                    issues.append(
                        {
                            "road_id": rid,
                            "type": "lane_too_narrow",
                            "value": a,
                        }
                    )
                elif a > PhysicsFeasibilityChecker.MAX_LANE_WIDTH:
                    issues.append(
                        {
                            "road_id": rid,
                            "type": "lane_too_wide",
                            "value": a,
                        }
                    )

        return issues
