"""Fail-closed repair for folded ``paramPoly3`` plan-view pairs.

SUMO/netconvert can occasionally emit a short ``paramPoly3`` whose local
longitudinal derivative changes sign and whose successor starts at the same
position with the opposite tangent.  That is not a valid traversable road
centreline.  This module recognizes the full defect signature rather than
trying to normalize every parametric polynomial with a derivative root.

The repair replaces the folded geometry and its direct successor with five
OpenDRIVE ``paramPoly3`` circular-arc approximations.  The representation is
accepted by the repository's strict CARLA validator, unlike ``spiral``.  The
replacement keeps the original combined ``s`` span, start pose, and end pose.
It is only committed when the candidate has no internal seam and does not
increase the maximum sampled curvature of the replaced pair.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np

from ultimate_pipeline.geometry.opendrive_geometry_kernel import (
    curvature_at_s,
    endpoint,
    pose_at_s,
)


DEFAULT_MAX_POSITION_GAP_M = 0.2
DEFAULT_MIN_REVERSAL_DEG = 170.0
_SOLVER_TOLERANCE = 1e-7
_MAX_SOLVER_ITERATIONS = 40
_SEGMENT_COUNT = 5
_MAX_PARAM_POLY_TURN_RAD = math.pi / 2.0


@dataclass(frozen=True)
class TangentReversalCandidate:
    road_id: str
    geometry_index: int
    successor_index: int
    derivative_roots: tuple[float, ...]
    position_gap_m: float
    heading_delta_deg: float


def _wrapped_angle(angle: float) -> float:
    return (float(angle) + math.pi) % (2.0 * math.pi) - math.pi


def _geometry_kind(geometry: ET.Element) -> str | None:
    child = next(iter(geometry), None)
    if child is None:
        return None
    return child.tag.rsplit("}", 1)[-1]


def _float_attr(element: ET.Element, name: str) -> float:
    value = float(element.get(name, "nan"))
    if not math.isfinite(value):
        raise ValueError(f"non-finite {name}")
    return value


def _derivative_roots(param_poly: ET.Element, domain_end: float) -> tuple[float, ...]:
    """Return strict-domain roots of du/dp for a paramPoly3."""
    b = _float_attr(param_poly, "bU")
    c = _float_attr(param_poly, "cU")
    d = _float_attr(param_poly, "dU")
    roots: list[float] = []
    epsilon = 1e-12
    if abs(d) <= epsilon:
        if abs(c) > epsilon:
            roots.append(-b / (2.0 * c))
    else:
        discriminant = 4.0 * c * c - 12.0 * d * b
        if discriminant >= 0.0:
            root = math.sqrt(discriminant)
            roots.extend(((-2.0 * c - root) / (6.0 * d), (-2.0 * c + root) / (6.0 * d)))
    return tuple(sorted(root for root in roots if epsilon < root < domain_end - epsilon))


def _has_du_sign_reversal(geometry: ET.Element) -> tuple[bool, tuple[float, ...]]:
    param_poly = geometry.find("paramPoly3")
    if param_poly is None:
        return False, ()
    length = _float_attr(geometry, "length")
    domain_end = 1.0 if param_poly.get("pRange", "arcLength") == "normalized" else length
    roots = _derivative_roots(param_poly, domain_end)
    if not roots:
        return False, ()
    b = _float_attr(param_poly, "bU")
    c = _float_attr(param_poly, "cU")
    d = _float_attr(param_poly, "dU")

    def derivative(value: float) -> float:
        return b + 2.0 * c * value + 3.0 * d * value * value

    epsilon = min(1e-7, domain_end * 1e-7)
    for root in roots:
        if derivative(max(0.0, root - epsilon)) * derivative(min(domain_end, root + epsilon)) < 0.0:
            return True, roots
    return False, ()


def find_parampoly3_tangent_reversals(
    root: ET.Element,
    *,
    max_position_gap_m: float = DEFAULT_MAX_POSITION_GAP_M,
    min_reversal_deg: float = DEFAULT_MIN_REVERSAL_DEG,
) -> list[TangentReversalCandidate]:
    """Find position-continuous, near-pi tangent reversals after a folded curve."""
    candidates: list[TangentReversalCandidate] = []
    for road in root.findall("road"):
        geometries = road.findall("./planView/geometry")
        for index, geometry in enumerate(geometries[:-1]):
            if _geometry_kind(geometry) != "paramPoly3":
                continue
            try:
                folded, roots = _has_du_sign_reversal(geometry)
                if not folded:
                    continue
                previous_end = endpoint(geometry)
                successor_start = pose_at_s(geometries[index + 1], 0.0)
            except ValueError:
                continue
            position_gap = math.hypot(
                previous_end.x - successor_start.x,
                previous_end.y - successor_start.y,
            )
            heading_delta = math.degrees(
                _wrapped_angle(successor_start.heading - previous_end.heading)
            )
            if position_gap <= max_position_gap_m and abs(heading_delta) >= min_reversal_deg:
                candidates.append(
                    TangentReversalCandidate(
                        road_id=str(road.get("id", "")),
                        geometry_index=index,
                        successor_index=index + 1,
                        derivative_roots=roots,
                        position_gap_m=position_gap,
                        heading_delta_deg=heading_delta,
                    )
                )
    return sorted(candidates, key=lambda item: (item.road_id, item.geometry_index))


def _param_poly_arc_approximation(
    s: float,
    pose: Any,
    length: float,
    curvature: float,
) -> ET.Element:
    """Create a cubic Bezier approximation of a constant-curvature arc.

    The endpoint and endpoint tangent are exact.  Candidates with an arc turn
    at or above 90 degrees are rejected before this representation is emitted,
    keeping the cubic approximation in its stable range.
    """
    turn = float(curvature) * float(length)
    if abs(turn) >= _MAX_PARAM_POLY_TURN_RAD:
        raise ValueError("paramPoly3 arc approximation turn is too large")
    if abs(curvature) <= 1e-12:
        end_x, end_y = float(length), 0.0
        handle = float(length) / 3.0
    else:
        end_x = math.sin(turn) / float(curvature)
        end_y = (1.0 - math.cos(turn)) / float(curvature)
        handle = 4.0 * math.tan(turn / 4.0) / (3.0 * float(curvature))
    control_1_x, control_1_y = handle, 0.0
    control_2_x = end_x - handle * math.cos(turn)
    control_2_y = end_y - handle * math.sin(turn)
    b_u, b_v = 3.0 * control_1_x, 3.0 * control_1_y
    c_u = 3.0 * (control_2_x - 2.0 * control_1_x)
    c_v = 3.0 * (control_2_y - 2.0 * control_1_y)
    d_u = end_x - 3.0 * control_2_x + 3.0 * control_1_x
    d_v = end_y - 3.0 * control_2_y + 3.0 * control_1_y
    geometry = ET.Element(
        "geometry",
        {
            "s": f"{float(s):.12f}",
            "x": f"{float(pose.x):.12f}",
            "y": f"{float(pose.y):.12f}",
            "hdg": f"{float(pose.heading):.12f}",
            "length": f"{float(length):.12f}",
        },
    )
    ET.SubElement(
        geometry,
        "paramPoly3",
        {
            "aU": "0.0",
            "bU": f"{b_u:.12f}",
            "cU": f"{c_u:.12f}",
            "dU": f"{d_u:.12f}",
            "aV": "0.0",
            "bV": f"{b_v:.12f}",
            "cV": f"{c_v:.12f}",
            "dV": f"{d_v:.12f}",
            "pRange": "normalized",
        },
    )
    return geometry


def _build_equal_length_arc_approximations(
    start: Any,
    total_length: float,
    curvatures: np.ndarray,
    *,
    start_s: float = 0.0,
) -> list[ET.Element]:
    segment_length = total_length / len(curvatures)
    current = start
    geometries: list[ET.Element] = []
    for index, curvature in enumerate(curvatures):
        geometry = _param_poly_arc_approximation(
            float(start_s) + float(index) * segment_length,
            current,
            segment_length,
            float(curvature),
        )
        geometries.append(geometry)
        current = endpoint(geometry)
    return geometries


def _solve_curvatures(start: Any, end: Any, total_length: float) -> np.ndarray | None:
    """Solve a deterministic five-segment endpoint and tangent fit.

    Equal-length segments leave five curvature variables for the two position
    constraints and one heading constraint.  Damped minimum-norm Newton
    iterations are deliberately bounded; an ill-conditioned candidate is
    rejected rather than forced.
    """
    if not math.isfinite(total_length) or total_length <= 1e-6:
        return None
    cos_h = math.cos(start.heading)
    sin_h = math.sin(start.heading)
    dx = float(end.x) - float(start.x)
    dy = float(end.y) - float(start.y)
    target = np.array(
        [
            cos_h * dx + sin_h * dy,
            -sin_h * dx + cos_h * dy,
            _wrapped_angle(float(end.heading) - float(start.heading)),
        ],
        dtype=float,
    )
    local_start = type(start)(x=0.0, y=0.0, heading=0.0, curvature=None)

    def residual(curvatures: np.ndarray) -> np.ndarray:
        try:
            geometries = _build_equal_length_arc_approximations(
                local_start, total_length, curvatures
            )
            result = endpoint(geometries[-1])
        except (ValueError, OverflowError):
            return np.array((math.inf, math.inf, math.inf), dtype=float)
        return np.array(
            [
                result.x - target[0],
                result.y - target[1],
                _wrapped_angle(result.heading - target[2]),
            ],
            dtype=float,
        )

    # The signs encode the lowest-turn S-family found for this defect class.
    curvatures = np.array((1.0, -2.0, -2.0, -1.0, 1.0), dtype=float)
    for _ in range(_MAX_SOLVER_ITERATIONS):
        current = residual(curvatures)
        if not np.all(np.isfinite(current)):
            return None
        if float(np.linalg.norm(current, ord=np.inf)) <= _SOLVER_TOLERANCE:
            turns = curvatures * (total_length / _SEGMENT_COUNT)
            return (
                curvatures
                if float(np.max(np.abs(turns))) < _MAX_PARAM_POLY_TURN_RAD
                else None
            )
        jacobian = np.empty((3, _SEGMENT_COUNT), dtype=float)
        for column in range(_SEGMENT_COUNT):
            step = 1e-5 * max(1.0, abs(float(curvatures[column])))
            probe = curvatures.copy()
            probe[column] += step
            jacobian[:, column] = (residual(probe) - current) / step
        try:
            correction = -jacobian.T @ np.linalg.solve(
                jacobian @ jacobian.T + 1e-8 * np.eye(3), current
            )
        except np.linalg.LinAlgError:
            return None
        if not np.all(np.isfinite(correction)):
            return None
        # Keep the deterministic solve in a physically meaningful basin.
        correction = np.clip(correction, -0.5, 0.5)
        curvatures += correction
        if float(np.max(np.abs(curvatures))) > 10.0:
            return None
    return None


def _max_sampled_curvature(geometries: list[ET.Element]) -> float:
    maximum = 0.0
    for geometry in geometries:
        length = _float_attr(geometry, "length")
        for index in range(33):
            value = curvature_at_s(geometry, length * index / 32.0)
            if value is None or not math.isfinite(value):
                raise ValueError("non-finite curvature")
            maximum = max(maximum, abs(value))
    return maximum


def _replacement_for_pair(
    geometry: ET.Element,
    successor: ET.Element,
) -> tuple[list[ET.Element], dict[str, Any]] | None:
    try:
        start = pose_at_s(geometry, 0.0)
        end = endpoint(successor)
        total_length = _float_attr(geometry, "length") + _float_attr(successor, "length")
        curvatures = _solve_curvatures(start, end, total_length)
        if curvatures is None:
            return None
        replacement = _build_equal_length_arc_approximations(
            start,
            total_length,
            curvatures,
            start_s=_float_attr(geometry, "s"),
        )
        replacement_end = endpoint(replacement[-1])
        endpoint_gap = math.hypot(replacement_end.x - end.x, replacement_end.y - end.y)
        endpoint_heading_gap = abs(_wrapped_angle(replacement_end.heading - end.heading))
        if endpoint_gap > _SOLVER_TOLERANCE or endpoint_heading_gap > _SOLVER_TOLERANCE:
            return None
        for previous, following in zip(replacement, replacement[1:]):
            previous_end = endpoint(previous)
            next_start = pose_at_s(following, 0.0)
            if math.hypot(previous_end.x - next_start.x, previous_end.y - next_start.y) > _SOLVER_TOLERANCE:
                return None
            if abs(_wrapped_angle(previous_end.heading - next_start.heading)) > _SOLVER_TOLERANCE:
                return None
        source_max_curvature = _max_sampled_curvature([geometry, successor])
        replacement_max_curvature = _max_sampled_curvature(replacement)
        if replacement_max_curvature > source_max_curvature + _SOLVER_TOLERANCE:
            return None
    except (ValueError, OverflowError, np.linalg.LinAlgError):
        return None
    return replacement, {
        "source_max_abs_curvature": source_max_curvature,
        "replacement_max_abs_curvature": replacement_max_curvature,
        "endpoint_gap_m": endpoint_gap,
        "endpoint_heading_gap_rad": endpoint_heading_gap,
        "curvatures": [float(value) for value in curvatures],
    }


def repair_parampoly3_tangent_reversals(root: ET.Element) -> dict[str, Any]:
    """Transactionally repair eligible folded paramPoly3/successor pairs.

    Failed fits are preserved exactly and recorded; no partial XML mutation is
    retained for an unsuccessful candidate.
    """
    candidates = find_parampoly3_tangent_reversals(root)
    report: dict[str, Any] = {
        "detected": len(candidates),
        "repaired": 0,
        "preserved": 0,
        "records": [],
    }
    by_road: dict[str, list[TangentReversalCandidate]] = {}
    for candidate in candidates:
        by_road.setdefault(candidate.road_id, []).append(candidate)

    for road in root.findall("road"):
        road_id = str(road.get("id", ""))
        road_candidates = by_road.get(road_id, [])
        if not road_candidates:
            continue
        plan_view = road.find("planView")
        if plan_view is None:
            continue
        # Work from highest index so removing a successor cannot invalidate a
        # lower candidate's recorded index.
        for candidate in sorted(road_candidates, key=lambda item: item.geometry_index, reverse=True):
            geometries = plan_view.findall("geometry")
            if candidate.successor_index >= len(geometries):
                report["preserved"] += 1
                report["records"].append({"road_id": road_id, "action": "PRESERVED_INDEX_CHANGED"})
                continue
            geometry = geometries[candidate.geometry_index]
            successor = geometries[candidate.successor_index]
            result = _replacement_for_pair(geometry, successor)
            if result is None:
                report["preserved"] += 1
                report["records"].append(
                    {
                        "road_id": road_id,
                        "geometry_index": candidate.geometry_index,
                        "action": "PRESERVED_REPAIR_REJECTED",
                    }
                )
                continue
            replacement, metrics = result
            following = (
                geometries[candidate.successor_index + 1]
                if candidate.successor_index + 1 < len(geometries)
                else None
            )
            replacement_end_s = _float_attr(replacement[-1], "s") + _float_attr(
                replacement[-1], "length"
            )
            if following is not None and abs(replacement_end_s - _float_attr(following, "s")) > _SOLVER_TOLERANCE:
                report["preserved"] += 1
                report["records"].append(
                    {
                        "road_id": road_id,
                        "geometry_index": candidate.geometry_index,
                        "action": "PRESERVED_S_SPAN_MISMATCH",
                    }
                )
                continue
            insertion_index = list(plan_view).index(geometry)
            plan_view.remove(successor)
            plan_view.remove(geometry)
            for offset, element in enumerate(replacement):
                plan_view.insert(insertion_index + offset, element)
            report["repaired"] += 1
            report["records"].append(
                {
                    "road_id": road_id,
                    "geometry_index": candidate.geometry_index,
                    "action": "REPAIRED_FIVE_PARAMPOLY3_ARC_APPROXIMATIONS",
                    "derivative_roots": list(candidate.derivative_roots),
                    "position_gap_m": candidate.position_gap_m,
                    "heading_delta_deg": candidate.heading_delta_deg,
                    **metrics,
                }
            )
    report["records"].sort(key=lambda item: (str(item.get("road_id", "")), int(item.get("geometry_index", -1))))
    return report
