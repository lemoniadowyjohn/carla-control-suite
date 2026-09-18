# ultimate_pipeline/geometry/crosssection_repair.py

import xml.etree.ElementTree as ET
from typing import Dict

from ultimate_pipeline.core.xodr_sanitizer import _safe_float


class CrossSectionRepair:
    @staticmethod
    def _lane_width(lane: ET.Element) -> float:
        w = lane.find("width")
        if w is None:
            return 0.0
        return _safe_float(w.get("a", "0"), 0.0)

    @staticmethod
    def enforce(root: ET.Element, max_gap: float = 0.3):
        print("\nCrossSectionRepair: enforcing continuity...")
        adjusted = 0
        for road in root.findall("road"):
            secs = list(road.findall("./lanes/laneSection"))
            if len(secs) < 2:
                continue
            secs.sort(key=lambda s: _safe_float(s.get("s", "0"), 0.0))

            for i in range(len(secs) - 1):
                a = secs[i]
                b = secs[i + 1]
                for side_name in ("left", "right"):
                    sa = a.find(side_name)
                    sb = b.find(side_name)
                    if sa is None or sb is None:
                        continue
                    lanes_a: Dict[str, ET.Element] = {
                        ln.get("id"): ln for ln in sa.findall("lane") if ln.get("id") is not None
                    }
                    lanes_b: Dict[str, ET.Element] = {
                        ln.get("id"): ln for ln in sb.findall("lane") if ln.get("id") is not None
                    }
                    for lid, la in lanes_a.items():
                        lb = lanes_b.get(lid)
                        if lb is None:
                            continue
                        wa = CrossSectionRepair._lane_width(la)
                        wb = CrossSectionRepair._lane_width(lb)
                        if wa > 0 and wb > 0 and abs(wa - wb) > max_gap:
                            w_node = lb.find("width")
                            if w_node is not None:
                                w_node.set("a", f"{wa:.3f}")
                                adjusted += 1
        print(f"✓ CrossSectionRepair: adjusted {adjusted} lane width jumps.")
