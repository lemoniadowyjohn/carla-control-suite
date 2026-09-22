"""ultimate_pipeline.quality.xodr_validation_policy

OC-59: one documented contract for OpenDRIVE validation profiles, geometry
tolerances, primitive coefficient requirements and the road-length policy.

Profiles (§5) -- explicit, no hidden default:
  OPEN_DRIVE_STRUCTURAL -- structural validity per the OpenDRIVE format
    (all five primitives supported and coefficient-checked).
  CARLA_0_9_16_COMPAT  -- structural validity PLUS the static subset CARLA
    0.9.16 demonstrably consumes (same five primitives; the production
    geometry pipeline has canonical support for all of them, so spiral is
    valid here -- an older validator comment claiming otherwise is retired).
  LEGACY_CONSERVATIVE  -- historical posture: spiral flagged (tooling that
    predates canonical spiral support). Kept for comparison only; NOT the
    authoritative semantics.

Thresholds (§8, §9) -- exactly one definition each, shared by every
validator instead of scattered literals.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, List, Tuple


OPEN_DRIVE_STRUCTURAL = "OPEN_DRIVE_STRUCTURAL"
CARLA_0_9_16_COMPAT = "CARLA_0_9_16_COMPAT"
LEGACY_CONSERVATIVE = "LEGACY_CONSERVATIVE"

PROFILES: Tuple[str, ...] = (
    OPEN_DRIVE_STRUCTURAL,
    CARLA_0_9_16_COMPAT,
    LEGACY_CONSERVATIVE,
)

DEFAULT_PROFILE = CARLA_0_9_16_COMPAT

# All five primitives the canonical geometry kernel
# (ultimate_pipeline.geometry.opendrive_geometry_kernel) evaluates.
ALL_PRIMITIVES: FrozenSet[str] = frozenset(
    {"line", "arc", "spiral", "poly3", "paramPoly3"}
)

# Per-profile primitive support (§5). Structural and CARLA profiles accept
# all five; legacy flags spiral (historical tooling limitation, kept visible
# rather than silently defaulted).
PROFILE_PRIMITIVES: Dict[str, FrozenSet[str]] = {
    OPEN_DRIVE_STRUCTURAL: ALL_PRIMITIVES,
    CARLA_0_9_16_COMPAT: ALL_PRIMITIVES,
    LEGACY_CONSERVATIVE: frozenset({"line", "arc", "poly3", "paramPoly3"}),
}

# Required finite numeric coefficients per primitive (§6).
PRIMITIVE_REQUIRED_ATTRS: Dict[str, Tuple[str, ...]] = {
    "line": (),
    "arc": ("curvature",),
    "spiral": ("curvStart", "curvEnd"),
    "poly3": ("a", "b", "c", "d"),
    "paramPoly3": ("aU", "bU", "cU", "dU", "aV", "bV", "cV", "dV"),
}

# paramPoly3 pRange contract (§6).
PARAMPOLY3_PRANGE_SUPPORTED: Tuple[str, ...] = ("arcLength", "normalized")

# Road-length consistency policy (§8): warn when BOTH the absolute and the
# relative error exceed their floors (small rounding on short roads must not
# warn; large absolute drift on long roads must not hide behind a ratio).
ROAD_LENGTH_ABS_TOL_M = 5.0
ROAD_LENGTH_REL_TOL = 0.25

# Geometry s-sequence policy (§9): segment boundary expectation
#   geometry[i+1].s ≈ geometry[i].s + geometry[i].length
# within this tolerance; violations classify as gap/overlap/duplicate_s.
GEOM_S_BOUNDARY_TOL_M = 1e-3
# Attribute-level monotonic comparisons keep the historical 1e-6 epsilon.
GEOM_S_EPS = 1e-6

# laneSection policy (§10).
LANESECTION_FIRST_S_TOL_M = 1e-3

# Lane-width policy (§12): plausibility ceiling for evaluated width.
MAX_PLAUSIBLE_LANE_WIDTH_M = 15.0


def primitives_for_profile(profile: str) -> FrozenSet[str]:
    if profile not in PROFILES:
        raise ValueError(
            f"unknown validation profile {profile!r} (expected one of "
            f"{list(PROFILES)}); refusing to guess primitive support"
        )
    return PROFILE_PRIMITIVES[profile]


def road_length_check(
    road_length: float, sum_geom: float
) -> Dict[str, object]:
    """Single road-length consistency policy (§8). No mutation, just a verdict."""
    abs_err = abs(sum_geom - road_length)
    rel_err = abs_err / max(abs(road_length), 1e-9)
    breached = (
        abs_err > ROAD_LENGTH_ABS_TOL_M and rel_err > ROAD_LENGTH_REL_TOL
    )
    return {
        "absolute_error_m": abs_err,
        "relative_error": rel_err,
        "abs_threshold_m": ROAD_LENGTH_ABS_TOL_M,
        "rel_threshold": ROAD_LENGTH_REL_TOL,
        "status": "MISMATCH" if breached else "OK",
    }


def width_extrema_over_interval(
    a: float, b: float, c: float, d: float, ds0: float, ds1: float,
    *, samples: int = 9,
) -> Dict[str, object]:
    """Analytic extrema of a+b·ds+c·ds²+d·ds³ over [ds0, ds1] (§12).

    Exact at stationary points (quadratic derivative roots inside the
    interval) plus deterministic endpoint/interior sampling for safety.
    Returns min/max; nonfinite inputs yield ok=False instead of a number.
    """
    import math

    for v in (a, b, c, d, ds0, ds1):
        if not math.isfinite(v):
            return {"ok": False, "reason": "nonfinite_coefficient_or_bound"}
    lo, hi = (ds0, ds1) if ds0 <= ds1 else (ds1, ds0)

    def _w(ds: float) -> float:
        return a + b * ds + c * ds * ds + d * ds * ds * ds

    points = [lo, hi]
    # dw/ds = b + 2c·ds + 3d·ds² = 0
    A, B, C = 3.0 * d, 2.0 * c, b
    if abs(A) > 1e-12:
        disc = B * B - 4.0 * A * C
        if disc >= 0:
            root = math.sqrt(disc)
            for ds in ((-B - root) / (2.0 * A), (-B + root) / (2.0 * A)):
                if lo <= ds <= hi:
                    points.append(ds)
    elif abs(B) > 1e-12:
        ds = -C / B
        if lo <= ds <= hi:
            points.append(ds)
    for j in range(samples):
        points.append(lo + (hi - lo) * j / max(samples - 1, 1))
    values = [_w(ds) for ds in points]
    if any(not math.isfinite(v) for v in values):
        return {"ok": False, "reason": "nonfinite_evaluation"}
    return {"ok": True, "min": min(values), "max": max(values)}


def classify_s_step(
    prev_s: float, prev_length: float, actual_s: float,
    *, tol: float = GEOM_S_BOUNDARY_TOL_M,
) -> str:
    """Classify one geometry boundary step (§9).

    ``prev_s``/``prev_length`` describe the previous validated segment;
    ``actual_s`` is this segment's declared start. Exact repeats are
    ``duplicate_s``; backward-but-distinct starts are ``overlap``.
    """
    if actual_s < 0:
        return "negative_s"
    if abs(actual_s - prev_s) <= GEOM_S_EPS:
        return "duplicate_s"
    expected = prev_s + max(prev_length, 0.0)
    delta = actual_s - expected
    if abs(delta) <= tol:
        return "continuous"
    return "gap" if delta > 0 else "overlap"


def supported_profiles() -> List[str]:
    return list(PROFILES)
