# ultimate_pipeline/geometry/elevation_smoother.py

import xml.etree.ElementTree as ET

from ultimate_pipeline.core.xodr_sanitizer import _safe_float


class ElevationSmoother:
    """
    Simple elevation smoothing:
    - clamps 'a' coefficient magnitude
    - sets b,c,d to zero (flat profile) if wild
    """

    @staticmethod
    def smooth(root: ET.Element, max_a: float = 20.0):
        count = 0
        for road in root.findall("road"):
            profile = road.find("elevationProfile")
            if profile is None:
                continue
            for ev in profile.findall("elevation"):
                a = _safe_float(ev.get("a", "0"), 0.0)
                if abs(a) > max_a:
                    a = 0.0
                ev.set("a", f"{a:.6f}")
                ev.set("b", "0.0")
                ev.set("c", "0.0")
                ev.set("d", "0.0")
                count += 1
        print(f"✓ ElevationSmoother: processed {count} elevation entries.")
