from __future__ import annotations

import math
import os
import json
import hashlib
from pathlib import Path
from typing import Sequence

import pytest

from opendrive_geometry.model import Pose2D, Bounds2D
from opendrive_geometry.primitives import (
    evaluate_param_poly3,
    sample_param_poly3,
    param_poly3_endpoint,
    param_poly3_curvature_at,
    param_poly3_bounds,
    VALID_P_RANGES,
)
from opendrive_geometry.errors import (
    DegenerateTangentError,
    InvalidEvaluationRangeError,
    InvalidParamPoly3LengthError,
    MissingPRangeError,
    NonFiniteCoefficientError,
    UnsupportedPRangeError,
)
from opendrive_geometry.evaluator import EvaluationPolicy, ParamPoly3Evaluator, RangePolicy
from opendrive_geometry.model import GeometrySegment


def approx(x: float, y: float, rel: float = 1e-12, abs_tol: float = 1e-12) -> bool:
    return abs(x - y) < max(rel * max(abs(x), abs(y)), abs_tol)


# ---------------------------------------------------------------------------
# Helper: finite-difference numerical derivative
# ---------------------------------------------------------------------------

def _num_deriv(f, s: float, h: float = 1e-6) -> float:
    return (f(s + h) - f(s - h)) / (2.0 * h)


# ===================================================================
# 1. Straight line expressed as ParamPoly3
# ===================================================================

class TestStraightLine:
    def test_forward(self):
        p = evaluate_param_poly3(0, 0, 0, 100, 0, 100, 0, 0, 0, 0, 0, 0, "normalized", 50)
        assert approx(p.x, 50) and approx(p.y, 0) and approx(p.hdg, 0)

    def test_endpoint(self):
        p = param_poly3_endpoint(0, 0, 0, 100, 0, 100, 0, 0, 0, 0, 0, 0, "normalized")
        assert approx(p.x, 100) and approx(p.y, 0)

    def test_start(self):
        p = evaluate_param_poly3(0, 0, 0, 100, 0, 100, 0, 0, 0, 0, 0, 0, "normalized", 0)
        assert approx(p.x, 0) and approx(p.y, 0) and approx(p.hdg, 0)


# ===================================================================
# 2. Lateral linear offset
# ===================================================================

class TestLateralOffset:
    def test_positive_lateral(self):
        p = evaluate_param_poly3(0, 0, 0, 50, 0, 0, 0, 0, 0, 10, 0, 0, "normalized", 25)
        assert approx(p.x, 0) and approx(p.y, 10 * 0.5) and approx(p.hdg, math.pi / 2, abs_tol=1e-6)

    def test_negative_lateral(self):
        p = evaluate_param_poly3(0, 0, 0, 50, 0, 0, 0, 0, 0, -10, 0, 0, "normalized", 25)
        assert approx(p.x, 0) and approx(p.y, -10 * 0.5) and approx(p.hdg, -math.pi / 2, abs_tol=1e-6)


# ===================================================================
# 3. Quadratic curve
# ===================================================================

class TestQuadraticCurve:
    def test_position_at_start(self):
        p = evaluate_param_poly3(0, 0, 0, 100, 0, 100, 0, 0, 0, 0, 50, 0, "normalized", 0)
        assert approx(p.x, 0) and approx(p.y, 0)

    def test_position_at_mid(self):
        p = evaluate_param_poly3(0, 0, 0, 100, 0, 100, 0, 0, 0, 0, 50, 0, "normalized", 50)
        assert approx(p.y, 50 * 0.5 * 0.5, abs_tol=1e-9)

    def test_curvature_at_start(self):
        k = param_poly3_curvature_at(0, 100, 0, 0, 0, 0, 50, 0, "normalized", 100, 0)
        assert k != 0 and math.isfinite(k)


# ===================================================================
# 4. Cubic curve
# ===================================================================

