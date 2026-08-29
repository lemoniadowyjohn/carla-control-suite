# -*- coding: utf-8 -*-
"""Tests for LaneOffsetNormalizer + normalize_junction_laneoffsets
(ultimate_pipeline/geometry/laneoffset_normalizer.py). Zero prior coverage.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.geometry.laneoffset_normalizer import (
    LaneOffsetNormalizer,
    normalize_junction_laneoffsets,
)


def _road(length, offsets, junction="-1"):
    """offsets: list of (s, a, b, c, d) tuples, added in the given order
    (not necessarily s-sorted, to exercise the sort-and-reorder path)."""
    road = ET.Element("road", id="1", length=f"{length}", junction=junction)
    lanes = ET.SubElement(road, "lanes")
    for s, a, b, c, d in offsets:
        ET.SubElement(
            lanes, "laneOffset",
            s=f"{s}", a=f"{a}", b=f"{b}", c=f"{c}", d=f"{d}",
        )
    return road


def _root(road):
    root = ET.Element("OpenDRIVE")
    root.append(road)
    return root


def _offsets_in_document_order(road):
    return road.find("lanes").findall("laneOffset")


def test_out_of_order_offsets_are_reordered_in_the_document():
    road = _road(100.0, [(50.0, 0, 0, 0, 0), (0.0, 0, 0, 0, 0), (25.0, 0, 0, 0, 0)])
    LaneOffsetNormalizer.normalize(_root(road))
    s_values = [float(o.get("s")) for o in _offsets_in_document_order(road)]
    assert s_values == sorted(s_values)


def test_no_offsets_creates_zero_offset_at_origin():
    road = ET.Element("road", id="1", length="50")
    ET.SubElement(road, "lanes")
    LaneOffsetNormalizer.normalize(_root(road))
    offsets = _offsets_in_document_order(road)
    assert len(offsets) == 1
    assert offsets[0].get("s") == "0.0"
    assert float(offsets[0].get("a")) == 0.0


def test_road_with_nonpositive_length_is_skipped_entirely():
    road = _road(0.0, [(0.0, 999.0, 0, 0, 0)])
    LaneOffsetNormalizer.normalize(_root(road))
    offsets = _offsets_in_document_order(road)
    # Untouched -- length <= 0 short-circuits before any offset processing.
    assert float(offsets[0].get("a")) == 999.0


def test_first_offset_forced_to_start_at_zero():
    road = _road(100.0, [(5.0, 1.0, 0, 0, 0)])
    LaneOffsetNormalizer.normalize(_root(road))
    assert _offsets_in_document_order(road)[0].get("s") == "0.0"


def test_insane_first_offset_a_clamped_to_zero():
    road = _road(100.0, [(0.0, 999.0, 0, 0, 0)])
    LaneOffsetNormalizer.normalize(_root(road), )
    assert float(_offsets_in_document_order(road)[0].get("a")) == 0.0


def test_continuity_reanchors_later_segment_a_to_previous_segment_end_value():
    # Segment 0: a=1.0, b=0.1 over ds=10 -> ends at 1.0 + 0.1*10 = 2.0
    # Segment 1's own 'a' (5.0) should be overwritten to continue from 2.0.
    road = _road(100.0, [(0.0, 1.0, 0.1, 0.0, 0.0), (10.0, 5.0, 0.0, 0.0, 0.0)])
    LaneOffsetNormalizer.normalize(_root(road))
    offsets = _offsets_in_document_order(road)
    assert float(offsets[1].get("a")) == 2.0


def test_junction_road_with_insane_first_offset_is_zeroed():
    road = _road(50.0, [(0.0, 10.0, 1.0, 1.0, 1.0)], junction="7")
    result = normalize_junction_laneoffsets(_root(road), max_abs_a=0.5)
    assert result["num_fixed"] == 1
    assert result["ok"] is True
    offset = road.find("lanes/laneOffset")
    assert float(offset.get("a")) == 0.0
    assert float(offset.get("b")) == 0.0


def test_junction_road_with_small_first_offset_is_left_alone():
    road = _road(50.0, [(0.0, 0.1, 0.0, 0.0, 0.0)], junction="7")
    result = normalize_junction_laneoffsets(_root(road), max_abs_a=0.5)
    assert result["num_fixed"] == 0
    offset = road.find("lanes/laneOffset")
    assert float(offset.get("a")) == 0.1


def test_non_junction_road_is_never_checked():
    road = _road(50.0, [(0.0, 999.0, 0.0, 0.0, 0.0)], junction="-1")
    result = normalize_junction_laneoffsets(_root(road), max_abs_a=0.5)
    assert result["num_checked"] == 0
    offset = road.find("lanes/laneOffset")
    assert float(offset.get("a")) == 999.0
