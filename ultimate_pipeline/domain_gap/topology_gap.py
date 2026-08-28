#!/usr/bin/env python3
"""
Topology gap:
Simple adjacency summary between roads and junctions.
Counts:
  - roads
  - junctions
  - road->junction references (roads that belong to a junction)
Outputs normalized differences for a quick structural check.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, Any


def _safe_int(val: str, default: int = -1) -> int:
    try:
        return int(val)
    except Exception:
        return default


def _norm_diff(a: int, b: int) -> float:
    denom = max(1, max(a, b))
    return abs(a - b) / float(denom)


class TopologyGap:
    """
    Summarize coarse topology between two OpenDRIVE maps.
    """

    @staticmethod
    def _summary(xodr_path: str) -> Dict[str, int]:
        root = ET.parse(xodr_path).getroot()
        roads = root.findall(".//road")
        junctions = root.findall(".//junction")

        junction_refs = 0
        for r in roads:
            j_attr = r.get("junction")
            if j_attr is None:
                continue
            j_id = _safe_int(j_attr, -1)
            if j_id != -1:
                junction_refs += 1

        return {
            "roads": len(roads),
            "junctions": len(junctions),
            "road_junction_refs": junction_refs,
        }

    @staticmethod
    def compute(manual_xodr: str, auto_xodr: str) -> Dict[str, Any]:
        """
        Returns:
            {
                "manual": {...},
                "auto": {...},
                "gap": {...},
                "disabled": False,
            }
        """
        try:
            manual = TopologyGap._summary(manual_xodr)
            auto = TopologyGap._summary(auto_xodr)
            gap = {
                k: _norm_diff(manual.get(k, 0), auto.get(k, 0))
                for k in ("roads", "junctions", "road_junction_refs")
            }
            return {
                "manual": manual,
                "auto": auto,
                "gap": gap,
                "disabled": False,
            }
        except Exception as e:
            return {"disabled": True, "error": str(e)}
