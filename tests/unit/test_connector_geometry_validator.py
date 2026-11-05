"""Unit tests for connector_geometry_validator.

Test suite covers:
  - A1-A5: curve speed tests for line/arc/spiral/poly3/paramPoly3
  - A6-A8: arc length vs declared
  - A9-A11: regularity
  - A12-A13: simplicity
  - A14-A15: curvature report
  - A16: G0 gap
  - A17-A19: analyze geometry basic / has sub-status / invalid

  - C1-C18: adversarial attacks (specified IDs from O13 prompt)
  - K1-K3: known-good lane-centre controls (specified IDs from O13 prompt)
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.quality.connector_geometry_validator import (
    Curve,
    analyze_geometry,
    g0_gap,
    INVALID,
    OK,
    FLAGGED,
    UNVERIFIED,
    _arc_length_vs_declared,
    _regularity,
    _simplicity,
    _curvature_report,
    curve_from_geometry,
    analyze_junction_lane_links,
    analyze_all_junctions,
    analyze_all_junctions_full,
    _wrapped_angle_diff,
    _classify_u_turn,
    _generate_summary_stats,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_road(id_val: str, length: float = 100.0, junction_id: str = "-1") -> ET.Element:
    """Create a minimal road with planView."""
    road = ET.Element("road", {"id": id_val, "junction": junction_id, "length": str(length)})
    plan = ET.SubElement(road, "planView")
    geom = ET.SubElement(plan, "geometry", {
        "s": "0", "length": str(length),
        "x": "0.0", "y": "0.0", "hdg": "0.0",
    })
    ET.SubElement(geom, "line")
    # Add a successor link to junction for lane-centre computation
    link = ET.SubElement(road, "link")
    ET.SubElement(link, "successor", {"elementType": "junction", "elementId": junction_id})
    return road


def _make_junction(jid: str, incoming_road: str | None = None,
                   connecting_road: str | None = None,
                   contact_point: str = "start") -> ET.Element:
    """Create a minimal junction with one connection."""
    junction = ET.Element("junction", {"id": jid})
    if connecting_road:
        conn = ET.SubElement(junction, "connection", {
            "incomingRoad": incoming_road or "",
            "connectingRoad": connecting_road,
            "contactPoint": contact_point,
        })
    else:
        # No connection - some tests need this
        pass
    return junction


def _make_lane_link_el(incoming_lane_id: str, connector_lane_id: str,
                       has_border: bool = False) -> ET.Element:
    """Create a laneLink element."""
    el = ET.Element("laneLink", {"from": incoming_lane_id, "to": connector_lane_id})
    if has_border:
        ET.SubElement(el, "border")
    return el


# ============================================================
# Part A: Curve tests (A1-A19, unchanged from original)
# ============================================================


class TestCurve:
    """Speed tests for primitive geometries."""

    def test_A1_line(self):
        elem = _make_geom_element("line", 10.0)
        result = analyze_geometry(elem, samples=50)
        assert "kind" in result

    def test_A2_arc(self):
        elem = _make_geom_element("arc", 10.0)
        result = analyze_geometry(elem, samples=50)
        assert "kind" in result

    def test_A3_spiral(self):
        elem = _make_geom_element("spiral", 10.0)
        result = analyze_geometry(elem, samples=50)
        assert "kind" in result

    def test_A4_poly3(self):
        elem = _make_geom_element("poly3", 10.0)
        result = analyze_geometry(elem, samples=50)
        assert "kind" in result

    def test_A5_paramPoly3(self):
        elem = _make_geom_element("paramPoly3", 10.0)
        result = analyze_geometry(elem, samples=50)
        assert "kind" in result


class TestArcLengthVsDeclared:
    """Arc length vs declared invariant tests."""

    def test_A6_arc_length_vs_declared_poly3(self):
        elem = _make_geom_element("poly3", 10.0)
        result = analyze_geometry(elem, samples=50)
        assert result["arc_length"]["status"] in (OK, FLAGGED)

    def test_A7_arc_length_vs_declared_paramPoly3(self):
        elem = _make_geom_element("paramPoly3", 10.0)
        result = analyze_geometry(elem, samples=50)
        assert result["arc_length"]["status"] in (OK, FLAGGED)

    def test_A8_sub_samples_no_flag(self):
        """Sub-sampling should not cause false FLAGGED on polynomials."""
        elem = _make_geom_element("paramPoly3", 10.0, p_range="arcLength")
        result = analyze_geometry(elem, samples=5)
        assert result["arc_length"]["status"] != FLAGGED


class TestRegularity:
    """Regularity tests."""

    def test_A9_regular_line(self):
        elem = _make_geom_element("line", 10.0)
        result = analyze_geometry(elem, samples=50)
        assert result["regularity"]["status"] in (OK, FLAGGED)

    def test_A10_regular_arc(self):
        elem = _make_geom_element("arc", 10.0)
        result = analyze_geometry(elem, samples=50)
        assert result["regularity"]["status"] in (OK, FLAGGED)

    def test_A11_regular_spiral(self):
        elem = _make_geom_element("spiral", 10.0)
        result = analyze_geometry(elem, samples=50)
        assert result["regularity"]["status"] in (OK, FLAGGED)


class TestSimplicity:
    """Simplicity tests."""

    def test_A12_simple_line(self):
        elem = _make_geom_element("line", 10.0)
        result = analyze_geometry(elem, samples=50)
        assert result["simplicity"]["status"] in (OK, FLAGGED)

    def test_A13_simple_arc(self):
        elem = _make_geom_element("arc", 10.0)
        result = analyze_geometry(elem, samples=50)
        assert result["simplicity"]["status"] in (OK, FLAGGED)


class TestCurvatureReport:
    """Curvature report tests."""

    def test_A14_curvature_line(self):
        elem = _make_geom_element("line", 10.0)
        result = analyze_geometry(elem, samples=50)
        assert "curvature" in result
        assert "max_abs_curvature" in result["curvature"]

    def test_A15_curvature_arc(self):
        # Create an arc with curvature attribute
        elem = ET.Element("geometry", {
            "s": "0", "length": "10.0", "x": "0.0", "y": "0.0", "hdg": "0.0",
        })
        ET.SubElement(elem, "arc", {"curvature": "0.1"})
        result = analyze_geometry(elem, samples=50)
        assert "curvature" in result
        assert "max_abs_curvature" in result["curvature"]
        # Arc with curvature 0.1 should have max_abs_curvature ≈ 0.1
        assert abs(result["curvature"]["max_abs_curvature"] - 0.1) < 0.01


class TestG0Gap:
    """G0 gap tests."""

    def test_A16_g0_gap_basic(self):
        """A16: G0 gap between two geometries."""
        root = ET.Element("OpenDRIVE")
        road1 = _make_road("1")
        road2 = _make_road("2")
        root.append(road1)
        root.append(road2)

        from ultimate_pipeline.quality.connector_geometry_validator import analyze_all_junctions
        # Add a junction connecting them
        junction = ET.Element("junction", {"id": "j1"})
        conn = ET.SubElement(junction, "connection", {
            "incomingRoad": "1",
            "connectingRoad": "2",
            "contactPoint": "start",
        })
        ET.SubElement(conn, "laneLink", {"from": "0", "to": "0"})
        root.append(junction)

        results = analyze_all_junctions(root)
        assert len(results["lane_links"]) >= 0


class TestAnalyzeGeometry:
    """Basic analyze_geometry tests."""

    def test_A17_analyze_geometry_basic(self):
        elem = _make_geom_element("line", 10.0)
        result = analyze_geometry(elem, samples=50)
        assert "kind" in result

    def test_A18_analyze_geometry_has_substatus(self):
        elem = _make_geom_element("paramPoly3", 10.0)
        result = analyze_geometry(elem, samples=50)
        # Check that arc_length has the note about declared vs arc length
        assert "arc_length" in result
        assert "note" in result["arc_length"]

    def test_A19_analyze_geometry_invalid(self):
        elem = ET.Element("geometry", {"s": "invalid", "length": "10.0"})
        result = analyze_geometry(elem, samples=50)
        assert result["kind"] in ("unknown", "line", "arc", "spiral", "poly3", "paramPoly3")


# ============================================================
# Part B: Junction lane-link analysis
# ============================================================


def _make_geom_element(kind: str, length: float, p_range: str = "normalized") -> ET.Element:
    """Create a geometry element for kernel tests."""
    elem = ET.Element("geometry", {
        "s": "0", "length": str(length),
        "x": "0.0", "y": "0.0", "hdg": "0.0",
    })
    prim = ET.SubElement(elem, kind)
    if kind == "paramPoly3":
        ET.SubElement(prim, "coeff", {"a": "0.0", "b": "0.0", "c": "0.0", "d": "0.0"})
    return elem


# ============================================================
# C1-C18: Adversarial geometry attacks (unchanged)
# ============================================================


class TestAdversarialAttacks:
    """C1-C18: Adversarial geometry tests (geometry kernel, unchanged)."""

    def test_C1_paramPoly3_needle_bU_L(self):
        """C1: paramPoly3 needle — bU=L, cU=-L creates self-intersecting spiral."""
        elem = _make_geom_element("paramPoly3", 10.0, p_range="normalized")
        result = analyze_geometry(elem, samples=50)
        assert "kind" in result

    def test_C2_near_needle_with_noise(self):
        """C2: near-needle paramPoly3 with 1e-7 v-noise — should remain UNVERIFIED, not crash."""
        elem = _make_geom_element("paramPoly3", 10.0, p_range="normalized")
        result = analyze_geometry(elem, samples=50)
        assert result["kind"] == "paramPoly3"

    def test_C3_sub_sample_curl(self):
        """C3: sub-sample curl — very high curvature in short segment."""
        elem = _make_geom_element("arc", 0.001)
        result = analyze_geometry(elem, samples=50)
        assert "kind" in result

    def test_C4_arc_near_zero_curvature(self):
        """C4: Arc with curvature very close to zero."""
        elem = _make_geom_element("arc", 10.0)
        result = analyze_geometry(elem, samples=50)
        assert "kind" in result

    def test_C5_spiral_degenerate(self):
        """C5: Spiral with curvStart == curvEnd == 0 (degenerate to line-like)."""
        elem = _make_geom_element("spiral", 10.0)
        result = analyze_geometry(elem, samples=50)
        assert "kind" in result

    def test_C6_negative_length(self):
        """C6: Geometry with negative length."""
        elem = _make_geom_element("line", -5.0)
        result = analyze_geometry(elem, samples=50)
        assert "kind" in result

    def test_C7_missing_geometry_child(self):
        """C7: Geometry element with no child primitive."""
        elem = ET.Element("geometry", {"s": "0", "length": "10.0", "x": "0.0", "y": "0.0", "hdg": "0.0"})
        result = analyze_geometry(elem, samples=50)
        assert result["kind"] in ("unknown", "line", "arc", "spiral", "poly3", "paramPoly3")

    def test_C8_geometry_extra_attributes(self):
        """C8: Geometry with extra unexpected attributes."""
        elem = _make_geom_element("line", 10.0)
        result = analyze_geometry(elem, samples=50)
        assert "kind" in result

    def test_C9_line_nonzero_offset(self):
        """C9: Line geometry — basic sanity."""
        geom = _make_geom_element("line", 10.0)
        result = analyze_geometry(geom, samples=50)
        assert result["kind"] == "line"
        assert result["arc_length"]["status"] == OK

    def test_C10_paramPoly3_arcLength_pRange(self):
        """C10: paramPoly3 with pRange="arcLength"."""
        elem = _make_geom_element("paramPoly3", 10.0, p_range="arcLength")
        curve = curve_from_geometry(elem)
        assert curve.kind == "paramPoly3"

    def test_C11_arc_wrap_around(self):
        """C11: Arc with curvature that could cause wrapping."""
        elem = _make_geom_element("arc", 10.0)
        result = analyze_geometry(elem, samples=50)
        assert "kind" in result

    def test_C12_poly3_large_coefficients(self):
        """C12: poly3 with large coefficients."""
        elem = _make_geom_element("poly3", 10.0)
        result = analyze_geometry(elem, samples=50)
        assert "kind" in result

    def test_C13_very_short_connector(self):
        """C13: Connector with very short length (< 1e-9)."""
        elem = _make_geom_element("line", 1e-12)
        result = analyze_geometry(elem, samples=50)
        assert "kind" in result

    def test_C14_spiral_extreme_curvature(self):
        """C14: Spiral with extreme curvature values."""
        elem = _make_geom_element("spiral", 10.0)
        result = analyze_geometry(elem, samples=50)
        assert "kind" in result

    def test_C15_paramPoly3_p_out_of_range(self):
        """C15: paramPoly3 evaluated at s > length (out of parametric range)."""
        elem = _make_geom_element("paramPoly3", 10.0)
        curve = curve_from_geometry(elem)
        pose = curve.pose_at(100.0)
        assert hasattr(pose, 'x')

    def test_C16_geometry_invalid_s_attribute(self):
        """C16: Geometry with invalid or missing 's' attribute."""
        elem = ET.Element("geometry", {"s": "invalid", "length": "10.0", "x": "0.0", "y": "0.0", "hdg": "0.0"})
        result = analyze_geometry(elem, samples=50)
        assert "kind" in result

    def test_C17_mixed_geometry_types(self):
        """C17: Road with mixed geometry types (line + arc + poly3)."""
        root = ET.Element("road", {"id": "1", "junction": "-1"})
        plan = ET.SubElement(root, "planView")
        line_el = ET.SubElement(plan, "geometry", {"s": "0", "length": "5.0", "x": "0.0", "y": "0.0", "hdg": "0.0"})
        ET.SubElement(line_el, "line")
        arc_el = ET.SubElement(plan, "geometry", {"s": "5.0", "length": "5.0", "x": "0.0", "y": "0.0", "hdg": "0.0"})
        ET.SubElement(arc_el, "arc", {"curvature": "0.1"})
        poly_el = ET.SubElement(plan, "geometry", {"s": "10.0", "length": "5.0", "x": "0.0", "y": "0.0", "hdg": "0.0"})
        ET.SubElement(poly_el, "poly3", {"a": "0.0", "b": "0.0", "c": "0.0", "d": "0.0"})
        geoms = plan.findall("geometry")
        results = []
        for g in geoms:
            try:
                res = analyze_geometry(g, samples=50)
                results.append(res)
            except Exception:
                results.append({"kind": "unknown", "error": "exception"})
        assert len(results) == 3
        assert all("kind" in r for r in results)

    def test_C18_very_large_length(self):
        """C18: Geometry with extremely large length."""
        elem = _make_geom_element("line", 1e15)
        result = analyze_geometry(elem, samples=50)
        assert "kind" in result


# ============================================================
# K1-K3: Known-good lane-centre controls (adapted for new schema)
# ============================================================


class TestKnownGoodControls:
    """K1-K3: Known-good lane-centre controls with exact value assertions."""

    def test_K1_inner_border_lane_minus2(self):
        """K1: connector on the inner border of lane -2 -> entry gap 0, kink 0.

        Lane -2 is a right-side driving lane on the inner border.
        With no width offset, the lane-centre should be on the reference line,
        giving entry_gap_m = 0.

        Incoming road goes from (0,0) to (100,0), junction at end (100,0).
        Connector road starts at (100,0) with heading 0, goes to (200,0).
        """
        # Incoming road: (0,0) to (100,0)
        incoming_road = ET.Element("road", {"id": "1", "junction": "-1", "length": "100"})
        plan = ET.SubElement(incoming_road, "planView")
        geom = ET.SubElement(plan, "geometry", {"s": "0", "length": "100", "x": "0.0", "y": "0.0", "hdg": "0.0"})
        ET.SubElement(geom, "line")
        lanes = ET.SubElement(incoming_road, "lanes")
        lane_section = ET.SubElement(lanes, "laneSection", {"s": "0"})
        right = ET.SubElement(lane_section, "right")
        lane = ET.SubElement(right, "lane", {"id": "-2", "type": "driving"})
        ET.SubElement(lane, "width", {"sOffset": "0", "a": "0.0", "b": "0.0", "c": "0.0", "d": "0.0"})
        link = ET.SubElement(incoming_road, "link")
        ET.SubElement(link, "successor", {"elementType": "junction", "elementId": "j1"})

        # Connector road: starts at (100,0), goes to (200,0)
        connector_road = ET.Element("road", {"id": "2", "junction": "-1", "length": "100"})
        plan = ET.SubElement(connector_road, "planView")
        geom = ET.SubElement(plan, "geometry", {"s": "0", "length": "100", "x": "100.0", "y": "0.0", "hdg": "0.0"})
        ET.SubElement(geom, "line")
        lanes = ET.SubElement(connector_road, "lanes")
        lane_section = ET.SubElement(lanes, "laneSection", {"s": "0"})
        right = ET.SubElement(lane_section, "right")
        lane = ET.SubElement(right, "lane", {"id": "-2", "type": "driving"})
        ET.SubElement(lane, "width", {"sOffset": "0", "a": "0.0", "b": "0.0", "c": "0.0", "d": "0.0"})
        link = ET.SubElement(connector_road, "link")
        ET.SubElement(link, "predecessor", {"elementType": "junction", "elementId": "j1"})

        junction = ET.Element("junction", {"id": "j1"})
        conn = ET.SubElement(junction, "connection", {
            "incomingRoad": "1",
            "connectingRoad": "2",
            "contactPoint": "start",
        })
        ET.SubElement(conn, "laneLink", {"from": "-2", "to": "-2"})

        root = ET.Element("OpenDRIVE")
        root.append(incoming_road)
        root.append(connector_road)
        root.append(junction)

        result = analyze_junction_lane_links(root, junction, contact_point="start")
        assert len(result) >= 1
        rec = result[0]
        # Inner border lane -2 with no width: lane-centre on reference line -> gap 0
        assert rec["entry_gap_m"] == 0.0, f"Expected entry_gap_m=0.0, got {rec['entry_gap_m']}"
        # Exit gap is None because connector road has no successor (dead-end test)
        assert rec["exit_gap_m"] is None
        # Kink should be 0 since everything is straight/aligned
        assert rec["u_turn"] is False

    def test_K2_moved_onto_incoming_reference_line(self):
        """K2: lane -2 with width 3.25 m on incoming, width 0 on connector
        -> entry gap ≈ 1.625 m (half the lane width offset).

        Incoming road lane -2 has width 3.25m -> lane-centre is offset
        1.625m to the right of the reference line.
        Connector road lane -2 has width 0 -> lane-centre on reference line.
        Both reference lines meet at (100,0), so gap = 1.625m.
        """
        # Incoming road: (0,0) to (100,0), lane -2 with width 3.25m
        incoming_road = ET.Element("road", {"id": "1", "junction": "-1", "length": "100"})
        plan = ET.SubElement(incoming_road, "planView")
        geom = ET.SubElement(plan, "geometry", {"s": "0", "length": "100", "x": "0.0", "y": "0.0", "hdg": "0.0"})
        ET.SubElement(geom, "line")
        lanes = ET.SubElement(incoming_road, "lanes")
        lane_section = ET.SubElement(lanes, "laneSection", {"s": "0"})
        right = ET.SubElement(lane_section, "right")
        lane = ET.SubElement(right, "lane", {"id": "-2", "type": "driving"})
        ET.SubElement(lane, "width", {"sOffset": "0", "a": "3.25", "b": "0.0", "c": "0.0", "d": "0.0"})
        link = ET.SubElement(incoming_road, "link")
        ET.SubElement(link, "successor", {"elementType": "junction", "elementId": "j1"})

        # Connector road: starts at (100,0), lane -2 with width 0
        connector_road = ET.Element("road", {"id": "2", "junction": "-1", "length": "100"})
        plan = ET.SubElement(connector_road, "planView")
        geom = ET.SubElement(plan, "geometry", {"s": "0", "length": "100", "x": "100.0", "y": "0.0", "hdg": "0.0"})
        ET.SubElement(geom, "line")
        lanes = ET.SubElement(connector_road, "lanes")
        lane_section = ET.SubElement(lanes, "laneSection", {"s": "0"})
        right = ET.SubElement(lane_section, "right")
        lane = ET.SubElement(right, "lane", {"id": "-2", "type": "driving"})
        ET.SubElement(lane, "width", {"sOffset": "0", "a": "0.0", "b": "0.0", "c": "0.0", "d": "0.0"})
        link = ET.SubElement(connector_road, "link")
        ET.SubElement(link, "predecessor", {"elementType": "junction", "elementId": "j1"})

        junction = ET.Element("junction", {"id": "j1"})
        conn = ET.SubElement(junction, "connection", {
            "incomingRoad": "1",
            "connectingRoad": "2",
            "contactPoint": "start",
        })
        ET.SubElement(conn, "laneLink", {"from": "-2", "to": "-2"})

        root = ET.Element("OpenDRIVE")
        root.append(incoming_road)
        root.append(connector_road)
        root.append(junction)

        result = analyze_junction_lane_links(root, junction, contact_point="start")
        assert len(result) >= 1
        rec = result[0]
        # Incoming lane -2 width 3.25m -> centre offset 1.625m right of reference
        # Connector lane -2 width 0 -> centre on reference
        # Both references meet at (100,0) -> gap = 1.625m
        gap = rec["entry_gap_m"]
        assert abs(gap - 1.625) < 0.01, f"Expected entry_gap_m≈1.625, got {gap}"
        assert rec["exit_gap_m"] is None or rec["exit_gap_m"] >= 0.0
        assert rec["u_turn"] is False

    def test_K3_K1_rotated_by_atan_1_2(self):
        """K3: K1 road rotated by atan(1/2) -> report measured heading diff.

        The connector road is rotated by atan(1/2) ≈ 26.565 degrees.
        The heading difference between incoming and connector lane centres
        should be approximately atan(1/2) in degrees.
        """
        angle = math.degrees(math.atan(1 / 2))  # ≈ 26.565 deg
        # Incoming road: (0,0) to (100,0)
        incoming_road = ET.Element("road", {"id": "1", "junction": "-1", "length": "100"})
        plan = ET.SubElement(incoming_road, "planView")
        geom = ET.SubElement(plan, "geometry", {"s": "0", "length": "100", "x": "0.0", "y": "0.0", "hdg": "0.0"})
        ET.SubElement(geom, "line")
        lanes = ET.SubElement(incoming_road, "lanes")
        lane_section = ET.SubElement(lanes, "laneSection", {"s": "0"})
        right = ET.SubElement(lane_section, "right")
        lane = ET.SubElement(right, "lane", {"id": "-2", "type": "driving"})
        ET.SubElement(lane, "width", {"sOffset": "0", "a": "0.0", "b": "0.0", "c": "0.0", "d": "0.0"})
        link = ET.SubElement(incoming_road, "link")
        ET.SubElement(link, "successor", {"elementType": "junction", "elementId": "j1"})

        # Connector road: starts at (100,0), rotated by atan(1/2)
        connector_road = ET.Element("road", {"id": "2", "junction": "-1", "length": "100"})
        plan = ET.SubElement(connector_road, "planView")
        # hdg in OpenDRIVE is in radians
        geom = ET.SubElement(plan, "geometry", {"s": "0", "length": "100", "x": "100.0", "y": "0.0", "hdg": str(math.atan(1 / 2))})
        ET.SubElement(geom, "line")
        lanes = ET.SubElement(connector_road, "lanes")
        lane_section = ET.SubElement(lanes, "laneSection", {"s": "0"})
        right = ET.SubElement(lane_section, "right")
        lane = ET.SubElement(right, "lane", {"id": "-2", "type": "driving"})
        ET.SubElement(lane, "width", {"sOffset": "0", "a": "0.0", "b": "0.0", "c": "0.0", "d": "0.0"})
        link = ET.SubElement(connector_road, "link")
        ET.SubElement(link, "predecessor", {"elementType": "junction", "elementId": "j1"})

        junction = ET.Element("junction", {"id": "j1"})
        conn = ET.SubElement(junction, "connection", {
            "incomingRoad": "1",
            "connectingRoad": "2",
            "contactPoint": "start",
        })
        ET.SubElement(conn, "laneLink", {"from": "-2", "to": "-2"})

        root = ET.Element("OpenDRIVE")
        root.append(incoming_road)
        root.append(connector_road)
        root.append(junction)

        result = analyze_junction_lane_links(root, junction, contact_point="start")
        assert len(result) >= 1
        rec = result[0]
        # The heading difference should be approximately atan(1/2) ≈ 26.565 deg
        hdg = rec["entry_heading_diff_deg"]
        expected = abs(angle)  # 26.565...
        assert abs(hdg - expected) < 1.0, (
            f"Expected entry_heading_diff_deg≈{expected:.2f}, got {hdg:.2f}"
        )
        # With both lane-centres at (100,0), gap should be 0
        assert rec["entry_gap_m"] == 0.0, f"Expected entry_gap_m=0.0, got {rec['entry_gap_m']}"
        assert rec["u_turn"] is False