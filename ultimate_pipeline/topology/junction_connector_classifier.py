# ultimate_pipeline/topology/junction_connector_classifier.py
# -*- coding: utf-8 -*-

"""
Junction connector association classifier (OC-2, AREA-014).

The topology tools that decide where a junction connector road attaches to
its incoming road historically picked the NEAREST incoming endpoint by
distance alone (junction_connector_snap) or rebuilt the planView without a
heading-consistency check (junction_connector_rebuild's direct-line
fallback). Both can corrupt a connector when the nearest endpoint is not
obviously the right one or when the connector's declared heading disagrees
with the target's.

This module assigns every examined association one of three tiers, pure and
deterministic:

- EXACT_TOPOLOGY:            the connector's start lies within the position
                             tolerance of the DECLARED incoming boundary
                             (contactPoint side) AND its heading agrees with
                             that boundary's pose heading.
- GEOMETRICALLY_INFERRED_HIGH: the declared boundary does not match within
                             tolerance, but the nearest endpoint is clearly
                             unambiguous (position margin above the
                             threshold) and the connector heading agrees with
                             it. Safe to act on geometrically.
- AMBIGUOUS:                the endpoint choice cannot be trusted (near tie
                             in distance, or heading contradiction). Tools
                             must NOT act on AMBIGUOUS associations
                             (fail-closed); report and skip instead.

All functions are offline and read-only (no CARLA dependency). Poses are
accepted as objects exposing ``.x``/``.y``/``.hdg`` (e.g. the ``Pose`` named
tuple from check_geometric_continuity) or as ``(x, y, hdg)`` sequences.
"""

from __future__ import annotations

import math
from typing import Any, Dict

EXACT_TOPOLOGY = "EXACT_TOPOLOGY"
GEOMETRICALLY_INFERRED_HIGH = "GEOMETRICALLY_INFERRED_HIGH"
AMBIGUOUS = "AMBIGUOUS"

# Alias kept for backward compatibility with the ConnectorValidator surface.
GEOMETRICALLY_INFERRED = GEOMETRICALLY_INFERRED_HIGH

DEFAULT_POSITION_EPS_M = 2.0
DEFAULT_HEADING_EPS_RAD = math.radians(30.0)
DEFAULT_MIN_MARGIN_M = 2.0


def _angle_error(a: float, b: float) -> float:
    return abs((float(a) - float(b) + math.pi) % (2.0 * math.pi) - math.pi)


def _norm(a: float) -> float:
    while a > math.pi:
        a -= 2.0 * math.pi
    while a < -math.pi:
        a += 2.0 * math.pi
    return a


def _xyh(pose: Any) -> Dict[str, float]:
    if hasattr(pose, "x") and hasattr(pose, "y") and hasattr(pose, "hdg"):
        return {"x": float(pose.x), "y": float(pose.y), "hdg": float(pose.hdg)}
    if isinstance(pose, (tuple, list)) and len(pose) >= 3:
        return {"x": float(pose[0]), "y": float(pose[1]), "hdg": float(pose[2])}
    raise ValueError(f"Unsupported pose type: {type(pose)!r}")


def _dist(pose_a: Dict[str, float], pose_b: Dict[str, float]) -> float:
    return math.hypot(pose_a["x"] - pose_b["x"], pose_a["y"] - pose_b["y"])


