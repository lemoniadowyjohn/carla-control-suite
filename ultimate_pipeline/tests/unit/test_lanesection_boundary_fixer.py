# -*- coding: utf-8 -*-
"""Tests for LaneSectionBoundaryFixer (ultimate_pipeline/geometry/lanesection_boundary_fixer.py).

Live: enforces CARLA-hard laneSection boundary invariants (non-negative,
first-at-zero, strictly monotonic, no insane gaps, last within road length).
Zero prior test coverage.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.geometry.lanesection_boundary_fixer import (
    LaneSectionBoundaryFixer,
)


def _road(length, section_s_values):
    road = ET.Element("road", id="1", length=f"{length}")
    lanes = ET.SubElement(road, "lanes")
    sections = []
    for s in section_s_values:
        sections.append(ET.SubElement(lanes, "laneSection", s=f"{s}"))
    return road, sections


def _root(road):
    root = ET.Element("OpenDRIVE")
    root.append(road)
    return root


def _s_values(road):
    return [float(s.get("s")) for s in road.findall("lanes/laneSection")]


def test_well_formed_sections_left_unchanged():
    road, _ = _road(100.0, [0.0, 25.0, 50.0])
    LaneSectionBoundaryFixer.fix(_root(road))
    assert _s_values(road) == [0.0, 25.0, 50.0]


def test_negative_start_clamped_to_zero():
    road, _ = _road(100.0, [-5.0, 25.0])
    LaneSectionBoundaryFixer.fix(_root(road))
    assert _s_values(road)[0] == 0.0


def test_first_section_forced_to_zero_if_not_already():
    road, _ = _road(100.0, [10.0, 25.0])
    LaneSectionBoundaryFixer.fix(_root(road))
    assert _s_values(road)[0] == 0.0


def test_nonmonotonic_sections_are_bumped_forward():
    road, _ = _road(100.0, [0.0, 20.0, 20.0])  # duplicate s -- not strictly increasing
    LaneSectionBoundaryFixer.fix(_root(road))
    values = _s_values(road)
    assert values[0] < values[1] < values[2]


def test_insane_gap_is_shrunk_but_stays_monotonic():
    road, _ = _road(1000.0, [0.0, 500.0])  # 500m gap > 150m insane-gap threshold
    LaneSectionBoundaryFixer.fix(_root(road))
    values = _s_values(road)
    assert values[1] - values[0] <= 50.0 + 1e-6
    assert values[1] > values[0]


def test_last_section_clamped_inside_road_length():
    road, _ = _road(100.0, [0.0, 150.0])  # exceeds road length
    LaneSectionBoundaryFixer.fix(_root(road))
    values = _s_values(road)
    assert values[-1] <= 100.0
    assert values[-1] > values[0]


def test_road_with_no_lanesections_is_skipped():
    road = ET.Element("road", id="1", length="10")
    ET.SubElement(road, "lanes")
    # Must not raise for a road with an empty <lanes> element.
    LaneSectionBoundaryFixer.fix(_root(road))


def test_unsorted_document_order_input_values_stay_numerically_correct_but_document_order_is_not_rewritten():
    # fix() sorts a Python-side list by `s` to compute correct monotonic
    # values, but never reorders the actual <laneSection> XML *siblings* --
    # so if a road ever arrives with laneSection elements out of document
    # order (values already ascending internally, just not in the order
    # they appear in the file), the fixed values remain numerically correct
    # relative to that internal sort, but re-querying the DOM in document
    # order still returns them out of order. Flagged as a known, currently
    # unproven-in-practice gap (see project_lane_width_clamp_noop_fix_20260829
    # memory) rather than fixed -- reordering XML siblings safely would also
    # need to preserve <laneOffset> siblings' relative positions, more
    # invasive than this session's other geometry fixes.
    road, _ = _road(100.0, [50.0, 0.0, 25.0])
    LaneSectionBoundaryFixer.fix(_root(road))
    document_order_values = _s_values(road)
    assert document_order_values == [50.0, 0.0, 25.0]  # unchanged: already consistent
