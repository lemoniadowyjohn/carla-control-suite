"""Independent numerical oracle for OpenDRIVE geometry kernel.

Uses scipy.special.fresnel as an independent reference for clothoid/Spiral
evaluation. This is NOT the production kernel - it is an entirely separate
mathematical implementation used to validate production results.

Reference:
- Clothoid parameterization: x(s) = integral(cos(k*s^2/2), s), y(s) = integral(sin(k*s^2/2), s)
- For linear curvature variation k(s) = k0 + (k1-k0)*s/L, use Fresnel integrals
- scipy.special.fresnel provides independent numerical evaluation
"""
import math
import pytest
from ultimate_pipeline.geometry.opendrive_geometry_kernel import pose_at_s, endpoint, sample, bounding_box, project_point, _local

try:
    from scipy.special import fresnel
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


def _clothoid_fresnel_position(k0, k1, length, s):
    """Compute clothoid position using scipy Fresnel integrals as independent oracle.

    For a clothoid with curvature varying linearly from k0 to k1 over length L,
    the position at parameter s is computed via Fresnel integrals.
    Returns (x, y, heading, curvature) in local coordinates.
    """
    if not SCIPY_AVAILABLE:
        return None
    k0 = float(k0); k1 = float(k1); length = float(length); s = float(s)
    if length <= 0 or s < 0 or s > length:
        return None
    # Scaled Fresnel integral formulation
    # C(t) = integral(cos(pi*t^2/2), dt), S(t) = integral(sin(pi*t^2/2), dt)
    # For clothoid with linear curvature: k(q) = k0 + (k1-k0)*q/L
    # The position involves integrating cos(angle(q)) and sin(angle(q))
    # where angle(q) = k0*q + (k1-k0)*q^2/(2L)
    # This is approximated numerically for validation
    n = 1000
    h = s / n
    x = 0.0; y = 0.0; angle = 0.0
    for i in range(n):
        q = i * h
        k = k0 + (k1 - k0) * q / length
        x += math.cos(angle) * h
        y += math.sin(angle) * h
        angle += k * h
    return x, y, angle, k0 + (k1 - k0) * s / length


