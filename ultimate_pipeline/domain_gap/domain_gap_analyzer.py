"""
DEPRECATED:
Replaced by ultimate_pipeline.run_full_domain_gap

Library code may still be imported,
but this file is not a pipeline entrypoint.
"""

# ultimate_pipeline/analysis/domain_gap_analyzer.py

import xml.etree.ElementTree as ET
import math
from typing import Dict, Any, List
from collections import Counter


class MapMetrics:
    """
    Lightweight container for map statistics; JSON-serializable.
    """
    def __init__(self):
        self.num_roads = 0
        self.num_junctions = 0
        self.lane_widths = []          # meters
        self.curvatures = []           # 1/m
        self.objects = Counter()       # object type -> count
        self.lane_types = Counter()    # lane type -> count
        self.intersection_degrees = [] # number of incoming roads per junction

    def to_dict(self) -> Dict[str, Any]:
        return {
            "num_roads": self.num_roads,
            "num_junctions": self.num_junctions,
            "lane_widths_mean": _safe_mean(self.lane_widths),
            "lane_widths_std": _safe_std(self.lane_widths),
            "curvature_mean": _safe_mean(self.curvatures),
            "curvature_std": _safe_std(self.curvatures),
            "objects": dict(self.objects),
            "lane_types": dict(self.lane_types),
            "intersection_degree_mean": _safe_mean(self.intersection_degrees),
            "intersection_degree_std": _safe_std(self.intersection_degrees),
        }


def _safe_mean(xs: List[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _safe_std(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _safe_mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


class DomainGapAnalyzer:
    """
    Compute map-level statistics from an XODR file and
    compare manual vs. automatic maps.
    """

    @staticmethod
    def compute_metrics(xodr_path: str) -> MapMetrics:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
        m = MapMetrics()

        # basic counts
        roads = root.findall("road")
        junctions = root.findall("junction")
        m.num_roads = len(roads)
        m.num_junctions = len(junctions)

        # lane stats
        for lane in root.findall(".//lane"):
            lane_type = lane.get("type", "none")
            m.lane_types[lane_type] += 1

            for w in lane.findall("width"):
                try:
                    a = float(w.get("a", "0.0"))
                    m.lane_widths.append(a)
                except ValueError:
                    continue

        # curvature stats (from <arc curvature> – approximated)
        for geo in root.findall(".//planView/geometry"):
            arc = geo.find("arc")
            if arc is not None:
                try:
                    curv = float(arc.get("curvature", "0.0"))
                    m.curvatures.append(abs(curv))
                except ValueError:
                    continue

        # object counts
        for o in root.findall(".//object"):
            t = o.get("type", "unknown")
            m.objects[t] += 1

        # intersection degree: number of connections per junction
        for j in junctions:
            conns = j.findall("connection")
            m.intersection_degrees.append(len(conns))

        return m

    @staticmethod
    def compare(manual_xodr: str, auto_xodr: str) -> Dict[str, Any]:
        """
        Compute metrics for both maps and return a dict with:
        - metrics_manual
        - metrics_auto
        - deltas (auto - manual)
        """
        m_man = DomainGapAnalyzer.compute_metrics(manual_xodr)
        m_aut = DomainGapAnalyzer.compute_metrics(auto_xodr)

        d_man = m_man.to_dict()
        d_aut = m_aut.to_dict()

        deltas = {}
        for key in ["num_roads", "num_junctions",
                    "lane_widths_mean", "curvature_mean",
                    "intersection_degree_mean"]:
            deltas[key] = d_aut.get(key, 0.0) - d_man.get(key, 0.0)

        return {
            "metrics_manual": d_man,
            "metrics_auto": d_aut,
            "deltas": deltas,
        }
