from __future__ import annotations
import math
from typing import Sequence

from opendrive_geometry.model import Pose2D, Bounds2D, Vec2
from opendrive_geometry.errors import (
    DegenerateTangentError,
    GeometryOutOfRangeError,
    InvalidEvaluationRangeError,
    InvalidParamPoly3LengthError,
    MissingPRangeError,
    NonFiniteCoefficientError,
    UnsupportedPRangeError,
)

EPS = 1e-12


def evaluate_line(
    x0: float, y0: float, hdg0: float, length: float, s: float
) -> Pose2D:
    if s < -EPS or s > length + EPS:
        raise GeometryOutOfRangeError(s, 0.0, length)
    s_clamped = max(0.0, min(s, length))
    return Pose2D(
        x=x0 + s_clamped * math.cos(hdg0),
        y=y0 + s_clamped * math.sin(hdg0),
        hdg=hdg0,
    )


def evaluate_arc(
    x0: float, y0: float, hdg0: float, length: float, curvature: float, s: float
) -> Pose2D:
    if s < -EPS or s > length + EPS:
        raise GeometryOutOfRangeError(s, 0.0, length)
    s_clamped = max(0.0, min(s, length))
    if abs(curvature) < EPS:
        return evaluate_line(x0, y0, hdg0, length, s_clamped)
    hdg = hdg0 + s_clamped * curvature
    inv_c = 1.0 / curvature
    return Pose2D(
        x=x0 + (math.sin(hdg) - math.sin(hdg0)) * inv_c,
        y=y0 + (math.cos(hdg0) - math.cos(hdg)) * inv_c,
        hdg=hdg,
    )


def curvature_line() -> float:
    return 0.0


def curvature_arc(curvature: float) -> float:
    return curvature


def sample_line(
    x0: float,
    y0: float,
    hdg0: float,
    length: float,
    spacing_m: float,
) -> Sequence[Pose2D]:
    if spacing_m <= 0:
        raise ValueError(f"spacing_m must be positive, got {spacing_m}")
    if length <= 0:
        raise ValueError(f"length must be positive, got {length}")
    n = max(1, int(length / spacing_m))
    poses = [
        evaluate_line(x0, y0, hdg0, length, min(i * spacing_m, length))
        for i in range(n + 1)
    ]
    if poses[-1].x != x0 + length * math.cos(hdg0) or poses[-1].y != y0 + length * math.sin(hdg0):
        poses[-1] = evaluate_line(x0, y0, hdg0, length, length)
    return poses


def sample_arc(
    x0: float,
    y0: float,
    hdg0: float,
    length: float,
    curvature: float,
    spacing_m: float,
) -> Sequence[Pose2D]:
    if spacing_m <= 0:
        raise ValueError(f"spacing_m must be positive, got {spacing_m}")
    if length <= 0:
        raise ValueError(f"length must be positive, got {length}")
    n = max(1, int(length / spacing_m))
    poses = [
        evaluate_arc(x0, y0, hdg0, length, curvature, min(i * spacing_m, length))
        for i in range(n + 1)
    ]
    if abs(curvature) < EPS:
        end = evaluate_line(x0, y0, hdg0, length, length)
    else:
        end = evaluate_arc(x0, y0, hdg0, length, curvature, length)
    if poses[-1].x != end.x or poses[-1].y != end.y:
        poses[-1] = end
    return poses


def line_bounds(
    x0: float, y0: float, hdg0: float, length: float
) -> Bounds2D:
    x1 = x0 + length * math.cos(hdg0)
    y1 = y0 + length * math.sin(hdg0)
    return Bounds2D(
        x_min=min(x0, x1),
        x_max=max(x0, x1),
        y_min=min(y0, y1),
        y_max=max(y0, y1),
    )


def arc_bounds(
    x0: float, y0: float, hdg0: float, length: float, curvature: float
) -> Bounds2D:
    poses = sample_arc(x0, y0, hdg0, length, curvature, length / 64.0)
    return Bounds2D.from_points([p.position() for p in poses])


# ============================================================
# ParamPoly3
# ============================================================

VALID_P_RANGES = frozenset({"normalized", "arcLength"})


