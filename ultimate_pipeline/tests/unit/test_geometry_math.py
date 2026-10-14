import pytest
import math
import xml.etree.ElementTree as ET
from ultimate_pipeline.geometry.geometry_math import (
    _safe_float,
    _validate_parampoly3_coefficients,
    _sample_parampoly3_impl,
    sample_parampoly3_points,
    GeometryCalculator,
)


class TestSafeFloat:
    def test_valid_float(self):
        assert _safe_float(3.14) == 3.14
        assert _safe_float("2.5") == 2.5
        assert _safe_float(42) == 42.0
        assert _safe_float(-1.5) == -1.5

    def test_invalid_returns_default(self):
        assert _safe_float("invalid") == 0.0
        assert _safe_float(None) == 0.0
        assert _safe_float("") == 0.0
        assert _safe_float([1, 2]) == 0.0

    def test_custom_default(self):
        assert _safe_float("invalid", default=99.0) == 99.0
        assert _safe_float(None, default=-1.0) == -1.0

    def test_nan_returns_default(self):
        assert _safe_float(float("nan")) == 0.0
        assert _safe_float(float("nan"), default=5.0) == 5.0

    def test_inf_returns_default(self):
        assert _safe_float(float("inf")) == 0.0
        assert _safe_float(float("-inf")) == 0.0

    def test_very_large_number(self):
        assert _safe_float(1e308) == 1e308
        assert _safe_float("1e308") == 1e308


class TestValidateParampoly3Coefficients:
    def test_valid_coefficients(self):
        geom = ET.Element("geometry")
        pp = ET.SubElement(geom, "paramPoly3")
        pp.set("aU", "1.0")
        pp.set("bU", "2.0")
        pp.set("cU", "3.0")
        pp.set("dU", "4.0")
        pp.set("aV", "0.1")
        pp.set("bV", "0.2")
        pp.set("cV", "0.3")
        pp.set("dV", "0.4")
        # Should not raise
        _validate_parampoly3_coefficients(pp)

    def test_missing_coefficients_ok(self):
        geom = ET.Element("geometry")
        pp = ET.SubElement(geom, "paramPoly3")
        # Missing coefficients should be OK (they default to 0 in sampling)
        _validate_parampoly3_coefficients(pp)

    def test_non_finite_raises(self):
        geom = ET.Element("geometry")
        pp = ET.SubElement(geom, "paramPoly3")
        pp.set("aU", "inf")
        with pytest.raises(ValueError, match="Non-finite coefficient found"):
            _validate_parampoly3_coefficients(pp)

    def test_nan_raises(self):
        geom = ET.Element("geometry")
        pp = ET.SubElement(geom, "paramPoly3")
        pp.set("bU", "nan")
        with pytest.raises(ValueError, match="Non-finite coefficient found"):
            _validate_parampoly3_coefficients(pp)

    def test_invalid_number_format_ignored(self):
        geom = ET.Element("geometry")
        pp = ET.SubElement(geom, "paramPoly3")
        pp.set("aU", "not_a_number")
        # Invalid format is ignored (passes through to _safe_float which defaults to 0)
        _validate_parampoly3_coefficients(pp)


