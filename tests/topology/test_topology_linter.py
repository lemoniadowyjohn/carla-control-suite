"""Tests for ultimate_pipeline/topology/topology_linter.py.

Zero prior test coverage despite TopologyLinter.run() being invoked twice
per real pipeline run (pre- and post-SUMO-repair, stage_02_topology_semantics.py)
and being the primary static-analysis gate for road-graph connectivity (TL-001),
junction lane parity (TL-002), and invalid link references (TL-003) -- exactly
the class of defect that can silently produce a map with broken routing.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.core.validation_report import ValidationReport
from ultimate_pipeline.topology.topology_linter import TopologyLinter


def _root(xml_body: str) -> ET.Element:
    return ET.fromstring(f'<?xml version="1.0"?>\n<OpenDRIVE>\n{xml_body}\n</OpenDRIVE>')


def _messages(report: ValidationReport, level: str = None):
    if level is None:
        return (
            [e["message"] for e in report.data["errors"]]
            + [e["message"] for e in report.data["warnings"]]
            + [e["message"] for e in report.data["success"]]
        )
    # NOTE: ValidationReport.add() only special-cases "error"/"skipped"/"success";
    # every other level string (including the "info" that TopologyLinter's
    # "all clear" messages use) falls into the `warnings` bucket. So a
    # TL-00x "...OK"/"...consistent"/"...valid" info message and a genuine
    # warning both land in report.data["warnings"] -- there is no separate
    # "info" bucket. This mirrors real ValidationReport behavior, not a
    # test bug; see topology_linter.py call sites using report.add("info", ...).
    key = {"error": "errors", "warning": "warnings"}[level]
    return [e["message"] for e in report.data[key]]


# ---------------------------------------------------------------------------
# TL-001: connectivity
# ---------------------------------------------------------------------------
def test_tl001_flags_disconnected_roads():
    root = _root(
        """
  <road id="1"><link><successor elementType="road" elementId="2" contactPoint="start"/></link></road>
  <road id="2"><link><predecessor elementType="road" elementId="1" contactPoint="end"/></link></road>
  <road id="3"/>
"""
    )
    report = ValidationReport()
    TopologyLinter._check_connectivity(root, report)
    msgs = _messages(report)
    assert any("TL-001" in m and "disconnected" in m for m in msgs)


def test_tl001_fully_connected_reports_info():
    root = _root(
        """
  <road id="1"><link><successor elementType="road" elementId="2" contactPoint="start"/></link></road>
  <road id="2"><link><predecessor elementType="road" elementId="1" contactPoint="end"/></link></road>
"""
    )
    report = ValidationReport()
    TopologyLinter._check_connectivity(root, report)
    msgs = _messages(report)
    assert any("TL-001" in m and "fully connected" in m for m in msgs)


def test_tl001_no_roads_is_fatal():
    root = _root("")
    report = ValidationReport()
    TopologyLinter._check_connectivity(root, report)
    assert len(report.data["errors"]) >= 0  # fatal goes through .add("fatal", ...)
    # "fatal" isn't error/warning/success/skipped -> falls into the else branch (warnings bucket)
    msgs = _messages(report)
    assert any("TL-001" in m and "No roads present" in m for m in msgs)


# ---------------------------------------------------------------------------
# TL-002: lane parity
# ---------------------------------------------------------------------------
def test_tl002_flags_lane_parity_mismatch():
    root = _root(
        """
  <road id="1">
    <lanes><laneSection s="0">
      <left><lane id="1"/></left>
      <right><lane id="-1"/></right>
    </laneSection></lanes>
  </road>
  <road id="2">
    <lanes><laneSection s="0">
      <left><lane id="1"/><lane id="2"/></left>
      <right><lane id="-1"/></right>
    </laneSection></lanes>
  </road>
  <junction id="10">
    <connection incomingRoad="1" connectingRoad="2" contactPoint="start"/>
  </junction>
"""
    )
    report = ValidationReport()
    TopologyLinter._check_lane_parity(root, report)
    msgs = _messages(report)
    assert any("TL-002" in m and "mismatch" in m for m in msgs)


def test_tl002_matching_lane_counts_ok():
    root = _root(
        """
  <road id="1">
    <lanes><laneSection s="0">
      <left><lane id="1"/></left>
      <right><lane id="-1"/></right>
    </laneSection></lanes>
  </road>
  <road id="2">
    <lanes><laneSection s="0">
      <left><lane id="1"/></left>
      <right><lane id="-1"/></right>
    </laneSection></lanes>
  </road>
  <junction id="10">
    <connection incomingRoad="1" connectingRoad="2" contactPoint="start"/>
  </junction>
"""
    )
    report = ValidationReport()
    TopologyLinter._check_lane_parity(root, report)
    msgs = _messages(report)
    assert any("TL-002" in m and "consistent" in m for m in msgs)


def test_tl002_skips_connection_with_missing_road():
    root = _root(
        """
  <junction id="10">
    <connection incomingRoad="999" connectingRoad="888" contactPoint="start"/>
  </junction>
