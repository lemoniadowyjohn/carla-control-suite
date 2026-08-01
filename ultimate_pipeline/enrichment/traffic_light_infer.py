#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Unified Traffic Light Inference (CARLA 0.9.16 compatible)

This merges both:
    • TrafficLightInferer (direct XODR insertion)
    • TrafficLightInference (returns OSMObject list)

Heuristics:
    - Junction has >= 3 connections
    - Junction NOT marked isRoundabout="true"
    - One TL per incoming road
    - TL placed ~5–7m before the junction center along road heading
"""

import math
import xml.etree.ElementTree as ET
from typing import Dict, List, Tuple

from ultimate_pipeline.core.xodr_sanitizer import _safe_float
from ultimate_pipeline.enrichment.object_injector import OSMObject


# =====================================================================
# Helper utilities
# =====================================================================

def _ensure_objects_parent(root: ET.Element) -> ET.Element:
    objs = root.find("objects")
    if objs is None:
        objs = ET.SubElement(root, "objects")
    return objs


def _road_endpoint(road: ET.Element, at_start: bool) -> Tuple[float, float, float]:
    """
    Extract (x, y, hdg) from first or last geometry element of road.
    """
    geoms = road.findall("./planView/geometry")
    if not geoms:
        return 0.0, 0.0, 0.0

    geoms.sort(key=lambda g: _safe_float(g.get("s", "0.0"), 0.0))

    g = geoms[0] if at_start else geoms[-1]
    x = _safe_float(g.get("x", "0.0"), 0.0)
    y = _safe_float(g.get("y", "0.0"), 0.0)
    hdg = _safe_float(g.get("hdg", "0.0"), 0.0)

    return x, y, hdg


# =====================================================================
# Unified Traffic Light Inference
# =====================================================================

class TrafficLightInferer:
    """
    Main class that infers traffic lights from junction topology.

    API:
        - infer_as_objects(root)  → list[OSMObject]
        - infer_and_insert(root) → int (count inserted)
    """

    BACK_OFFSET = 6.0     # TL position behind the endpoint
    HEIGHT = 5.0          # meters
    SIZE = 0.4            # TL width/length

    # -----------------------------------------------------------------

    @staticmethod
    def _estimate_junction_center(junc: ET.Element, roads: Dict[str, ET.Element]) -> Tuple[float, float]:
        xs, ys = [], []

        for c in junc.findall("connection"):
            incoming = c.get("incomingRoad")
            if incoming not in roads:
                continue
            x, y, _ = _road_endpoint(roads[incoming], at_start=False)
            xs.append(x)
            ys.append(y)

        if not xs:
            return 0.0, 0.0

        return sum(xs)/len(xs), sum(ys)/len(ys)

    # -----------------------------------------------------------------

    @staticmethod
    def infer_as_objects(root: ET.Element) -> List[OSMObject]:
        """
        Returns inferred TLs as OSMObject (for ObjectInjector).
        """
        roads = {r.get("id"): r for r in root.findall("road") if r.get("id")}

        out: List[OSMObject] = []

        for junc in root.findall("junction"):
            if junc.get("isRoundabout", "false") == "true":
                continue

            conns = junc.findall("connection")
            if len(conns) < 3:
                continue

            cx, cy = TrafficLightInferer._estimate_junction_center(junc, roads)

            idx = 0
            for c in conns:
                rid = c.get("incomingRoad")
                if rid not in roads:
                    continue

                rx, ry, hdg = _road_endpoint(roads[rid], at_start=False)

                # place light back from endpoint along heading
                lx = rx - TrafficLightInferer.BACK_OFFSET * math.cos(hdg)
                ly = ry - TrafficLightInferer.BACK_OFFSET * math.sin(hdg)

                out.append(OSMObject(
                    x=lx, y=ly, z=0.0,
                    obj_type="traffic_light",
                    subtype="auto_inferred"
                ))

                idx += 1

        return out

    # -----------------------------------------------------------------

    @staticmethod
    def infer_and_insert(root: ET.Element) -> int:
        """
        Inserts traffic lights as standard OpenDRIVE <object> elements under the
        corresponding incoming <road>/<objects> element (road-relative placement).

        This avoids non-standard <positionWorld> extensions and is generally safer
        for CARLA/OpenDRIVE parsers.

        Returns number of inserted TLs.
        """
        roads = {r.get("id"): r for r in root.findall("road") if r.get("id")}

        count = 0

        for junc in root.findall("junction"):
            if junc.get("isRoundabout", "false") == "true":
                continue

            conns = junc.findall("connection")
            if len(conns) < 3:
                continue

            idx = 0
            for c in conns:
                incoming = c.get("incomingRoad")
                if incoming not in roads:
                    continue

                road = roads[incoming]
                length = _safe_float(road.get("length", "0.0"), 0.0)

                # road end pose
                _, _, hdg = _road_endpoint(road, at_start=False)

                # place ~BACK_OFFSET meters before road end (clamped)
                s_pos = max(0.0, length - TrafficLightInferer.BACK_OFFSET)

                tl_id = f"tl_{junc.get('id','J')}_{idx}"

                # ensure <objects> under road
                road_objs = road.find("objects")
                if road_objs is None:
                    road_objs = ET.SubElement(road, "objects")

                ET.SubElement(road_objs, "object", {
                    "id": tl_id,
                    "name": tl_id,
                    "type": "traffic_light",
                    "s": f"{s_pos:.3f}",
                    "t": "0.0",
                    "zOffset": "0.0",
                    "hdg": f"{hdg:.6f}",
                    "pitch": "0.0",
                    "roll": "0.0",
                    "orientation": "none",
                    "dynamic": "no",
                    "height": f"{TrafficLightInferer.HEIGHT:.3f}",
                    "length": f"{TrafficLightInferer.SIZE:.3f}",
                    "width": f"{TrafficLightInferer.SIZE:.3f}",
                })

                count += 1
                idx += 1

        return count

    # -----------------------------------------------------------------
    # Post-inference validation of signal → lane references
    # -----------------------------------------------------------------
    @staticmethod
    def validate_signal_references(root: ET.Element):
        """
        Validate that every <signalReference laneId="X"> refers to an existing lane.
        Returns list[str] with human-readable errors.
        """
        # collect all lane ids
        lane_ids = set()
        for lane in root.findall(".//lane"):
            lid = lane.get("id")
            if lid is not None:
                lane_ids.add(lid)

        bad_refs = []

        # check all signalReference nodes
        for sig_ref in root.findall(".//signalReference"):
            sig_id = sig_ref.get("id", "UNKNOWN")
            lane_id = sig_ref.get("laneId")

            if lane_id is None:
                bad_refs.append(
                    f"signalReference id={sig_id}: missing laneId attribute."
                )
                continue

            if lane_id not in lane_ids:
                bad_refs.append(
                    f"signalReference id={sig_id}: laneId={lane_id} does not exist in this map."
                )

        return bad_refs
