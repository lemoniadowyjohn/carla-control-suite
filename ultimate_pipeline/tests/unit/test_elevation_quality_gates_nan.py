# -*- coding: utf-8 -*-
"""Elevation-subsystem audit (post-audit-phase-e): NaN/Inf elevation values must
fail closed at every quality gate that reads OpenDRIVE elevation coefficients.

Bug found: `check_elevation_continuity.py`, `check_elevation_missing_and_cliffs.py`,
`check_elevation_seams.py`, and `elevation_structure_invariants.py` (all four
gate map acceptance) each defined a local `_safe_float(x, default=0.0)` that
only catches parse *exceptions* -- `float("nan")` and `float("inf")` parse
successfully in Python, so a NaN/Inf elevation coefficient sailed straight
through unguarded. Every downstream comparison against a NaN dz/height then
evaluates False (IEEE-754: `nan > threshold` and `nan <= threshold` are both
False), so the "flag if too big" checks silently never fire for that road and
the gate reports `ok: True` on a map containing a NaN/Inf elevation value.

This is the same defect class already fixed once this session in a different
file (`_safe_float(v, 0.0)` substituting a finite default for non-finite input
made a finiteness check permanently dead) -- except here there was no
finiteness check to begin with. The current real elevation-writing producer
(`ElevationImporter.make_raster_sampler`) already validates `math.isfinite`
before ever writing a value, so a NaN elevation is not currently reachable
through the main pipeline; this closes the gate-side gap so a future producer
regression (or a hand-crafted/corrupted XODR) cannot silently pass acceptance.

Fix: each `_safe_float` now also rejects non-finite values, matching the
existing correct pattern already used elsewhere in this codebase (see
`extract_elevation_stats.py::_safe_float`, `elevation_gap.py::_safe_float`,
`elevation_summary.py::_safe_float`).
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.quality.check_elevation_continuity import (
    check_elevation_continuity,
)
from ultimate_pipeline.quality.check_elevation_missing_and_cliffs import (
    check_elevation_missing_and_cliffs,
)
from ultimate_pipeline.quality.check_elevation_seams import check_elevation_seams
from ultimate_pipeline.quality.elevation_structure_invariants import (
    validate_elevation_profile_structure,
)


def _nan_linked_pair_xodr(tmp_path: Path, *, bad_value: str = "nan") -> str:
    """Two roads linked successor->predecessor; road 1's elevation 'a' is NaN/Inf.

    Road 2 starts flat at z=5.0. If NaN were treated as a huge finite jump the
    gates would (correctly) flag it; the bug is that NaN comparisons are
    silently False, so nothing is flagged at all.
    """
    root = ET.Element("OpenDRIVE")
    road1 = ET.SubElement(root, "road", id="1", length="10.0", junction="-1")
    link1 = ET.SubElement(road1, "link")
    ET.SubElement(link1, "successor", elementType="road", elementId="2", contactPoint="start")
    prof1 = ET.SubElement(road1, "elevationProfile")
    ET.SubElement(prof1, "elevation", s="0.0", a=bad_value, b="0", c="0", d="0")

    road2 = ET.SubElement(root, "road", id="2", length="10.0", junction="-1")
    prof2 = ET.SubElement(road2, "elevationProfile")
    ET.SubElement(prof2, "elevation", s="0.0", a="5.0", b="0", c="0", d="0")

    path = tmp_path / "nan_pair.xodr"
    ET.ElementTree(root).write(str(path), encoding="utf-8", xml_declaration=True)
    return str(path)


class TestCheckElevationContinuityRejectsNonFinite:
    def test_nan_elevation_is_flagged_not_silently_passed(self, tmp_path):
        xodr = _nan_linked_pair_xodr(tmp_path, bad_value="nan")
        rep = check_elevation_continuity(xodr, eps_z=0.5)
        assert rep["ok"] is False
        assert rep["num_issues"] >= 1

    def test_inf_elevation_is_flagged_not_silently_passed(self, tmp_path):
        xodr = _nan_linked_pair_xodr(tmp_path, bad_value="inf")
        rep = check_elevation_continuity(xodr, eps_z=0.5)
        assert rep["ok"] is False
        assert rep["num_issues"] >= 1

    def test_ordinary_finite_values_still_pass(self, tmp_path):
        xodr = _nan_linked_pair_xodr(tmp_path, bad_value="5.0")
        rep = check_elevation_continuity(xodr, eps_z=0.5)
        assert rep["ok"] is True
        assert rep["num_issues"] == 0


class TestCheckElevationMissingAndCliffsRejectsNonFinite:
    def test_nan_elevation_is_not_silently_ok(self, tmp_path):
        xodr = _nan_linked_pair_xodr(tmp_path, bad_value="nan")
        rep = check_elevation_missing_and_cliffs(xodr, max_link_dz_m=50.0)
        assert not (math.isnan(rep["max_link_dz"]))
        # A NaN source value must not silently report a finite, in-bounds dz.
        assert rep["ok"] is False or rep["max_link_dz"] > 50.0

    def test_ordinary_finite_values_still_pass(self, tmp_path):
        xodr = _nan_linked_pair_xodr(tmp_path, bad_value="5.0")
        rep = check_elevation_missing_and_cliffs(xodr, max_link_dz_m=50.0)
        assert rep["ok"] is True
        assert math.isfinite(rep["max_link_dz"])


class TestCheckElevationSeamsRejectsNonFinite:
    def test_nan_elevation_does_not_poison_seam_stats(self, tmp_path):
        """NaN must fail closed to a finite default (0.0), not propagate: a
        NaN 'a' coefficient must never leave seam_stats.max_jump/p95_jump as
        NaN, because a NaN threshold comparison is always False and would
        silently disable the seam-jump gate for the rest of the map (every
        `dz > step_threshold_m` check downstream of a NaN sample is False).
        """
        xodr = _nan_linked_pair_xodr(tmp_path, bad_value="nan")
        rep = check_elevation_seams(xodr)
        assert math.isfinite(rep["seam_stats"]["max_jump"])
        assert rep["seam_stats"]["p95_jump"] is None or math.isfinite(rep["seam_stats"]["p95_jump"])

    def test_inf_elevation_does_not_poison_seam_stats(self, tmp_path):
        xodr = _nan_linked_pair_xodr(tmp_path, bad_value="inf")
        rep = check_elevation_seams(xodr)
        assert math.isfinite(rep["seam_stats"]["max_jump"])

    def test_ordinary_finite_values_still_pass(self, tmp_path):
        xodr = _nan_linked_pair_xodr(tmp_path, bad_value="5.0")
        rep = check_elevation_seams(xodr)
        assert math.isfinite(rep["seam_stats"]["max_jump"])


class TestElevationStructureInvariantsRejectsNonFinite:
    def _root_with_bad_value(self, bad_value: str) -> ET.Element:
        # Road length kept below MIN_PIECEWISE_ROAD_LENGTH_M (60.0) so the
        # unrelated ELV-002 "single linear segment on a long road" rule does
        # not also fire and confound the finiteness-specific assertion.
        root = ET.Element("OpenDRIVE")
        road = ET.SubElement(root, "road", id="1", length="10.0")
        profile = ET.SubElement(road, "elevationProfile")
        ET.SubElement(profile, "elevation", s="0.0", a=bad_value, b="0.0", c="0.0", d="0.0")
        return root

    def test_nan_coefficient_fails_closed_to_finite_default(self):
        """A NaN 'a' coefficient must fail closed to a finite default (0.0)
        rather than propagate: an unguarded NaN would make every subsequent
        ELV-003/ELV-004 numeric comparison against it evaluate False (IEEE-754
        NaN comparisons are always False), silently disabling those checks for
        the road instead of just neutrally treating it as height 0.
        """
        root = self._root_with_bad_value("nan")
        res = validate_elevation_profile_structure(root)
        # No issue should itself be reported as a NaN/Inf value leaking through.
        for issue in res["issues"]:
            assert "nan" not in str(issue.get("detail", "")).lower()
            assert "inf" not in str(issue.get("detail", "")).lower()

    def test_ordinary_finite_values_still_pass(self):
        root = self._root_with_bad_value("5.0")
        res = validate_elevation_profile_structure(root)
        assert res["ok"] is True
