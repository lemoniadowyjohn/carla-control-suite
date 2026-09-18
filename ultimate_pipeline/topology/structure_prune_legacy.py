#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Legacy "aggressive" structure prune.

Warning:
    This module is intentionally destructive and should NOT be used
    in the main pipeline unless explicitly enabled in settings.py.

What it does:
    - Scans an OpenDRIVE file for:
        • multi-successor roads
        • multi-predecessor roads
        • self-links
        • endpoint mismatch (>5 m)
        • broken junction refs
        • roads inside >3 junctions
        • roads with zero geometry

    - All flagged roads are removed.
    - All junction connections referencing removed IDs are removed.

This is ONLY intended as a fallback for small/synthetic maps
where CARLA crashes due to truly broken topology.

DO NOT USE FOR REAL CITY MAPS.
"""

import os
import math
import xml.etree.ElementTree as ET
from typing import List, Tuple


# ---------------------------------------------------------------------------
# Helper: Remove roads from XML
# ---------------------------------------------------------------------------
def _remove_roads(root: ET.Element, road_ids: List[str]) -> int:
    road_ids = set(road_ids)
    removed = 0

    # Remove road elements
    for road in list(root.findall("road")):
        if road.get("id") in road_ids:
            root.remove(road)
            removed += 1

    # Remove junction connections referencing deleted roads
    for j in root.findall("junction"):
        for conn in list(j.findall("connection")):
            inc = conn.get("incomingRoad")
            con = conn.get("connectingRoad")
            if inc in road_ids or con in road_ids:
                j.remove(conn)

    return removed


# ---------------------------------------------------------------------------
# Legacy classifier
# ---------------------------------------------------------------------------
def _legacy_scan(root: ET.Element):
    """
    Return a dict of issues using your OLD aggressive rules.
    """

    roads = {r.get("id"): r for r in root.findall("road") if r.get("id")}

    preds = {rid: [] for rid in roads}
    succs = {rid: [] for rid in roads}

    # Gather links
    for rid, road in roads.items():
        link = road.find("link")
        if link is None:
            continue

        for p in link.findall("predecessor"):
            if p.get("elementType") == "road":
                preds[rid].append(p.get("elementId"))

        for s in link.findall("successor"):
            if s.get("elementType") == "road":
                succs[rid].append(s.get("elementId"))

    issues = {
        "multi_predecessor": [],
        "multi_successor": [],
        "self_links": [],
        "endpoint_mismatch": [],
        "broken_junction_refs": [],
        "zero_geometry": [],
        "too_many_junctions": []
    }

    # 1) multi-predecessor / successor
    for rid in roads:
        if len(preds[rid]) > 1:
            issues["multi_predecessor"].append(rid)
        if len(succs[rid]) > 1:
            issues["multi_successor"].append(rid)

    # 2) self-links
    for rid in roads:
        if rid in preds[rid] or rid in succs[rid]:
            issues["self_links"].append(rid)

    # 3) Zero geometry roads
    for rid, road in roads.items():
        geos = road.findall("./planView/geometry")
        if len(geos) == 0:
            issues["zero_geometry"].append(rid)

    # 4) Geometry endpoint mismatch in junctions
    def last_geom(road):
        geos = road.findall("./planView/geometry")
        if not geos:
            return None
        g = geos[-1]
        try:
            x = float(g.get("x", 0))
            y = float(g.get("y", 0))
            hdg = float(g.get("hdg", 0))
            length = float(g.get("length", 0.01))
            return x, y, hdg, length
        except:
            return None

    def dist(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])

    # Junction connection check
    for j in root.findall("junction"):
        conns = j.findall("connection")

        if len(conns) > 20:
            # old aggressive rule
            for c in conns:
                rid = c.get("incomingRoad")
                if rid:
                    issues["too_many_junctions"].append(rid)

        for c in conns:
            inc = c.get("incomingRoad")
            con = c.get("connectingRoad")

            if inc not in roads or con not in roads:
                issues["broken_junction_refs"].append((inc, con))
                continue

            g1 = last_geom(roads[inc])
            g2 = last_geom(roads[con])

            if not g1 or not g2:
                continue

            if dist((g1[0], g1[1]), (g2[0], g2[1])) > 5.0:
                issues["endpoint_mismatch"].append((inc, con))

    return issues


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def prune(xodr_path: str) -> Tuple[str, List[str]]:
    """
    Perform OLD aggressive prune on the given XODR.

    Returns:
        (output_path, removed_ids)
    """
    if not os.path.exists(xodr_path):
        raise FileNotFoundError(xodr_path)

    tree = ET.parse(xodr_path)
    root = tree.getroot()

    issues = _legacy_scan(root)

    # flatten sets of IDs
    remove_ids = set()

    remove_ids.update(issues["multi_predecessor"])
    remove_ids.update(issues["multi_successor"])
    remove_ids.update(issues["self_links"])
    remove_ids.update(issues["zero_geometry"])
    remove_ids.update([a for (a, b) in issues["endpoint_mismatch"]])
    remove_ids.update([a for (a, b) in issues["broken_junction_refs"]])

    # optionally remove roads that appear in too many junctions
    for rid_count in issues["too_many_junctions"]:
        remove_ids.add(rid_count)

    remove_ids = list(remove_ids)

    # nothing to remove: return original
    if not remove_ids:
        print("Legacy prune: Nothing to remove.")
        out = xodr_path.replace(".xodr", "_legacy_pruned.xodr")
        tree.write(out, encoding="utf-8", xml_declaration=True)
        return out, []

    removed = _remove_roads(root, remove_ids)

    out_path = xodr_path.replace(".xodr", "_legacy_pruned.xodr")
    tree.write(out_path, encoding="utf-8", xml_declaration=True)

    print(f"Legacy prune removed {removed} roads.")
    return out_path, remove_ids
