# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/diagnostics/mesh_checker.py and
pipeline_diagnostics.py. Both zero prior coverage, both print-only
diagnostic utilities (no pass/fail gate signal). Reviewed for the NaN
class of bug found elsewhere this session -- both use
xodr_sanitizer._safe_float, which already correctly clamps NaN/Inf to
its default rather than propagating them, so int()/comparison crashes
from malformed numeric text are not possible here.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.diagnostics.mesh_checker import MeshChecker
from ultimate_pipeline.diagnostics.pipeline_diagnostics import PipelineDiagnostics


# ---------------------------------------------------------------------------
# MeshChecker
# ---------------------------------------------------------------------------


def test_sample_road_returns_points_along_geometry():
    road = ET.fromstring(
        '<road id="1" length="10"><planView>'
        '<geometry s="0" x="0" y="0" hdg="0" length="10"/>'
        "</planView></road>"
    )
    pts = MeshChecker._sample_road(road, step=5.0)
    assert len(pts) >= 2
    assert pts[0] == (0.0, 0.0)
    assert pts[-1][0] == 10.0


def test_sample_road_with_no_geometry_returns_empty():
    road = ET.fromstring('<road id="1" length="0"><planView/></road>')
    assert MeshChecker._sample_road(road) == []


def test_sample_road_nan_length_does_not_crash():
    # length="nan" would crash int(l/step) if _safe_float didn't clamp
    # NaN -- verify the existing NaN guard actually protects this call site.
    road = ET.fromstring(
        '<road id="1" length="10"><planView>'
        '<geometry s="0" x="0" y="0" hdg="0" length="nan"/>'
        "</planView></road>"
    )
    pts = MeshChecker._sample_road(road)  # must not raise
    assert pts  # length clamps to 0.0 -> default, still yields the start point


def test_quick_check_runs_without_crashing_on_empty_root(capsys):
    root = ET.fromstring("<OpenDRIVE></OpenDRIVE>")
    MeshChecker.quick_check(root)
    assert "No geometry points sampled" in capsys.readouterr().out


def test_quick_check_flags_extremely_large_span(capsys):
    road = ET.fromstring(
        '<road id="1" length="1"><planView>'
        '<geometry s="0" x="0" y="0" hdg="0" length="1"/>'
        '<geometry s="1" x="2000000" y="0" hdg="0" length="1"/>'
        "</planView></road>"
    )
    root = ET.fromstring("<OpenDRIVE></OpenDRIVE>")
    root.append(road)
    MeshChecker.quick_check(root)
    assert "extremely large" in capsys.readouterr().out


def test_quick_check_normal_span_reports_reasonable(capsys):
    road = ET.fromstring(
        '<road id="1" length="10"><planView>'
        '<geometry s="0" x="0" y="0" hdg="0" length="10"/>'
        "</planView></road>"
    )
    root = ET.fromstring("<OpenDRIVE></OpenDRIVE>")
    root.append(road)
    MeshChecker.quick_check(root)
    assert "looks reasonable" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# PipelineDiagnostics
# ---------------------------------------------------------------------------


def test_check_elevation_flags_suspicious_values(capsys):
    root = ET.fromstring(
        '<OpenDRIVE><road id="1" length="1">'
        '<elevationProfile><elevation s="0" a="100" b="0" c="0" d="0"/></elevationProfile>'
        "</road></OpenDRIVE>"
    )
    result = PipelineDiagnostics.check_elevation(root, "test")
    assert result == {}
    assert "suspicious elevation" in capsys.readouterr().out


def test_check_elevation_reports_reasonable_when_clean(capsys):
    root = ET.fromstring(
        '<OpenDRIVE><road id="1" length="1">'
        '<elevationProfile><elevation s="0" a="1.0" b="0" c="0" d="0"/></elevationProfile>'
        "</road></OpenDRIVE>"
    )
    PipelineDiagnostics.check_elevation(root, "test")
    assert "look reasonable" in capsys.readouterr().out


def test_check_lane_widths_flags_non_positive_width(capsys):
    root = ET.fromstring(
        '<OpenDRIVE><road id="1" length="1"><lanes><laneSection s="0"><right>'
        '<lane id="-1" type="driving"><width sOffset="0" a="0" b="0" c="0" d="0"/></lane>'
        "</right></laneSection></lanes></road></OpenDRIVE>"
    )
    PipelineDiagnostics.check_lane_widths(root, "test")
    assert "non-positive width" in capsys.readouterr().out


def test_check_lane_widths_reports_positive_when_clean(capsys):
    root = ET.fromstring(
        '<OpenDRIVE><road id="1" length="1"><lanes><laneSection s="0"><right>'
        '<lane id="-1" type="driving"><width sOffset="0" a="3.5" b="0" c="0" d="0"/></lane>'
        "</right></laneSection></lanes></road></OpenDRIVE>"
    )
    PipelineDiagnostics.check_lane_widths(root, "test")
    assert "All lane widths positive" in capsys.readouterr().out
