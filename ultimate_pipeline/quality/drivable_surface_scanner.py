from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Any


class DrivableSurfaceScanner:
    """
    Offline XODR scan for drivable-surface discontinuities (holes, seams, drops).

    Scans every <road> with driving lanes and every <junction> and reports
    gaps between lane successor/predecessor pairs, heading discontinuities,
    elevation drops, and dead connections.
    """

    @staticmethod
    def scan(
        xodr_path: str,
        hole_threshold_m: float = 0.5,
        seam_threshold_deg: float = 5.0,
        drop_threshold_m: float = 0.3,
    ) -> dict[str, Any]:
        tree = ET.parse(xodr_path)
        root = tree.getroot()

        holes: list[dict] = []
        seams: list[dict] = []
        drops: list[dict] = []
        dead_connections: list[dict] = []

        roads: dict[str, ET.Element] = {}
        for road in root.findall("road"):
            roads[road.get("id", "")] = road

        for road in root.findall("road"):
            rid = road.get("id", "")
            lanes_elem = road.find("lanes")
            if lanes_elem is None:
                continue

            planview = road.find("planView")
            elevation_profile = road.find("elevationProfile")

            for lane_section in lanes_elem.findall("laneSection"):
                sect_s = float(lane_section.get("s", "0"))
                for side in ("left", "center", "right"):
                    side_elem = lane_section.find(side)
                    if side_elem is None:
                        continue
                    for lane in side_elem.findall("lane"):
                        lane_type = lane.get("type", "")
                        if lane_type != "driving":
                            continue
                        lane_id = int(lane.get("id", "0"))
                        link_elem = lane.find("link")
                        if link_elem is None:
                            continue
                        succ_elem = link_elem.find("successor")
                        if succ_elem is None:
                            continue

                        succ_lane_id = int(succ_elem.get("id", "0"))

                        succ_section = DrivableSurfaceScanner._find_successor_lane_section(
                            lanes_elem, lane_section, succ_lane_id
                        )
                        if succ_section is None:
                            continue
                        succ_s = float(succ_section.get("s", "0"))

                        pred_end_geo = DrivableSurfaceScanner._lane_end_geometry(
                            planview, sect_s, lane_id
                        )
                        succ_start_geo = DrivableSurfaceScanner._lane_start_geometry(
                            planview, succ_s, succ_lane_id
                        )
                        if pred_end_geo is None or succ_start_geo is None:
                            continue

                        geo_gap = math.hypot(
                            succ_start_geo["x"] - pred_end_geo["x"],
                            succ_start_geo["y"] - pred_end_geo["y"],
                        )
                        if geo_gap > hole_threshold_m:
                            holes.append({
                                "road_id": rid,
                                "s": sect_s,
                                "gap_m": round(geo_gap, 3),
                                "type": "lane_section_gap",
                                "from_lane": lane_id,
                                "to_lane": succ_lane_id,
                            })

                        hdg_diff = DrivableSurfaceScanner._heading_diff(
                            pred_end_geo["hdg"], succ_start_geo["hdg"]
                        )
                        if hdg_diff > seam_threshold_deg:
                            seams.append({
                                "road_id": rid,
                                "s": sect_s,
                                "heading_deg": round(hdg_diff, 2),
                                "from_lane": lane_id,
                                "to_lane": succ_lane_id,
                            })

                        z_pred = DrivableSurfaceScanner._elevation_at(
                            elevation_profile, sect_s
                        )
                        z_succ = DrivableSurfaceScanner._elevation_at(
                            elevation_profile, succ_s
                        )
                        if z_pred is not None and z_succ is not None:
                            z_diff = abs(z_succ - z_pred)
                            if z_diff > drop_threshold_m:
                                drops.append({
                                    "road_id": rid,
                                    "s": sect_s,
                                    "z_diff_m": round(z_diff, 3),
                                    "from_lane": lane_id,
                                    "to_lane": succ_lane_id,
                                })

        for junction in root.findall("junction"):
            jid = junction.get("id", "")
            for conn in junction.findall("connection"):
                conn_road_id = conn.get("connectingRoad", "")
                if conn_road_id not in roads:
                    dead_connections.append({
                        "junction_id": jid,
                        "connecting_road": conn_road_id,
                        "reason": "connecting_road_missing",
                    })
                    continue
                conn_road = roads[conn_road_id]
                conn_lanes = conn_road.find("lanes")
                if conn_lanes is None:
                    dead_connections.append({
                        "junction_id": jid,
                        "connecting_road": conn_road_id,
                        "reason": "connecting_road_has_no_lanes",
                    })
                    continue
                lane_links = conn.findall("laneLink")
                if not lane_links:
                    dead_connections.append({
                        "junction_id": jid,
                        "connecting_road": conn_road_id,
                        "reason": "no_lane_links",
                    })

        total_holes = len(holes)
        total_seams = len(seams)
        total_drops = len(drops)
        total_dead = len(dead_connections)
        total_issues = total_holes + total_seams + total_drops + total_dead

        return {
            "total_holes": total_holes,
            "total_seams": total_seams,
            "total_drops": total_drops,
            "total_dead_connections": total_dead,
            "total_issues": total_issues,
            "holes": holes,
            "seams": seams,
            "drops": drops,
            "dead_connections": dead_connections,
            "ok": total_issues == 0,
        }

    @staticmethod
    def _find_successor_lane_section(
        lanes_elem: ET.Element,
        current_section: ET.Element,
        succ_lane_id: int,
    ) -> ET.Element | None:
        """Find the lane section that contains the successor lane."""
        sections = lanes_elem.findall("laneSection")
        current_s = float(current_section.get("s", "0"))
        candidate: ET.Element | None = None
        for sec in sections:
            sec_s = float(sec.get("s", "0"))
            if sec_s <= current_s:
                continue
            for side in ("left", "center", "right"):
                side_elem = sec.find(side)
                if side_elem is None:
                    continue
                for lane in side_elem.findall("lane"):
                    if int(lane.get("id", "0")) == succ_lane_id:
                        candidate = sec
                        break
        return candidate

    @staticmethod
    def _lane_end_geometry(
        planview: ET.Element | None,
        section_s: float,
        lane_id: int,
    ) -> dict | None:
        """Estimate geometry at lane end within the section."""
        if planview is None:
            return None
        geoms = planview.findall("geometry")
        if not geoms:
            return None
        relevant: ET.Element | None = None
        for g in geoms:
            g_s = float(g.get("s", "0"))
            g_len = float(g.get("length", "0"))
            if g_s <= section_s < g_s + g_len + 1e-3:
                relevant = g
                break
        if relevant is None:
            relevant = geoms[-1]
        x = float(relevant.get("x", "0"))
        y = float(relevant.get("y", "0"))
        hdg = float(relevant.get("hdg", "0"))
        g_len = float(relevant.get("length", "0"))
        g_s = float(relevant.get("s", "0"))
        frac = 1.0
        if g_len > 0:
            end_s = section_s
            if end_s < g_s:
                end_s = g_s
            if end_s < g_s + g_len:
                frac = (end_s - g_s) / g_len
        end_x = x + frac * g_len * math.cos(hdg)
        end_y = y + frac * g_len * math.sin(hdg)
        return {"x": end_x, "y": end_y, "hdg": hdg}

    @staticmethod
    def _lane_start_geometry(
        planview: ET.Element | None,
        section_s: float,
        lane_id: int,
    ) -> dict | None:
        """Estimate geometry at lane start within the section."""
        if planview is None:
            return None
        geoms = planview.findall("geometry")
        if not geoms:
            return None
        relevant: ET.Element | None = None
        for g in geoms:
            g_s = float(g.get("s", "0"))
            g_len = float(g.get("length", "0"))
            if g_s <= section_s < g_s + g_len + 1e-3:
                relevant = g
                break
        if relevant is None:
            relevant = geoms[0]
        x = float(relevant.get("x", "0"))
        y = float(relevant.get("y", "0"))
        hdg = float(relevant.get("hdg", "0"))
        g_len = float(relevant.get("length", "0"))
        g_s = float(relevant.get("s", "0"))
        frac = 0.0
        if g_len > 0 and section_s > g_s:
            frac = (section_s - g_s) / g_len
        start_x = x + frac * g_len * math.cos(hdg)
        start_y = y + frac * g_len * math.sin(hdg)
        return {"x": start_x, "y": start_y, "hdg": hdg}

    @staticmethod
    def _elevation_at(
        elevation_profile: ET.Element | None,
        s: float,
    ) -> float | None:
        if elevation_profile is None:
            return None
        elevations = elevation_profile.findall("elevation")
        if not elevations:
            return None
        elevations.sort(key=lambda e: float(e.get("s", "0")))
        result: float | None = None
        for e in elevations:
            e_s = float(e.get("s", "0"))
            if e_s <= s:
                a = float(e.get("a", "0"))
                b = float(e.get("b", "0"))
                c = float(e.get("c", "0"))
                d = float(e.get("d", "0"))
                ds = s - e_s
                result = a + b * ds + c * ds * ds + d * ds * ds * ds
        return result

    @staticmethod
    def _heading_diff(hdg1: float, hdg2: float) -> float:
        diff = abs(hdg1 - hdg2) % (2 * math.pi)
        if diff > math.pi:
            diff = 2 * math.pi - diff
        return math.degrees(diff)
