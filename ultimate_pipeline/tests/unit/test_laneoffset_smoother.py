# -*- coding: utf-8 -*-
"""Tests for LaneOffsetSmoother (ultimate_pipeline/geometry/laneoffset_smoother.py).

Live geometry-repair module: clamps insane laneOffset coefficients and
limits the delta in 'a' between consecutive offsets to max_delta. Zero
prior test coverage.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.geometry.laneoffset_smoother import LaneOffsetSmoother


def _road(offsets):
    """offsets: list of (s, a, b, c, d) tuples."""
    road = ET.Element("road", id="1", length="100")
    lanes = ET.SubElement(road, "lanes")
    for s, a, b, c, d in offsets:
        ET.SubElement(lanes, "laneOffset", s=f"{s}", a=f"{a}", b=f"{b}", c=f"{c}", d=f"{d}")
    return road


def _root(road):
    root = ET.Element("OpenDRIVE")
    root.append(road)
    return root


def _a_values(road):
    return [float(o.get("a")) for o in road.findall("lanes/laneOffset")]


def test_large_jump_between_consecutive_offsets_is_clamped_to_max_delta():
    road = _road([(0.0, 0.0, 0, 0, 0), (10.0, 5.0, 0, 0, 0)])
    LaneOffsetSmoother.smooth(_root(road), max_delta=0.5)
    a_vals = _a_values(road)
    assert a_vals[0] == 0.0
    assert a_vals[1] == 0.5  # clamped from 5.0 to 0.0 + 0.5


def test_negative_jump_clamped_in_correct_direction():
    road = _road([(0.0, 5.0, 0, 0, 0), (10.0, 0.0, 0, 0, 0)])
    LaneOffsetSmoother.smooth(_root(road), max_delta=0.5)
    a_vals = _a_values(road)
    assert a_vals[1] == 4.5  # clamped from 0.0 to 5.0 - 0.5


def test_small_jump_within_tolerance_untouched():
    road = _road([(0.0, 1.0, 0, 0, 0), (10.0, 1.2, 0, 0, 0)])
    LaneOffsetSmoother.smooth(_root(road), max_delta=0.5)
    assert _a_values(road)[1] == 1.2


def test_insane_coefficient_clamped_to_zero():
    road = _road([(0.0, 5000.0, 0, 0, 0)])
    LaneOffsetSmoother.smooth(_root(road))
    assert _a_values(road)[0] == 0.0


def test_road_with_no_offsets_is_a_noop():
    road = ET.Element("road", id="1", length="10")
    ET.SubElement(road, "lanes")
    LaneOffsetSmoother.smooth(_root(road))  # must not raise


def test_out_of_order_input_is_processed_in_s_order_regardless_of_document_order():
    # Offsets are appended out of s-order; the delta clamp must still be
    # evaluated in ascending-s order, not document (insertion) order.
    road = _road([(10.0, 5.0, 0, 0, 0), (0.0, 0.0, 0, 0, 0)])
    LaneOffsetSmoother.smooth(_root(road), max_delta=0.5)
    by_s = sorted(road.findall("lanes/laneOffset"), key=lambda o: float(o.get("s")))
    assert float(by_s[0].get("a")) == 0.0
    assert float(by_s[1].get("a")) == 0.5  # clamped relative to the s=0 entry
