# ultimate_pipeline/topology/roundabout_reconstructor.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Unified Roundabout Detector + Reconstructor (CARLA-safe)

This module replaces all older "reconstructor" logic.

Steps:
  1) Detect roundabout clusters around junctions
  2) Estimate center + radius
  3) Create a clean circular road
  4) Make a simple single-lane section (CARLA-safe)
  5) Rewrite junction <connection> to the new road
  6) Remove the noisy original OSM roundabout roads
"""

import math
import xml.etree.ElementTree as ET
from typing import Dict, List

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.core.xodr_sanitizer import _safe_float


# -------------------------------------------------------------------
# Internal detector
# -------------------------------------------------------------------

class _RoundaboutDetector:
    """
    Simple but robust detector for OSM-style roundabouts:

    • Junction has ≥ 3 connections
    • At least N roads are short, curved, and one-way
    """

    @staticmethod
    def _road_is_short_and_curvy(road: ET.Element) -> bool:
        length = _safe_float(road.get("length", "0.0"), 0.0)

        max_len = getattr(SETTINGS, "ROUNDABOUT_MAX_LENGTH", 80.0)
        if length > max_len:
            return False

        geoms = road.findall("./planView/geometry")
        arc_count = sum(1 for g in geoms if g.find("arc") is not None)

        min_arcs = getattr(SETTINGS, "ROUNDABOUT_MIN_ARCS", 2)
        return arc_count >= min_arcs

    @staticmethod
    def _road_is_one_way(road: ET.Element) -> bool:
        """
        Treat road as one-way if all non-zero driving lanes are on only one side.
        """
        lanes = road.find("lanes")
        if lanes is None:
            return False

        has_left = False
        has_right = False

        for sec in lanes.findall("laneSection"):
            L = sec.find("left")
            R = sec.find("right")

            if L is not None:
                for ln in L.findall("lane"):
                    lid = ln.get("id")
                    if lid and ln.get("type", "driving") == "driving" and (lid.lstrip("-").isdigit()) and int(lid) != 0:
                        has_left = True

            if R is not None:
                for ln in R.findall("lane"):
                    lid = ln.get("id")
                    if lid and ln.get("type", "driving") == "driving" and (lid.lstrip("-").isdigit()) and int(lid) != 0:
                        has_right = True

        # XOR → exactly one side has driving lanes
        return has_left ^ has_right

    @staticmethod
    def detect(root: ET.Element) -> Dict[str, Dict]:
        roads = {r.get("id"): r for r in root.findall("road") if r.get("id")}
        out: Dict[str, Dict] = {}

        for j in root.findall("junction"):
            jid = j.get("id")
            conns = j.findall("connection")
            if len(conns) < 3:
                continue

            # candidate road ids
            road_ids = set()
            for c in conns:
                rin = c.get("incomingRoad")
                rco = c.get("connectingRoad")
                if rin in roads:
                    road_ids.add(rin)
                if rco in roads:
                    road_ids.add(rco)

            if len(road_ids) < 3:
                continue

            # heuristics filtering
            candidates = [
                rid for rid in road_ids
                if _RoundaboutDetector._road_is_short_and_curvy(roads[rid])
                and _RoundaboutDetector._road_is_one_way(roads[rid])
            ]

            min_core_roads = getattr(SETTINGS, "ROUNDABOUT_MIN_CORE_ROADS", 3)
            if len(candidates) < min_core_roads:
                continue

            # compute approximate center
            xs, ys = [], []
            for rid in candidates:
                g0 = roads[rid].find("./planView/geometry")
                if g0 is None:
                    continue
                xs.append(_safe_float(g0.get("x", "0"), 0.0))
                ys.append(_safe_float(g0.get("y", "0"), 0.0))

            if not xs or not ys:
                continue

            cx = sum(xs) / len(xs)
            cy = sum(ys) / len(ys)

            out[jid] = {
                "roads": candidates,
                "center": (cx, cy),
            }

        return out


# -------------------------------------------------------------------
# Public reconstructor
# -------------------------------------------------------------------

class RoundaboutReconstructor:
    """
    Create clean circular roundabout roads and replace messy OSM ones.

    Controlled by SETTINGS:
      - ENABLE_ROUNDABOUT_RECONSTRUCTION
      - ROUNDABOUT_MAX_LENGTH
      - ROUNDABOUT_MIN_ARCS
      - ROUNDABOUT_MIN_CORE_ROADS
    """

    @staticmethod
    def reconstruct(root: ET.Element) -> Dict[str, Dict]:
        if not getattr(SETTINGS, "ENABLE_ROUNDABOUT_RECONSTRUCTION", True):
            print("⏭ RoundaboutReconstructor: disabled in settings.")
            return {}

        meta = _RoundaboutDetector.detect(root)
        if not meta:
            print("⏭ RoundaboutReconstructor: no roundabouts detected.")
            return {}

        road_map = {
            r.get("id"): r for r in root.findall("road")
            if r.get("id") is not None
        }

        out: Dict[str, Dict] = {}

        for jid, info in meta.items():
            old = info["roads"]
            cx, cy = info["center"]

            # estimate radius
            radii = []
            for rid in old:
                g = road_map[rid].find("./planView/geometry")
                if g is None:
                    continue
                x = _safe_float(g.get("x", "0"), 0.0)
                y = _safe_float(g.get("y", "0"), 0.0)
                radii.append(math.dist((x, y), (cx, cy)))

            if not radii:
                continue

            R = sum(radii) / len(radii)

            new_id = RoundaboutReconstructor._new_id(root)
            new_road = RoundaboutReconstructor._build_roundabout(new_id, cx, cy, R)
            root.append(new_road)

            # rewrite junction connections
            RoundaboutReconstructor._rewrite_junction(root, jid, old, new_id, cx, cy)

            # remove old roads
            for rid in old:
                r = road_map.get(rid)
                if r is not None:
                    root.remove(r)

            out[jid] = {
                "new_road": new_id,
                "old_roads": old,
                "center": (cx, cy),
                "radius": R,
            }

        print(f"🔄 RoundaboutReconstructor: rebuilt {len(out)} roundabouts.")
        return out

    # ===========================================================
    # Helpers
    # ===========================================================

    @staticmethod
    def _new_id(root: ET.Element) -> str:
        existing = [
            int(r.get("id"))
            for r in root.findall("road")
            if r.get("id") and r.get("id").isdigit()
        ]
        return str(max(existing) + 1 if existing else 10000)

    @staticmethod
    def _build_roundabout(rid: str, cx: float, cy: float, R: float) -> ET.Element:
        L = 2 * math.pi * R

        road = ET.Element("road", {
            "id": rid,
            "name": f"roundabout_{rid}",
            "length": f"{L:.3f}",
            "junction": "-1",
        })

        planView = ET.SubElement(road, "planView")

        sx = cx + R
        sy = cy

        geom = ET.SubElement(planView, "geometry", {
            "s": "0",
            "x": f"{sx:.3f}",
            "y": f"{sy:.3f}",
            "hdg": "0.0",
            "length": f"{L:.3f}",
        })
        ET.SubElement(geom, "arc", {
            "curvature": f"{1.0 / R:.6f}"
        })

        
        # SIMPLE single-lane circular road (CARLA-safe baseline)
        lanes = ET.SubElement(road, "lanes")
        sec = ET.SubElement(lanes, "laneSection", {"s": "0.0"})

        # Center lane (id=0) is required by OpenDRIVE
        center = ET.SubElement(sec, "center")
        cl = ET.SubElement(center, "lane", {
            "id": "0",
            "type": "none",
            "level": "false",
        })
        ET.SubElement(cl, "roadMark", {
            "sOffset": "0.0",
            "type": "solid",
            "color": "standard",
            "width": "0.15",
        })

        right = ET.SubElement(sec, "right")
        ln = ET.SubElement(right, "lane", {
            "id": "-1",
            "type": "driving",
            "level": "false",
        })

        # Lane width must be > 0 for CARLA/SUMO; make it configurable
        try:
            lane_w = float(getattr(SETTINGS, "ROUNDABOUT_LANE_WIDTH", 3.5))
        except Exception:
            lane_w = 3.5
        lane_w = max(0.5, min(8.0, lane_w))

        ET.SubElement(ln, "width", {
            "sOffset": "0",
            "a": f"{lane_w:.3f}",
            "b": "0.0",
            "c": "0.0",
            "d": "0.0",
        })
        ET.SubElement(ln, "roadMark", {
            "sOffset": "0.0",
            "type": "broken",
            "color": "standard",
            "width": "0.15",
        })

        return road

    @staticmethod
    def _rewrite_junction(
        root: ET.Element,
        jid: str,
        old_roads: List[str],
        new_id: str,
        cx: float,
        cy: float,
    ) -> None:

        j = root.find(f"./junction[@id='{jid}']")
        if j is None:
            return

        for conn in j.findall("connection"):
            if conn.get("connectingRoad") in old_roads:
                conn.set("connectingRoad", new_id)

                incoming = conn.get("incomingRoad")
                angle = RoundaboutReconstructor._angle(root, incoming, cx, cy)
                conn.set("contactPoint", "start" if angle < math.pi else "end")

    @staticmethod
    def _angle(root: ET.Element, rid: str, cx: float, cy: float) -> float:
        r = root.find(f"./road[@id='{rid}']")
        if r is None:
            return 0.0

        geoms = r.findall("./planView/geometry")
        if not geoms:
            return 0.0

        g = geoms[-1]
        x = _safe_float(g.get("x", "0"), 0.0)
        y = _safe_float(g.get("y", "0"), 0.0)
        return math.atan2(y - cy, x - cx)
