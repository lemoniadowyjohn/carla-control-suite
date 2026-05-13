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
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Any, Dict, List

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
    def _road_is_short_and_curvy(road: ET.Element) -> tuple[bool, str]:
        length = _safe_float(road.get("length", "0.0"), 0.0)

        max_len = getattr(SETTINGS, "ROUNDABOUT_MAX_LENGTH", 80.0)
        if length > max_len:
            return False, "too_long"

        geoms = road.findall("./planView/geometry")
        arc_count = sum(1 for g in geoms if g.find("arc") is not None)

        min_arcs = getattr(SETTINGS, "ROUNDABOUT_MIN_ARCS", 2)
        if arc_count >= min_arcs:
            return True, "arc_count"

        min_curvy_geoms = getattr(SETTINGS, "ROUNDABOUT_MIN_CURVY_GEOMS", 4)
        min_heading_change = getattr(SETTINGS, "ROUNDABOUT_MIN_HEADING_CHANGE_DEG", 45.0)
        geom_count = len(geoms)
        if geom_count < min_curvy_geoms:
            return False, "not_curvy"

        def _norm_angle(rad: float) -> float:
            return (rad + math.pi) % (2.0 * math.pi) - math.pi

        def _angle_diff(a: float, b: float) -> float:
            return _norm_angle(a - b)

        hdgs = []
        for g in geoms:
            hdg = _safe_float(g.get("hdg", "0.0"), 0.0)
            hdgs.append(hdg)

        total_hdg = 0.0
        for idx in range(1, len(hdgs)):
            total_hdg += abs(_angle_diff(hdgs[idx], hdgs[idx - 1]))

        total_hdg_deg = math.degrees(total_hdg)
        if total_hdg_deg >= min_heading_change:
            return True, "heading_change"

        return False, "not_curvy"

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
    def detect(root: ET.Element) -> tuple[Dict[str, Dict], Dict[str, Any]]:
        roads = {r.get("id"): r for r in root.findall("road") if r.get("id")}
        out: Dict[str, Dict] = {}
        meta = {
            "candidate_junctions_checked": 0,
            "candidate_roads_considered": 0,
            "rejections": {
                "not_enough_connections": 0,
                "too_long": 0,
                "not_curvy": 0,
                "not_one_way": 0,
            },
        }

        for j in root.findall("junction"):
            jid = j.get("id")
            conns = j.findall("connection")
            meta["candidate_junctions_checked"] += 1
            if len(conns) < 3:
                meta["rejections"]["not_enough_connections"] += 1
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
                meta["rejections"]["not_enough_connections"] += 1
                continue

            # heuristics filtering
            candidates = []
            for rid in road_ids:
                meta["candidate_roads_considered"] += 1
                is_curvy, reason = _RoundaboutDetector._road_is_short_and_curvy(roads[rid])
                if not is_curvy:
                    meta["rejections"][reason] = meta["rejections"].get(reason, 0) + 1
                    continue
                if not _RoundaboutDetector._road_is_one_way(roads[rid]):
                    meta["rejections"]["not_one_way"] += 1
                    continue
                candidates.append(rid)

            min_core_roads = getattr(SETTINGS, "ROUNDABOUT_MIN_CORE_ROADS", 3)
            if len(candidates) < min_core_roads:
                meta["rejections"]["not_enough_connections"] += 1
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

        return out, meta


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
    def reconstruct(root: ET.Element, out_dir: str | None = None) -> Dict[str, Dict]:
        if not getattr(SETTINGS, "ENABLE_ROUNDABOUT_RECONSTRUCTION", True):
            print("⏭ RoundaboutReconstructor: disabled in settings.")
            return {}

        detected, meta = _RoundaboutDetector.detect(root)
        if not detected:
            print("? RoundaboutReconstructor: no roundabouts detected.")
            meta["roundabouts_reconstructed"] = 0
            result: Dict[str, Dict] = {"_meta": meta}
            RoundaboutReconstructor._write_meta(result, out_dir)
            return result

        road_map = {
            r.get("id"): r for r in root.findall("road")
            if r.get("id") is not None
        }

        out: Dict[str, Dict] = {}

        for jid, info in detected.items():
            old = info["roads"]
            cx, cy = info["center"]

            # ---------------------------------------------------------
            # SAFETY GUARDRAILS
            # ---------------------------------------------------------
            # CARLA's OpenDRIVE importer can hard-crash on certain malformed
            # junction/connection states. Before we touch anything, ensure the
            # junction exists and that every referenced road id exists.
            j = root.find(f"./junction[@id='{jid}']")
            if j is None:
                continue

            referenced: List[str] = []
            for c in j.findall("connection"):
                if c.get("incomingRoad"):
                    referenced.append(c.get("incomingRoad"))
                if c.get("connectingRoad"):
                    referenced.append(c.get("connectingRoad"))

            # If we can't resolve ids, do not attempt reconstruction.
            if any((rid not in road_map) for rid in referenced):
                continue

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
            # CARLA-safe circular connector road. Important: connectingRoads
            # inside a junction should have road@junction set to that junction id.
            new_road = RoundaboutReconstructor._build_roundabout(new_id, jid, cx, cy, R, old, road_map)
            root.append(new_road)

            # Smooth elevation transitions between the roundabout connector road
            # and its connected incoming roads (best-effort, non-destructive).
            try:
                z0_el = new_road.find("./elevationProfile/elevation")
                z0 = float(z0_el.get("a", "0.0")) if z0_el is not None else 0.0
                RoundaboutReconstructor._smooth_elevation_around_roundabout(root, j, new_id, target_z=z0)
            except Exception:
                # Never fail the whole reconstruction due to smoothing.
                pass

            # rewrite junction connections (best-effort)
            RoundaboutReconstructor._rewrite_junction(root, jid, old, new_id, cx, cy)

            # NOTE: We intentionally do NOT delete old roads by default.
            # Deleting roads that are referenced elsewhere (links, other
            # junctions) is a common source of CARLA hard-crashes.
            # Instead we keep them, but mark them as non-drivable if possible.
            for rid in old:
                r = road_map.get(rid)
                if r is None:
                    continue
                # If the road is not referenced by any junction connection after
                # rewriting, we can safely orphan it by setting junction=-1 and
                # converting lanes to type="none".
                if not root.findall(f"./junction/connection[@incomingRoad='{rid}']") and \
                   not root.findall(f"./junction/connection[@connectingRoad='{rid}']"):
                    r.set("junction", "-1")
                    for ln in r.findall(".//lane"):
                        if ln.get("type") == "driving":
                            ln.set("type", "none")

            out[jid] = {
                "new_road": new_id,
                "old_roads": old,
                "center": (cx, cy),
                "radius": R,
            }

        meta["roundabouts_reconstructed"] = len(out)
        result = dict(out)
        result["_meta"] = meta
        print(f"🔄 RoundaboutReconstructor: rebuilt {len(out)} roundabouts.")
        RoundaboutReconstructor._write_meta(result, out_dir)
        return result

    # ===========================================================
    @staticmethod
    def _write_meta(result: Dict[str, Dict], out_dir: str | None) -> None:
        if not out_dir:
            return
        try:
            import json
            import os

            qa_dir = os.path.join(out_dir, "qa_stage_reports")
            os.makedirs(qa_dir, exist_ok=True)
            path = os.path.join(qa_dir, "roundabout_reconstruction.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
        except Exception:
            pass

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
    def _build_roundabout(
        rid: str,
        jid: str,
        cx: float,
        cy: float,
        R: float,
        old_roads: List[str],
        road_map: Dict[str, ET.Element],
    ) -> ET.Element:
        L = 2 * math.pi * R

        road = ET.Element(
            "road",
            {
                "id": rid,
                "name": f"roundabout_{rid}",
                "length": f"{L:.3f}",
                # Important for CARLA: connectingRoad within a junction should
                # have this attribute set to the junction id.
                "junction": str(jid),
            },
        )

        # NOTE:
        # We intentionally avoid creating a self-referential predecessor/successor
        # link (road->same road). Some sanitizers remove those links, and certain
        # CARLA builds have been observed to behave poorly with self-links.
        # The roundabout is connected through <junction><connection> entries.

        planView = ET.SubElement(road, "planView")

        sx = cx + R
        sy = cy

        geom = ET.SubElement(
            planView,
            "geometry",
            {
            "s": "0",
            "x": f"{sx:.3f}",
            "y": f"{sy:.3f}",
            "hdg": "0.0",
            "length": f"{L:.3f}",
            },
        )
        ET.SubElement(geom, "arc", {
            "curvature": f"{1.0 / R:.6f}"
        })

        # Elevation profile: keep it smooth and consistent with connected roads.
        z0 = RoundaboutReconstructor._estimate_roundabout_elevation(old_roads, road_map)
        elev = ET.SubElement(road, "elevationProfile")
        ET.SubElement(elev, "elevation", {
            "s": "0.0",
            "a": f"{z0:.3f}",
            "b": "0.0",
            "c": "0.0",
            "d": "0.0",
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
    def _estimate_roundabout_elevation(old_roads: List[str], road_map: Dict[str, ET.Element]) -> float:
        """Best-effort estimate of a constant elevation for the new roundabout.

        CARLA can become unstable when elevation discontinuities are extreme.
        We sample the starting elevation "a" coefficient from any connected
        roads that already have an elevationProfile and average them.
        """
        zs: List[float] = []
        for rid in old_roads:
            r = road_map.get(rid)
            if r is None:
                continue
            e0 = r.find("./elevationProfile/elevation")
            if e0 is None:
                continue
            try:
                zs.append(float(e0.get("a", "0.0")))
            except Exception:
                continue
        if not zs:
            return 0.0
        return sum(zs) / len(zs)

    @staticmethod
    def _smooth_elevation_around_roundabout(
        root: ET.Element,
        junction: ET.Element,
        roundabout_road_id: str,
        target_z: float,
        transition_m: float = 12.0,
    ) -> None:
        """Smooth elevation near the roundabout connections.

        CARLA can behave poorly when elevation discontinuities exist at
        junction boundaries. We do not attempt a full re-fit of elevation
        polynomials. Instead, we insert a short linear transition near the
        connecting end of each incoming road so its endpoint matches target_z.

        This is best-effort and intentionally conservative.
        """
        # Identify incoming roads that connect to the new roundabout.
        for conn in junction.findall("connection"):
            if conn.get("connectingRoad") != roundabout_road_id:
                continue

            incoming_id = conn.get("incomingRoad")
            if not incoming_id:
                continue

            # If contactPoint is 'end', we smooth the end of the incoming road.
            cp = conn.get("contactPoint", "start")
            smooth_end = (cp == "end")
            RoundaboutReconstructor._ensure_elevation_transition(
                root,
                road_id=incoming_id,
                target_z=target_z,
                transition_m=transition_m,
                at_end=smooth_end,
            )

    @staticmethod
    def _ensure_elevation_transition(
        root: ET.Element,
        road_id: str,
        target_z: float,
        transition_m: float,
        at_end: bool,
    ) -> None:
        road = root.find(f"./road[@id='{road_id}']")
        if road is None:
            return

        try:
            road_len = float(road.get("length", "0.0"))
        except Exception:
            road_len = 0.0
        if road_len <= 0.0:
            return

        ep = road.find("elevationProfile")
        if ep is None:
            ep = ET.SubElement(road, "elevationProfile")

        # Choose the s position to start the transition.
        s0 = max(0.0, road_len - transition_m) if at_end else 0.0
        s1 = road_len if at_end else min(road_len, transition_m)
        if s1 <= s0:
            return

        # Determine current z at s0 using the first elevation 'a' as a proxy.
        # We keep this conservative because fitting polynomials is risky.
        existing = ep.findall("elevation")
        if existing:
            try:
                base_z = float(existing[0].get("a", "0.0"))
            except Exception:
                base_z = 0.0
        else:
            base_z = target_z

        # Insert two elevation segments:
        # - constant at base_z until s0
        # - linear b to reach target_z over [s0, s1]
        # CARLA accepts multiple elevation entries with increasing s.
        def _mk(s: float, a: float, b: float) -> ET.Element:
            el = ET.Element("elevation", {
                "s": f"{s:.3f}",
                "a": f"{a:.3f}",
                "b": f"{b:.6f}",
                "c": "0.0",
                "d": "0.0",
            })
            return el

        # Clear only elevations that overlap our small transition window.
        # Keep other elevations untouched.
        kept: List[ET.Element] = []
        for el in existing:
            try:
                s = float(el.get("s", "0.0"))
            except Exception:
                s = 0.0
            if s < s0 - 1e-3 or s > s1 + 1e-3:
                kept.append(el)

        for el in list(ep):
            ep.remove(el)
        for el in kept:
            ep.append(el)

        # Ensure monotonic insertion.
        b = (target_z - base_z) / (s1 - s0)
        ep.append(_mk(s0, base_z, 0.0))
        ep.append(_mk(s0, base_z, b))


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

        # Determine target elevation from the new roundabout (constant z)
        z_target = None
        rb = root.find(f"./road[@id='{new_id}']")
        if rb is not None:
            e_rb = rb.find("./elevationProfile/elevation")
            if e_rb is not None:
                try:
                    z_target = float(e_rb.get("a", "0.0"))
                except Exception:
                    z_target = None

        for conn in j.findall("connection"):
            if conn.get("connectingRoad") in old_roads:
                conn.set("connectingRoad", new_id)

                incoming = conn.get("incomingRoad")
                angle = RoundaboutReconstructor._angle(root, incoming, cx, cy)
                conn.set("contactPoint", "start" if angle < math.pi else "end")

                # Best-effort laneLink: many imported maps omit this, but
                # providing it improves CARLA stability at complex junctions.
                if conn.find("laneLink") is None:
                    ET.SubElement(conn, "laneLink", {"from": "-1", "to": "-1"})

                # Smooth elevations around roundabout entries to avoid large
                # vertical seams that can destabilize mesh generation.
                if z_target is not None:
                    try:
                        RoundaboutReconstructor._smooth_elevation_near_connection(root, incoming, target_z=z_target)
                    except Exception:
                        pass

        # Additional pass: smooth any remaining large seams around the roundabout.
        if z_target is not None:
            try:
                RoundaboutReconstructor._smooth_elevation_near_roundabout(root, jid, new_id)
            except Exception:
                pass


    @staticmethod
    def _smooth_elevation_near_connection(
        root: ET.Element,
        incoming_road_id: str | None,
        *,
        target_z: float | None,
        smooth_len_m: float = 8.0,
        max_jump_m: float = 2.5,
    ) -> None:
        """Best-effort elevation seam reduction at the end of an incoming road.

        This is intentionally conservative: it never changes planView, and only
        inserts/adjusts elevationProfile coefficients near the road end.
        """
        if not incoming_road_id:
            return
        r = root.find(f"./road[@id='{incoming_road_id}']")
        if r is None:
            return
        L = _safe_float(r.get("length", "0"), 0.0)
        if L <= 0.0:
            return

        prof = r.find("elevationProfile")
        if prof is None:
            prof = ET.SubElement(r, "elevationProfile")

        # Determine current end elevation as last 'a'
        elevs = prof.findall("elevation")
        if elevs:
            try:
                current_end = float(elevs[-1].get("a", "0.0"))
            except Exception:
                current_end = 0.0
        else:
            current_end = 0.0

        if target_z is None:
            target_z = current_end

        if abs(float(target_z) - float(current_end)) <= max_jump_m:
            return

        s0 = max(0.0, L - float(smooth_len_m))

        # Insert smoothing knot at s0
        ET.SubElement(
            prof,
            "elevation",
            {
                "s": f"{s0:.3f}",
                "a": f"{float(target_z):.3f}",
                "b": "0.0",
                "c": "0.0",
                "d": "0.0",
            },
        )

    @staticmethod
    def _smooth_elevation_near_roundabout(root: ET.Element, jid: str, new_id: str, smooth_len: float = 8.0) -> None:
        """Blend the endpoint elevations of incoming roads towards the roundabout.

        This is a conservative local smoothing: it only touches the *last* elevation
        entry near the end of incoming roads (or creates one) so that the elevation
        "a" coefficient matches the roundabout's constant elevation.
        """
        # Roundabout elevation
        rb = root.find(f"./road[@id='{new_id}']")
        if rb is None:
            return
        e_rb = rb.find("./elevationProfile/elevation")
        if e_rb is None:
            return
        try:
            z_target = float(e_rb.get("a", "0.0"))
        except Exception:
            return

        j = root.find(f"./junction[@id='{jid}']")
        if j is None:
            return

        for conn in j.findall("connection"):
            incoming = conn.get("incomingRoad")
            if not incoming:
                continue
            r = root.find(f"./road[@id='{incoming}']")
            if r is None:
                continue
            L = _safe_float(r.get("length", "0.0"), 0.0)
            if L <= 0.0:
                continue

            prof = r.find("elevationProfile")
            if prof is None:
                prof = ET.SubElement(r, "elevationProfile")

            elevs = prof.findall("elevation")
            if elevs:
                last = elevs[-1]
                last_a = _safe_float(last.get("a", "0.0"), 0.0)
            else:
                last = None
                last_a = 0.0

            # If jump is large, insert a blending entry before the end.
            if abs(z_target - last_a) > 0.25:
                s0 = max(0.0, L - float(smooth_len))
                ET.SubElement(prof, "elevation", {
                    "s": f"{s0:.3f}",
                    "a": f"{last_a:.3f}",
                    "b": "0.0",
                    "c": "0.0",
                    "d": "0.0",
                })
                ET.SubElement(prof, "elevation", {
                    "s": f"{L:.3f}",
                    "a": f"{z_target:.3f}",
                    "b": "0.0",
                    "c": "0.0",
                    "d": "0.0",
                })

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