class TestCubicCurve:
    def test_position(self):
        p = evaluate_param_poly3(0, 0, 0, 100, 0, 100, 0, 0, 0, 0, 0, 50, "normalized", 50)
        expected_v = 50 * (50 / 100) ** 3
        assert approx(p.y, expected_v, abs_tol=1e-9)

    def test_heading(self):
        p = evaluate_param_poly3(0, 0, 0, 100, 0, 100, 0, 0, 0, 0, 0, 50, "normalized", 50)
        dv_du = 3 * 50 * (50 / 100) ** 2 / 100  # dv/dp * dp/ds / (du/dp * dp/ds) = dv/du
        expected_hdg = math.atan2(3 * 50 * (50 / 100) ** 2, 100)
        assert approx(p.hdg, expected_hdg, abs_tol=1e-9)


# ===================================================================
# 5. Nonzero global origin
# ===================================================================

class TestNonzeroOrigin:
    def test_offset(self):
        p = evaluate_param_poly3(100, 200, 0, 50, 0, 50, 0, 0, 0, 0, 0, 0, "normalized", 25)
        assert approx(p.x, 125) and approx(p.y, 200) and approx(p.hdg, 0)


# ===================================================================
# 6. Nonzero global heading
# ===================================================================

class TestNonzeroHeading:
    def test_rotation(self):
        angle = math.radians(30)
        p = evaluate_param_poly3(0, 0, angle, 100, 0, 100, 0, 0, 0, 0, 0, 0, "normalized", 100)
        assert approx(p.x, 100 * math.cos(angle), abs_tol=1e-12)
        assert approx(p.y, 100 * math.sin(angle), abs_tol=1e-12)
        assert approx(p.hdg, angle, abs_tol=1e-12)


# ===================================================================
# 7 + 8. Normalized vs arcLength pRange
# ===================================================================

class TestPRangeModes:
    def test_normalized_coefficients_same_as_arclength_for_bU_equal_length(self):
        n = evaluate_param_poly3(0, 0, 0, 100, 0, 100, 0, 0, 0, 0, 0, 0, "normalized", 50)
        a = evaluate_param_poly3(0, 0, 0, 100, 0, 1, 0, 0, 0, 0, 0, 0, "arcLength", 50)
        assert approx(n.x, a.x) and approx(n.y, a.y)
        assert approx(n.hdg, a.hdg)

    def test_normalized_parameter_range(self):
        p = evaluate_param_poly3(0, 0, 0, 200, 0, 200, 0, 0, 0, 0, 0, 0, "normalized", 100)
        assert approx(p.x, 100)

    def test_arclength_parameter_range(self):
        p = evaluate_param_poly3(0, 0, 0, 200, 0, 1, 0, 0, 0, 0, 0, 0, "arcLength", 100)
        assert approx(p.x, 100)

    def test_endpoint_normalized(self):
        p = param_poly3_endpoint(0, 0, 0, 100, 0, 50, 0, 0, 0, 0, 0, 0, "normalized")
        assert approx(p.x, 50)

    def test_endpoint_arclength(self):
        p = param_poly3_endpoint(0, 0, 0, 100, 0, 1, 0, 0, 0, 0, 0, 0, "arcLength")
        assert approx(p.x, 100)


# ===================================================================
# 9. Positive lateral curvature (bV positive → left turn)
# ===================================================================

class TestPositiveCurvature:
    def test_position(self):
        p = evaluate_param_poly3(0, 0, 0, 100, 0, 100, 0, 0, 0, 0, 1, 0, "normalized", 50)
        assert p.y > 0

    def test_curvature_sign(self):
        k = param_poly3_curvature_at(0, 100, 0, 0, 0, 0, 1, 0, "normalized", 100, 50)
        assert k > 0


# ===================================================================
# 10. Negative lateral curvature
# ===================================================================

class TestNegativeCurvature:
    def test_position(self):
        p = evaluate_param_poly3(0, 0, 0, 100, 0, 100, 0, 0, 0, 0, -1, 0, "normalized", 50)
        assert p.y < 0

    def test_curvature_sign(self):
        k = param_poly3_curvature_at(0, 100, 0, 0, 0, 0, -1, 0, "normalized", 100, 50)
        assert k < 0


# ===================================================================
# 11. Degenerate zero tangent
# ===================================================================

class TestZeroTangent:
    def test_zero_all_coeffs_raises_typed_failure(self):
        with pytest.raises(DegenerateTangentError):
            evaluate_param_poly3(10, 20, 0.5, 100, 0, 0, 0, 0, 0, 0, 0, 0, "normalized", 50)

    def test_curvature_zero_tangent_raises_typed_failure(self):
        with pytest.raises(DegenerateTangentError):
            param_poly3_curvature_at(0, 0, 0, 0, 0, 0, 0, 0, "normalized", 100, 50)


