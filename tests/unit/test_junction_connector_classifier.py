# tests/unit/test_junction_connector_classifier.py
# -*- coding: utf-8 -*-

"""
Tests for OC-2 junction connector association classification (AREA-014):

- classify_connector_association tiers (EXACT_TOPOLOGY /
  GEOMETRICALLY_INFERRED_HIGH / AMBIGUOUS) are deterministic.
- AMBIGUOUS associations are skipped by snap_junction_connectors by default
  (fail-closed) and repaired only when explicitly allowed.
- The direct-line fallback is refused when the chord ignores a boundary
  heading (direct_line_boundary_ok guard).
- ConnectorValidator exposes the shared classification vocabulary + classify.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.quality.check_geometric_continuity import Pose
from ultimate_pipeline.tools.junction_connector_snap import snap_junction_connectors
from ultimate_pipeline.topology.junction_connector_classifier import (
    AMBIGUOUS,
    EXACT_TOPOLOGY,
    GEOMETRICALLY_INFERRED_HIGH,
    classify_connector_association,
    direct_line_boundary_ok,
)
from ultimate_pipeline.topology.junction_connector_rebuild import (
    ConnectorValidator,
    _write_rebuild_geometry,
)


def _pose(x: float, y: float, hdg_deg: float) -> Pose:
    return Pose(x, y, math.radians(hdg_deg))


# ---------------------------------------------------------------------------
# Pure classifier tiers
# ---------------------------------------------------------------------------


def test_exact_topology_declared_side_within_tolerance() -> None:
    result = classify_connector_association(
        connector_start=_pose(10.1, 0.0, 0.0),
        incoming_start=_pose(10.0, 0.0, 0.0),
        incoming_end=_pose(30.0, 0.0, 0.0),
        declared_side="start",
    )
    assert result["classification"] == EXACT_TOPOLOGY
    assert result["nearest_boundary"] == "start"
    assert result["gap_declared_m"] <= 2.0


def test_exact_topology_declared_end_side() -> None:
    result = classify_connector_association(
        connector_start=_pose(30.2, 0.0, 0.0),
        incoming_start=_pose(10.0, 0.0, 0.0),
        incoming_end=_pose(30.0, 0.0, 0.0),
        declared_side="end",
    )
    assert result["classification"] == EXACT_TOPOLOGY
    assert result["nearest_boundary"] == "end"


def test_inferred_high_unambiguous_nearest_with_heading() -> None:
    # Connector 40m along the line: nearest is the END (30,0) with a clear
    # margin (20m) and aligned heading.
    result = classify_connector_association(
        connector_start=_pose(40.0, 0.0, 0.0),
        incoming_start=_pose(10.0, 0.0, 0.0),
        incoming_end=_pose(30.0, 0.0, 0.0),
        declared_side="start",
    )
    assert result["classification"] == GEOMETRICALLY_INFERRED_HIGH
    assert result["nearest_boundary"] == "end"
    assert result["margin_m"] > 2.0


def test_ambiguous_near_tie() -> None:
    # Connector equidistant from both endpoints of a 10m-long road.
    result = classify_connector_association(
        connector_start=_pose(5.0, 0.0, 0.0),
        incoming_start=_pose(0.0, 0.0, 0.0),
        incoming_end=_pose(10.0, 0.0, 0.0),
        declared_side="start",
    )
    assert result["classification"] == AMBIGUOUS
    assert "margin" in result["reason"]


def test_ambiguous_heading_contradiction() -> None:
    # Nearest endpoint unambiguous by distance, but the connector's heading
    # (90 deg) contradicts the road axis (0/180 deg).
    result = classify_connector_association(
        connector_start=_pose(30.0, 0.0, 90.0),
        incoming_start=_pose(0.0, 0.0, 0.0),
        incoming_end=_pose(10.0, 0.0, 0.0),
        declared_side="start",
    )
    assert result["classification"] == AMBIGUOUS
    assert "heading" in result["reason"]


def test_connector_validator_vocabulary_and_classify() -> None:
    assert ConnectorValidator.CLASSIFICATION_EXACT == EXACT_TOPOLOGY
    assert ConnectorValidator.CLASSIFICATION_INFERRED == GEOMETRICALLY_INFERRED_HIGH
    assert ConnectorValidator.CLASSIFICATION_AMBIGUOUS == AMBIGUOUS
    classification = ConnectorValidator.classify(
        connector_start=_pose(10.1, 0.0, 0.0),
        incoming_start=_pose(10.0, 0.0, 0.0),
        incoming_end=_pose(30.0, 0.0, 0.0),
        declared_side="start",
    )
    assert classification == EXACT_TOPOLOGY


# ---------------------------------------------------------------------------
# direct-line heading guard
# ---------------------------------------------------------------------------


def test_direct_line_boundary_ok_matching_headings() -> None:
    # Chord (0,0)->(10,0); start heading 0 and end heading 180 (returning).
    assert direct_line_boundary_ok(
        start_x=0.0, start_y=0.0, end_x=10.0, end_y=0.0,
        start_hdg=0.0, end_hdg=math.pi,
        max_chord_heading_deviation_rad=math.radians(45.0),
    ) is True


def test_direct_line_boundary_ok_refuses_heading_mismatch() -> None:
    # Same chord but the end boundary heading is ~90 deg off-axis: refused.
    assert direct_line_boundary_ok(
        start_x=0.0, start_y=0.0, end_x=10.0, end_y=0.0,
        start_hdg=0.0, end_hdg=math.radians(90.0),
        max_chord_heading_deviation_rad=math.radians(45.0),
    ) is False


def test_rebuild_direct_line_guard_blocks_bad_heading() -> None:
    road = ET.fromstring(
        '<road id="1" length="10.0"><planView>'
        '<geometry s="0" x="0" y="0" hdg="0" length="10.0">'
        "<spiral curvatureStart=\"0.0\" curvatureEnd=\"0.1\"/>"
        "</geometry></planView></road>"
    )
    written = _write_rebuild_geometry(
        connector_road=road,
        original_kind="spiral",
        plan_start=Pose(0.0, 0.0, 0.0),
        plan_end=Pose(10.0, 0.0, math.radians(90.0)),
        start_hdg=0.0,
        max_abs_curvature=1.0,
        allow_straight_chord_fallback=True,
    )
    assert written is None  # blocked: straight chord ignores end heading


def test_rebuild_direct_line_allowed_when_headings_ok() -> None:
    road = ET.fromstring(
        '<road id="1" length="10.0"><planView>'
        '<geometry s="0" x="0" y="0" hdg="0" length="10.0">'
        "<spiral curvatureStart=\"0.0\" curvatureEnd=\"0.1\"/>"
        "</geometry></planView></road>"
    )
    written = _write_rebuild_geometry(
        connector_road=road,
        original_kind="spiral",
        plan_start=Pose(0.0, 0.0, 0.0),
        plan_end=Pose(10.0, 0.0, math.pi),
        start_hdg=0.0,
        max_abs_curvature=1.0,
        allow_straight_chord_fallback=True,
    )
    assert written == "line"


# ---------------------------------------------------------------------------
# Snap integration: AMBIGUOUS skipped by default, escapable explicitly
# ---------------------------------------------------------------------------


def _road_fragment(rid: str, junction: str, x: float, length: float = 10.0) -> str:
    return (
        f'<road id="{rid}" junction="{junction}" length="{length}">'
        f'<planView><geometry s="0" x="{x}" y="0" hdg="0" length="{length}">'
        "<line/></geometry></planView>"
        "<lanes><laneSection><right>"
        '<lane id="-1" type="driving"><width sOffset="0" a="3.5" b="0" c="0" d="0"/></lane>'
        "</right></laneSection></lanes></road>"
    )


def _junction_fragment(jid: str, incoming: str, connecting: str) -> str:
    return (
        f'<junction id="{jid}">'
        f'<connection id="0" incomingRoad="{incoming}" connectingRoad="{connecting}" '
        'contactPoint="start"><laneLink from="-1" to="-1"/></connection>'
        "</junction>"
    )


def _ambiguous_root() -> ET.Element:
    # Incoming road spans (0,0)->(10,0); the connector starts at (5,0) --
    # equidistant from both boundaries (AMBIGUOUS near-tie).
    return ET.fromstring(
        "<OpenDRIVE>"
        + _road_fragment("10", "-1", 0.0)
        + _road_fragment("99", "5", 5.0)
        + _junction_fragment("5", "10", "99")
        + "</OpenDRIVE>"
    )


def test_snap_skips_ambiguous_by_default() -> None:
    report = snap_junction_connectors(_ambiguous_root())
    assert report["skip_ambiguous"] is True
    assert report["classified_ambiguous"] == 1
    assert report["skipped_ambiguous"] == 1
    assert report["connectors_snapped"] == 0


def test_snap_allows_ambiguous_when_opted_in() -> None:
    report = snap_junction_connectors(_ambiguous_root(), skip_ambiguous=False)
    assert report["skip_ambiguous"] is False
    assert report["skipped_ambiguous"] == 0
    assert report["connectors_snapped"] == 1


def test_snap_classifies_unambiguous_displaced_inferred_and_snaps() -> None:
    root = ET.fromstring(
        "<OpenDRIVE>"
        + _road_fragment("20", "-1", 0.0)
        + _road_fragment("88", "6", 30.0)
        + _junction_fragment("6", "20", "88")
        + "</OpenDRIVE>"
    )
    # Incoming (0,0)->(10,0); connector start at (30,0): nearest is END
    # (distance 20), margin vs start = 20 -> unambiguous, heading aligned ->
    # GEOMETRICALLY_INFERRED_HIGH -> snapped to the end boundary.
    report = snap_junction_connectors(root)
    assert report["classified_inferred_high"] == 1
    assert report["skipped_ambiguous"] == 0
    assert report["connectors_snapped"] == 1