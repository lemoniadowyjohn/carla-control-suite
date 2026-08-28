"""Tests for ultimate_pipeline/topology/semantic_verifier.py.

Prior to this test file, SemanticVerifier had zero coverage despite being
wired into stage_02_topology_semantics.py's "Semantic Risk Scan" step on
every real pipeline run (STEP 2D), operating on the post-SUMO-repair XODR.

Bug found and fixed here: analyze_xodr() crashed with IndexError on any
road with zero planView geometries, as long as the file had at least one
geometry element anywhere else. Check #1 already flags "missing geometry"
roads (risk += 5), but execution fell through unconditionally to check #8
("floating island"), which read geoms[0] without checking geoms was
non-empty. Zero-geometry roads are a real, tracked condition elsewhere in
this codebase (see structure_scanner.py's zero_geometry_roads and
topology_linter.py TL comments), so this was reachable on real maps, not
just synthetic edge cases.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from ultimate_pipeline.topology.semantic_verifier import SemanticVerifier


def _write_xodr(tmp_path, body: str) -> str:
    path = os.path.join(str(tmp_path), "test.xodr")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f'<?xml version="1.0"?>\n<OpenDRIVE>\n{body}\n</OpenDRIVE>')
    return path


def test_analyze_xodr_missing_file_raises(tmp_path):
    missing = os.path.join(str(tmp_path), "does_not_exist.xodr")
    with pytest.raises(FileNotFoundError):
        SemanticVerifier.analyze_xodr(missing)


def test_analyze_xodr_zero_geometry_road_does_not_crash(tmp_path):
    """RED (before fix): raised IndexError on geoms[0] in check #8.

    A road with normal geometry establishes a non-trivial global_span so
    check #8's `if xs and ys:` branch is entered; a second road with a
    <planView> but zero <geometry> children must not crash the scan.
    """
    xodr = _write_xodr(
        tmp_path,
        """
  <road id="1" length="10.0">
    <planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>
  </road>
  <road id="2" length="5.0">
    <planView></planView>
  </road>
""",
    )
    risk_map = SemanticVerifier.analyze_xodr(xodr)
    assert risk_map["1"] == pytest.approx(0.0)
    # Road 2 has no geometry -> check #1 penalty (risk += 5) applies.
    assert risk_map["2"] >= 5.0


def test_analyze_xodr_road_with_no_planview_element_does_not_crash(tmp_path):
    """Same guard, but the road has no <planView> element at all."""
    xodr = _write_xodr(
        tmp_path,
        """
  <road id="1" length="10.0">
    <planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>
  </road>
  <road id="2" length="5.0">
  </road>
""",
    )
    risk_map = SemanticVerifier.analyze_xodr(xodr)
    assert risk_map["2"] >= 5.0


def test_analyze_xodr_normal_road_low_risk(tmp_path):
    xodr = _write_xodr(
        tmp_path,
        """
  <road id="1" length="10.0">
    <planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>
  </road>
""",
    )
    risk_map = SemanticVerifier.analyze_xodr(xodr)
    assert risk_map["1"] == pytest.approx(0.0)


def test_analyze_xodr_degenerate_length_flagged(tmp_path):
    xodr = _write_xodr(
        tmp_path,
        """
  <road id="1" length="0.1">
    <planView><geometry s="0" x="0" y="0" hdg="0" length="0.1"><line/></geometry></planView>
  </road>
""",
    )
    risk_map = SemanticVerifier.analyze_xodr(xodr)
    assert risk_map["1"] >= 3.0


def test_analyze_xodr_geometry_overflow_flagged(tmp_path):
    xodr = _write_xodr(
        tmp_path,
        """
  <road id="1" length="5.0">
    <planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>
  </road>
""",
    )
    risk_map = SemanticVerifier.analyze_xodr(xodr)
    assert risk_map["1"] >= 3.0


def test_analyze_xodr_far_outlier_flagged_as_floating_island(tmp_path):
    # global_span is the max of (x-spread, y-spread) pooled across ALL
    # geometries in the file, so a single point can only trip
    # `abs(coord) > 1.5 * global_span` when its large coordinate is on a
    # DIFFERENT axis than the one defining the span (a same-axis outlier
    # always dominates its own span and can never exceed a 1.0x ratio of
    # itself, let alone 1.5x). This case decouples x/y: road 1's y0 is far
    # outside the x-defined span while both roads' y-values stay close
    # together, so global_span (from x) stays small relative to y0.
    xodr = _write_xodr(
        tmp_path,
        """
  <road id="1" length="10.0">
    <planView><geometry s="0" x="18.799280212259873" y="421.8428056768596" hdg="0" length="10"><line/></geometry></planView>
  </road>
  <road id="2" length="10.0">
    <planView><geometry s="0" x="-238.39589362685604" y="491.7692073325584" hdg="0" length="10"><line/></geometry></planView>
  </road>
""",
    )
    risk_map = SemanticVerifier.analyze_xodr(xodr)
    assert risk_map["1"] >= 5.0


def test_get_high_risk_roads_filters_by_threshold():
    risk_map = {"1": 2.0, "2": 8.0, "3": 9.5, "4": 7.9}
    high = SemanticVerifier.get_high_risk_roads(risk_map, threshold=8.0)
    assert set(high) == {"2", "3"}


def test_get_high_risk_roads_empty_map():
    assert SemanticVerifier.get_high_risk_roads({}, threshold=8.0) == []


def test_summarize_does_not_raise_on_empty_map(capsys):
    SemanticVerifier.summarize({})
    captured = capsys.readouterr()
    assert "Total roads analyzed:" in captured.out


def test_summarize_prints_high_risk_ids(capsys):
    SemanticVerifier.summarize({"1": 9.0, "2": 1.0})
    captured = capsys.readouterr()
    assert "High-risk roads" in captured.out