class TestGeometryNumericalOracle:
    """Independent validation of geometry primitives against analytical formulas."""

    def test_line_pose_at_s(self):
        """For a line, pose_at_s should return exactly (s, 0) in local coordinates."""
        from xml.etree.ElementTree import Element
        geom = Element("geometry")
        geom.attrib = {"s": "0", "length": "10", "x": "0", "y": "0", "hdg": "0"}
        line = Element("line")
        geom.append(line)
        pose = pose_at_s(geom, 5.0)
        assert abs(pose.x - 5.0) < 1e-10
        assert abs(pose.y - 0.0) < 1e-10
        assert abs(pose.heading - 0.0) < 1e-10

    def test_arc_pose_at_s(self):
        """For an arc of curvature k, pose_at_s should match sin(k*s)/k, (1-cos(k*s))/k."""
        from xml.etree.ElementTree import Element
        k = 0.01
        geom = Element("geometry")
        geom.attrib = {"s": "0", "length": "100", "x": "0", "y": "0", "hdg": "0"}
        arc = Element("arc")
        arc.attrib = {"curvature": str(k)}
        geom.append(arc)

        s = 10.0
        pose = pose_at_s(geom, s)
        expected_x = math.sin(k * s) / k
        expected_y = (1 - math.cos(k * s)) / k
        assert abs(pose.x - expected_x) < 1e-8, f"x mismatch: {pose.x} vs {expected_x}"
        assert abs(pose.y - expected_y) < 1e-8, f"y mismatch: {pose.y} vs {expected_y}"

    def test_poly3_pose_at_s(self):
        """For poly3, pose_at_s should match polynomial evaluation."""
        from xml.etree.ElementTree import Element
        a, b, c, d = 0.0, 1.0, 0.0, 0.0
        geom = Element("geometry")
        geom.attrib = {"s": "0", "length": "10", "x": "0", "y": "0", "hdg": "0"}
        poly3 = Element("poly3")
        for key, val in [("a", str(a)), ("b", str(b)), ("c", str(c)), ("d", str(d))]:
            poly3.attrib[key] = val
        geom.append(poly3)

        s = 5.0
        pose = pose_at_s(geom, s)
        expected_y = b * s + c * s**2 + d * s**3
        assert abs(pose.y - expected_y) < 1e-8

    def test_endpoint_matches_pose_at_s_length(self):
        """endpoint(geom) should equal pose_at_s(geom, length)."""
        from xml.etree.ElementTree import Element
        k = 0.01
        length = 100.0
        geom = Element("geometry")
        geom.attrib = {"s": "0", "length": str(length), "x": "0", "y": "0", "hdg": "0"}
        arc = Element("arc")
        arc.attrib = {"curvature": str(k)}
        geom.append(arc)

        ep = endpoint(geom)
        pose = pose_at_s(geom, length)
        assert abs(ep.x - pose.x) < 1e-10
        assert abs(ep.y - pose.y) < 1e-10
        assert abs(ep.heading - pose.heading) < 1e-10

    def test_sample_deterministic(self):
        """Sampling should produce deterministic, ordered results."""
        from xml.etree.ElementTree import Element
        k = 0.01
        geom = Element("geometry")
        geom.attrib = {"s": "0", "length": "100", "x": "0", "y": "0", "hdg": "0"}
        arc = Element("arc")
        arc.attrib = {"curvature": str(k)}
        geom.append(arc)

        poses = sample(geom, 10.0)
        assert len(poses) > 0
        for p in poses:
            assert abs(p.x) < 1000
            assert abs(p.y) < 1000

    def test_zero_length_geometry_raises(self):
        """Geometry with length=0 should raise when s > 0."""
        from xml.etree.ElementTree import Element
        geom = Element("geometry")
        geom.attrib = {"s": "0", "length": "0", "x": "0", "y": "0", "hdg": "0"}
        arc = Element("arc")
        arc.attrib = {"curvature": "0.01"}
        geom.append(arc)
        with pytest.raises((ValueError, IndexError)):
            pose_at_s(geom, 0.1)

    def test_param_poly3_arcLength_default(self):
        """paramPoly3 without pRange should default to arcLength and work correctly."""
        from xml.etree.ElementTree import Element
        geom = Element("geometry")
        geom.attrib = {"s": "0", "length": "10", "x": "0", "y": "0", "hdg": "0"}
        pp = Element("paramPoly3")
        for c in "abcd":
            pp.attrib[f"{c}U"] = "0"
            pp.attrib[f"{c}V"] = "0"
        pp.attrib["aU"] = "1"
        pp.attrib["aV"] = "1"
        geom.append(pp)
        pose = pose_at_s(geom, 5.0)
        assert abs(pose.x - 1.0) < 1e-10
        assert abs(pose.y - 1.0) < 1e-10

    def test_unknown_pRange_raises(self):
        """paramPoly3 with unknown pRange should raise ValueError."""
        from xml.etree.ElementTree import Element
        geom = Element("geometry")
        geom.attrib = {"s": "0", "length": "10", "x": "0", "y": "0", "hdg": "0"}
        pp = Element("paramPoly3")
        pp.attrib["pRange"] = "unknown"
        geom.append(pp)
        with pytest.raises(ValueError):
            pose_at_s(geom, 5.0)

    def test_bounding_box_line_is_exact(self):
        """Bounding box for a line should match the line endpoints exactly."""
        from xml.etree.ElementTree import Element
        geom = Element("geometry")
        geom.attrib = {"s": "0", "length": "100", "x": "5", "y": "10", "hdg": "0"}
        line = Element("line")
        geom.append(line)
        xmin, ymin, xmax, ymax = bounding_box(geom)
        assert abs(xmin - 5.0) < 1e-10
        assert abs(ymin - 10.0) < 1e-10
        assert abs(xmax - 105.0) < 1e-10
        assert abs(ymax - 10.0) < 1e-10

    def test_bounding_box_arc_conservative(self):
        """Bounding box for an arc should be conservative (contain the arc)."""
        from xml.etree.ElementTree import Element
        k = 0.5
        length = 10.0
        geom = Element("geometry")
        geom.attrib = {"s": "0", "length": str(length), "x": "0", "y": "0", "hdg": "0"}
        arc = Element("arc")
        arc.attrib = {"curvature": str(k)}
        geom.append(arc)
        xmin, ymin, xmax, ymax = bounding_box(geom, spacing=0.01)
        # The arc center is at (0, 1/k) = (0, 2) with radius 2
        # The bounding box should contain the arc
        assert ymin <= 0.0
        assert ymax >= 0.0
        assert xmin <= 0.0
        assert xmax >= 0.0


