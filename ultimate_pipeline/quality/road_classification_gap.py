# ultimate_pipeline/quality/road_classification_gap.py

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from typing import Dict, Any


class RoadClassificationGap:
    """
    Compare road "class" / "type" distributions between manual and auto XODR.

    We look at:
      - <type roadType="...">
      - or <userData> tags like <param name="road_class" value="...">
    """

    @staticmethod
    def _extract_classes(xodr_path: str) -> Counter:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
        counts: Counter = Counter()

        for road in root.findall("road"):
            rtype = None

            # Native OpenDRIVE type
            t = road.find("type")
            if t is not None and "type" in t.attrib:
                rtype = t.attrib["type"]

            # Try userData param
            if rtype is None:
                user_data = road.find("userData")
                if user_data is not None:
                    for p in user_data.findall("param"):
                        if p.get("name") in ("road_class", "class", "hierarchy"):
                            rtype = p.get("value")
                            break

            if rtype is None:
                rtype = "unknown"

            counts[rtype] += 1

        return counts

    @staticmethod
    def compute(manual_xodr: str, auto_xodr: str) -> Dict[str, Any]:
        man = RoadClassificationGap._extract_classes(manual_xodr)
        aut = RoadClassificationGap._extract_classes(auto_xodr)

        all_keys = set(man.keys()) | set(aut.keys())

        diff = {}
        for k in all_keys:
            diff[k] = {
                "manual": int(man.get(k, 0)),
                "auto": int(aut.get(k, 0)),
                "delta": int(aut.get(k, 0) - man.get(k, 0)),
            }

        return {
            "manual_counts": {k: int(v) for k, v in man.items()},
            "auto_counts": {k: int(v) for k, v in aut.items()},
            "per_class_diff": diff,
        }
