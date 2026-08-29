# -*- coding: utf-8 -*-
"""Tests for PhysicsFeasibilityChecker (ultimate_pipeline/quality/check_physics_feasibility.py).

Wired live into ultimate_pipeline/quality/quality_gate_manager.py::gate_physics_feasibility
(imported by main_pipeline.py) with zero prior test coverage.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.quality.check_physics_feasibility import PhysicsFeasibilityChecker


def _root_with_lane(*, lane_type: str = "driving", width_a: str = "3.5") -> ET.Element:
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1")
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection", s="0.0")
    side = ET.SubElement(section, "left")
    lane = ET.SubElement(side, "lane", id="1", type=lane_type)
    ET.SubElement(lane, "width", sOffset="0", a=width_a)
    return root


def test_reasonable_width_no_issue():
    root = _root_with_lane(width_a="3.5")
    issues = PhysicsFeasibilityChecker.validate(root)
    assert issues == []


def test_too_narrow_flagged():
    root = _root_with_lane(width_a="0.5")
    issues = PhysicsFeasibilityChecker.validate(root)
    assert any(i["type"] == "lane_too_narrow" for i in issues)


def test_too_wide_flagged():
    root = _root_with_lane(width_a="9.0")
    issues = PhysicsFeasibilityChecker.validate(root)
    assert any(i["type"] == "lane_too_wide" for i in issues)


def test_non_driveable_lane_ignored():
    root = _root_with_lane(lane_type="sidewalk", width_a="0.2")
    issues = PhysicsFeasibilityChecker.validate(root)
    assert issues == []


def test_nonfinite_width_flagged_not_silently_passed():
    # A bare float(width.get("a", "3.5")) parses "nan" without error, and
    # `nan < MIN` / `nan > MAX` are both always False in IEEE-754 -- so a
    # corrupted width coefficient silently produced zero issues instead of
    # being flagged as physically infeasible/unverifiable.
    root = _root_with_lane(width_a="nan")
    issues = PhysicsFeasibilityChecker.validate(root)
    assert issues != []
    assert any(i["type"] == "lane_width_non_finite" for i in issues)


def test_unparseable_width_flagged_not_crashed():
    # The original bare float() call had no try/except at all -- a genuinely
    # malformed (non-numeric) width attribute would crash the whole gate
    # rather than being reported as an issue.
    root = _root_with_lane(width_a="not_a_number")
    issues = PhysicsFeasibilityChecker.validate(root)
    assert any(i["type"] == "lane_width_non_finite" for i in issues)
