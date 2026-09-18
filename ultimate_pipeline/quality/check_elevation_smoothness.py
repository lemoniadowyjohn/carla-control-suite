# ultimate_pipeline/quality/check_elevation_smoothness.py

from __future__ import annotations

import math
from typing import List, Dict, Any
from xml.etree.ElementTree import Element


class ElevationSmoothnessGate:
    """
    Checks that elevation changes along roads are not insanely spiky.

    This is a heuristic: we compute |dz| / ds between consecutive elevations
    and flag if too many segments exceed a threshold.
    """

    MAX_DZ_PER_M = 0.25  # 25cm per meter ~ 14 degrees slope
    MAX_SPIKY_SEGMENTS_PER_ROAD = 10

    @staticmethod
    def validate(root: Element) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []

        for road in root.findall("road"):
            rid = road.get("id", "UNKNOWN")
            elev_profile = road.find("./elevationProfile")
            if elev_profile is None:
                continue

            elems = elev_profile.findall("elevation")
            elems = sorted(elems, key=lambda e: float(e.get("s", "0")))
            spiky = 0

            for i in range(1, len(elems)):
                p = elems[i - 1]
                c = elems[i]
                s0 = float(p.get("s", "0"))
                s1 = float(c.get("s", "0"))
                a0 = float(p.get("a", "0"))
                a1 = float(c.get("a", "0"))

                ds = max(1e-3, s1 - s0)
                dz = a1 - a0
                slope = abs(dz) / ds

                if slope > ElevationSmoothnessGate.MAX_DZ_PER_M:
                    spiky += 1

            if spiky > ElevationSmoothnessGate.MAX_SPIKY_SEGMENTS_PER_ROAD:
                issues.append(
                    {
                        "road_id": rid,
                        "type": "elevation_spiky",
                        "spiky_segments": spiky,
                    }
                )

        return issues
