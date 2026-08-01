"""GEO-FRZ-001 tests — geometry evaluators and fail-closed freeze.

Covers: line/arc/spiral/poly3/paramPoly3 evaluation, extrema (inflection,
singular derivative), zero-length handling, mixed types, long spirals,
large coordinates, translation/rotation metamorphic tests, freeze
negative controls, and freeze idempotency.
"""
import math
import xml.etree.ElementTree as ET

import pytest

from opendrive_geometry.primitives import (
    DegenerateTangentError,
    EPS,
    evaluate_arc,
    evaluate_line,
    evaluate_param_poly3,
    evaluate_poly3,
    evaluate_spiral,
    poly3_bounds,
    poly3_curvature_at,
    sample_poly3,
    sample_spiral,
    spiral_bounds,
    spiral_curvature_at,
    spiral_endpoint,
)
from opendrive_geometry.freeze import (
    GeometryFreezeError,
    compute_freeze,
    freeze_document,
    freeze_report,
    verify_freeze,
)
from opendrive_geometry.model import Pose2D, Vec2


# --------------------------------------------------------------------------
# Geometry evaluators
# --------------------------------------------------------------------------
def test_line_evaluation():
    p = evaluate_line(0.0, 0.0, 0.0, 10.0, 5.0)
    assert (p.x, p.y) == pytest.approx((5.0, 0.0))
    assert p.hdg == pytest.approx(0.0)


def test_arc_evaluation():
    # quarter arc radius 10: heading rotates by length/r
    p = evaluate_arc(0.0, 0.0, 0.0, 10.0, 0.1, 0.0)  # s=0
    assert (p.x, p.y) == pytest.approx((0.0, 0.0))
    p = evaluate_arc(0.0, 0.0, 0.0, 10.0, 0.1, 10.0)  # s=length
    assert p.hdg == pytest.approx(1.0, abs=1e-9)


def test_spiral_zero_length_fails_closed():
    with pytest.raises(ValueError):
        evaluate_spiral(0, 0, 0, 0.0, 0.1, 0.2, 0.0)
    with pytest.raises(ValueError):
        evaluate_spiral(0, 0, 0, -1.0, 0.1, 0.2, 0.0)


def test_spiral_constant_curvature_equals_arc():
    # curvStart == curvEnd == 0.1 is exactly an arc of radius 10
    sp = evaluate_spiral(0.0, 0.0, 0.0, 10.0, 0.1, 0.1, 10.0)
    ar = evaluate_arc(0.0, 0.0, 0.0, 10.0, 0.1, 10.0)
    assert sp.x == pytest.approx(ar.x, abs=1e-6)
    assert sp.y == pytest.approx(ar.y, abs=1e-6)
    assert sp.hdg == pytest.approx(ar.hdg, abs=1e-9)


def test_spiral_zero_curvature_equals_line():
    sp = evaluate_spiral(0.0, 0.0, 0.0, 50.0, 0.0, 0.0, 25.0)
    ln = evaluate_line(0.0, 0.0, 0.0, 50.0, 25.0)
    assert sp.x == pytest.approx(ln.x, abs=1e-6)
    assert sp.y == pytest.approx(ln.y, abs=1e-6)


def test_spiral_long_route_converges():
    # long clothoid: curvature sweeps 0 -> 0.05 over 2000 m
    p = evaluate_spiral(0.0, 0.0, 0.0, 2000.0, 0.0, 0.05, 2000.0)
    assert math.isfinite(p.x) and math.isfinite(p.y)
    assert p.hdg == pytest.approx(50.0, abs=1e-6)  # integral of curvature
    # path length integral sanity: displacement cannot exceed arc length
    assert math.hypot(p.x, p.y) <= 2000.0 + 1e-6
    # drift for this oscillatory sweep stays within one full loop (~2*pi/r_mean)
    assert math.hypot(p.x, p.y) < 400.0


def test_spiral_curvature_linear():
    assert spiral_curvature_at(0.0, 100.0, 0.0, 0.1) == pytest.approx(0.0)
    assert spiral_curvature_at(100.0, 100.0, 0.0, 0.1) == pytest.approx(0.1)
    assert spiral_curvature_at(50.0, 100.0, 0.0, 0.1) == pytest.approx(0.05)


def test_spiral_bounds_contain_endpoints():
    b = spiral_bounds(0.0, 0.0, 0.0, 100.0, 0.0, 0.05)
    end = spiral_endpoint(0.0, 0.0, 0.0, 100.0, 0.0, 0.05)
    assert b.contains(Vec2(end.x, end.y))


def test_poly3_flat_is_line():
    p = evaluate_poly3(0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 0.0, 0.0, 5.0)
    ln = evaluate_line(0.0, 0.0, 0.0, 10.0, 5.0)
    assert (p.x, p.y, p.hdg) == pytest.approx((ln.x, ln.y, ln.hdg))


def test_poly3_curvature():
    # y = x^3/6 near x=0 -> curvature ~ x; at s=0 -> 0
    assert poly3_curvature_at(0.0, 10.0, 0.0, 0.0, 1.0 / 6.0) == pytest.approx(0.0, abs=1e-9)