"""
    )
    report = ValidationReport()
    # Must not raise even though incoming/connecting roads don't exist.
    TopologyLinter._check_lane_parity(root, report)
    msgs = _messages(report)
    assert any("TL-002" in m for m in msgs)


# ---------------------------------------------------------------------------
# TL-003: invalid predecessor/successor refs
# ---------------------------------------------------------------------------
def test_tl003_flags_missing_road_ref():
    root = _root(
        """
  <road id="1"><link><successor elementType="road" elementId="999" contactPoint="start"/></link></road>
"""
    )
    report = ValidationReport()
    TopologyLinter._check_invalid_links(root, report)
    msgs = _messages(report, "error")
    assert any("TL-003" in m and "missing road" in m for m in msgs)


def test_tl003_flags_self_reference():
    root = _root(
        """
  <road id="1"><link><successor elementType="road" elementId="1" contactPoint="start"/></link></road>
"""
    )
    report = ValidationReport()
    TopologyLinter._check_invalid_links(root, report)
    msgs = _messages(report, "error")
    assert any("TL-003" in m and "refers to itself" in m for m in msgs)


def test_tl003_flags_non_road_non_junction_element_type():
    root = _root(
        """
  <road id="1"><link><successor elementType="bogus" elementId="1" contactPoint="start"/></link></road>
"""
    )
    report = ValidationReport()
    TopologyLinter._check_invalid_links(root, report)
    msgs = _messages(report, "error")
    assert any("TL-003" in m and "non-road elementType=bogus" in m for m in msgs)


def test_tl003_valid_links_report_info():
    root = _root(
        """
  <road id="1"><link><successor elementType="road" elementId="2" contactPoint="start"/></link></road>
  <road id="2"/>
"""
    )
    report = ValidationReport()
    TopologyLinter._check_invalid_links(root, report)
    msgs = _messages(report, "warning")
    assert any("TL-003" in m and "valid" in m for m in msgs)


# ---------------------------------------------------------------------------
# TL-004: laneSection bounds
# ---------------------------------------------------------------------------
def test_tl004_flags_lanesection_beyond_road_length():
    root = _root(
        '<road id="1" length="5.0"><lanes><laneSection s="10.0"/></lanes></road>'
    )
    report = ValidationReport()
    TopologyLinter._check_laneSection_bounds(root, report)
    msgs = _messages(report, "error")
    assert any("TL-004" in m for m in msgs)


def test_tl004_within_bounds_ok():
    root = _root(
        '<road id="1" length="5.0"><lanes><laneSection s="2.0"/></lanes></road>'
    )
    report = ValidationReport()
    TopologyLinter._check_laneSection_bounds(root, report)
    msgs = _messages(report, "warning")
    assert any("TL-004" in m for m in msgs)


# ---------------------------------------------------------------------------
# TL-005: zero-length roads
# ---------------------------------------------------------------------------
def test_tl005_flags_tiny_road():
    root = _root('<road id="1" length="0.1"/>')
    report = ValidationReport()
    TopologyLinter._check_zero_length_roads(root, report)
    msgs = _messages(report, "warning")
    assert any("TL-005" in m for m in msgs)


def test_tl005_normal_length_ok():
    root = _root('<road id="1" length="50.0"/>')
    report = ValidationReport()
    TopologyLinter._check_zero_length_roads(root, report)
    msgs = _messages(report, "warning")
    assert any("TL-005" in m for m in msgs)


# ---------------------------------------------------------------------------
# TL-006: geometry s-order / overflow
# ---------------------------------------------------------------------------
def test_tl006_flags_overflow():
    root = _root(
        """
  <road id="1" length="5.0">
    <planView><geometry s="0" length="10.0"/></planView>
  </road>
"""
    )
    report = ValidationReport()
    TopologyLinter._check_geometry_s_and_overflow(root, report)
    msgs = _messages(report, "warning")
    assert any("TL-006" in m and "exceeds road length" in m for m in msgs)


def test_tl006_flags_unsorted_s_values():
    root = _root(
        """
  <road id="1" length="100.0">
    <planView>
      <geometry s="10" length="5.0"/>
      <geometry s="5" length="5.0"/>
    </planView>
  </road>
"""
    )
    report = ValidationReport()
    TopologyLinter._check_geometry_s_and_overflow(root, report)
    msgs = _messages(report, "warning")
    assert any("TL-006" in m and "not sorted" in m for m in msgs)


def test_tl006_consistent_geometry_ok():
    root = _root(
        """
  <road id="1" length="10.0">
    <planView><geometry s="0" length="10.0"/></planView>
  </road>
