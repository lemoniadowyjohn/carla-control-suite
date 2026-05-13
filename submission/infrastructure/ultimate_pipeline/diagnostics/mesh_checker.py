# ultimate_pipeline/diagnostics/mesh_checker.py

import xml.etree.ElementTree as ET
from typing import List, Tuple
import math

from ultimate_pipeline.core.xodr_sanitizer import _safe_float


class MeshChecker:
    @staticmethod
    def _sample_road(road: ET.Element, step: float = 5.0) -> List[Tuple[float, float]]:
        geoms = road.findall("./planView/geometry")
        if not geoms:
            return []
        geoms.sort(key=lambda g: _safe_float(g.get("s", "0"), 0.0))
        pts: List[Tuple[float, float]] = []
        for g in geoms:
            s = _safe_float(g.get("s", "0"), 0.0)
            l = _safe_float(g.get("length", "0"), 0.0)
            x0 = _safe_float(g.get("x", "0"), 0.0)
            y0 = _safe_float(g.get("y", "0"), 0.0)
            hdg = _safe_float(g.get("hdg", "0"), 0.0)
            n = max(1, int(l / step))
            for i in range(n + 1):
                t = min(l, i * step)
                x = x0 + t * math.cos(hdg)
                y = y0 + t * math.sin(hdg)
                pts.append((x, y))
        return pts

    @staticmethod
    def quick_check(root: ET.Element):
        print("\n🕸 MeshChecker: coarse geometry sanity...")
        all_pts: List[Tuple[float, float]] = []
        for road in root.findall("road"):
            all_pts.extend(MeshChecker._sample_road(road))

        if not all_pts:
            print("   ⚠ No geometry points sampled.")
            return

        xs = [p[0] for p in all_pts]
        ys = [p[1] for p in all_pts]
        span_x = max(xs) - min(xs)
        span_y = max(ys) - min(ys)

        print(f"   Span X: {span_x:.1f} m, Span Y: {span_y:.1f} m")
        if span_x > 1e6 or span_y > 1e6:
            print("   ⚠ Span extremely large; coordinates might be corrupted.")
        else:
            print("   ✔ Geometry span looks reasonable.")