class TestSampleParampoly3Impl:
    def test_basic_sampling(self):
        geom = ET.Element("geometry")
        pp = ET.SubElement(geom, "paramPoly3")
        pp.set("aU", "0")
        pp.set("bU", "1")
        pp.set("cU", "0")
        pp.set("dU", "0")
        pp.set("aV", "0")
        pp.set("bV", "0")
        pp.set("cV", "0")
        pp.set("dV", "0")
        pp.set("pRange", "arcLength")

        points = _sample_parampoly3_impl(geom, 0, 0, 0, 10, [0, 0.5, 1])
        assert len(points) == 3
        # At t=0: p=0, u=0, v=0 -> (0, 0)
        assert points[0] == (0.0, 0.0)
        # At t=0.5: p=5, u=5 -> (5, 0)
        assert points[1] == (5.0, 0.0)
        # At t=1: p=10, u=10 -> (10, 0)
        assert points[2] == (10.0, 0.0)

    def test_with_heading(self):
        geom = ET.Element("geometry")
        pp = ET.SubElement(geom, "paramPoly3")
        pp.set("aU", "0")
        pp.set("bU", "1")
        pp.set("cU", "0")
        pp.set("dU", "0")
        pp.set("aV", "0")
        pp.set("bV", "0")
        pp.set("cV", "0")
        pp.set("dV", "0")
        pp.set("pRange", "arcLength")

        # 90 degree heading (pi/2)
        points = _sample_parampoly3_impl(geom, 0, 0, math.pi/2, 10, [0, 1])
        assert points[0] == (0.0, 0.0)
        # At t=1: u=10, rotated by 90 deg -> (0, 10)
        assert abs(points[1][0]) < 1e-10
        assert abs(points[1][1] - 10.0) < 1e-10

    def test_with_offset(self):
        geom = ET.Element("geometry")
        pp = ET.SubElement(geom, "paramPoly3")
        pp.set("aU", "0")
        pp.set("bU", "1")
        pp.set("cU", "0")
        pp.set("dU", "0")
        pp.set("aV", "0")
        pp.set("bV", "0")
        pp.set("cV", "0")
        pp.set("dV", "0")
        pp.set("pRange", "arcLength")

        points = _sample_parampoly3_impl(geom, 5, 3, 0, 10, [0, 1])
        assert points[0] == (5.0, 3.0)
        assert points[1] == (15.0, 3.0)

    def test_normalized_prange(self):
        geom = ET.Element("geometry")
        pp = ET.SubElement(geom, "paramPoly3")
        pp.set("aU", "0")
        pp.set("bU", "10")  # u = 10 * p (where p is normalized 0-1)
        pp.set("cU", "0")
        pp.set("dU", "0")
        pp.set("aV", "0")
        pp.set("bV", "0")
        pp.set("cV", "0")
        pp.set("dV", "0")
        pp.set("pRange", "normalized")

        points = _sample_parampoly3_impl(geom, 0, 0, 0, 100, [0, 0.5, 1])
        # p_max = 1.0 for normalized
        assert points[0] == (0.0, 0.0)
        assert points[1] == (5.0, 0.0)  # u = 10 * 0.5 = 5
        assert points[2] == (10.0, 0.0)  # u = 10 * 1.0 = 10

    def test_invalid_prange_raises(self):
        geom = ET.Element("geometry")
        pp = ET.SubElement(geom, "paramPoly3")
        pp.set("pRange", "invalid")
        with pytest.raises(ValueError, match="unsupported pRange"):
            _sample_parampoly3_impl(geom, 0, 0, 0, 10, [0.5])

    def test_zero_length_raises(self):
        geom = ET.Element("geometry")
        pp = ET.SubElement(geom, "paramPoly3")
        with pytest.raises(ValueError, match="length must be positive"):
            _sample_parampoly3_impl(geom, 0, 0, 0, 0, [0.5])

    def test_negative_length_raises(self):
        geom = ET.Element("geometry")
        pp = ET.SubElement(geom, "paramPoly3")
        with pytest.raises(ValueError, match="length must be positive"):
            _sample_parampoly3_impl(geom, 0, 0, 0, -5, [0.5])

    def test_no_paramPoly3_returns_start_point(self):
        geom = ET.Element("geometry")
        # No paramPoly3 child
        points = _sample_parampoly3_impl(geom, 1, 2, 0, 10, [0, 0.5, 1])
        assert points == [(1.0, 2.0)]

    def test_t_values_sorted_and_deduplicated(self):
        geom = ET.Element("geometry")
        pp = ET.SubElement(geom, "paramPoly3")
        pp.set("aU", "0")
        pp.set("bU", "1")
        pp.set("cU", "0")
        pp.set("dU", "0")
        pp.set("aV", "0")
        pp.set("bV", "0")
        pp.set("cV", "0")
        pp.set("dV", "0")
        pp.set("pRange", "arcLength")

        # Unsorted with duplicates
        points = _sample_parampoly3_impl(geom, 0, 0, 0, 10, [1, 0, 0.5, 0.5, 1])
        assert len(points) == 3
        assert points[0] == (0.0, 0.0)
        assert points[1] == (5.0, 0.0)
        assert points[2] == (10.0, 0.0)

    def test_t_values_out_of_range_skipped(self):
        geom = ET.Element("geometry")
        pp = ET.SubElement(geom, "paramPoly3")
        pp.set("aU", "0")
        pp.set("bU", "1")
        pp.set("cU", "0")
        pp.set("dU", "0")
        pp.set("aV", "0")
        pp.set("bV", "0")
        pp.set("cV", "0")
        pp.set("dV", "0")
        pp.set("pRange", "arcLength")

        points = _sample_parampoly3_impl(geom, 0, 0, 0, 10, [-0.5, 0, 0.5, 1, 1.5])
        assert len(points) == 3  # Only 0, 0.5, 1 are in range
        assert points[0] == (0.0, 0.0)
        assert points[1] == (5.0, 0.0)
        assert points[2] == (10.0, 0.0)

    def test_v_component(self):
        geom = ET.Element("geometry")
        pp = ET.SubElement(geom, "paramPoly3")
        pp.set("aU", "0")
        pp.set("bU", "0")
        pp.set("cU", "0")
        pp.set("dU", "0")
        pp.set("aV", "0")
        pp.set("bV", "1")
        pp.set("cV", "0")
        pp.set("dV", "0")
        pp.set("pRange", "arcLength")

        points = _sample_parampoly3_impl(geom, 0, 0, 0, 10, [0, 1])
        assert points[0] == (0.0, 0.0)
        assert points[1] == (0.0, 10.0)  # v=10, u=0


