from __future__ import annotations
import matplotlib
matplotlib.use("Agg")  # headless backend: this system's default (tkagg) needs a display
import matplotlib.pyplot as plt
from shapely.geometry import LineString
import numpy as np
import xml.etree.ElementTree as ET
from typing import List


def _sample_polylines(path: str) -> List[LineString]:
    tree = ET.parse(path)
    root = tree.getroot()

    lines = []
    for g in root.findall(".//geometry"):
        x = float(g.get("x", "0"))
        y = float(g.get("y", "0"))
        hdg = float(g.get("hdg", "0"))
        length = float(g.get("length", "0"))

        pts = [(x + t * np.cos(hdg),
                y + t * np.sin(hdg)) for t in np.linspace(0, length, 8)]
        lines.append(LineString(pts))

    return lines


class CityDriftField:
    """
    Visualizes a vector field showing coordinate drift
    between auto-map and manual-map geometry.
    """

    @staticmethod
    def plot(
        manual_xodr: str,
        auto_xodr: str,
        out_png: str,
        max_vectors: int = 200
    ):
        m_lines = _sample_polylines(manual_xodr)
        a_lines = _sample_polylines(auto_xodr)

        if not m_lines or not a_lines:
            print("❌ No geometry found.")
            return

        m_union = m_lines[0]
        for l in m_lines[1:]:
            m_union = m_union.union(l)

        xs, ys, us, vs = [], [], [], []

        count = 0
        for l in a_lines:
            for d in np.linspace(0, 1, 4):
                if count > max_vectors:
                    break

                p = l.interpolate(d, normalized=True)
                q = m_union.interpolate(m_union.project(p))

                xs.append(p.x)
                ys.append(p.y)
                us.append(q.x - p.x)
                vs.append(q.y - p.y)

                count += 1

        plt.figure(figsize=(8, 8))
        plt.quiver(xs, ys, us, vs, angles='xy', scale_units='xy', scale=1)
        plt.gca().set_aspect("equal", adjustable="box")
        plt.grid(True)
        plt.title("City-Scale Drift Vector Field")
        plt.savefig(out_png, dpi=200)
        plt.close()
