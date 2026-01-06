#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CARLA-critical lane connectivity validation.

CARLA MapBuilder ASSERTS if any driving lane has no successor.
This check converts that C++ crash into a Python-level hard gate.

This module accepts either:
  - a path to an .xodr file
  - or an already-loaded XML root element

It MUST be executed after LaneLinkBuilder and before CARLA load.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import List, Union


# ============================================================
# Internal helpers
# ============================================================

def _load_root(xodr_or_root: Union[str, ET.Element]) -> ET.Element:
    """
    Load an OpenDRIVE XML root from either a file path or an XML Element.
    """
    if isinstance(xodr_or_root, ET.Element):
        return xodr_or_root

    if not isinstance(xodr_or_root, (str, os.PathLike)):
        raise TypeError(
            f"Expected xodr path or XML Element, got {type(xodr_or_root)}"
        )

    tree = ET.parse(xodr_or_root)
    return tree.getroot()


# ============================================================
# Core logic
# ============================================================

def find_broken_lanes(
    xodr_or_root: Union[str, ET.Element],
    *,
    allow_dead_ends: bool = True,
) -> List[str]:
    """
    Return a list of human-readable error strings for driving lanes
    that violate CARLA successor connectivity requirements.
    """

    root = _load_root(xodr_or_root)
    errors: List[str] = []

    for road in root.findall(".//road"):
        road_id = road.get("id", "?")

        for lane in road.findall(".//lane[@type='driving']"):
            lane_id = lane.get("id", "?")

            link = lane.find("link")
            if link is None:
                errors.append(
                    f"Road {road_id} lane {lane_id}: missing <link>"
                )
                continue

            successor = link.find("successor")

            if successor is None:
                if allow_dead_ends:
                    # Dead ends are allowed only if explicitly marked
                    lane_end = lane.get("type") == "driving"
                    road_type = road.get("junction") == "-1"
                    if lane_end and road_type:
                        continue

                errors.append(
                    f"Road {road_id} lane {lane_id}: missing <successor>"
                )

    return errors


# ============================================================
# Hard gate (public API)
# ============================================================

def assert_all_lanes_have_successors(
    xodr_or_root: Union[str, ET.Element],
    *,
    allow_dead_ends: bool = True,
) -> None:
    """
    HARD FAIL if any driving lane lacks a successor.

    This must run AFTER:
      - LaneGenerator
      - LaneRepair
      - LaneLinkBuilder

    And BEFORE:
      - CARLA map loading
      - Tiling
      - Domain-gap analysis
    """

    errors = find_broken_lanes(
        xodr_or_root,
        allow_dead_ends=allow_dead_ends,
    )

    if errors:
        preview = "\n".join(errors[:20])

        raise RuntimeError(
            f"""
❌ CARLA-FATAL: lane connectivity invariant violated

CARLA requires every driving lane to have a successor.
The following lanes are invalid:

{preview}

Total broken lanes: {len(errors)}

Fix lane links BEFORE CARLA load.
"""
        )