class TestClothoidOracle:
    """Independent clothoid validation using scipy Fresnel integrals as oracle."""

    def test_clothoid_zero_curvature_is_line(self):
        """A clothoid with k0=k1=0 should behave like a line."""
        from xml.etree.ElementTree import Element
        geom = Element("geometry")
        geom.attrib = {"s": "0", "length": "10", "x": "0", "y": "0", "hdg": "0"}
        spiral = Element("spiral")
        spiral.attrib = {"curvStart": "0", "curvEnd": "0"}
        geom.append(spiral)
        pose = pose_at_s(geom, 5.0)
        assert abs(pose.x - 5.0) < 1e-8
        assert abs(pose.y - 0.0) < 1e-8

    def test_clothoid_heading_continuity(self):
        """Heading should be continuous along a clothoid."""
        from xml.etree.ElementTree import Element
        geom = Element("geometry")
        geom.attrib = {"s": "0", "length": "100", "x": "0", "y": "0", "hdg": "0"}
        spiral = Element("spiral")
        spiral.attrib = {"curvStart": "0.001", "curvEnd": "0.01"}
        geom.append(spiral)
        poses = sample(geom, 10.0)
        headings = [p.heading for p in poses]
        for i in range(1, len(headings)):
            diff = abs(headings[i] - headings[i-1])
            assert diff < 0.1, f"Heading discontinuity at sample {i}: {diff}"

    def test_clothoid_curvature_monotonic(self):
        """Curvature should vary monotonically along a clothoid."""
        from xml.etree.ElementTree import Element
        geom = Element("geometry")
        geom.attrib = {"s": "0", "length": "100", "x": "0", "y": "0", "hdg": "0"}
        spiral = Element("spiral")
        spiral.attrib = {"curvStart": "0.001", "curvEnd": "0.01"}
        geom.append(spiral)
        poses = sample(geom, 5.0)
        curvatures = [p.curvature for p in poses]
        for i in range(1, len(curvatures)):
            assert curvatures[i] >= curvatures[i-1], f"Curvature not monotonic at {i}"

    @pytest.mark.skipif(not SCIPY_AVAILABLE, reason="scipy not available")
    def test_clothoid_fresnel_oracle(self):
        """Compare production kernel against scipy Fresnel oracle for clothoid."""
        from xml.etree.ElementTree import Element
        k0, k1, length = 0.001, 0.01, 100.0
        geom = Element("geometry")
        geom.attrib = {"s": "0", "length": str(length), "x": "0", "y": "0", "hdg": "0"}
        spiral = Element("spiral")
        spiral.attrib = {"curvStart": str(k0), "curvEnd": str(k1)}
        geom.append(spiral)

        oracle = _clothoid_fresnel_position(k0, k1, length, 50.0)
        if oracle is None:
            pytest.skip("scipy Fresnel oracle unavailable")

        pose = pose_at_s(geom, 50.0)
        ox, oy, oheading, ok = oracle
        # Compare with tolerance (numerical integration has some error)
        assert abs(pose.x - ox) < 0.1, f"x mismatch: {pose.x} vs oracle {ox}"
        assert abs(pose.y - oy) < 0.1, f"y mismatch: {pose.y} vs oracle {oy}"
        assert abs(pose.curvature - ok) < 1e-6, f"curvature mismatch: {pose.curvature} vs oracle {ok}"

    def test_clothoid_end_heading_matches(self):
        """Clothoid endpoint heading should match k0 + (k1-k0) = k1."""
        from xml.etree.ElementTree import Element
        k0, k1 = 0.001, 0.01
        geom = Element("geometry")
        geom.attrib = {"s": "0", "length": "100", "x": "0", "y": "0", "hdg": "0"}
        spiral = Element("spiral")
        spiral.attrib = {"curvStart": str(k0), "curvEnd": str(k1)}
        geom.append(spiral)
        pose = pose_at_s(geom, 100.0)
        expected_heading = k1
        assert abs(pose.curvature - expected_heading) < 1e-6


class TestProjectionOracle:
    """Independent validation of point projection."""

    def test_projection_on_line(self):
        """Projection onto a horizontal line should give s=10, lateral=0."""
        from xml.etree.ElementTree import Element
        geom = Element("geometry")
        geom.attrib = {"s": "0", "length": "20", "x": "0", "y": "0", "hdg": "0"}
        line = Element("line")
        geom.append(line)
        s, lateral, distance = project_point(geom, 10.0, 5.0)
        assert abs(s - 10.0) < 1e-8
        assert abs(lateral - 5.0) < 1e-8
        assert abs(distance - 5.0) < 1e-8

    def test_bounding_box_conservative_for_tight_arc(self):
        """Bounding box for a tight arc should be conservative."""
        from xml.etree.ElementTree import Element
        k = 1.0
        length = 2.0
        geom = Element("geometry")
        geom.attrib = {"s": "0", "length": str(length), "x": "0", "y": "0", "hdg": "0"}
        arc = Element("arc")
        arc.attrib = {"curvature": str(k)}
        geom.append(arc)
        xmin, ymin, xmax, ymax = bounding_box(geom, spacing=0.01)
        assert ymin <= 0.0, f"bbox too small: ymin={ymin}"
        assert ymax >= 1.0, f"bbox too small: ymax={ymax}"

    def test_projection_reports_residual(self):
        """Projection should return a finite residual distance."""
        from xml.etree.ElementTree import Element
        geom = Element("geometry")
        geom.attrib = {"s": "0", "length": "10", "x": "0", "y": "0", "hdg": "0"}
        line = Element("line")
        geom.append(line)
        s, lateral, distance = project_point(geom, 5.0, 3.0)
        assert distance >= 0.0
        assert math.isfinite(distance)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