def classify_connector_association(
    *,
    connector_start: Any,
    incoming_start: Any,
    incoming_end: Any,
    declared_side: str = "start",
    position_eps_m: float = DEFAULT_POSITION_EPS_M,
    heading_eps_rad: float = DEFAULT_HEADING_EPS_RAD,
    min_margin_m: float = DEFAULT_MIN_MARGIN_M,
) -> Dict[str, Any]:
    """Classify which incoming boundary a connector start associates with.

    Args:
        connector_start: pose of the connector road's start geometry.
        incoming_start: pose of the incoming road's start boundary.
        incoming_end: pose of the incoming road's end boundary.
        declared_side: the connection's contactPoint ("start" = connector
            binds the incoming road's START boundary).
        position_eps_m: position tolerance for EXACT_TOPOLOGY (m).
        heading_eps_rad: heading tolerance (rad) for tier qualification.
        min_margin_m: the nearest-endpoint margin required to call the
            association unambiguous (m).

    Returns a dict with ``classification``, plus the supporting evidence
    (gaps, margin, heading error, nearest boundary).
    """
    conn = _xyh(connector_start)
    start = _xyh(incoming_start)
    end = _xyh(incoming_end)

    side = (declared_side or "start").strip().lower()
    if side not in ("start", "end"):
        side = "start"

    declared_pose = start if side == "start" else end
    alt_pose = end if side == "start" else start

    gap_declared = _dist(conn, declared_pose)
    gap_alt = _dist(conn, alt_pose)
    margin = abs(gap_declared - gap_alt)
    hdg_declared = _angle_error(conn["hdg"], declared_pose["hdg"])
    hdg_alt = _angle_error(conn["hdg"], alt_pose["hdg"])

    nearest_boundary = side if gap_declared <= gap_alt else ("end" if side == "start" else "start")
    nearest_gap = min(gap_declared, gap_alt)

    if gap_declared <= position_eps_m and hdg_declared <= heading_eps_rad:
        classification = EXACT_TOPOLOGY
        reason = (
            f"connector start within {position_eps_m:g}m of declared "
            f"{side.upper()} boundary and heading aligned"
        )
    elif margin > min_margin_m:
        nearest_hdg = hdg_declared if nearest_boundary == side else hdg_alt
        if nearest_hdg <= heading_eps_rad:
            classification = GEOMETRICALLY_INFERRED_HIGH
            reason = (
                f"nearest endpoint {nearest_boundary.upper()} unambiguous "
                f"(margin {margin:.2f}m) and heading aligned"
            )
        else:
            classification = AMBIGUOUS
            reason = (
                f"nearest endpoint {nearest_boundary.upper()} unambiguous by "
                f"distance but heading disagrees "
                f"({math.degrees(nearest_hdg):.1f} deg > "
                f"{math.degrees(heading_eps_rad):.1f} deg)"
            )
    else:
        reason = (
            "endpoints not separable by distance "
            f"(margin {margin:.2f}m <= {min_margin_m:g}m)"
        )
        classification = AMBIGUOUS

    return {
        "classification": classification,
        "declared_side": side,
        "nearest_boundary": nearest_boundary,
        "nearest_gap_m": round(nearest_gap, 6),
        "gap_declared_m": round(gap_declared, 6),
        "gap_alternate_m": round(gap_alt, 6),
        "margin_m": round(margin, 6),
        "heading_error_rad": round(hdg_declared, 9),
        "position_eps_m": position_eps_m,
        "heading_eps_rad": heading_eps_rad,
        "min_margin_m": min_margin_m,
        "reason": reason,
    }


def direct_line_boundary_ok(
    *,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    start_hdg: float,
    end_hdg: float,
    max_chord_heading_deviation_rad: float,
) -> bool:
    """Heading-consistency check for the direct-line planView fallback.

    Returns True only when the straight chord's direction respects BOTH
    boundary headings: the chord must align with the start heading (within
    ``max_chord_heading_deviation_rad``) AND align with the end heading
    treated as the chord traversed backward. A straight replacement that
    ignores either boundary's declared direction is a corrupting
    simplification and must be refused.
    """
    dx = float(end_x) - float(start_x)
    dy = float(end_y) - float(start_y)
    tol = float(max_chord_heading_deviation_rad)
    if math.hypot(dx, dy) <= 1e-12:
        return False
    chord_hdg = math.atan2(dy, dx)
    if _angle_error(chord_hdg, float(start_hdg)) > tol:
        return False
    reverse_end_hdg = _norm(float(end_hdg) + math.pi)
    if _angle_error(chord_hdg, reverse_end_hdg) > tol:
        return False
    return True