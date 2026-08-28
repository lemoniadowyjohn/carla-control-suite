"""Tests for ultimate_pipeline/topology/structure_scanner.py.

Zero prior test coverage despite StructureScanner.analyze() being invoked
on every real pipeline run (STEP 2C: Structural Scan, in
stage_02_topology_semantics.py) and feeding vreport["structure_scan"].
It is explicitly documented as NON-DESTRUCTIVE / DIAGNOSTIC-ONLY.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.topology.structure_scanner import StructureScanner, _safe_float


def _root(xml_body: str) -> ET.Element:
    return ET.fromstring(f'<?xml version="1.0"?>\n<OpenDRIVE>\n{xml_body}\n</OpenDRIVE>')


# ---------------------------------------------------------------------------
# _safe_float
# ---------------------------------------------------------------------------
def test_safe_float_parses_normal_value():
    assert _safe_float("3.5") == 3.5


def test_safe_float_none_returns_default():
    assert _safe_float(None, default=1.5) == 1.5


def test_safe_float_nan_returns_default():
    assert _safe_float("nan", default=0.0) == 0.0


def test_safe_float_inf_returns_default():
    assert _safe_float("inf", default=0.0) == 0.0


def test_safe_float_garbage_returns_default():
    assert _safe_float("not-a-number", default=7.0) == 7.0


# ---------------------------------------------------------------------------
# analyze(): does not mutate input
# ---------------------------------------------------------------------------
def test_analyze_does_not_modify_xml():
    root = _root(
        """
  <road id="1" length="10.0">
    <link><successor elementType="road" elementId="2" contactPoint="start"/></link>
    <planView><geometry s="0" x="0" y="0" hdg="0" length="10"/></planView>
  </road>
  <road id="2" length="10.0"/>
"""
    )
    before = ET.tostring(root)
    StructureScanner.analyze(root)
    after = ET.tostring(root)
    assert before == after


def test_analyze_empty_map_returns_report_without_raising():
    root = _root("")
    report = StructureScanner.analyze(root)
    assert report["multi_successor"] == []
    assert report["zero_geometry_roads"] == []
    assert report["graph_islands"]["total_roads"] == 0


# ---------------------------------------------------------------------------
# Legacy quick checks: multi-successor / multi-predecessor / self-links
# ---------------------------------------------------------------------------
def test_multi_successor_detected():
    root = _root(
        """
  <road id="1">
    <link>
      <successor elementType="road" elementId="2" contactPoint="start"/>
      <successor elementType="road" elementId="3" contactPoint="start"/>
    </link>
  </road>
  <road id="2"/>
  <road id="3"/>
"""
    )
    report = StructureScanner.analyze(root)
    assert "1" in report["multi_successor"]


def test_self_link_detected():
    root = _root(
        '<road id="1"><link><successor elementType="road" elementId="1" contactPoint="start"/></link></road>'
    )
    report = StructureScanner.analyze(root)
    assert "1" in report["self_links"]


# ---------------------------------------------------------------------------
# Zero-geometry roads
# ---------------------------------------------------------------------------
def test_zero_geometry_road_no_planview():
    root = _root('<road id="1"/>')
    report = StructureScanner.analyze(root)
    assert "1" in report["zero_geometry_roads"]


def test_zero_geometry_road_empty_planview():
    root = _root('<road id="1"><planView></planView></road>')
    report = StructureScanner.analyze(root)
    assert "1" in report["zero_geometry_roads"]


def test_road_with_geometry_not_flagged_zero():
    root = _root(
        '<road id="1"><planView><geometry s="0" x="0" y="0" hdg="0" length="10"/></planView></road>'
    )
    report = StructureScanner.analyze(root)
    assert "1" not in report["zero_geometry_roads"]


# ---------------------------------------------------------------------------
# Broken junction refs
# ---------------------------------------------------------------------------
def test_broken_junction_ref_missing_incoming():
    root = _root(
        """
  <road id="2"/>
  <junction id="10"><connection incomingRoad="999" connectingRoad="2"/></junction>