def _validate_param_poly3(
    length: float,
    p_range: str | None,
    coefficients: Sequence[tuple[str, float]],
) -> str:
    if p_range is None or p_range == "":
        raise MissingPRangeError()
    if p_range not in VALID_P_RANGES:
        raise UnsupportedPRangeError(p_range)
    if not math.isfinite(length) or length <= 0.0:
        raise InvalidParamPoly3LengthError(length)
    for name, value in coefficients:
        if not math.isfinite(value):
            raise NonFiniteCoefficientError(name, value)
    return p_range


def _validate_evaluation_s(s: float, length: float, allow_extrapolation: bool) -> float:
    if not math.isfinite(s):
        raise InvalidEvaluationRangeError(s, 0.0, length)
    if not allow_extrapolation and (s < -EPS or s > length + EPS):
        raise InvalidEvaluationRangeError(s, 0.0, length)
    if allow_extrapolation:
        return s
    return max(0.0, min(s, length))


def _p_to_param(p_range: str, s: float, length: float) -> tuple[float, float]:
    """Convert arc-length s to parameter p and dp/ds."""
    if p_range == "arcLength":
        return s, 1.0
    if p_range == "normalized":
        return s / length, 1.0 / length
    raise UnsupportedPRangeError(p_range)


def _eval_param_poly3_uv(
    p: float,
    aU: float, bU: float, cU: float, dU: float,
    aV: float, bV: float, cV: float, dV: float,
) -> tuple[float, float, float, float, float, float]:
    """Compute (u, v, du_dp, dv_dp, ddu_dp, ddv_dp) at parameter p."""
    p2 = p * p
    p3 = p2 * p
    u = aU + bU * p + cU * p2 + dU * p3
    v = aV + bV * p + cV * p2 + dV * p3
    du_dp = bU + 2.0 * cU * p + 3.0 * dU * p2
    dv_dp = bV + 2.0 * cV * p + 3.0 * dV * p2
    ddu_dp = 2.0 * cU + 6.0 * dU * p
    ddv_dp = 2.0 * cV + 6.0 * dV * p
    return u, v, du_dp, dv_dp, ddu_dp, ddv_dp


def evaluate_param_poly3(
    x0: float, y0: float, hdg0: float, length: float,
    aU: float, bU: float, cU: float, dU: float,
    aV: float, bV: float, cV: float, dV: float,
    p_range: str | None,
    s: float,
    *,
    allow_extrapolation: bool = False,
) -> Pose2D:
    coefficients = (
        ("aU", aU), ("bU", bU), ("cU", cU), ("dU", dU),
        ("aV", aV), ("bV", bV), ("cV", cV), ("dV", dV),
    )
    valid_p_range = _validate_param_poly3(length, p_range, coefficients)
    s_evaluated = _validate_evaluation_s(s, length, allow_extrapolation)
    p, dp_ds = _p_to_param(valid_p_range, s_evaluated, length)
    u, v, du_dp, dv_dp, _ddu, _ddv = _eval_param_poly3_uv(p, aU, bU, cU, dU, aV, bV, cV, dV)
    cos0 = math.cos(hdg0)
    sin0 = math.sin(hdg0)
    x = x0 + cos0 * u - sin0 * v
    y = y0 + sin0 * u + cos0 * v
    du_ds = du_dp * dp_ds
    dv_ds = dv_dp * dp_ds
    if math.hypot(du_ds, dv_ds) == 0.0:
        raise DegenerateTangentError(s_evaluated)
    hdg = hdg0 + math.atan2(dv_ds, du_ds)
    return Pose2D(x=x, y=y, hdg=hdg)


