# semantic_verifier.py
import xml.etree.ElementTree as ET
import math
import os
from typing import List, Dict


class SemanticVerifier:
    """
    Predicts which roads are likely to crash CARLA before simulation
    by inspecting geometry, link, and topology heuristics.
    """

    @staticmethod
    def analyze_xodr(file_path: str) -> Dict[str, float]:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"XODR file not found: {file_path}")

        tree = ET.parse(file_path)
        root = tree.getroot()
        risk_map = {}

        # Precompute global bounds (semantic)
        xs, ys = [], []
        for geo in root.findall(".//geometry"):
            try:
                xs.append(float(geo.get("x", "0")))
                ys.append(float(geo.get("y", "0")))
            except:
                pass
        if xs and ys:
            global_span = max(max(xs) - min(xs), max(ys) - min(ys))
        else:
            global_span = 0

        for road in root.findall(".//road"):
            rid = road.get("id", "?")
            risk = 0.0
            length = float(road.get("length", "0") or 0)

            geoms = road.findall(".//planView/geometry")
            lanes = road.findall(".//laneSection")

            # 1) Missing geometry
            if not geoms:
                risk += 5

            # 2) Too many geometry segments → potential fragmentation
            if len(geoms) > 50:
                risk += min(5, len(geoms) / 20)

            # 3) Sudden heading jumps
            last_hdg = None
            for g in geoms:
                hdg = float(g.get("hdg", "0"))
                if last_hdg is not None:
                    delta = abs(hdg - last_hdg)
                    if delta > 1.0:
                        risk += 0.3
                last_hdg = hdg

            # 4) Curvature inconsistencies
            last_k = None
            for g in geoms:
                arc = g.find(".//arc")
                if arc is not None:
                    k = float(arc.get("curvature", "0"))
                    if abs(k) > 0.4:
                        risk += 1
                    if last_k is not None and abs(k - last_k) > 0.2:
                        risk += 0.5
                    last_k = k

            # 5) Coordinate discontinuity
            last_x, last_y = None, None
            for g in geoms:
                x = float(g.get("x", "0"))
                y = float(g.get("y", "0"))
                if last_x is not None:
                    dist = math.hypot(x - last_x, y - last_y)
                    if dist > 200:
                        risk += 2
                last_x, last_y = x, y

            # 6) Geometry overflow
            for g in geoms:
                s = float(g.get("s", "0"))
                glen = float(g.get("length", "0"))
                if s + glen > length + 0.01:
                    risk += 3

            # 7) Lane section misalignment
            for sct in lanes:
                s = float(sct.get("s", "0"))
                if s > length:
                    risk += 3

            # 8) Roads too far from global center (stray outliers)
            if xs and ys:
                x0 = float(geoms[0].get("x", "0"))
                y0 = float(geoms[0].get("y", "0"))
                if abs(x0) > global_span * 1.5 or abs(y0) > global_span * 1.5:
                    risk += 5  # floating island

            # 9) Degenerate lengths
            if length < 0.5:
                risk += 3

            # Normalize
            risk_map[rid] = min(20.0, risk)

        return risk_map


    @staticmethod
    def get_high_risk_roads(risk_map: Dict[str, float], threshold: float = 8.0) -> List[str]:
        """Return list of road IDs above a given risk threshold."""
        return [rid for rid, score in risk_map.items() if score >= threshold]

    @staticmethod
    def summarize(risk_map: Dict[str, float]) -> None:
        """Print a readable risk summary."""
        total = len(risk_map)
        avg = sum(risk_map.values()) / max(1, total)
        risky = [rid for rid, s in risk_map.items() if s >= 8.0]
        print(f"🧠 Semantic risk analysis complete:")
        print(f"   Total roads analyzed: {total}")
        print(f"   Average risk score:   {avg:.2f}")
        print(f"   High-risk roads:      {len(risky)} ({len(risky)/max(1,total)*100:.1f}%)")
        if risky:
            print("   ⚠️  Example high-risk IDs:", ", ".join(risky[:10]))


if __name__ == "__main__":
    # Example standalone run
    xodr_path = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\cities\ingolstadt\sanitized_iter8.xodr"
    risk_map = SemanticVerifier.analyze_xodr(xodr_path)
    SemanticVerifier.summarize(risk_map)
