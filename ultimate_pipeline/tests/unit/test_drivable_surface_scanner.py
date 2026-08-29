# -*- coding: utf-8 -*-
"""Tests for DrivableSurfaceScanner (ultimate_pipeline/quality/drivable_surface_scanner.py).

Wired live into main_pipeline.py stage 08G (drivable_surface gate), with zero
prior test coverage.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.quality.drivable_surface_scanner import DrivableSurfaceScanner


def _two_section_road(*, x="0", a0="0", a1="0"):
    """A road with two lane sections linked by a lane successor, one planView
    geometry (so both sections' geometry lookups resolve to it), and matching
    elevationProfile entries so a drop can be exercised too."""
    road = ET.Element("road", id="1", length="20")
    pv = ET.SubElement(road, "planView")
    g1 = ET.SubElement(pv, "geometry", s="0", x=x, y="0", hdg="0", length="10")
    ET.SubElement(g1, "line")

    elev = ET.SubElement(road, "elevationProfile")
    ET.SubElement(elev, "elevation", s="0", a=a0, b="0", c="0", d="0")
    ET.SubElement(elev, "elevation", s="10", a=a1, b="0", c="0", d="0")

    lanes = ET.SubElement(road, "lanes")
    sec0 = ET.SubElement(lanes, "laneSection", s="0")
    left0 = ET.SubElement(sec0, "left")
    lane0 = ET.SubElement(left0, "lane", id="1", type="driving")
    link0 = ET.SubElement(lane0, "link")
    ET.SubElement(link0, "successor", id="1")
    sec1 = ET.SubElement(lanes, "laneSection", s="10")
    left1 = ET.SubElement(sec1, "left")
    ET.SubElement(left1, "lane", id="1", type="driving")
    return road


def _write(tmp_path: Path, road: ET.Element) -> str:
    root = ET.Element("OpenDRIVE")
    root.append(road)
    p = tmp_path / "test.xodr"
    ET.ElementTree(root).write(str(p))
    return str(p)


def test_valid_geometry_hole_detected(tmp_path):
    # Baseline: pred-end (frac=0) vs succ-start (frac=1) along the one
    # geometry naturally differ by the geometry's own length (10m) here --
    # this proves the gate fires on a real, finite, over-threshold gap.
    p = _write(tmp_path, _two_section_road())
    report = DrivableSurfaceScanner.scan(p, hole_threshold_m=0.5)
    assert report["ok"] is False
    assert report["total_holes"] == 1


def test_nonfinite_planview_x_flagged_not_silently_passed(tmp_path):
    # A corrupted planView x="nan" makes geo_gap = math.hypot(...) non-finite;
    # `nan > hole_threshold_m` is always False in IEEE-754, so this silently
    # reported zero holes / ok=True instead of flagging the corruption.
    p = _write(tmp_path, _two_section_road(x="nan"))
    report = DrivableSurfaceScanner.scan(p, hole_threshold_m=0.5)
    assert report["ok"] is False
    assert report["total_holes"] >= 1


def test_nonfinite_elevation_flagged_not_silently_passed(tmp_path):
    # A corrupted elevation a="nan" makes z_diff non-finite; `nan >
    # drop_threshold_m` is always False in IEEE-754, so a genuinely corrupt
    # elevation profile silently reported zero drops instead of being
    # flagged. Use a tiny hole/seam threshold gap (frac=0 vs frac=1 on the
    # same 10m geometry) that won't itself dominate -- raise those
    # thresholds so only the drop check is exercised.
    p = _write(tmp_path, _two_section_road(a0="0", a1="nan"))
    report = DrivableSurfaceScanner.scan(
        p, hole_threshold_m=1000.0, seam_threshold_deg=1000.0, drop_threshold_m=0.3
    )
    assert report["ok"] is False
    assert report["total_drops"] >= 1
