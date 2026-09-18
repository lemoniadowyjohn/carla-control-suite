#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ultimate_pipeline.debug.carla_crash_fixtures

Offline-only OpenDRIVE fixture generator.

Purpose:
- When CARLA crashes natively, Python exceptions cannot capture it.
- These fixtures create *small, deterministic* mutant .xodr files that exercise
  common CARLA importer failure classes, so you can regression-test your harness.

This module does NOT import carla.
"""

from __future__ import annotations

import copy
import os
import xml.etree.ElementTree as ET
from typing import Callable, Dict, Tuple


def _clone_tree(tree: ET.ElementTree) -> ET.ElementTree:
    return ET.ElementTree(copy.deepcopy(tree.getroot()))


def _write_tree(tree: ET.ElementTree, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _case1_negative_s(tree: ET.ElementTree) -> ET.ElementTree:
    """Case 1: Negative s (geometry layer). Often triggers: s >= 0.0"""
    root = tree.getroot()
    geom = root.find(".//road/planView/geometry")
    if geom is not None:
        geom.set("s", "-1.0")
    return tree


def _case2_non_monotonic_geometry_s(tree: ET.ElementTree) -> ET.ElementTree:
    """Case 2: Non-monotonic geometry s within a road."""
    root = tree.getroot()
    road = root.find(".//road")
    if road is None:
        return tree
    geoms = road.findall("./planView/geometry")
    if len(geoms) >= 2:
        geoms[0].set("s", "10.0")
        geoms[1].set("s", "5.0")
    return tree


def _case3_bad_junction_lanelink(tree: ET.ElementTree) -> ET.ElementTree:
    """Case 3: Junction laneLink mismatch (invalid mapping)."""
    root = tree.getroot()
    ll = root.find(".//junction/connection/laneLink")
    if ll is not None:
        ll.set("from", "123")
        ll.set("to", "456")
    return tree


def _case4_illegal_driving_lane_id_0(tree: ET.ElementTree) -> ET.ElementTree:
    """Case 4: Illegal driving lane id=0 (CARLA frequently hates this)."""
    root = tree.getroot()
    lane = root.find(".//lane[@type='driving']")
    if lane is not None:
        lane.set("id", "0")
    return tree


CASES: Tuple[Tuple[str, Callable[[ET.ElementTree], ET.ElementTree]], ...] = (
    ("case1_negative_s.xodr", _case1_negative_s),
    ("case2_non_monotonic_geometry_s.xodr", _case2_non_monotonic_geometry_s),
    ("case3_bad_junction_lanelink.xodr", _case3_bad_junction_lanelink),
    ("case4_illegal_lane_id_0.xodr", _case4_illegal_driving_lane_id_0),
)


def generate_fixtures(input_xodr: str, out_dir: str) -> Dict[str, str]:
    """Generate fixture mutants from input_xodr into out_dir.

    Returns dict: fixture_filename -> output_path
    """
    base = ET.parse(input_xodr)
    outputs: Dict[str, str] = {}
    for fname, mut in CASES:
        t = _clone_tree(base)
        t = mut(t)
        out_path = os.path.join(out_dir, fname)
        _write_tree(t, out_path)
        outputs[fname] = out_path
    return outputs
