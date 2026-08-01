# ultimate_pipeline/geometry/elevation_smoother.py

import xml.etree.ElementTree as ET

from ultimate_pipeline.core.xodr_sanitizer import _safe_float


class ElevationSmoother:
    """
    Elevation sanitization (NOT flattening):
    - preserves absolute elevation 'a'
    - clamps only slope-related terms if they are wild
    """

    @staticmethod
    def smooth(root: ET.Element, max_abs_b: float = 2.0):
        count = 0
        for road in root.findall("road"):
            profile = road.find("elevationProfile")
            if profile is None:
                continue

            for ev in profile.findall("elevation"):
                a = _safe_float(ev.get("a", "0"), 0.0)
                b = _safe_float(ev.get("b", "0"), 0.0)
                c = _safe_float(ev.get("c", "0"), 0.0)
                d = _safe_float(ev.get("d", "0"), 0.0)

                # Keep real-world height.
                # Only kill insane slopes.
                if abs(b) > max_abs_b:
                    b = 0.0
                    c = 0.0
                    d = 0.0

                ev.set("a", f"{a:.6f}")
                ev.set("b", f"{b:.6f}")
                ev.set("c", f"{c:.6f}")
                ev.set("d", f"{d:.6f}")
                count += 1

        print(f"✓ ElevationSmoother: processed {count} elevation entries.")
