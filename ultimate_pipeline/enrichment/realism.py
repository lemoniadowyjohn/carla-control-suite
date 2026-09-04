"""
Realism enrichment module:
Injects guardrails, benches, smart lamps, trash bins, etc.
All enrichment rules are defined in StreetFurnitureRules.
"""

from __future__ import annotations
import xml.etree.ElementTree as ET

# Safe import: if optional module fails, we disable realism but pipeline continues
try:
    from ultimate_pipeline.enrichment.street_furniture_rules import StreetFurnitureRules
except Exception as e:
    print(f"[WARN] Failed to import StreetFurnitureRules → realism disabled: {e}")
    StreetFurnitureRules = None

import os
import math
import random
from typing import List, Tuple

from ultimate_pipeline.core.xodr_sanitizer import _safe_float
from ultimate_pipeline.enrichment.object_injector import OSMObject
from ultimate_pipeline.config.settings import SETTINGS

class RealismModule:
    """
    Adds street furniture and signs using simple heuristics:
      - lamp posts every 30–50 meters
      - speed signs based on maxspeed
      - optional rule-based advanced realism (benches, guardrails, bins)
    """

    @staticmethod
    def _ensure_objects(road: ET.Element) -> ET.Element:
        objs = road.find("objects")
        if objs is None:
            objs = ET.SubElement(road, "objects")
        return objs


    @staticmethod
    def enrich(root: ET.Element):
        count = 0

        for road in root.findall("road"):
            length = float(road.get("length", "0"))
            speed = RealismModule._infer_speed(road)

            # ---------------------------------------------------------
            # 1) SIMPLE MODE (default)
            # ---------------------------------------------------------
            if not SETTINGS.ENABLE_REALISM_RULES:
                count += RealismModule._simple_lamps(road, length)
                count += RealismModule._speed_signs(road, speed)
                continue

            # ---------------------------------------------------------
            # 2) RULES MODE (advanced)
            # ---------------------------------------------------------
            if StreetFurnitureRules is None:
                # fail-safe fallback
                count += RealismModule._simple_lamps(road, length)
                count += RealismModule._speed_signs(road, speed)
                continue

            # SMART LAMPS
            if SETTINGS.ENABLE_SMART_LAMPS:
                spacing = StreetFurnitureRules.LAMP_SPACING
                offset = StreetFurnitureRules.LAMP_OFFSET

                if hasattr(RealismModule, "_rule_lamps"):
                    count += RealismModule._rule_lamps(road, spacing, offset)
                else:
                    count += RealismModule._simple_lamps(road, length)

            # BENCHES
            if SETTINGS.ENABLE_BENCHES and StreetFurnitureRules.is_residential(speed):
                if hasattr(RealismModule, "_benches"):
                    count += RealismModule._benches(road)

            # GUARDRAILS
            if SETTINGS.ENABLE_GUARDRAILS:
                if hasattr(RealismModule, "_estimate_curvature") and \
                   hasattr(StreetFurnitureRules, "needs_guardrail"):
                    curv = RealismModule._estimate_curvature(road)
                    if StreetFurnitureRules.needs_guardrail(curv):
                        if hasattr(RealismModule, "_guardrail"):
                            count += RealismModule._guardrail(road)

            # TRASH BINS
            if SETTINGS.ENABLE_TRASH_BINS:
                if hasattr(RealismModule, "_trash_bins"):
                    count += RealismModule._trash_bins(road)

        return count

    # ---------------------------------------------------------
    # Simple mode helpers
    # ---------------------------------------------------------

    @staticmethod
    def _simple_lamps(road, length):
        spacing = 40.0
        count = 0
        num_posts = int(length // spacing)
        for i in range(num_posts):
            s = i * spacing
            ET.SubElement(RealismModule._ensure_objects(road), "object", {
                "type": "lamp_post",
                "id": f"lamp_{road.get('id')}_{i}",
                "s": f"{s:.2f}",
                "t": "5.0",
                "zOffset": "0.0",
                "hdg": "0.0",
                "pitch": "0.0",
                "roll": "0.0",
                "orientation": "none",
                "dynamic": "no",
                "height": "5.0",
                "length": "0.5",
                "width": "0.5",
            })
            count += 1
        return count

    @staticmethod
    def _speed_signs(road, speed):
        if not speed:
            return 0
        ET.SubElement(RealismModule._ensure_objects(road), "object", {
            "type": f"speed_{speed}",
            "id": f"speed_{road.get('id')}",
            "s": "0.0",
            "t": "-2.5",
            "zOffset": "0.0",
            "hdg": "0.0",
            "pitch": "0.0",
            "roll": "0.0",
            "orientation": "none",
            "dynamic": "no",
            "height": "2.0",
            "length": "0.2",
            "width": "0.2",
        })
        return 1

    @staticmethod
    def _infer_speed(road: ET.Element):
        """Real per-road speed (km/h, rounded), preferring the road's own
        <lane><speed> data over the <type> heuristic below.

        This pipeline's own base OSM-to-XODR conversion stamps max="X" (no
        unit attribute == OpenDRIVE's documented m/s default) on nearly
        every driving/restricted lane (34,285/34,291 on the real
        map-of-record candidate, confirmed 2026-09-04); speed_limit_writer.py's
        separate, OSM-street-name-matched km/h writer only inserts a
        <speed> where one is not already present, so in practice it almost
        never fires -- the base-conversion value is the actual,
        near-universal-coverage signal, not an OSM-only one.

        Every road this pipeline generates carries <type type="town">
        (OpenDRIVE-standard vocabulary), which never matches the
        motorway/primary/secondary/residential substrings below -- that
        fallback is kept only for fixtures/other maps using the OSM-style
        <type> vocabulary and lacking any <speed> data at all.
        """
        for lane in road.iter("lane"):
            if lane.get("type") not in ("driving", "restricted"):
                continue
            sp = lane.find("speed")
            if sp is None:
                continue
            raw = sp.get("max")
            if raw is None:
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            unit = sp.get("unit")
            if unit == "km/h":
                kmh = value
            elif unit == "mph":
                kmh = value * 1.60934
            else:  # None or "m/s" -- OpenDRIVE's documented default unit
                kmh = value * 3.6
            return round(kmh)

        typ = road.find("type")
        if typ is None:
            return None

        t = typ.get("type", "")
        if "motorway" in t:
            return 120
        if "primary" in t:
            return 80
        if "secondary" in t:
            return 60
        if "residential" in t:
            return 30
        return None

    # ---------------------------------------------------------
    # RULES MODE helpers (2026-08-26)
    #
    # ENABLE_REALISM_RULES/ENABLE_GUARDRAILS/ENABLE_BENCHES/ENABLE_SMART_LAMPS/
    # ENABLE_TRASH_BINS all default True, but enrich()'s RULES MODE branch
    # guards every feature behind hasattr(RealismModule, "..."). None of these
    # 5 methods existed -- despite every flag reading "enabled", benches/
    # guardrails/trash bins were never generated on any real regen, silently,
    # with no error. street_furniture_rules.py already defined the rule
    # constants; only this placement logic was missing.
    # ---------------------------------------------------------

    @staticmethod
    def _estimate_curvature(road: ET.Element) -> float:
        """Representative |curvature| (1/m) for `road` -- reuses the same
        arc/spiral/paramPoly3 sampler as domain_gap/map_stats_xodr.py (C14),
        not a separate implementation. 0.0 for a straight road / no samples."""
        from ultimate_pipeline.domain_gap.map_stats_xodr import XODRMapStatsExtractor

        samples = XODRMapStatsExtractor._collect_curvatures(road)
        return max((abs(k) for k in samples), default=0.0)

    @staticmethod
    def _rule_lamps(road: ET.Element, spacing: float, offset: float) -> int:
        """Same placement as _simple_lamps, parameterized by the governed
        StreetFurnitureRules constants instead of hardcoded values."""
        length = float(road.get("length", "0"))
        count = 0
        num_posts = int(length // spacing) if spacing > 0 else 0
        for i in range(num_posts):
            s = i * spacing
            ET.SubElement(RealismModule._ensure_objects(road), "object", {
                "type": "lamp_post",
                "id": f"lamp_{road.get('id')}_{i}",
                "s": f"{s:.2f}",
                "t": str(offset),
                "zOffset": "0.0",
                "hdg": "0.0",
                "pitch": "0.0",
                "roll": "0.0",
                "orientation": "none",
                "dynamic": "no",
                "height": "5.0",
                "length": "0.5",
                "width": "0.5",
            })
            count += 1
        return count

    @staticmethod
    def _benches(road: ET.Element) -> int:
        """Place a bench every StreetFurnitureRules.BENCH_INTERVAL meters."""
        length = float(road.get("length", "0"))
        interval = StreetFurnitureRules.BENCH_INTERVAL
        count = 0
        num = int(length // interval) if interval > 0 else 0
        for i in range(num):
            s = (i + 1) * interval
            ET.SubElement(RealismModule._ensure_objects(road), "object", {
                "type": "bench",
                "id": f"bench_{road.get('id')}_{i}",
                "s": f"{s:.2f}",
                "t": "5.5",
                "zOffset": "0.0",
                "hdg": "0.0",
                "pitch": "0.0",
                "roll": "0.0",
                "orientation": "none",
                "dynamic": "no",
                "height": "0.9",
                "length": "1.5",
                "width": "0.6",
            })
            count += 1
        return count

    @staticmethod
    def _trash_bins(road: ET.Element) -> int:
        """Place a trash bin every StreetFurnitureRules.TRASH_EVERY meters."""
        length = float(road.get("length", "0"))
        interval = StreetFurnitureRules.TRASH_EVERY
        count = 0
        num = int(length // interval) if interval > 0 else 0
        for i in range(num):
            s = (i + 1) * interval
            ET.SubElement(RealismModule._ensure_objects(road), "object", {
                "type": "trash_bin",
                "id": f"trashbin_{road.get('id')}_{i}",
                "s": f"{s:.2f}",
                "t": "-5.5",
                "zOffset": "0.0",
                "hdg": "0.0",
                "pitch": "0.0",
                "roll": "0.0",
                "orientation": "none",
                "dynamic": "no",
                "height": "0.9",
                "length": "0.5",
                "width": "0.5",
            })
            count += 1
        return count

    @staticmethod
    def _guardrail(road: ET.Element) -> int:
        """Place one guard_rail object spanning the road when curvature exceeds
        StreetFurnitureRules.MAX_CURVATURE_FOR_GUARDRAIL. Self-checks curvature
        (safe to call standalone, not just via enrich()'s external gate)."""
        curv = RealismModule._estimate_curvature(road)
        if not StreetFurnitureRules.needs_guardrail(curv):
            return 0
        length = float(road.get("length", "0"))
        ET.SubElement(RealismModule._ensure_objects(road), "object", {
            "type": "guard_rail",
            "id": f"guardrail_{road.get('id')}",
            "s": "0.0",
            "t": "5.0",
            "zOffset": "0.0",
            "hdg": "0.0",
            "pitch": "0.0",
            "roll": "0.0",
            "orientation": "none",
            "dynamic": "no",
            "height": "0.75",
            "length": f"{length:.2f}",
            "width": "0.1",
        })
        return 1