"""
    )
    report = StructureScanner.analyze(root)
    refs = report["broken_junction_refs"]
    assert any(r["type"] == "missing_incomingRoad" for r in refs)


def test_broken_junction_ref_missing_connecting():
    root = _root(
        """
  <road id="1"/>
  <junction id="10"><connection incomingRoad="1" connectingRoad="999"/></junction>
"""
    )
    report = StructureScanner.analyze(root)
    refs = report["broken_junction_refs"]
    assert any(r["type"] == "missing_connectingRoad" for r in refs)


def test_valid_junction_ref_not_flagged():
    root = _root(
        """
  <road id="1"/><road id="2"/>
  <junction id="10"><connection incomingRoad="1" connectingRoad="2"/></junction>
"""
    )
    report = StructureScanner.analyze(root)
    assert report["broken_junction_refs"] == []
    stats = report["junction_stats"]["stats"]
    assert stats["total_junctions"] == 1
    assert stats["num_roads_with_junctions"] == 2


# ---------------------------------------------------------------------------
# Curvature analysis
# ---------------------------------------------------------------------------
def test_curvature_no_geometry_returns_empty():
    root = _root('<road id="1"/>')
    report = StructureScanner.analyze(root)
    curv = report["curvature_anomalies"]
    assert curv["per_road"] == []
    assert curv["threshold"] is None


def test_curvature_arc_value_detected():
    root = _root(
        """
  <road id="1">
    <planView>
      <geometry s="0" x="0" y="0" hdg="0" length="10"><arc curvature="0.8"/></geometry>
    </planView>
  </road>
"""
    )
    report = StructureScanner.analyze(root)
    curv = report["curvature_anomalies"]
    entry = next(e for e in curv["per_road"] if e["road_id"] == "1")
    assert entry["max_abs_curvature"] == pytest.approx(0.8)
    assert any(a["road_id"] == "1" for a in curv["anomalous_roads"])


def test_curvature_estimated_from_heading_delta_when_no_arc():
    root = _root(
        """
  <road id="1">
    <planView>
      <geometry s="0" x="0" y="0" hdg="0.0" length="10"/>
      <geometry s="10" x="10" y="0" hdg="1.5" length="10"/>
    </planView>
  </road>
"""
    )
    report = StructureScanner.analyze(root)
    curv = report["curvature_anomalies"]
    entry = next((e for e in curv["per_road"] if e["road_id"] == "1"), None)
    assert entry is not None
    assert entry["max_abs_curvature"] > 0.0


# ---------------------------------------------------------------------------
# Lane-section discontinuities
#
# Bug found and fixed here: _analyze_lane_sections sorted laneSections by s
# BEFORE checking them for "non-monotonic" order, then checked the now-sorted
# list. A check that sorts its input and then tests the sorted result for
# sortedness can, by construction, only ever fire on exact ties (s[i+1] <=
# s[i] can only be true when equal, never "<", once sorted ascending) -- it
# can never detect the actual defect it claims to check for: laneSections
# declared out of order in the XML. Fixed by checking declared (pre-sort)
# order for monotonicity, while keeping the sort for the separate
# width-jump analysis that legitimately wants s-ascending order.
# ---------------------------------------------------------------------------
def test_lane_section_declared_out_of_order_is_detected():
    """RED (before fix): this genuinely out-of-order XML was invisible to the
    check because sorting-before-checking silently "fixed" it first."""
    root = _root(
        """
  <road id="1">
    <lanes>
      <laneSection s="10"/>
      <laneSection s="5"/>
    </lanes>
  </road>
"""
    )
    report = StructureScanner.analyze(root)
    non_mono = report["lane_section_issues"]["non_monotonic"]
    assert any(e["road_id"] == "1" for e in non_mono)
    entry = next(e for e in non_mono if e["road_id"] == "1")
    # s_values reflects declared (document) order, not sorted order.
    assert entry["s_values"] == [10.0, 5.0]


def test_lane_section_duplicate_s_tie_is_detected():
    root = _root(
        """
  <road id="1">
    <lanes>
      <laneSection s="5"/>
      <laneSection s="5"/>
    </lanes>
  </road>