def param_poly3_curvature_at(
    aU: float, bU: float, cU: float, dU: float,
    aV: float, bV: float, cV: float, dV: float,
    p_range: str | None,
    length: float,
    s: float,
    *,
    allow_extrapolation: bool = False,
) -> float:
    coefficients = (
        ("aU", aU), ("bU", bU), ("cU", cU), ("dU", dU),
        ("aV", aV), ("bV", bV), ("cV", cV), ("dV", dV),
    )
    valid_p_range = _validate_param_poly3(length, p_range, coefficients)
    s_evaluated = _validate_evaluation_s(s, length, allow_extrapolation)
    p, dp_ds = _p_to_param(valid_p_range, s_evaluated, length)
    _u, _v, du_dp, dv_dp, ddu_dp, ddv_dp = _eval_param_poly3_uv(p, aU, bU, cU, dU, aV, bV, cV, dV)

    du_ds = du_dp * dp_ds
    dv_ds = dv_dp * dp_ds
    ddu_ds = ddu_dp * dp_ds * dp_ds
    ddv_ds = ddv_dp * dp_ds * dp_ds

    denom = (du_ds * du_ds + dv_ds * dv_ds) ** 1.5
    if denom == 0.0:
        raise DegenerateTangentError(s_evaluated)
    return (du_ds * ddv_ds - dv_ds * ddu_ds) / denom


def param_poly3_endpoint(
    x0: float, y0: float, hdg0: float, length: float,
    aU: float, bU: float, cU: float, dU: float,
    aV: float, bV: float, cV: float, dV: float,
    p_range: str | None,
) -> Pose2D:
    return evaluate_param_poly3(x0, y0, hdg0, length, aU, bU, cU, dU, aV, bV, cV, dV, p_range, length)


def sample_param_poly3(
    x0: float, y0: float, hdg0: float, length: float,
    aU: float, bU: float, cU: float, dU: float,
    aV: float, bV: float, cV: float, dV: float,
    p_range: str | None,
    spacing_m: float,
) -> Sequence[Pose2D]:
    if not math.isfinite(spacing_m) or spacing_m <= 0:
        raise ValueError(f"spacing_m must be positive, got {spacing_m}")
    coefficients = (
        ("aU", aU), ("bU", bU), ("cU", cU), ("dU", dU),
        ("aV", aV), ("bV", bV), ("cV", cV), ("dV", dV),
    )
    _validate_param_poly3(length, p_range, coefficients)
    interior_count = int(length / spacing_m)
    sample_s = [i * spacing_m for i in range(interior_count + 1)]
    if not math.isclose(sample_s[-1], length, rel_tol=0.0, abs_tol=EPS):
        sample_s.append(length)
    else:
        sample_s[-1] = length
    poses = [
        evaluate_param_poly3(
            x0, y0, hdg0, length,
            aU, bU, cU, dU, aV, bV, cV, dV,
            p_range, s,
        )
        for s in sample_s
    ]
    end = param_poly3_endpoint(x0, y0, hdg0, length, aU, bU, cU, dU, aV, bV, cV, dV, p_range)
    poses[-1] = end
    return poses


def param_poly3_bounds(
    x0: float, y0: float, hdg0: float, length: float,
    aU: float, bU: float, cU: float, dU: float,
    aV: float, bV: float, cV: float, dV: float,
    p_range: str | None,
) -> Bounds2D:
    coefficients = (
        ("aU", aU), ("bU", bU), ("cU", cU), ("dU", dU),
        ("aV", aV), ("bV", bV), ("cV", cV), ("dV", dV),
    )
    valid_p_range = _validate_param_poly3(length, p_range, coefficients)
    p_end = 1.0 if valid_p_range == "normalized" else length
    cos0 = math.cos(hdg0)
    sin0 = math.sin(hdg0)

    def derivative_roots(b: float, c: float, d: float) -> list[float]:
        qa = 3.0 * d
        qb = 2.0 * c
        qc = b
        if qa == 0.0:
            return [] if qb == 0.0 else [-qc / qb]
        discriminant = qb * qb - 4.0 * qa * qc
        if discriminant < 0.0:
            return []
        root = math.sqrt(discriminant)
        return [(-qb - root) / (2.0 * qa), (-qb + root) / (2.0 * qa)]

    x_coeffs = (
        x0 + cos0 * aU - sin0 * aV,
        cos0 * bU - sin0 * bV,
        cos0 * cU - sin0 * cV,
        cos0 * dU - sin0 * dV,
    )
    y_coeffs = (
        y0 + sin0 * aU + cos0 * aV,
        sin0 * bU + cos0 * bV,
        sin0 * cU + cos0 * cV,
        sin0 * dU + cos0 * dV,
    )
    candidates = {0.0, p_end}
    for axis_coeffs in (x_coeffs, y_coeffs):
        for root in derivative_roots(*axis_coeffs[1:]):
            if 0.0 < root < p_end:
                candidates.add(root)

    xs = [
        x_coeffs[0] + x_coeffs[1] * p + x_coeffs[2] * p * p + x_coeffs[3] * p * p * p
        for p in candidates
    ]
    ys = [
        y_coeffs[0] + y_coeffs[1] * p + y_coeffs[2] * p * p + y_coeffs[3] * p * p * p
        for p in candidates
    ]
    return Bounds2D(min(xs), max(xs), min(ys), max(ys))


