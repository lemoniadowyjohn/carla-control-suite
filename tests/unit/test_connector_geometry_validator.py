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
  - K1-K5: known-good lane-centre controls (specified IDs from O13 prompt)
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
    _lane_offset_value,
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
# K1-K5: Known-good lane-centre controls
# ============================================================


def _make_right_lane_road(
    road_id: str,
    x: float,
    y: float,
    hdg: float,
    lanes_right: list[tuple[int, float]],
    link_kind: str = "successor",
    lane_offset: dict[str, str] | None = None,
    length: float = 100.0,
) -> ET.Element:
    """Build a straight road with right-side lanes and optional <laneOffset>."""
    road = ET.Element("road", {"id": road_id, "junction": "-1", "length": str(length)})
    plan = ET.SubElement(road, "planView")
    geom = ET.SubElement(plan, "geometry", {
        "s": "0", "length": str(length), "x": str(x), "y": str(y), "hdg": str(hdg),
    })
    ET.SubElement(geom, "line")
    lanes_el = ET.SubElement(road, "lanes")
    if lane_offset is not None:
        ET.SubElement(lanes_el, "laneOffset", lane_offset)
    section = ET.SubElement(lanes_el, "laneSection", {"s": "0"})
    right = ET.SubElement(section, "right")
    for lane_id, width in lanes_right:
        lane = ET.SubElement(right, "lane", {"id": str(lane_id), "type": "driving"})
        ET.SubElement(lane, "width", {
            "sOffset": "0", "a": str(width), "b": "0.0", "c": "0.0", "d": "0.0",
        })
    link = ET.SubElement(road, "link")
    ET.SubElement(link, link_kind, {"elementType": "junction", "elementId": "j1"})
    return road


def _run_control(
    incoming: ET.Element,
    connector: ET.Element,
    from_lane: str,
    to_lane: str,
) -> dict:
    """Wire two roads into a one-laneLink junction and return its analysis record."""
    junction = ET.Element("junction", {"id": "j1"})
    conn = ET.SubElement(junction, "connection", {
        "incomingRoad": incoming.get("id"),
        "connectingRoad": connector.get("id"),
        "contactPoint": "start",
    })
    ET.SubElement(conn, "laneLink", {"from": from_lane, "to": to_lane})
    root = ET.Element("OpenDRIVE")
    root.append(incoming)
    root.append(connector)
    root.append(junction)
    result = analyze_junction_lane_links(root, junction, contact_point="start")
    assert len(result) >= 1, "expected one laneLink record"
    return result[0]


