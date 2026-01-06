# geometry/lanesection_boundary_fixer.py
import xml.etree.ElementTree as ET
from ultimate_pipeline.core.xodr_sanitizer import _safe_float

class LaneSectionBoundaryFixer:

    @staticmethod
    def fix(root: ET.Element):
        for road in root.findall("road"):
            length = _safe_float(road.get("length", "0"), 0.0)
            sections = road.findall("lanes/laneSection")
            if not sections:
                continue

            # sort laneSections
            sections.sort(key=lambda s: _safe_float(s.get("s", "0"), 0.0))

            # ensure first section starts at s=0
            s0 = _safe_float(sections[0].get("s", "0"), 0.0)
            if s0 > 1e-4:
                sections[0].set("s", "0.0")

            for i in range(1, len(sections)):
                prev = sections[i-1]
                curr = sections[i]

                sp = _safe_float(prev.get("s", "0"), 0.0)
                sc = _safe_float(curr.get("s", "0"), 0.0)

                # Ensure monotonicity
                if sc <= sp:
                    curr.set("s", f"{sp + 0.05:.5f}")

                # prevent insane gaps
                if sc - sp > 150.0:
                    curr.set("s", f"{sp + 50.0:.5f}")

            # clamp last section inside road length
            last = sections[-1]
            sl = _safe_float(last.get("s", "0"), 0.0)
            if sl > length:
                last.set("s", f"{length - 0.05:.5f}")