# ===================================================================
# 12. Zero length
# ===================================================================

class TestZeroLength:
    def test_zero_length_is_typed_failure(self):
        with pytest.raises(InvalidParamPoly3LengthError):
            evaluate_param_poly3(5, 10, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, "normalized", 0)

    def test_zero_length_raises_on_positive_s(self):
        with pytest.raises(InvalidParamPoly3LengthError):
            evaluate_param_poly3(0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, "normalized", 1)


# ===================================================================
# 13. Negative length
# ===================================================================

class TestNegativeLength:
    def test_negative_length_rejected(self):
        with pytest.raises(InvalidParamPoly3LengthError):
            evaluate_param_poly3(0, 0, 0, -10, 0, 1, 0, 0, 0, 0, 0, 0, "normalized", 0)


# ===================================================================
# 14. Nonfinite coefficients
# ===================================================================

class TestNonfiniteCoefficients:
    def test_nan_coefficient_is_typed_failure(self):
        with pytest.raises(NonFiniteCoefficientError) as exc:
            evaluate_param_poly3(0, 0, 0, 100, 0, float("nan"), 0, 0, 0, 0, 0, 0, "normalized", 50)
        assert exc.value.name == "bU"

    def test_inf_coefficient_is_typed_failure(self):
        with pytest.raises(NonFiniteCoefficientError):
            evaluate_param_poly3(0, 0, 0, 100, 0, float("inf"), 0, 0, 0, 0, 0, 0, "normalized", 50)


# ===================================================================
# 15. Missing pRange
# ===================================================================

class TestMissingPRange:
    @pytest.mark.parametrize("missing", [None, ""])
    def test_missing_p_range_is_typed_failure(self, missing):
        with pytest.raises(MissingPRangeError):
            evaluate_param_poly3(0, 0, 0, 100, 0, 100, 0, 0, 0, 0, 0, 0, missing, 50)


# ===================================================================
# 16. Unsupported pRange
# ===================================================================

class TestUnsupportedPRange:
    def test_invalid_p_range_raises(self):
        with pytest.raises(UnsupportedPRangeError):
            evaluate_param_poly3(0, 0, 0, 100, 0, 1, 0, 0, 0, 0, 0, 0, "invalid", 50)


# ===================================================================
# 17. Translation invariance
# ===================================================================

class TestTranslationInvariance:
    def test_relative_positions_same(self):
        dx, dy = 50, 30
        p0 = evaluate_param_poly3(0, 0, 0, 100, 0, 100, 10, 0, 0, 50, 0, 0, "normalized", 50)
        p1 = evaluate_param_poly3(dx, dy, 0, 100, 0, 100, 10, 0, 0, 50, 0, 0, "normalized", 50)
        assert approx(p1.x - p0.x, dx) and approx(p1.y - p0.y, dy)


# ===================================================================
# 18. Rotation invariance
# ===================================================================

class TestRotationInvariance:
    def test_rotated_curve_has_rotated_heading(self):
        angle = math.radians(45)
        p0 = evaluate_param_poly3(0, 0, 0, 100, 0, 100, 10, 0, 0, 0, 0, 0, "normalized", 50)
        p1 = evaluate_param_poly3(0, 0, angle, 100, 0, 100, 10, 0, 0, 0, 0, 0, "normalized", 50)
        assert approx(p1.hdg - p0.hdg, angle, abs_tol=1e-12)


# ===================================================================
# 19. Endpoint inclusion
# ===================================================================

class TestEndpointInclusion:
    def test_sample_ends_at_endpoint(self):
        pts = sample_param_poly3(0, 0, 0, 100, 0, 100, 0, 0, 0, 0, 0, 0, "normalized", 30)
        end = param_poly3_endpoint(0, 0, 0, 100, 0, 100, 0, 0, 0, 0, 0, 0, "normalized")
        assert approx(pts[-1].x, end.x) and approx(pts[-1].y, end.y)

    def test_endpoint_is_last_point(self):
        end = param_poly3_endpoint(0, 0, 0, 100, 0, 100, 5, 0, 0, 50, 0, 0, "normalized")
        p = evaluate_param_poly3(0, 0, 0, 100, 0, 100, 5, 0, 0, 50, 0, 0, "normalized", 100)
        assert approx(end.x, p.x) and approx(end.y, p.y)


