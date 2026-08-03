# ultimate_pipeline/geometry/laneoffset_smoother.py

import xml.etree.ElementTree as ET
from typing import List, Tuple

from ultimate_pipeline.core.xodr_sanitizer import _safe_float


class LaneOffsetSmoother:
    @staticmethod
    def _collect_offsets(road: ET.Element) -> List[Tuple[float, ET.Element]]:
        offsets = []
        for off in road.findall("lanes/laneOffset"):
            s = _safe_float(off.get("s", "0"), 0.0)
            offsets.append((s, off))
        offsets.sort(key=lambda x: x[0])
        return offsets

    @staticmethod
    def _sanitize_coeffs(off: ET.Element):
        for k in ("a", "b", "c", "d"):
            v = _safe_float(off.get(k, "0"), 0.0)
            if abs(v) > 1000:
                v = 0.0
            off.set(k, f"{v:.6f}")

    @staticmethod
    def smooth(root: ET.Element, max_delta: float = 0.5):
        print("\nLaneOffsetSmoother: smoothing laneOffsets...")
        fixed = 0

        for road in root.findall("road"):
            offs = LaneOffsetSmoother._collect_offsets(road)
            if not offs:
                continue

            last_a = None

            for s, off in offs:
                LaneOffsetSmoother._sanitize_coeffs(off)
                a = _safe_float(off.get("a", "0"), 0.0)

                # keep anchor stable
                if s == 0.0:
                    last_a = a
                    continue

                if last_a is not None and abs(a - last_a) > max_delta:
                    a = last_a + max_delta * (1 if a > last_a else -1)
                    off.set("a", f"{a:.6f}")
                    fixed += 1

                last_a = a

        print(f"✓ LaneOffsetSmoother: clamped {fixed} entries.")

