# -*- coding: utf-8 -*-
"""Post-audit-phase-e sweep: NaN/Inf values must fail closed at quality gates
that compare `_safe_float`-derived numbers against a magnitude threshold.

Bug found: `check_geometric_continuity.py`, `check_lane_geometry_continuity.py`,
`check_lane_width_continuity.py`, and `check_origin_sanity.py` (all four wired
into `quality_gate_manager.py` / `stage_06_links.py` / `stage_09_tiling.py` as
live map-acceptance gates) each define a local `_safe_float(x, default=0.0)`
that only catches parse *exceptions*. `float("nan")` parses successfully, so a
NaN XODR attribute (planView x/y, lane width coefficient, laneOffset
coefficient) sails through unguarded and propagates through arithmetic
(subtraction, `math.hypot`, polynomial evaluation) into a value compared with
a magnitude-threshold operator: `dxy > eps_xy`, `delta > lane_offset_eps`,
`start_width <= min_width`, `dist > fail_distance_m`, etc.

Unlike a `math.isfinite(x)`/`math.isnan(x)` check (which correctly detects NaN
even on an unguarded value -- not a bug), a magnitude comparison against NaN
is *always* False in IEEE-754 (`nan > threshold` and `nan <= threshold` both
evaluate False). So the "flag if too far apart" / "flag if too small" checks
silently never fire for that road, and the gate reports `ok: True` on a map
containing a NaN attribute -- exactly the kind of corrupted geometry these
gates exist to catch.

Fix: each defeated comparison site now has an explicit `math.isfinite` guard
that raises its own issue when the derived value is non-finite, rather than
silently falling through the magnitude check. This mirrors the same
fail-closed intent as the `_parse_float_strict` fix in
`check_carla_opendrive_compat.py` (e5ae532f) -- reject non-finite explicitly
instead of relying on a downstream comparison that turns out not to catch it.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.quality.check_geometric_continuity import (
    check_geometric_continuity,
)
from ultimate_pipeline.quality.check_lane_geometry_continuity import (
    check_lane_geometry_continuity,
)
from ultimate_pipeline.quality.check_lane_width_continuity import (
    check_lane_width_continuity,
)
from ultimate_pipeline.quality.check_origin_sanity import check_origin_sanity


def _write_xodr(path: Path, root: ET.Element) -> str:
    ET.ElementTree(root).write(str(path), encoding="utf-8", xml_declaration=True)
    return str(path)


class TestCheckGeometricContinuityRejectsNonFinite:
    def _linked_pair(self, *, x_value: str) -> ET.Element:
        root = ET.Element("OpenDRIVE")
        r1 = ET.SubElement(root, "road", id="1", length="10.0", junction="-1")
        link1 = ET.SubElement(r1, "link")
        ET.SubElement(link1, "successor", elementType="road", elementId="2", contactPoint="start")
        pv1 = ET.SubElement(r1, "planView")
        g1 = ET.SubElement(pv1, "geometry", s="0", x="0", y="0", hdg="0", length="10")
        ET.SubElement(g1, "line")

        r2 = ET.SubElement(root, "road", id="2", length="10.0", junction="-1")
        link2 = ET.SubElement(r2, "link")
        ET.SubElement(link2, "predecessor", elementType="road", elementId="1", contactPoint="end")
        pv2 = ET.SubElement(r2, "planView")
        # Road 2 starts at y=500 (an obvious 500m discontinuity) with x=<bad>.
        g2 = ET.SubElement(pv2, "geometry", s="0", x=x_value, y="500", hdg="0", length="10")
        ET.SubElement(g2, "line")
        return root

    def test_nan_coordinate_is_flagged_not_silently_passed(self, tmp_path):
        xodr = _write_xodr(tmp_path / "nan.xodr", self._linked_pair(x_value="nan"))
        rep = check_geometric_continuity(xodr)
        assert rep["ok"] is False
        assert rep["num_issues"] >= 1

    def test_ordinary_large_gap_still_flagged(self, tmp_path):
        xodr = _write_xodr(tmp_path / "gap.xodr", self._linked_pair(x_value="0"))
        rep = check_geometric_continuity(xodr)
        assert rep["ok"] is False
        assert rep["num_issues"] >= 1

    def test_ordinary_continuous_pair_still_passes(self, tmp_path):
        root = ET.Element("OpenDRIVE")
        r1 = ET.SubElement(root, "road", id="1", length="10.0", junction="-1")
        link1 = ET.SubElement(r1, "link")
        ET.SubElement(link1, "successor", elementType="road", elementId="2", contactPoint="start")
        pv1 = ET.SubElement(r1, "planView")
        g1 = ET.SubElement(pv1, "geometry", s="0", x="0", y="0", hdg="0", length="10")
        ET.SubElement(g1, "line")

        r2 = ET.SubElement(root, "road", id="2", length="10.0", junction="-1")
        link2 = ET.SubElement(r2, "link")
        ET.SubElement(link2, "predecessor", elementType="road", elementId="1", contactPoint="end")
        pv2 = ET.SubElement(r2, "planView")
        g2 = ET.SubElement(pv2, "geometry", s="0", x="10", y="0", hdg="0", length="10")
        ET.SubElement(g2, "line")

        xodr = _write_xodr(tmp_path / "ok.xodr", root)
        rep = check_geometric_continuity(xodr)
        assert rep["ok"] is True
        assert rep["num_issues"] == 0


class TestCheckLaneGeometryContinuityRejectsNonFinite:
    def _two_sections(self, *, width_a: str) -> ET.Element:
        root = ET.Element("OpenDRIVE")
        road = ET.SubElement(root, "road", id="1", length="20.0")
        lanes = ET.SubElement(road, "lanes")
        sec1 = ET.SubElement(lanes, "laneSection", s="0.0")
        left1 = ET.SubElement(sec1, "left")
        lane1 = ET.SubElement(left1, "lane", id="1", type="driving")
        ET.SubElement(lane1, "width", sOffset="0", a="3.5", b="0", c="0", d="0")

        sec2 = ET.SubElement(lanes, "laneSection", s="10.0")
        left2 = ET.SubElement(sec2, "left")
        lane2 = ET.SubElement(left2, "lane", id="1", type="driving")
        ET.SubElement(lane2, "width", sOffset="0", a=width_a, b="0", c="0", d="0")
        return root

    def test_nan_width_is_flagged_not_silently_passed(self, tmp_path):
        xodr = _write_xodr(tmp_path / "nan.xodr", self._two_sections(width_a="nan"))
        rep = check_lane_geometry_continuity(xodr)
        assert rep["ok"] is False
        assert rep["n_issues"] >= 1

    def test_ordinary_large_jump_still_flagged(self, tmp_path):
        xodr = _write_xodr(tmp_path / "jump.xodr", self._two_sections(width_a="30.0"))
        rep = check_lane_geometry_continuity(xodr)
        assert rep["ok"] is False
        assert rep["n_issues"] >= 1

    def test_ordinary_continuous_widths_still_pass(self, tmp_path):
        xodr = _write_xodr(tmp_path / "ok.xodr", self._two_sections(width_a="3.5"))
        rep = check_lane_geometry_continuity(xodr)
        assert rep["ok"] is True
        assert rep["n_issues"] == 0


class TestCheckLaneWidthContinuityRejectsNonFinite:
    def _single_section(self, *, width_a: str) -> ET.Element:
        root = ET.Element("OpenDRIVE")
        road = ET.SubElement(root, "road", id="1", length="10.0")
        lanes = ET.SubElement(road, "lanes")
        sec1 = ET.SubElement(lanes, "laneSection", s="0.0")
        lane1 = ET.SubElement(sec1, "lane", id="1", type="driving")
        ET.SubElement(lane1, "width", sOffset="0", a=width_a, b="0", c="0", d="0")
        return root

    def test_nan_width_is_flagged_not_silently_passed(self, tmp_path):
        xodr = _write_xodr(tmp_path / "nan.xodr", self._single_section(width_a="nan"))
        rep = check_lane_width_continuity(xodr)
        assert rep["ok"] is False
        assert rep["num_issues"] >= 1

    def test_ordinary_negative_width_still_flagged(self, tmp_path):
        xodr = _write_xodr(tmp_path / "neg.xodr", self._single_section(width_a="-2.0"))
        rep = check_lane_width_continuity(xodr)
        assert rep["ok"] is False
        assert rep["num_issues"] >= 1

    def test_ordinary_valid_width_still_passes(self, tmp_path):
        xodr = _write_xodr(tmp_path / "ok.xodr", self._single_section(width_a="3.5"))
        rep = check_lane_width_continuity(xodr)
        assert rep["ok"] is True
        assert rep["num_issues"] == 0


class TestCheckOriginSanityRejectsNonFinite:
    def _single_geometry(self, *, x_value: str) -> ET.Element:
        root = ET.Element("OpenDRIVE")
        road = ET.SubElement(root, "road", id="1", length="10.0")
        pv = ET.SubElement(road, "planView")
        ET.SubElement(pv, "geometry", s="0", x=x_value, y="0", hdg="0", length="10")
        return root

    def test_nan_origin_is_flagged_not_silently_passed(self, tmp_path):
        xodr = _write_xodr(tmp_path / "nan.xodr", self._single_geometry(x_value="nan"))
        rep = check_origin_sanity(xodr)
        assert rep["ok"] is False
        assert any("non-finite" in w or "nan" in w.lower() for w in rep["warnings"])

    def test_ordinary_far_origin_still_flagged(self, tmp_path):
        xodr = _write_xodr(tmp_path / "far.xodr", self._single_geometry(x_value="900000"))
        rep = check_origin_sanity(xodr)
        assert rep["ok"] is False

    def test_ordinary_near_origin_still_passes(self, tmp_path):
        xodr = _write_xodr(tmp_path / "ok.xodr", self._single_geometry(x_value="100"))
        rep = check_origin_sanity(xodr)
        assert rep["ok"] is True