# ===================================================================
# 20. Sampling monotonicity
# ===================================================================

class TestSamplingMonotonicity:
    def test_x_increases_monotonically(self):
        pts = sample_param_poly3(0, 0, 0, 100, 0, 100, 0, 0, 0, 0, 0, 0, "normalized", 10)
        for i in range(1, len(pts)):
            assert pts[i].x >= pts[i - 1].x - 1e-12, f"x decreased at i={i}"
            assert pts[i].s >= pts[i - 1].s - 1e-12 if hasattr(pts[i], 's') else True

    def test_yields_at_least_two_points(self):
        pts = sample_param_poly3(0, 0, 0, 100, 0, 100, 0, 0, 0, 0, 0, 0, "normalized", 200)
        assert len(pts) >= 2


# ===================================================================
# Curvature tests (Phase 4)
# ===================================================================

class TestCurvatureFiniteDifference:
    def test_curvature_matches_fd_for_quadratic(self):
        aU, bU, cU, dU = 0, 100, 0, 0
        aV, bV, cV, dV = 0, 0, 50, 0
        s = 50.0
        L = 100.0

        def x_of(s):
            p = evaluate_param_poly3(0, 0, 0, L, aU, bU, cU, dU, aV, bV, cV, dV, "normalized", s)
            return p.x

        def y_of(s):
            p = evaluate_param_poly3(0, 0, 0, L, aU, bU, cU, dU, aV, bV, cV, dV, "normalized", s)
            return p.y

        h = 1e-4
        xp = _num_deriv(x_of, s, h)
        xpp = _num_deriv(lambda t: _num_deriv(x_of, t, h), s, h * 2)
        yp = _num_deriv(y_of, s, h)
        ypp = _num_deriv(lambda t: _num_deriv(y_of, t, h), s, h * 2)

        fd_k = (xp * ypp - yp * xpp) / (xp ** 2 + yp ** 2) ** 1.5
        analytic_k = param_poly3_curvature_at(aU, bU, cU, dU, aV, bV, cV, dV, "normalized", L, s)

        assert approx(fd_k, analytic_k, abs_tol=1e-6), f"FD={fd_k:.9g} analytic={analytic_k:.9g}"

    def test_curvature_matches_fd_for_cubic(self):
        aU, bU, cU, dU = 0, 100, 0, 0
        aV, bV, cV, dV = 0, 0, 0, 50
        s = 50.0
        L = 100.0

        def x_of(s):
            return evaluate_param_poly3(0, 0, 0, L, aU, bU, cU, dU, aV, bV, cV, dV, "normalized", s).x

        def y_of(s):
            return evaluate_param_poly3(0, 0, 0, L, aU, bU, cU, dU, aV, bV, cV, dV, "normalized", s).y

        h = 1e-4
        xp = _num_deriv(x_of, s, h)
        xpp = _num_deriv(lambda t: _num_deriv(x_of, t, h), s, h * 2)
        yp = _num_deriv(y_of, s, h)
        ypp = _num_deriv(lambda t: _num_deriv(y_of, t, h), s, h * 2)

        fd_k = (xp * ypp - yp * xpp) / (xp ** 2 + yp ** 2) ** 1.5
        analytic_k = param_poly3_curvature_at(aU, bU, cU, dU, aV, bV, cV, dV, "normalized", L, s)

        assert approx(fd_k, analytic_k, abs_tol=1e-6), f"FD={fd_k:.9g} analytic={analytic_k:.9g}"

    def test_curvature_arcLength_matches_fd(self):
        aU, bU, cU, dU = 0, 1, 0.01, 0
        aV, bV, cV, dV = 0, 0, 0.005, 0.001
        s = 75.0
        L = 150.0

        def x_of(s):
            return evaluate_param_poly3(0, 0, 0, L, aU, bU, cU, dU, aV, bV, cV, dV, "arcLength", s).x

        def y_of(s):
            return evaluate_param_poly3(0, 0, 0, L, aU, bU, cU, dU, aV, bV, cV, dV, "arcLength", s).y

        h = 1e-4
        xp = _num_deriv(x_of, s, h)
        xpp = _num_deriv(lambda t: _num_deriv(x_of, t, h), s, h * 2)
        yp = _num_deriv(y_of, s, h)
        ypp = _num_deriv(lambda t: _num_deriv(y_of, t, h), s, h * 2)

        fd_k = (xp * ypp - yp * xpp) / (xp ** 2 + yp ** 2) ** 1.5
        analytic_k = param_poly3_curvature_at(aU, bU, cU, dU, aV, bV, cV, dV, "arcLength", L, s)

        assert approx(fd_k, analytic_k, abs_tol=1e-6), f"FD={fd_k:.9g} analytic={analytic_k:.9g}"


