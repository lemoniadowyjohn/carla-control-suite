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