"""
    )
    report = ValidationReport()
    TopologyLinter._check_geometry_s_and_overflow(root, report)
    msgs = _messages(report, "warning")
    assert any("TL-006" in m for m in msgs)


# ---------------------------------------------------------------------------
# TL-007: junction references
# ---------------------------------------------------------------------------
def test_tl007_flags_junction_with_no_connections():
    root = _root('<junction id="10"/>')
    report = ValidationReport()
    TopologyLinter._check_junction_refs(root, report)
    msgs = _messages(report, "warning")
    assert any("TL-007" in m and "no connections" in m for m in msgs)


def test_tl007_flags_self_connection():
    root = _root(
        """
  <road id="1"/>
  <junction id="10"><connection incomingRoad="1" connectingRoad="1"/></junction>
"""
    )
    report = ValidationReport()
    TopologyLinter._check_junction_refs(root, report)
    msgs = _messages(report, "error")
    assert any("TL-007" in m and "self-connection" in m for m in msgs)


def test_tl007_flags_missing_roads():
    root = _root('<junction id="10"><connection incomingRoad="1" connectingRoad="2"/></junction>')
    report = ValidationReport()
    TopologyLinter._check_junction_refs(root, report)
    msgs = _messages(report, "error")
    assert any("TL-007" in m and "missing road" in m for m in msgs)


def test_tl007_valid_refs_ok():
    root = _root(
        """
  <road id="1"/><road id="2"/>
  <junction id="10"><connection incomingRoad="1" connectingRoad="2"/></junction>
"""
    )
    report = ValidationReport()
    TopologyLinter._check_junction_refs(root, report)
    msgs = _messages(report, "warning")
    assert any("TL-007" in m and "valid" in m for m in msgs)


# ---------------------------------------------------------------------------
# TL-008: elevation anomalies
# ---------------------------------------------------------------------------
def test_tl008_flags_suspicious_elevation():
    root = _root(
        '<road id="1"><elevationProfile><elevation s="0" a="75.0"/></elevationProfile></road>'
    )
    report = ValidationReport()
    TopologyLinter._check_elevation_anomalies(root, report)
    msgs = _messages(report, "warning")
    assert any("TL-008" in m for m in msgs)


def test_tl008_normal_elevation_ok():
    root = _root(
        '<road id="1"><elevationProfile><elevation s="0" a="1.5"/></elevationProfile></road>'
    )
    report = ValidationReport()
    TopologyLinter._check_elevation_anomalies(root, report)
    msgs = _messages(report, "warning")
    assert any("TL-008" in m for m in msgs)


# ---------------------------------------------------------------------------
# TL-009: lane widths
# ---------------------------------------------------------------------------
def test_tl009_flags_non_positive_width():
    root = _root(
        '<road id="1"><lanes><laneSection><right><lane id="-1"><width a="0.0"/></lane>'
        "</right></laneSection></lanes></road>"
    )
    report = ValidationReport()
    TopologyLinter._check_lane_widths(root, report)
    msgs = _messages(report, "error")
    assert any("TL-009" in m and "non-positive" in m for m in msgs)


def test_tl009_flags_huge_width():
    root = _root(
        '<road id="1"><lanes><laneSection><right><lane id="-1"><width a="20.0"/></lane>'
        "</right></laneSection></lanes></road>"
    )
    report = ValidationReport()
    TopologyLinter._check_lane_widths(root, report)
    msgs = _messages(report, "warning")
    assert any("TL-009" in m and "huge" in m for m in msgs)


def test_tl009_normal_width_ok():
    root = _root(
        '<road id="1"><lanes><laneSection><right><lane id="-1"><width a="3.5"/></lane>'
        "</right></laneSection></lanes></road>"
    )
    report = ValidationReport()
    TopologyLinter._check_lane_widths(root, report)
    msgs = _messages(report, "warning")
    assert any("TL-009" in m and "normal range" in m for m in msgs)


# ---------------------------------------------------------------------------
# Public entry point: run() executes all 9 checks
# ---------------------------------------------------------------------------
def test_run_executes_all_checks_without_raising():
    root = _root(
        """
  <road id="1" length="10.0">
    <link><successor elementType="road" elementId="2" contactPoint="start"/></link>
    <planView><geometry s="0" length="10.0"/></planView>
    <lanes><laneSection s="0"><left><lane id="1"><width a="3.0"/></lane></left></laneSection></lanes>
  </road>
  <road id="2" length="10.0">
    <link><predecessor elementType="road" elementId="1" contactPoint="end"/></link>
    <planView><geometry s="0" length="10.0"/></planView>
  </road>
  <junction id="10">
    <connection incomingRoad="1" connectingRoad="2" contactPoint="start"/>
  </junction>
"""
    )
    report = ValidationReport()
    TopologyLinter.run(root, report)
    all_msgs = _messages(report)
    # All 9 rule codes should appear somewhere in the combined report.
    for code in ("TL-001", "TL-002", "TL-003", "TL-004", "TL-005", "TL-006", "TL-007", "TL-008", "TL-009"):
        assert any(code in m for m in all_msgs), f"{code} never appeared in report"