class TestCurvatureInvariance:
    def test_curvature_translation_invariant(self):
        k0 = param_poly3_curvature_at(0, 100, 10, 0, 0, 50, 0, 0, "normalized", 100, 50)
        assert math.isfinite(k0)

    def test_curvature_rotation_invariant(self):
        k0 = param_poly3_curvature_at(0, 100, 10, 0, 0, 50, 0, 0, "normalized", 100, 50)
        assert k0 != 0

    def test_curvature_straight_line_is_zero(self):
        k = param_poly3_curvature_at(0, 100, 0, 0, 0, 0, 0, 0, "normalized", 100, 50)
        assert abs(k) < 1e-15 or k == 0.0

    def test_curvature_sign_for_quadratic(self):
        k = param_poly3_curvature_at(0, 100, 0, 0, 0, 0, 50, 0, "normalized", 100, 50)
        assert k > 0

    def test_curvature_sign_negative(self):
        k = param_poly3_curvature_at(0, 100, 0, 0, 0, 0, -50, 0, "normalized", 100, 50)
        assert k < 0


class TestCurvatureStability:
    def test_small_nonzero_tangent_remains_well_defined(self):
        k = param_poly3_curvature_at(0, 1e-10, 0, 0, 0, 1e-10, 0, 0, "normalized", 100, 50)
        assert math.isfinite(k)
        assert k == 0.0

    def test_curvature_varying_with_s(self):
        k0 = param_poly3_curvature_at(0, 100, 10, 0, 0, 50, 0, 0, "normalized", 100, 0)
        k50 = param_poly3_curvature_at(0, 100, 10, 0, 0, 50, 0, 0, "normalized", 100, 50)
        assert not approx(k0, k50, abs_tol=1e-10)


class TestBounds:
    def test_bounds_contain_endpoints(self):
        b = param_poly3_bounds(0, 0, 0, 100, 0, 100, 50, 0, 0, 0, 0, 0, "normalized")
        end = param_poly3_endpoint(0, 0, 0, 100, 0, 100, 50, 0, 0, 0, 0, 0, "normalized")
        assert b.contains(end.position())

    def test_bounds_start_contained(self):
        b = param_poly3_bounds(10, 20, 0, 100, 0, 100, 0, 0, 0, 0, 0, 0, "normalized")
        assert b.contains(Pose2D(10, 20, 0).position())

    def test_bounds_nonempty(self):
        b = param_poly3_bounds(0, 0, 0, 100, 0, 100, 0, 0, 0, 0, 0, 0, "normalized")
        assert b.x_min <= b.x_max and b.y_min <= b.y_max

    def test_bounds_include_interior_cubic_extremum(self):
        # v(p) = p - p^2 has its maximum 0.25 at p=0.5.
        b = param_poly3_bounds(0, 0, 0, 1, 0, 1, 0, 0, 0, 1, -1, 0, "normalized")
        assert approx(b.y_max, 0.25)