"""
    )
    report = StructureScanner.analyze(root)
    non_mono = report["lane_section_issues"]["non_monotonic"]
    assert any(e["road_id"] == "1" for e in non_mono)


def test_lane_section_properly_ascending_not_flagged():
    root = _root(
        """
  <road id="1">
    <lanes>
      <laneSection s="0"/>
      <laneSection s="10"/>
    </lanes>
  </road>
"""
    )
    report = StructureScanner.analyze(root)
    non_mono = report["lane_section_issues"]["non_monotonic"]
    assert not any(e["road_id"] == "1" for e in non_mono)


def test_lane_section_width_jump_detected():
    root = _root(
        """
  <road id="1">
    <lanes>
      <laneSection s="0"><right><lane id="-1"><width a="3.0"/></lane></right></laneSection>
      <laneSection s="10"><right>
        <lane id="-1"><width a="3.0"/></lane>
        <lane id="-2"><width a="3.0"/></lane>
      </right></laneSection>
    </lanes>
  </road>
"""
    )
    report = StructureScanner.analyze(root)
    jumps = report["lane_section_issues"]["width_jumps"]
    assert any(j["road_id"] == "1" for j in jumps)


def test_lane_section_single_section_skipped():
    root = _root('<road id="1"><lanes><laneSection s="0"/></lanes></road>')
    report = StructureScanner.analyze(root)
    assert report["lane_section_issues"]["non_monotonic"] == []
    assert report["lane_section_issues"]["width_jumps"] == []


# ---------------------------------------------------------------------------
# Elevation jumps
# ---------------------------------------------------------------------------
def test_elevation_jump_detected():
    root = _root(
        """
  <road id="1">
    <elevationProfile>
      <elevation s="0" a="0.0"/>
      <elevation s="1" a="10.0"/>
    </elevationProfile>
  </road>
"""
    )
    report = StructureScanner.analyze(root)
    elev = report["elevation_anomalies"]
    entry = next(e for e in elev["per_road"] if e["road_id"] == "1")
    assert entry["local_anomalies"], "expected a flagged dz/slope anomaly"


def test_elevation_single_point_skipped():
    root = _root('<road id="1"><elevationProfile><elevation s="0" a="1.0"/></elevationProfile></road>')
    report = StructureScanner.analyze(root)
    assert report["elevation_anomalies"]["per_road"] == []


# ---------------------------------------------------------------------------
# Graph islands
# ---------------------------------------------------------------------------
def test_graph_islands_small_component_flagged():
    # 2-road component vs. min island size (20) -> flagged as an island.
    root = _root(
        """
  <road id="1"><link><successor elementType="road" elementId="2" contactPoint="start"/></link></road>
  <road id="2"><link><predecessor elementType="road" elementId="1" contactPoint="end"/></link></road>
"""
    )
    report = StructureScanner.analyze(root)
    islands = report["graph_islands"]
    assert islands["num_components"] == 1
    assert islands["num_islands"] == 1
    assert islands["islands"][0]["size"] == 2


def test_graph_islands_isolated_road_is_its_own_component():
    root = _root('<road id="1"/><road id="2"/>')
    report = StructureScanner.analyze(root)
    islands = report["graph_islands"]
    assert islands["num_components"] == 2
    assert islands["largest_component_size"] == 1


# ---------------------------------------------------------------------------
# summarize(): must not raise on any well-formed report
# ---------------------------------------------------------------------------
def test_summarize_does_not_raise(capsys):
    root = _root(
        """
  <road id="1" length="10.0">
    <planView><geometry s="0" x="0" y="0" hdg="0" length="10"/></planView>
  </road>
"""
    )
    report = StructureScanner.analyze(root)
    StructureScanner.summarize(report)
    captured = capsys.readouterr()
    assert "Structure Scanner v2 Report" in captured.out


def test_summarize_handles_empty_report_dict(capsys):
    StructureScanner.summarize({})
    captured = capsys.readouterr()
    assert "Structure Scanner v2 Report" in captured.out
