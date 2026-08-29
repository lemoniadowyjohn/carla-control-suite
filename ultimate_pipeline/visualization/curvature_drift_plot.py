from __future__ import annotations
import xml.etree.ElementTree as ET
import matplotlib
matplotlib.use("Agg")  # headless backend: this system's default (tkagg) needs a display
import matplotlib.pyplot as plt
from typing import Dict


def _road_curvature(road: ET.Element):
    vals = []
    for g in road.findall("planView/geometry"):
        arc = g.find("arc")
        if arc is not None:
            vals.append(abs(float(arc.get("curvature", "0"))))
    return vals


class CurvatureDriftPlot:
    @staticmethod
    def plot(manual_xodr: str, auto_xodr: str, out_png: str):
        rm = ET.parse(manual_xodr).getroot()
        ra = ET.parse(auto_xodr).getroot()

        m_roads = rm.findall("road")
        a_roads = ra.findall("road")

        ids = []
        m_vals = []
        a_vals = []

        for mr in m_roads:
            rid = mr.get("id")
            ar = ra.find(f"road[@id='{rid}']")
            if ar is None:
                continue

            mc = _road_curvature(mr)
            ac = _road_curvature(ar)
            if not mc or not ac:
                continue

            ids.append(rid)
            m_vals.append(sum(mc) / len(mc))
            a_vals.append(sum(ac) / len(ac))

        plt.figure(figsize=(12, 5))
        plt.plot(m_vals, label="manual")
        plt.plot(a_vals, label="auto")
        plt.legend()
        plt.title("Per-Road Mean Curvature Drift")
        plt.xlabel("Road index")
        plt.ylabel("Mean absolute curvature")
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(out_png, dpi=200)
        plt.close()