# --------------------------------------------------------------------------
# Spiral (clothoid) — OpenDRIVE <spiral> with curvStart/curvEnd.
#
# Heading evolves linearly: hdg(s) = hdg0 + curvStart*s + k*s**2/2, with
# k = (curvEnd - curvStart)/length.  Position requires integrating
# (cos hdg(s), sin hdg(s)) over s — no closed form without Fresnel
# integrals, so we use adaptive Simpson integration with an explicit
# error bound (no biased fixed-step Euler approximation).
# --------------------------------------------------------------------------

#: default absolute arc-length tolerance for adaptive spiral integration
SPIRAL_ARC_TOL = 1e-9
#: maximum adaptive subdivision depth (fail-closed guard against non-convergence)
SPIRAL_MAX_DEPTH = 24


def _spiral_heading(hdg0: float, curv_start: float, curv_end: float,
                    length: float, s: float) -> float:
    k = (curv_end - curv_start) / length
    return hdg0 + curv_start * s + 0.5 * k * s * s


def _spiral_integrand_x(s: float, hdg0: float, curv_start: float,
                        curv_end: float, length: float) -> float:
    return math.cos(_spiral_heading(hdg0, curv_start, curv_end, length, s))


def _spiral_integrand_y(s: float, hdg0: float, curv_start: float,
                        curv_end: float, length: float) -> float:
    return math.sin(_spiral_heading(hdg0, curv_start, curv_end, length, s))


def _adaptive_simpson(f, a: float, b: float, tol: float, max_depth: int,
                      hdg0: float, curv_start: float, curv_end: float,
                      length: float, depth: int = 0) -> float:
    """Adaptive Simpson integration with error control; raises on divergence."""
    h = (b - a) * 0.5
    m = a + h
    fa = f(a, hdg0, curv_start, curv_end, length)
    fm = f(m, hdg0, curv_start, curv_end, length)
    fb = f(b, hdg0, curv_start, curv_end, length)
    whole = h / 3.0 * (fa + 4.0 * fm + fb)
    left = (m - a) / 6.0 * (fa + 4.0 * f((a + m) * 0.5, hdg0, curv_start, curv_end, length) + fm)
    right = (b - m) / 6.0 * (fm + 4.0 * f((m + b) * 0.5, hdg0, curv_start, curv_end, length) + fb)
    err = abs(left + right - whole)
    if err <= 15.0 * tol or depth >= max_depth:
        if depth >= max_depth and err > 15.0 * tol * 64.0:
            raise ArithmeticError(
                f"spiral adaptive integration failed to converge at s in [{a:.6g},{b:.6g}]")
        return left + right + (left + right - whole) / 15.0
    return (_adaptive_simpson(f, a, m, tol * 0.5, max_depth, hdg0, curv_start, curv_end, length, depth + 1)
            + _adaptive_simpson(f, m, b, tol * 0.5, max_depth, hdg0, curv_start, curv_end, length, depth + 1))


def _validate_spiral(length: float, curv_start: float, curv_end: float) -> None:
    if not math.isfinite(length) or length <= 0.0:
        raise ValueError(f"spiral length must be finite and positive, got {length!r}")
    if not (math.isfinite(curv_start) and math.isfinite(curv_end)):
        raise ValueError("spiral curvStart/curvEnd must be finite")


