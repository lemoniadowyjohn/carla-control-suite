# -*- coding: utf-8 -*-
"""Tests for ElevationSmoothnessGate (ultimate_pipeline/quality/check_elevation_smoothness.py).

Called live by PhysicsFeasibilityChecker.validate() (wired into
quality_gate_manager.py::gate_physics_feasibility), with zero prior test
coverage.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.quality.check_elevation_smoothness import ElevationSmoothnessGate


def _road_with_elevations(segments):
    """segments: list of (s, a) tuples."""
    road = ET.Element("road", id="1")
    profile = ET.SubElement(road, "elevationProfile")
    for s, a in segments:
        ET.SubElement(profile, "elevation", s=f"{s}", a=f"{a}", b="0", c="0", d="0")
    return road


def _root(roads):
    root = ET.Element("OpenDRIVE")
    for r in roads:
        root.append(r)
    return root


def test_smooth_profile_no_issue():
    # 11 segments, each 10cm rise over 10m = 1% grade, well under MAX_DZ_PER_M.
    segs = [(float(i * 10), float(i) * 0.1) for i in range(11)]
    root = _root([_road_with_elevations(segs)])
    assert ElevationSmoothnessGate.validate(root) == []


def test_spiky_profile_flagged():
    # Alternating huge jumps -> every segment exceeds MAX_DZ_PER_M (0.25 m/m),
    # more than MAX_SPIKY_SEGMENTS_PER_ROAD (10) of them.
    segs = [(float(i), float(i % 2) * 100.0) for i in range(15)]
    root = _root([_road_with_elevations(segs)])
    issues = ElevationSmoothnessGate.validate(root)
    assert any(i["type"] == "elevation_spiky" for i in issues)


def test_nonfinite_elevation_flagged_not_silently_passed():
    # A corrupted `a` coefficient ("nan") makes dz/slope non-finite; `nan >
    # MAX_DZ_PER_M` is always False in IEEE-754, so every one of these
    # segments would silently count as non-spiky instead of being flagged.
    segs = [(float(i * 10), "nan" if i % 2 else 0.0) for i in range(15)]
    road = ET.Element("road", id="1")
    profile = ET.SubElement(road, "elevationProfile")
    for i, (s, a) in enumerate(segs):
        ET.SubElement(profile, "elevation", s=f"{s}", a=str(a), b="0", c="0", d="0")
    root = _root([road])
    issues = ElevationSmoothnessGate.validate(root)
    assert any(i["type"] == "elevation_spiky" for i in issues)
