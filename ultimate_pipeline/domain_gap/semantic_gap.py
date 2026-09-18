# ultimate_pipeline/domain_gap/semantic_gap.py
from __future__ import annotations
import xml.etree.ElementTree as ET
from typing import Dict, Any
from ultimate_pipeline.config.settings import SETTINGS

class SemanticGap:
    """Semantic-level domain gap between two OpenDRIVE maps.

    Fix: compute() must return a dict (some repo states had stub compute()).
    """

    @staticmethod
    def _safe_float(x: str | None) -> float:
        try:
            return float(x) if x is not None else 0.0
        except Exception:
            return 0.0

    @staticmethod
    def _count_objects_by_type(root: ET.Element) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for obj in root.findall(".//object"):
            t = (obj.get("type") or "unknown").lower().strip()
            counts[t] = counts.get(t, 0) + 1
        return counts

    @staticmethod
    def _count_traffic_lights(root: ET.Element) -> int:
        return sum(
            1 for obj in root.findall(".//object")
            if "traffic" in (obj.get("type") or "").lower() and "light" in (obj.get("type") or "").lower()
        )

    @staticmethod
    def _count_lane_markings(root: ET.Element) -> int:
        return len(root.findall(".//laneMark"))

    @staticmethod
    def _road_type_lengths(root: ET.Element) -> Dict[str, float]:
        lengths: Dict[str, float] = {}
        for road in root.findall("road"):
            length = SemanticGap._safe_float(road.get("length"))
            typ = road.find("type")
            rtype = (typ.get("type") if typ is not None else "unknown").lower().strip()
            lengths[rtype] = lengths.get(rtype, 0.0) + length
        return lengths

    @staticmethod
    def _total_road_length(root: ET.Element) -> float:
        return sum(SemanticGap._safe_float(r.get("length")) for r in root.findall("road"))

    @staticmethod
    def compare(manual_xodr: str, auto_xodr: str) -> Dict[str, Any]:
        rm = ET.parse(manual_xodr).getroot()
        ra = ET.parse(auto_xodr).getroot()

        obj_m = SemanticGap._count_objects_by_type(rm)
        obj_a = SemanticGap._count_objects_by_type(ra)
        all_obj_types = sorted(set(obj_m) | set(obj_a))
        obj_delta = {t: obj_a.get(t, 0) - obj_m.get(t, 0) for t in all_obj_types}

        rt_m = SemanticGap._road_type_lengths(rm)
        rt_a = SemanticGap._road_type_lengths(ra)
        all_rtypes = sorted(set(rt_m) | set(rt_a))
        rt_delta = {t: rt_a.get(t, 0.0) - rt_m.get(t, 0.0) for t in all_rtypes}

        total_len_m = max(SemanticGap._total_road_length(rm), 1e-6)
        total_len_a = max(SemanticGap._total_road_length(ra), 1e-6)

        rt_norm_delta = {
            t: (rt_a.get(t, 0.0) / total_len_a) - (rt_m.get(t, 0.0) / total_len_m)
            for t in all_rtypes
        }

        tl_m = SemanticGap._count_traffic_lights(rm)
        tl_a = SemanticGap._count_traffic_lights(ra)
        tl_density_m = tl_m / total_len_m
        tl_density_a = tl_a / total_len_a

        lm_m = SemanticGap._count_lane_markings(rm)
        lm_a = SemanticGap._count_lane_markings(ra)
        lm_density_m = lm_m / total_len_m
        lm_density_a = lm_a / total_len_a

        return {
            "objects": {"manual": obj_m, "auto": obj_a, "delta": obj_delta},
            "road_types": {"manual_length": rt_m, "auto_length": rt_a, "delta_length": rt_delta, "delta_normalized": rt_norm_delta},
            "traffic_lights": {"manual_count": tl_m, "auto_count": tl_a, "manual_density": tl_density_m, "auto_density": tl_density_a, "delta_density": tl_density_a - tl_density_m},
            "lane_markings": {"manual_count": lm_m, "auto_count": lm_a, "manual_density": lm_density_m, "auto_density": lm_density_a, "delta_density": lm_density_a - lm_density_m},
            "meta": {"manual_total_road_length": total_len_m, "auto_total_road_length": total_len_a, "normalized": True,
                     "settings": {"reference": getattr(SETTINGS, "PROJECT_NAME", "unknown")}},
        }

    @classmethod
    def compute(cls, manual_xodr: str, auto_xodr: str) -> Dict[str, Any]:
        return cls.compare(manual_xodr, auto_xodr)
