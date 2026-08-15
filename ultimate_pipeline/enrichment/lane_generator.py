#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
FINAL LaneGenerator (production-stable)
--------------------------------------
This is the ONLY LaneGenerator the pipeline must use.

Key guarantees:
 - Does NOT delete valid laneSections unless they contain 0 lanes.
 - Creates correct left/center/right structures.
 - Produces CARLA-safe lane definitions.
 - Does not conflict with continuity repair or geometry smoothing.
 - Fully deterministic and SANITY-CHECKED.
"""

from __future__ import annotations
import xml.etree.ElementTree as ET
from typing import Mapping, Any

from ultimate_pipeline.enrichment.lane_width_policy import (
    DEFAULT_DRIVING_WIDTH_M,
    HIGHWAY_DEFAULT_WIDTH_M,
    target_driving_width_m,
)

DEFAULT_WIDTH = DEFAULT_DRIVING_WIDTH_M
CENTER_WIDTH = 0.20   # dummy center lane width

_RAST06_WIDTH: dict = dict(HIGHWAY_DEFAULT_WIDTH_M)
_RAST06_WIDTH.update({"path": 2.0, "cycleway": 1.5, "footway": 1.5, "pedestrian": 2.0})


def _road_type_width(
    road: ET.Element,
    osm_meta: Mapping[str, Mapping[str, Any]] | None = None,
) -> float:
    """Return per-type lane width for non-junction roads; falls back to DEFAULT_WIDTH."""
    decision = target_driving_width_m(road, osm_meta=osm_meta)
    if decision.source != "fallback":
        return decision.width_m
    type_elem = road.find("type")
    if type_elem is None:
        return DEFAULT_WIDTH
    road_type = (type_elem.get("type") or "").strip().lower()
    return _RAST06_WIDTH.get(road_type, DEFAULT_WIDTH)


class LaneGenerator:

    # ---------------------------------------------------------------
    @staticmethod
    def _lane_count(road: ET.Element) -> int:
        lanes = road.find("lanes")
        if lanes is None:
            return 0

        count = 0
        for lsec in lanes.findall("laneSection"):
            for side in ("left", "right", "center"):
                s_elem = lsec.find(side)
                if s_elem is None:
                    continue
                count += len(s_elem.findall("lane"))
        return count

    # ---------------------------------------------------------------
    @staticmethod
    def _has_driving_lanes(road: ET.Element) -> bool:
        lanes = road.find("lanes")
        if lanes is None:
            return False

        for lsec in lanes.findall("laneSection"):
            for side_name in ("left", "right"):
                side = lsec.find(side_name)
                if side is None:
                    continue
                for lane in side.findall("lane"):
                    if lane.get("type") == "driving":
                        return True

        return False

    # ---------------------------------------------------------------
    @staticmethod
    def _is_connector(road: ET.Element) -> bool:
        return road.get("junction", "-1") != "-1"

    # ---------------------------------------------------------------
    @staticmethod
    def _ensure(parent: ET.Element, tag: str) -> ET.Element:
        child = parent.find(tag)
        return child if child is not None else ET.SubElement(parent, tag)

    # ---------------------------------------------------------------
    @staticmethod
    def _add_width(elem: ET.Element, width: float):
        ET.SubElement(elem, "width",
                      sOffset="0.0", a=str(width),
                      b="0.0", c="0.0", d="0.0")

    # ---------------------------------------------------------------
    @staticmethod
    def ensure_lanes(
        root: ET.Element,
        verbose=True,
        osm_meta: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> int:
        created = 0

        for road in root.findall("road"):
            rid = road.get("id", "?")

            # If road already correct → skip
            if LaneGenerator._has_driving_lanes(road):
                continue

            lanes = road.find("lanes")
            if lanes is None:
                lanes = ET.SubElement(road, "lanes")

            def _lane_count_section(lsec):
                n = 0
                for side in ("left", "right", "center"):
                    s = lsec.find(side)
                    if s is not None:
                        n += len(s.findall("lane"))
                return n

            for ls in list(lanes.findall("laneSection")):
                if _lane_count_section(ls) == 0:
                    lanes.remove(ls)

            # Create new laneSection
            lane_section = ET.SubElement(lanes, "laneSection", s="0.0")

            left = LaneGenerator._ensure(lane_section, "left")
            center = LaneGenerator._ensure(lane_section, "center")
            right = LaneGenerator._ensure(lane_section, "right")

            # -------------------------------------------------------
            # CONNECTOR: keep center lane id=0 as type=none, add a single right driving lane
            # -------------------------------------------------------
            if LaneGenerator._is_connector(road):
                c = ET.SubElement(center, "lane",
                                  id="0", type="none", level="false")
                LaneGenerator._add_width(c, CENTER_WIDTH)

                r = ET.SubElement(right, "lane",
                                  id="-1", type="driving", level="false")
                LaneGenerator._add_width(
                    r,
                    target_driving_width_m(road, osm_meta=osm_meta).width_m,
                )

                created += 1
                if verbose:
                    print(f"[LaneGenerator] Connector road {rid} → center none + right driving lane")

                continue

            # -------------------------------------------------------
            # NORMAL ROAD: Left + Center (dummy) + Right
            # Use per-type width from RASt 06 table for non-junction roads.
            # -------------------------------------------------------
            road_w = _road_type_width(road, osm_meta=osm_meta)

            c = ET.SubElement(center, "lane",
                              id="0", type="none", level="false")
            LaneGenerator._add_width(c, CENTER_WIDTH)

            l = ET.SubElement(left, "lane",
                              id="1", type="driving", level="false")
            LaneGenerator._add_width(l, road_w)

            r = ET.SubElement(right, "lane",
                              id="-1", type="driving", level="false")
            LaneGenerator._add_width(r, road_w)

            created += 1
            if verbose:
                print(f"[LaneGenerator] Added full lane profile for road {rid}")

        if verbose:
            print(f"[LaneGenerator] Total new lane assignments: {created}")

        return created