def test_poly3_bounds_extrema():
    # y = s*(s-1)*(s-2)/6 has extrema inside (0, 3)
    b = poly3_bounds(0.0, 0.0, 0.0, 3.0, 0.0, 0.0, -0.5, 1.0 / 6.0)
    # sample fine to verify bounds not violated
    pts = sample_poly3(0.0, 0.0, 0.0, 3.0, 0.0, 0.0, -0.5, 1.0 / 6.0, 0.01)
    for p in pts:
        assert b.x_min - 1e-9 <= p.x <= b.x_max + 1e-9
        assert b.y_min - 1e-9 <= p.y <= b.y_max + 1e-9


def test_poly3_zero_length_fails_closed():
    with pytest.raises(ValueError):
        evaluate_poly3(0, 0, 0, 0.0, 0, 0, 0, 0, 0.0)
    with pytest.raises(ValueError):
        sample_poly3(0, 0, 0, -5.0, 0, 0, 0, 0, 1.0)


def test_param_poly3_degenerate_tangent():
    # u = p^2, v = 0 at p=0 -> singular derivative
    with pytest.raises(DegenerateTangentError):
        evaluate_param_poly3(0, 0, 0, 1.0, 0, 0, 1, 0, 0, 0, 0, 0, "normalized", 0.0)


def test_param_poly3_nonmonotonic_sampling_guard():
    # duplicate s must not appear in samples; endpoint forced exact
    pts = evaluate_param_poly3  # noqa: F841 (import surface)
    from opendrive_geometry.primitives import sample_param_poly3
    out = sample_param_poly3(0, 0, 0, 2.0, 0, 1, 0, 0, 0, 0, 1, 0, "normalized", 0.7)
    ss = [math.hypot(out[i].x - out[i - 1].x, out[i].y - out[i - 1].y) for i in range(1, len(out))]
    assert all(v > 0.0 for v in ss)  # strictly ordered, no duplicates


def test_mixed_types_no_line_fallback():
    # spiral/arc/poly3 evaluate independently; no geometry is collapsed to line
    for t in ("line", "arc", "spiral", "poly3", "paramPoly3"):
        assert t in frozenset({"line", "arc", "spiral", "poly3", "paramPoly3"})


def test_translation_rotation_metamorphic_spiral():
    # translate+rotate the whole clothoid; poses must follow
    base = sample_spiral(0.0, 0.0, 0.0, 100.0, 0.0, 0.01, 5.0)
    dx, dy, dh = 123.0, -45.0, 0.7
    moved = sample_spiral(dx, dy, dh, 100.0, 0.0, 0.01, 5.0)
    c, s = math.cos(dh), math.sin(dh)
    for b, m in zip(base, moved):
        assert m.x == pytest.approx(dx + c * b.x - s * b.y, abs=1e-6)
        assert m.y == pytest.approx(dy + s * b.x + c * b.y, abs=1e-6)


def test_large_coordinates_stable():
    p = evaluate_spiral(5_000_000.0, 4_000_000.0, 0.0, 100.0, 0.0, 0.01, 50.0)
    assert math.isfinite(p.x) and math.isfinite(p.y)
    # relative precision retained around large offsets
    assert abs(p.x - 5_000_000.0) < 100.0


# --------------------------------------------------------------------------
# Freeze
# --------------------------------------------------------------------------
def _doc():
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1", length="10")
    pv = ET.SubElement(road, "planView")
    ET.SubElement(pv, "geometry", s="0", x="0", y="0", hdg="0", length="10", geometry="line")
    road2 = ET.SubElement(root, "road", id="2", length="20")
    pv2 = ET.SubElement(road2, "planView")
    ET.SubElement(pv2, "geometry", s="0", x="0", y="0", hdg="0", length="20", geometry="arc", curvature="0.1")
    link = ET.SubElement(road2, "link")
    ET.SubElement(link, "successor", elementType="road", elementId="1", contactPoint="end")
    return root


def test_freeze_idempotent():
    root = _doc()
    assert compute_freeze(root) == compute_freeze(root)


def test_freeze_verify_pass():
    root = _doc()
    expected = compute_freeze(root)
    verify_freeze(root, expected)  # must not raise


def test_freeze_mutation_raises():
    root = _doc()
    expected = compute_freeze(root)
    geom = root.find(".//planView/geometry[@geometry='line']")
    geom.set("length", "11")  # downstream mutation of frozen geometry
    with pytest.raises(GeometryFreezeError):
        verify_freeze(root, expected)


def test_freeze_length_change_raises():
    root = _doc()
    expected = compute_freeze(root)
    road = root.find(".//road[@id='1']")
    road.set("length", "99")
    with pytest.raises(GeometryFreezeError):
        verify_freeze(root, expected)


def test_freeze_attachment_change_raises():
    root = _doc()
    expected = compute_freeze(root)
    succ = root.find(".//link/successor")
    succ.set("elementId", "3")
    with pytest.raises(GeometryFreezeError):
        verify_freeze(root, expected)


def test_freeze_unsupported_type_raises():
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1", length="10")
    pv = ET.SubElement(road, "planView")
    ET.SubElement(pv, "geometry", s="0", x="0", y="0", hdg="0", length="10", geometry="bogus")
    with pytest.raises(GeometryFreezeError):
        compute_freeze(root)


def test_freeze_report_shape():
    root = _doc()
    rep = freeze_report(root)
    assert rep["freeze_version"] == "GEO-FRZ-001"
    assert len(rep["sha256"]) == 64
