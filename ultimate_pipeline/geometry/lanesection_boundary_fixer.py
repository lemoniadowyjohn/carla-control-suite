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

            # Sort laneSections by s (Python-list only -- does not reorder
            # the actual <laneSection> XML siblings under <lanes>). Real
            # generators always emit sections in ascending document order
            # already, so this is currently safe; if that ever changes, the
            # fixed s-values below would stay numerically monotonic while
            # document order silently stays stale.
            sections.sort(key=lambda s: _safe_float(s.get("s", "0"), 0.0))

            # clamp any negative starts (CARLA hard requirement)
            for sec in sections:
                sv = _safe_float(sec.get("s", "0"), 0.0)
                if sv < 0.0:
                    sec.set("s", "0.0")

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
                    # Use an epsilon that cannot push beyond road length
                    eps = min(0.05, max(1e-4, length * 0.01))
                    new_s = min(length, sp + eps)
                    curr.set("s", f"{new_s:.8f}")

                # prevent insane gaps
                if sc - sp > 150.0:
                    curr.set("s", f"{min(length, sp + 50.0):.8f}")

            # clamp last section inside road length
            last = sections[-1]
            sl = _safe_float(last.get("s", "0"), 0.0)
            if sl > length:
                # Clamp inside [0, length] even for tiny roads
                eps = min(0.05, max(1e-4, length * 0.01))
                last.set("s", f"{max(0.0, length - eps):.8f}")