def _spiral_integrate_x_y(s0: float, s1: float, hdg0: float, curv_start: float,
                          curv_end: float, length: float, tol: float = SPIRAL_ARC_TOL) -> tuple[float, float]:
    """Integrate (cos, sin) of heading from s0 to s1 (s0 < s1) with error control."""
    if not (0.0 <= s0 <= s1 <= length):
        raise InvalidEvaluationRangeError(s1, s0, length)
    dx = _adaptive_simpson(_spiral_integrand_x, s0, s1, tol, SPIRAL_MAX_DEPTH,
                           hdg0, curv_start, curv_end, length)
    dy = _adaptive_simpson(_spiral_integrand_y, s0, s1, tol, SPIRAL_MAX_DEPTH,
                           hdg0, curv_start, curv_end, length)
    return dx, dy


def evaluate_spiral(x0: float, y0: float, hdg0: float, length: float,
                    curv_start: float, curv_end: float, s: float,
                    *,
                    allow_extrapolation: bool = False,
                    tol: float = SPIRAL_ARC_TOL) -> Pose2D:
    """Pose at arc length ``s`` along a clothoid (adaptive integration)."""
    _validate_spiral(length, curv_start, curv_end)
    s_eval = _validate_evaluation_s(s, length, allow_extrapolation)
    dx, dy = _spiral_integrate_x_y(0.0, s_eval, hdg0, curv_start, curv_end, length, tol)
    return Pose2D(
        x=x0 + dx,
        y=y0 + dy,
        hdg=_spiral_heading(hdg0, curv_start, curv_end, length, s_eval),
    )


def spiral_curvature_at(s: float, length: float, curv_start: float,
                        curv_end: float) -> float:
    _validate_spiral(length, curv_start, curv_end)
    if not math.isfinite(s):
        raise InvalidEvaluationRangeError(s, 0.0, length)
    k = (curv_end - curv_start) / length
    return curv_start + k * s


def spiral_endpoint(x0: float, y0: float, hdg0: float, length: float,
                    curv_start: float, curv_end: float,
                    tol: float = SPIRAL_ARC_TOL) -> Pose2D:
    return evaluate_spiral(x0, y0, hdg0, length, curv_start, curv_end, length, tol=tol)


def sample_spiral(x0: float, y0: float, hdg0: float, length: float,
                  curv_start: float, curv_end: float, spacing_m: float,
                  tol: float = SPIRAL_ARC_TOL) -> list[Pose2D]:
    """Uniform arc-length sampling; each interval integrated adaptively."""
    if not math.isfinite(spacing_m) or spacing_m <= 0:
        raise ValueError(f"spacing_m must be positive, got {spacing_m}")
    _validate_spiral(length, curv_start, curv_end)
    interior = int(length / spacing_m)
    sample_s = [i * spacing_m for i in range(interior + 1)]
    if not math.isclose(sample_s[-1], length, rel_tol=0.0, abs_tol=EPS):
        sample_s.append(length)
    else:
        sample_s[-1] = length
    poses = []
    acc_x, acc_y = 0.0, 0.0
    prev = 0.0
    for s in sample_s:
        dx, dy = _spiral_integrate_x_y(prev, s, hdg0, curv_start, curv_end, length, tol)
        acc_x += dx
        acc_y += dy
        poses.append(Pose2D(x=x0 + acc_x, y=y0 + acc_y,
                            hdg=_spiral_heading(hdg0, curv_start, curv_end, length, s)))
        prev = s
    return poses


def spiral_bounds(x0: float, y0: float, hdg0: float, length: float,
                  curv_start: float, curv_end: float,
                  tol: float = SPIRAL_ARC_TOL) -> Bounds2D:
    """Bounds via adaptive sampling expanded by the integration error bound."""
    _validate_spiral(length, curv_start, curv_end)
    pts = sample_spiral(x0, y0, hdg0, length, curv_start, curv_end, max(length / 64.0, 1.0), tol)
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    margin = tol * 64.0  # every interval converges to < 15*tol; 64 intervals worst case
    return Bounds2D(min(xs) - margin, max(xs) + margin, min(ys) - margin, max(ys) + margin)


# --------------------------------------------------------------------------
# Poly3 — OpenDRIVE <poly3> cubic y(x) in the local frame.
# --------------------------------------------------------------------------