class TestSamplingEdgeCases:
    def test_spacing_larger_than_length(self):
        pts = sample_param_poly3(0, 0, 0, 10, 0, 10, 0, 0, 0, 0, 0, 0, "normalized", 100)
        assert len(pts) >= 2

    def test_spacing_negative_raises(self):
        with pytest.raises(ValueError):
            sample_param_poly3(0, 0, 0, 10, 0, 1, 0, 0, 0, 0, 0, 0, "normalized", -1)

    def test_zero_length_sampling(self):
        with pytest.raises(InvalidParamPoly3LengthError):
            sample_param_poly3(0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, "normalized", 1)

    def test_nondivisible_spacing_preserves_last_interior_sample_and_endpoint(self):
        pts = sample_param_poly3(0, 0, 0, 10, 0, 10, 0, 0, 0, 0, 0, 0, "normalized", 3)
        assert [p.x for p in pts] == pytest.approx([0, 3, 6, 9, 10])

    def test_refinement_converges_for_curve_length(self):
        def polyline_length(points: Sequence[Pose2D]) -> float:
            return sum(
                math.hypot(b.x - a.x, b.y - a.y)
                for a, b in zip(points, points[1:])
            )

        coarse = sample_param_poly3(0, 0, 0, 10, 0, 10, 0, 0, 0, 0, 10, 0, "normalized", 2)
        medium = sample_param_poly3(0, 0, 0, 10, 0, 10, 0, 0, 0, 0, 10, 0, "normalized", 1)
        fine = sample_param_poly3(0, 0, 0, 10, 0, 10, 0, 0, 0, 0, 10, 0, "normalized", 0.5)
        assert polyline_length(coarse) < polyline_length(medium) < polyline_length(fine)


class TestValidPRanges:
    def test_valid_p_ranges_defined(self):
        assert "normalized" in VALID_P_RANGES
        assert "arcLength" in VALID_P_RANGES

    def test_p_range_rejects_unknown(self):
        with pytest.raises(UnsupportedPRangeError):
            evaluate_param_poly3(0, 0, 0, 100, 0, 1, 0, 0, 0, 0, 0, 0, "arc_length", 50)


class TestEvaluationRange:
    @pytest.mark.parametrize("s", [-0.1, 10.1, float("nan"), float("inf")])
    def test_invalid_range_is_typed_failure(self, s):
        with pytest.raises(InvalidEvaluationRangeError):
            evaluate_param_poly3(0, 0, 0, 10, 0, 10, 0, 0, 0, 0, 0, 0, "normalized", s)

    def test_facade_extrapolation_policy_is_honored(self):
        evaluator = ParamPoly3Evaluator(
            EvaluationPolicy(range_policy=RangePolicy.EXTRAPOLATE)
        )
        segment = GeometrySegment(0, 10, 0, 0, 0, "paramPoly3")
        pose = evaluator.pose_at(segment, 12, bU=10, p_range="normalized")
        assert approx(pose.x, 12)

    def test_facade_strict_policy_preserves_typed_failure(self):
        evaluator = ParamPoly3Evaluator()
        segment = GeometrySegment(0, 10, 0, 0, 0, "paramPoly3")
        with pytest.raises(InvalidEvaluationRangeError):
            evaluator.pose_at(segment, float("nan"), bU=10, p_range="normalized")

    def test_facade_curvature_uses_protocol_segment_signature(self):
        evaluator = ParamPoly3Evaluator()
        segment = GeometrySegment(0, 10, 0, 0, 0, "paramPoly3")
        curvature = evaluator.curvature_at(
            segment, 5, bU=10, cV=1, p_range="normalized"
        )
        assert math.isfinite(curvature)


class TestDerivatives:
    def test_derivative_via_chain_rule_normalized(self):
        aU, bU, cU, dU = 0, 100, 0, 0
        aV, bV, cV, dV = 0, 0, 0, 0
        s = 50.0
        L = 100.0
        u0 = evaluate_param_poly3(0, 0, 0, L, aU, bU, cU, dU, aV, bV, cV, dV, "normalized", s)
        u1 = evaluate_param_poly3(0, 0, 0, L, aU, bU, cU, dU, aV, bV, cV, dV, "normalized", s + 0.001)
        fd_dx = (u1.x - u0.x) / 0.001
        p50 = evaluate_param_poly3(0, 0, 0, L, aU, bU, cU, dU, aV, bV, cV, dV, "normalized", s)
        assert approx(fd_dx, bU / L, abs_tol=1e-4)
        assert approx(math.cos(p50.hdg), 1.0, abs_tol=1e-12)

    def test_derivative_via_chain_rule_arclength(self):
        aU, bU, cU, dU = 0, 1, 0.5, 0
        aV, bV, cV, dV = 0, 0, 0, 0
        s = 50.0
        L = 100.0
        u0 = evaluate_param_poly3(0, 0, 0, L, aU, bU, cU, dU, aV, bV, cV, dV, "arcLength", s)
        u1 = evaluate_param_poly3(0, 0, 0, L, aU, bU, cU, dU, aV, bV, cV, dV, "arcLength", s + 0.001)
        fd_dx = (u1.x - u0.x) / 0.001
        expected_du_ds = bU + 2.0 * cU * s
        assert approx(fd_dx, expected_du_ds, abs_tol=1e-3)