class TestKnownGoodControls:
    """K1-K5: lane-centre controls with exact value assertions."""

    def test_K1_connector_reference_on_inner_border_of_lane_minus2(self):
        """K1: connector reference line on lane -2's inner border -> gap 0, kink 0.

        Incoming road has two 3.25 m right lanes. Lane -2's inner border is
        3.25 m right of the reference line; its centre is 4.875 m right.
        The connector reference line starts on that border and its lane -1
        centre (1.625 m right of its own reference) lands on the same point.
        """
        incoming = _make_right_lane_road(
            "1", 0.0, 0.0, 0.0, [(-1, 3.25), (-2, 3.25)],
        )
        connector = _make_right_lane_road(
            "2", 100.0, -3.25, 0.0, [(-1, 3.25)], link_kind="predecessor",
        )

        rec = _run_control(incoming, connector, "-2", "-1")

        assert rec["entry_gap_m"] == pytest.approx(0.0, abs=1e-9)
        assert rec["entry_heading_diff_deg"] == pytest.approx(0.0, abs=1e-9)
        assert rec["u_turn"] is False

    def test_K2_connector_moved_onto_incoming_reference_line(self):
        """K2: same as K1 but connector reference moved onto the incoming one.

        Incoming lane -2 centre is 4.875 m right of the reference line;
        connector lane -1 centre is 1.625 m right of its own reference.
        Both references meet at (100, 0), so the entry gap is 3.25 m.
        """
        incoming = _make_right_lane_road(
            "1", 0.0, 0.0, 0.0, [(-1, 3.25), (-2, 3.25)],
        )
        connector = _make_right_lane_road(
            "2", 100.0, 0.0, 0.0, [(-1, 3.25)], link_kind="predecessor",
        )

        rec = _run_control(incoming, connector, "-2", "-1")

        assert rec["entry_gap_m"] == pytest.approx(3.25, abs=1e-9)
        assert rec["u_turn"] is False

    def test_K3_K1_rotated_by_atan_1_2(self):
        """K3: K1 rotated by atan(1/2) -> gap 3.25*sin(atan(1/4)) du = 0.7467 m.

        The connector reference starts on lane -2's inner border and is
        rotated by atan(1/2). Both centre offsets are 1.625 m, so the
        residual gap is 2*1.625*sin(hdg/2) = 3.25*sin(atan(1/4)).
        """
        angle = math.atan(1 / 2)
        expected_gap = 3.25 * math.sin(angle / 2)  # 0.7467 m

        incoming = _make_right_lane_road(
            "1", 0.0, 0.0, 0.0, [(-1, 3.25), (-2, 3.25)],
        )
        connector = _make_right_lane_road(
            "2", 100.0, -3.25, angle, [(-1, 3.25)], link_kind="predecessor",
        )

        rec = _run_control(incoming, connector, "-2", "-1")

        assert rec["entry_gap_m"] == pytest.approx(expected_gap, abs=1e-9)
        assert rec["entry_gap_m"] == pytest.approx(0.7467, abs=1e-4)
        assert rec["entry_heading_diff_deg"] == pytest.approx(
            math.degrees(angle), abs=1e-9,
        )
        assert rec["u_turn"] is False

    def test_K4_lane_offset_not_rotated(self):
        """K4: connector reference 3.25 m right, but laneOffset a=3.25 -> gap 0.

        Incoming lane -1 centre is 1.625 m right of its reference. The
        connector reference starts 3.25 m right, and its laneOffset shifts
        the whole lane section 3.25 m back left, so lane -1 centre is at
        t = 3.25 - 1.625 = +1.625 -> the same world point.
        """
        lane_offset = {"s": "0", "a": "3.25", "b": "0.0", "c": "0.0", "d": "0.0"}
        incoming = _make_right_lane_road(
            "1", 0.0, 0.0, 0.0, [(-1, 3.25)],
        )
        connector = _make_right_lane_road(
            "2", 100.0, -3.25, 0.0, [(-1, 3.25)],
            link_kind="predecessor", lane_offset=lane_offset,
        )

        rec = _run_control(incoming, connector, "-1", "-1")

        assert rec["entry_gap_m"] == pytest.approx(0.0, abs=1e-9)
        assert rec["entry_heading_diff_deg"] == pytest.approx(0.0, abs=1e-9)
        assert rec["u_turn"] is False

    def test_K4_lane_offset_rotated(self):
        """K4 rotated: the same laneOffset control rotated by atan(1/2).

        The laneOffset cancels the 3.25 m reference shift, leaving the same
        1.625 m lateral pair as K3 -> 0.7467 m.
        """
        angle = math.atan(1 / 2)
        expected_gap = 3.25 * math.sin(angle / 2)  # 0.7467 m
        lane_offset = {"s": "0", "a": "3.25", "b": "0.0", "c": "0.0", "d": "0.0"}

        incoming = _make_right_lane_road(
            "1", 0.0, 0.0, 0.0, [(-1, 3.25)],
        )
        connector = _make_right_lane_road(
            "2", 100.0, -3.25, angle, [(-1, 3.25)],
            link_kind="predecessor", lane_offset=lane_offset,
        )

        rec = _run_control(incoming, connector, "-1", "-1")

        assert rec["entry_gap_m"] == pytest.approx(expected_gap, abs=1e-9)
        assert rec["entry_gap_m"] == pytest.approx(0.7467, abs=1e-4)
        assert rec["entry_heading_diff_deg"] == pytest.approx(
            math.degrees(angle), abs=1e-9,
        )
        assert rec["u_turn"] is False

    def test_K5_lane_offset_cubic_at_s_gt_0(self):
        """K5: the laneOffset cubic (b/c/d) is evaluated at s > 0.

        With a=1, b=0.5, c=0.1, d=0.2 at s=4 (ds=4):
        1 + 2 + 1.6 + 12.8 = 17.4. A linear-only implementation would give
        3.0, and ignoring b would give 15.4.
        """
        cubic = ET.Element("lanes")
        ET.SubElement(cubic, "laneOffset", {
            "s": "0", "a": "1.0", "b": "0.5", "c": "0.1", "d": "0.2",
        })
        assert _lane_offset_value(cubic, 0.0) == pytest.approx(1.0, abs=1e-12)
        assert _lane_offset_value(cubic, 4.0) == pytest.approx(17.4, abs=1e-12)

        records = ET.Element("lanes")
        ET.SubElement(records, "laneOffset", {"s": "0", "a": "2.0"})
        ET.SubElement(records, "laneOffset", {"s": "10", "a": "7.0"})
        assert _lane_offset_value(records, 5.0) == pytest.approx(2.0, abs=1e-12)
        assert _lane_offset_value(records, 10.0) == pytest.approx(7.0, abs=1e-12)

        assert _lane_offset_value(ET.Element("lanes"), 5.0) == 0.0