def _validate_poly3(length: float, a: float, b: float, c: float, d: float) -> None:
    if not math.isfinite(length) or length <= 0.0:
        raise ValueError(f"poly3 length must be finite and positive, got {length!r}")
    for name, value in (("a", a), ("b", b), ("c", c), ("d", d)):
        if not math.isfinite(value):
            raise NonFiniteCoefficientError(name, value)


def evaluate_poly3(x0: float, y0: float, hdg0: float, length: float,
                   a: float, b: float, c: float, d: float, s: float,
                   *,
                   allow_extrapolation: bool = False) -> Pose2D:
    """Pose at arc length ``s`` along a cubic y(x) poly3."""
    _validate_poly3(length, a, b, c, d)
    s_eval = _validate_evaluation_s(s, length, allow_extrapolation)
    y_l = a + b * s_eval + c * s_eval * s_eval + d * s_eval ** 3
    dy_dx = b + 2.0 * c * s_eval + 3.0 * d * s_eval * s_eval
    cos0 = math.cos(hdg0)
    sin0 = math.sin(hdg0)
    x = x0 + cos0 * s_eval - sin0 * y_l
    y = y0 + sin0 * s_eval + cos0 * y_l
    return Pose2D(x=x, y=y, hdg=hdg0 + math.atan2(dy_dx, 1.0))


def poly3_curvature_at(s: float, length: float, b: float, c: float, d: float) -> float:
    _validate_poly3(length, 0.0, b, c, d)
    if not math.isfinite(s):
        raise InvalidEvaluationRangeError(s, 0.0, length)
    dydx = b + 2.0 * c * s + 3.0 * d * s * s
    d2 = 2.0 * c + 6.0 * d * s
    return d2 / (1.0 + dydx * dydx) ** 1.5


def poly3_endpoint(x0: float, y0: float, hdg0: float, length: float,
                   a: float, b: float, c: float, d: float) -> Pose2D:
    return evaluate_poly3(x0, y0, hdg0, length, a, b, c, d, length)


def sample_poly3(x0: float, y0: float, hdg0: float, length: float,
                 a: float, b: float, c: float, d: float,
                 spacing_m: float) -> list[Pose2D]:
    if not math.isfinite(spacing_m) or spacing_m <= 0:
        raise ValueError(f"spacing_m must be positive, got {spacing_m}")
    _validate_poly3(length, a, b, c, d)
    interior = int(length / spacing_m)
    sample_s = [i * spacing_m for i in range(interior + 1)]
    if not math.isclose(sample_s[-1], length, rel_tol=0.0, abs_tol=EPS):
        sample_s.append(length)
    else:
        sample_s[-1] = length
    return [evaluate_poly3(x0, y0, hdg0, length, a, b, c, d, s) for s in sample_s]


def poly3_bounds(x0: float, y0: float, hdg0: float, length: float,
                 a: float, b: float, c: float, d: float) -> Bounds2D:
    """Exact extrema-based bounds (roots of dy/dx in the local frame)."""
    _validate_poly3(length, a, b, c, d)
    cos0 = math.cos(hdg0)
    sin0 = math.sin(hdg0)

    def _x_at(s: float) -> float:
        return x0 + cos0 * s - sin0 * (a + b * s + c * s * s + d * s ** 3)

    def _y_at(s: float) -> float:
        return y0 + sin0 * s + cos0 * (a + b * s + c * s * s + d * s ** 3)

    candidates = {0.0, length}
    qa = 3.0 * d
    qb = 2.0 * c
    qc = b
    if qa == 0.0:
        roots = [] if qb == 0.0 else [-qc / qb]
    else:
        disc = qb * qb - 4.0 * qa * qc
        if disc >= 0.0:
            sq = math.sqrt(disc)
            roots = [(-qb - sq) / (2.0 * qa), (-qb + sq) / (2.0 * qa)]
        else:
            roots = []
    for r in roots:
        if 0.0 < r < length:
            candidates.add(r)
    xs = [_x_at(s) for s in candidates]
    ys = [_y_at(s) for s in candidates]
    return Bounds2D(min(xs), max(xs), min(ys), max(ys))
