# geometry/lane_width_clamp.py
import xml.etree.ElementTree as ET
from ultimate_pipeline.core.xodr_sanitizer import _safe_float

class LaneWidthClamp:

    MIN_WIDTH = 0.25   # CARLA safe
    MAX_WIDTH = 8.0

    @staticmethod
    def clamp(root: ET.Element):
        for width in root.findall(".//lanes/lane/width"):
            a = _safe_float(width.get("a", "0"), 0.0)

            if a < LaneWidthClamp.MIN_WIDTH:
                width.set("a", f"{LaneWidthClamp.MIN_WIDTH:.3f}")
            if a > LaneWidthClamp.MAX_WIDTH:
                width.set("a", f"{LaneWidthClamp.MAX_WIDTH:.3f}")
