#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
XODRStatistics — structural, geometric, and semantic statistics for XODR maps.

Used after Step 8 (final map) to produce an analytic fingerprint of the map,
usable for domain-gap evaluation, reproducibility checks, and thesis analysis.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
import os
import json
from typing import Dict, Any, List


class XODRStatistics:

    # --------------------------------------------
    # PUBLIC API
    # --------------------------------------------
    @staticmethod
    def compute(xodr_path: str) -> Dict[str, Any]:
        tree = ET.parse(xodr_path)
        root = tree.getroot()

        stats = {
            "roads": XODRStatistics._road_stats(root),
            "lanes": XODRStatistics._lane_stats(root),
            "geometry": XODRStatistics._geometry_stats(root),
            "junctions": XODRStatistics._junction_stats(root),
            "traffic": XODRStatistics._traffic_stats(root),
            "elevation": XODRStatistics._elevation_stats(root),
        }

        stats["success"] = True
        return stats

    @staticmethod
    def save_json(stats: Dict[str, Any], out_path: str):
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)

    # --------------------------------------------
    # ROAD STATS
    # --------------------------------------------
    @staticmethod
    def _road_stats(root: ET.Element) -> Dict[str, Any]:
        roads = root.findall("road")
        lengths = []
        for r in roads:
            try:
                lengths.append(float(r.attrib.get("length", 0.0)))
            except:
                pass

        if lengths:
            total = sum(lengths)
            avg = total / len(lengths)
            mn = min(lengths)
            mx = max(lengths)
        else:
            total = avg = mn = mx = 0.0

        # histogram buckets (meters)
        bins = [10, 30, 60, 120, 250, 500]
        hist = {f"0-{bins[0]}": 0}
        for i in range(len(bins) - 1):
            hist[f"{bins[i]}-{bins[i+1]}"] = 0
        hist[f">{bins[-1]}"] = 0

        for L in lengths:
            placed = False
            if L < bins[0]:
                hist[f"0-{bins[0]}"] += 1
                continue
            for i in range(len(bins) - 1):
                if bins[i] <= L < bins[i+1]:
                    hist[f"{bins[i]}-{bins[i+1]}"] += 1
                    placed = True
                    break
            if not placed:
                hist[f">{bins[-1]}"] += 1

        return {
            "count": len(roads),
            "total_length_m": total,
            "avg_length_m": avg,
            "min_length_m": mn,
            "max_length_m": mx,
            "length_histogram": hist,
        }

    # --------------------------------------------
    # LANE STATS
    # --------------------------------------------
    @staticmethod
    def _lane_stats(root: ET.Element) -> Dict[str, Any]:
        total_lanes = 0
        widths = []

        for road in root.findall("road"):
            for ls in road.findall("lanes/laneSection"):
                for lane in ls.findall(".//lane"):
                    lid = lane.attrib.get("id")
                    if lid and int(lid) != 0:  # ignore center lane=0
                        total_lanes += 1

                    # lane width elements
                    for w in lane.findall("width"):
                        try:
                            widths.append(float(w.attrib.get("a", 0.0)))
                        except:
                            pass

        if widths:
            mn = min(widths)
            mx = max(widths)
            avg = sum(widths) / len(widths)
        else:
            mn = mx = avg = 0.0

        return {
            "total_lanes": total_lanes,
            "avg_lanes_per_road": total_lanes / max(1, len(root.findall("road"))),
            "width_min": mn,
            "width_avg": avg,
            "width_max": mx,
        }

    # --------------------------------------------
    # GEOMETRY STATS
    # --------------------------------------------
    @staticmethod
    def _geometry_stats(root: ET.Element) -> Dict[str, Any]:
        types = {"line": 0, "spiral": 0, "arc": 0, "poly3": 0, "paramPoly3": 0}
        curvatures = []

        for road in root.findall("road"):
            planview = road.find("planView")
            if planview is None:
                continue

            for geom in planview.findall("geometry"):
                length = float(geom.attrib.get("length", 0.0))
                for gtype in types.keys():
                    child = geom.find(gtype)
                    if child is not None:
                        types[gtype] += 1

                        if gtype == "arc":
                            try:
                                curvatures.append(abs(float(child.attrib["curvature"])))
                            except:
                                pass

        if curvatures:
            mn = min(curvatures)
            mx = max(curvatures)
            avg = sum(curvatures) / len(curvatures)
        else:
            mn = mx = avg = 0.0

        return {
            "geometry_counts": types,
            "curvature_min": mn,
            "curvature_avg": avg,
            "curvature_max": mx,
        }

    # --------------------------------------------
    # JUNCTION STATS
    # --------------------------------------------
    @staticmethod
    def _junction_stats(root: ET.Element) -> Dict[str, Any]:
        junctions = root.findall("junction")
        return {"count": len(junctions)}

    # --------------------------------------------
    # TRAFFIC STATS
    # --------------------------------------------
    @staticmethod
    def _traffic_stats(root: ET.Element) -> Dict[str, Any]:
        lights_obj = root.findall(".//object[@type='trafficLight']")
        # Traffic lights may also be encoded as <signal type="trafficLight"> depending on generator.
        lights_sig = [
            s for s in root.findall(".//signal")
            if (s.attrib.get("type", "") or "").lower() in ("trafficlight", "traffic_light")
        ]
        speed_elems = root.findall(".//speed")

        speeds = []
        for s in speed_elems:
            try:
                speeds.append(float(s.attrib.get("max", 0)))
            except:
                pass

        speed_hist = {}
        for v in speeds:
            bucket = int(v)
            speed_hist[bucket] = speed_hist.get(bucket, 0) + 1

        return {
            "traffic_lights": len(lights_obj) + len(lights_sig),
            "traffic_lights_objects": len(lights_obj),
            "traffic_lights_signals": len(lights_sig),
            "signals_total": len(root.findall(".//signal")),
            "speed_limit_distribution": speed_hist,
        }

    # --------------------------------------------
    # ELEVATION STATS
    # --------------------------------------------
    @staticmethod
    def _elevation_stats(root: ET.Element) -> Dict[str, Any]:
        z_vals: List[float] = []

        def _fs(elem: ET.Element, key: str, default: float = 0.0) -> float:
            try:
                return float(elem.attrib.get(key, default))
            except Exception:
                return default

        for road in root.findall("road"):
            el = road.find("elevationProfile")
            if el is None:
                continue

            # Road length helps evaluate last segment at the road end.
            try:
                road_len = float(road.attrib.get("length", 0.0))
            except Exception:
                road_len = 0.0

            segs = el.findall("elevation")
            if not segs:
                continue

            # Sort by s to evaluate boundaries consistently.
            segs = sorted(segs, key=lambda s: _fs(s, "s", 0.0))

            for i, seg in enumerate(segs):
                s0 = _fs(seg, "s", 0.0)
                a = _fs(seg, "a", 0.0)
                b = _fs(seg, "b", 0.0)
                c = _fs(seg, "c", 0.0)
                d = _fs(seg, "d", 0.0)

                # start value
                z_vals.append(a)

                # end boundary (next segment start, else road end)
                s1 = _fs(segs[i + 1], "s", road_len) if i + 1 < len(segs) else road_len
                ds = max(0.0, s1 - s0)
                z_end = a + b * ds + c * ds * ds + d * ds * ds * ds
                z_vals.append(z_end)

        if not z_vals:
            return {"min_z": 0.0, "max_z": 0.0, "z_range": 0.0}

        return {
            "min_z": min(z_vals),
            "max_z": max(z_vals),
            "z_range": max(z_vals) - min(z_vals),
        }