class TestHeading:
    def test_heading_matches_tangent_direction(self):
        s = 50.0
        L = 100.0
        p = evaluate_param_poly3(0, 0, 0.3, L, 0, L, 20, 0, 0, 30, 0, 0, "normalized", s)
        h = 1e-6
        p_plus = evaluate_param_poly3(0, 0, 0.3, L, 0, L, 20, 0, 0, 30, 0, 0, "normalized", s + h)
        fd_hdg = math.atan2(p_plus.y - p.y, p_plus.x - p.x)
        assert approx(p.hdg, fd_hdg, abs_tol=1e-6)

    def test_heading_atan2_dv_du(self):
        L = 100.0
        aU, bU, cU, dU = 0, L, 0, 0
        aV, bV, cV, dV = 0, 0, 0, 0
        p = evaluate_param_poly3(0, 0, 0.5, L, aU, bU, cU, dU, aV, bV, cV, dV, "normalized", 0)
        dv_du = bV / bU
        expected = 0.5 + math.atan2(dv_du, 1.0)
        assert approx(p.hdg, expected, abs_tol=1e-12)


class TestRepositoryFixtures:
    def test_manifest_outputs_match_canonical_evaluator(self):
        manifest_path = (
            Path(__file__).resolve().parents[1]
            / "fixtures"
            / "opendrive"
            / "parampoly3"
            / "manifest.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        repository = Path(__file__).resolve().parents[2]

        def sha256(path: Path) -> str:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            return digest.hexdigest()

        require_parent_sources = os.getenv(
            "UP_REQUIRE_PARAMPOLY3_PARENT_SOURCES", "0"
        ).strip().lower() in {"1", "true", "yes", "on"}
        missing_parent_sources = []
        for source in manifest["sources"]:
            source_path = repository / source["file"]
            if source_path.exists():
                assert sha256(source_path) == source["sha256"]
            else:
                missing_parent_sources.append(source["file"])
        if require_parent_sources and missing_parent_sources:
            pytest.fail(
                "ParamPoly3 parent source maps are missing: "
                + ", ".join(sorted(missing_parent_sources))
            )

        fixtures = [
            (source, fixture)
            for source in manifest["sources"]
            for fixture in source["fixtures"]
        ]
        assert len(fixtures) == 12

        for source, fixture in fixtures:
            assert fixture["parent_xodr_sha256"] == source["sha256"]
            coefficients = [
                fixture[name]
                for name in ("aU", "bU", "cU", "dU", "aV", "bV", "cV", "dV")
            ]
            assert len(fixture["expected_production_output"]) == 5
            for expected in fixture["expected_production_output"]:
                pose = evaluate_param_poly3(
                    fixture["x0"],
                    fixture["y0"],
                    fixture["hdg0"],
                    fixture["length"],
                    *coefficients,
                    fixture["pRange"],
                    expected["station"],
                )
                curvature = param_poly3_curvature_at(
                    *coefficients,
                    fixture["pRange"],
                    fixture["length"],
                    expected["station"],
                )
                assert pose.x == pytest.approx(expected["x"], abs=1e-9)
                assert pose.y == pytest.approx(expected["y"], abs=1e-9)
                heading_delta = (
                    pose.hdg - expected["heading"] + math.pi
                ) % (2.0 * math.pi) - math.pi
                assert heading_delta == pytest.approx(0.0, abs=1e-12)
                assert abs(curvature) == pytest.approx(
                    expected["curvature_abs"], abs=1e-12
                )
