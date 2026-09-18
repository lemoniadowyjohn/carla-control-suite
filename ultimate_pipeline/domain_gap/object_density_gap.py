from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, Any
from collections import Counter


class ObjectDensityGap:
    """
    Object density domain-gap analysis for OpenDRIVE maps.

    Measures:
      - absolute object counts
      - normalized object densities (per km road length)
      - semantic-category deltas

    This avoids map-size bias and supports cross-map comparison.
    """

    # --------------------------------------------------
    # Semantic grouping (stable across maps)
    # --------------------------------------------------
    OBJECT_GROUPS = {
        "traffic": {"traffic_light", "traffic_sign", "signal"},
        "buildings": {"building"},
        "roadside": {"pole", "tree", "vegetation", "fence"},
        "props": {"static", "dynamic", "unknown"},
    }

    # --------------------------------------------------
    # Core helpers
    # --------------------------------------------------

    @staticmethod
    def _extract_road_length(root: ET.Element) -> float:
        """
        Total road length in meters.
        """
        total = 0.0
        for r in root.findall("road"):
            try:
                total += float(r.get("length", "0"))
            except Exception:
                continue
        return total

    @staticmethod
    def _count_objects(root: ET.Element) -> Counter:
        """
        Raw object counts by type.
        """
        counts = Counter()
        for obj in root.findall(".//object"):
            t = obj.get("type", "unknown")
            counts[t] += 1
        return counts

    @staticmethod
    def _group_objects(counts: Counter) -> Dict[str, int]:
        """
        Aggregate object counts into semantic groups.
        """
        grouped = {k: 0 for k in ObjectDensityGap.OBJECT_GROUPS}
        grouped["other"] = 0

        for obj_type, n in counts.items():
            matched = False
            for group, members in ObjectDensityGap.OBJECT_GROUPS.items():
                if obj_type in members:
                    grouped[group] += n
                    matched = True
                    break
            if not matched:
                grouped["other"] += n

        return grouped

    @staticmethod
    def _normalize(counts: Dict[str, int], road_len_m: float) -> Dict[str, float]:
        """
        Normalize counts per km of road.
        """
        if road_len_m <= 0:
            return {k: 0.0 for k in counts}

        km = road_len_m / 1000.0
        return {k: v / km for k, v in counts.items()}

    # --------------------------------------------------
    # Public API
    # --------------------------------------------------

    @staticmethod
    def compare(manual_xodr: str, auto_xodr: str) -> Dict[str, Any]:
        """
        Compare object densities between manual and auto maps.
        """

        rm = ET.parse(manual_xodr).getroot()
        ra = ET.parse(auto_xodr).getroot()

        # Road length
        len_m = ObjectDensityGap._extract_road_length(rm)
        len_a = ObjectDensityGap._extract_road_length(ra)

        # Raw object counts
        raw_m = ObjectDensityGap._count_objects(rm)
        raw_a = ObjectDensityGap._count_objects(ra)

        # Grouped counts
        grp_m = ObjectDensityGap._group_objects(raw_m)
        grp_a = ObjectDensityGap._group_objects(raw_a)

        # Normalized densities
        dens_m = ObjectDensityGap._normalize(grp_m, len_m)
        dens_a = ObjectDensityGap._normalize(grp_a, len_a)

        # Delta (auto − manual)
        delta = {
            k: dens_a.get(k, 0.0) - dens_m.get(k, 0.0)
            for k in set(dens_m) | set(dens_a)
        }

        return {
            "manual": {
                "road_length_m": round(len_m, 2),
                "object_counts": dict(raw_m),
                "grouped_counts": grp_m,
                "densities_per_km": dens_m,
            },
            "auto": {
                "road_length_m": round(len_a, 2),
                "object_counts": dict(raw_a),
                "grouped_counts": grp_a,
                "densities_per_km": dens_a,
            },
            "delta_density": delta,
            "assumptions": {
                "normalization": "objects per km of road",
                "grouping": "fixed semantic object groups",
                "source": "OpenDRIVE <object> elements only",
            },
        }