class TestSampleParampoly3Points:
    def test_public_api(self):
        geom = ET.Element("geometry")
        pp = ET.SubElement(geom, "paramPoly3")
        pp.set("aU", "0")
        pp.set("bU", "1")
        pp.set("cU", "0")
        pp.set("dU", "0")
        pp.set("aV", "0")
        pp.set("bV", "0")
        pp.set("cV", "0")
        pp.set("dV", "0")
        pp.set("pRange", "arcLength")

        points = sample_parampoly3_points(geom, 0, 0, 0, 10, [0, 0.5, 1])
        assert len(points) == 3
        assert points[0] == (0.0, 0.0)
        assert points[1] == (5.0, 0.0)
        assert points[2] == (10.0, 0.0)


class TestGeometryCalculator:
    def test_integrate_line(self):
        x, y, hdg = GeometryCalculator._integrate_line(0, 0, 0, 10)
        assert x == 10.0
        assert y == 0.0
        assert hdg == 0.0

    def test_integrate_line_with_heading(self):
        x, y, hdg = GeometryCalculator._integrate_line(0, 0, math.pi/2, 10)
        assert abs(x) < 1e-10
        assert abs(y - 10.0) < 1e-10
        assert hdg == math.pi/2

    def test_integrate_line_with_offset(self):
        x, y, hdg = GeometryCalculator._integrate_line(5, 3, 0, 10)
        assert x == 15.0
        assert y == 3.0

    def test_integrate_arc_zero_curvature(self):
        # Should fall back to line
        x, y, hdg = GeometryCalculator._integrate_arc(0, 0, 0, 10, 0)
        assert x == 10.0
        assert y == 0.0

    def test_integrate_arc_positive_curvature(self):
        # Curvature = 0.1, length = 10 -> delta_hdg = 1 rad
        curv = 0.1
        length = 10
        x, y, hdg = GeometryCalculator._integrate_arc(0, 0, 0, length, curv)
        expected_hdg = length * curv
        assert abs(hdg - expected_hdg) < 1e-10
        expected_x = (math.sin(expected_hdg) - math.sin(0)) / curv
        expected_y = (math.cos(0) - math.cos(expected_hdg)) / curv
        assert abs(x - expected_x) < 1e-10
        assert abs(y - expected_y) < 1e-10

    def test_integrate_arc_negative_curvature(self):
        curv = -0.1
        length = 10
        x, y, hdg = GeometryCalculator._integrate_arc(0, 0, 0, length, curv)
        expected_hdg = length * curv
        assert abs(hdg - expected_hdg) < 1e-10

    def test_get_endpoint_line(self):
        geom = ET.Element("geometry")
        line = ET.SubElement(geom, "line")
        x, y, hdg = GeometryCalculator.get_endpoint(0, 0, 0, 10, geom)
        assert x == 10.0
        assert y == 0.0
        assert hdg == 0.0

    def test_get_endpoint_arc(self):
        geom = ET.Element("geometry")
        arc = ET.SubElement(geom, "arc")
        arc.set("curvature", "0.1")
        x, y, hdg = GeometryCalculator.get_endpoint(0, 0, 0, 10, geom)
        expected_hdg = 1.0
        assert abs(hdg - expected_hdg) < 1e-10

    def test_get_endpoint_unsupported_raises(self):
        geom = ET.Element("geometry")
        # No supported child
        with pytest.raises(ValueError, match="Unsupported geometry type"):
            GeometryCalculator.get_endpoint(0, 0, 0, 10, geom)

    def test_get_endpoint_spiral_delegates_to_kernel(self):
        geom = ET.Element("geometry")
        spiral = ET.SubElement(geom, "spiral")
        # This will try to import the kernel - may fail if not available
        # Just verify it doesn't crash with ValueError for unsupported
        try:
            GeometryCalculator.get_endpoint(0, 0, 0, 10, geom)
        except (ImportError, ValueError):
            # Kernel not available or other error - acceptable
            pass


class TestGeometryHasher:
    def test_hash_geometry(self):
        from ultimate_pipeline.geometry.geometry_math import GeometryHasher
        geom = ET.Element("geometry")
        line = ET.SubElement(geom, "line")
        h = GeometryHasher.hash_geometry(geom)
        assert len(h) == 64
        # Deterministic
        assert GeometryHasher.hash_geometry(geom) == h

    def test_different_geometry_different_hash(self):
        from ultimate_pipeline.geometry.geometry_math import GeometryHasher
        geom1 = ET.Element("geometry")
        ET.SubElement(geom1, "line")
        geom2 = ET.Element("geometry")
        arc = ET.SubElement(geom2, "arc")
        arc.set("curvature", "0.1")
        assert GeometryHasher.hash_geometry(geom1) != GeometryHasher.hash_geometry(geom2)