# ultimate_pipeline/quality/check_semantic_overlap.py

from __future__ import annotations

from typing import List, Dict, Any
from xml.etree.ElementTree import Element


class SemanticOverlapChecker:
    """
    Heuristic overlap checker.

    Flags if roads & sidewalks/buildings share the same id or bounding tag
    patterns that look suspicious. This is intentionally lightweight and
    conservative; it's mainly a hook for LLM explanation.
    """

    @staticmethod
    def validate(root: Element) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []

        # Very simple: count roads and objects per road id, flag if "too many"
        for road in root.findall("road"):
            rid = road.get("id", "UNKNOWN")

            objects = road.findall(".//objects/object")
            sidewalks = [o for o in objects if o.get("type") == "sidewalk"]
            buildings = [o for o in objects if o.get("type") == "building"]

            # Overly simplistic: if we have buildings AND sidewalks directly on the same road
            # it's not necessarily wrong, but it's something to review.
            if sidewalks and buildings:
                issues.append(
                    {
                        "road_id": rid,
                        "type": "sidewalk_building_overlap_candidate",
                        "n_sidewalks": len(sidewalks),
                        "n_buildings": len(buildings),
                    }
                )

        return issues
