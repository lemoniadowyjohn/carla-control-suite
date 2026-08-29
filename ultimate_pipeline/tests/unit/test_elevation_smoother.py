# -*- coding: utf-8 -*-
"""Tests for ElevationSmoother (ultimate_pipeline/geometry/elevation_smoother.py).

Live: called by pipeline_stages (geometry hardening pass) to clamp insane
elevation slopes while preserving absolute height. Zero prior test coverage.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.geometry.elevation_smoother import ElevationSmoother


def _road_with_elevation(a="10.0", b="0.05", c="0.0", d="0.0"):
    road = ET.Element("road", id="1", length="10")
    profile = ET.SubElement(road, "elevationProfile")
    ev = ET.SubElement(profile, "elevation", s="0", a=a, b=b, c=c, d=d)
    return road, ev


def _root(roads):
    root = ET.Element("OpenDRIVE")
    for r in roads:
        root.append(r)
    return root


def test_normal_slope_preserved_unchanged():
    road, ev = _road_with_elevation(a="10.0", b="0.05", c="0.001", d="0.0")
    ElevationSmoother.smooth(_root([road]))
    assert float(ev.get("a")) == 10.0
    assert float(ev.get("b")) == 0.05
    assert float(ev.get("c")) == 0.001


def test_insane_slope_flattened_but_absolute_height_preserved():
    road, ev = _road_with_elevation(a="42.0", b="99.0", c="5.0", d="1.0")
    ElevationSmoother.smooth(_root([road]), max_abs_b=2.0)
    assert float(ev.get("a")) == 42.0  # absolute height preserved
    assert float(ev.get("b")) == 0.0
    assert float(ev.get("c")) == 0.0
    assert float(ev.get("d")) == 0.0


def test_negative_insane_slope_also_flattened():
    road, ev = _road_with_elevation(a="0.0", b="-50.0")
    ElevationSmoother.smooth(_root([road]), max_abs_b=2.0)
    assert float(ev.get("b")) == 0.0


def test_road_without_elevation_profile_is_skipped():
    road = ET.Element("road", id="1", length="10")
    root = _root([road])
    # Must not raise for a road with no elevationProfile at all.
    ElevationSmoother.smooth(root)


def test_nonfinite_coefficient_sanitized_to_default_not_propagated():
    # _safe_float (xodr_sanitizer.py) already guards NaN/Inf internally,
    # returning the default (0.0) rather than letting NaN through -- a
    # corrupted b="nan" is treated as a flat/safe slope, not propagated.
    road, ev = _road_with_elevation(a="5.0", b="nan")
    ElevationSmoother.smooth(_root([road]), max_abs_b=2.0)
    assert float(ev.get("b")) == 0.0
