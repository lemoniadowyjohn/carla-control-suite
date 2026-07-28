"""Mesh-XODR alignment validation for RoadRunner exports.

Computes and validates alignment metrics between visual mesh output and
source XODR data.  Checks scale error, rotation/heading error,
translation error, Y inversion, control-point fit, road-centre residual,
lane-edge residual, junction-surface residual, and vertical residual.

Thresholds:
    scale relative error <= 1e-4;
    systematic heading error <= 0.1 degrees;
    road-centre mesh/XODR residual <= 0.10 m (target <= 0.05 m);
    lane-edge residual <= 0.15 m;
    grounded sign/light residual <= 0.30 m;
    no unexplained tile-origin offset.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from .exceptions import RoadRunnerContractError
from .models import SerializableContract, deterministic_json, utc_now_iso, validate_identifier, validate_sha256

SCALE_RELATIVE_TOLERANCE = 1e-4
HEADING_ERROR_DEGREES_TOLERANCE = 0.1
ROAD_CENTRE_RESIDUAL_TOLERANCE_M = 0.10
ROAD_CENTRE_RESIDUAL_TARGET_M = 0.05
LANE_EDGE_RESIDUAL_TOLERANCE_M = 0.15
GROUNDED_SIGN_LIGHT_RESIDUAL_TOLERANCE_M = 0.30
VERTICAL_RESIDUAL_TOLERANCE_M = 0.10
TRANSLATION_RESIDUAL_TOLERANCE_M = 0.10


def _finite(value: float, label: str) -> float:
    if not math.isfinite(value):
        raise RoadRunnerContractError(f"{label} must be finite, got {value}")
    return value


def _non_negative(value: float, label: str) -> float:
    _finite(value, label)
    if value < 0:
        raise RoadRunnerContractError(f"{label} must be non-negative, got {value}")
    return value


def _degrees_to_radians(deg: float) -> float:
    return deg * math.pi / 180.0


def _radians_to_degrees(rad: float) -> float:
    return rad * 180.0 / math.pi


@dataclass(frozen=True)
class ControlPoint:
    """A 3D control point for alignment fitting."""

    label: str
    x_mesh: float
    y_mesh: float
    z_mesh: float
    x_xodr: float
    y_xodr: float
    z_xodr: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "label", validate_identifier(self.label, "label"))
        for name in ("x_mesh", "y_mesh", "z_mesh", "x_xodr", "y_xodr", "z_xodr"):
            _finite(getattr(self, name), name)

    @property
    def horizontal_error_m(self) -> float:
        dx = self.x_mesh - self.x_xodr
        dy = self.y_mesh - self.y_xodr
        return math.sqrt(dx * dx + dy * dy)

    @property
    def vertical_error_m(self) -> float:
        return abs(self.z_mesh - self.z_xodr)

    @property
    def total_error_m(self) -> float:
        dx = self.x_mesh - self.x_xodr
        dy = self.y_mesh - self.y_xodr
        dz = self.z_mesh - self.z_xodr
        return math.sqrt(dx * dx + dy * dy + dz * dz)


@dataclass(frozen=True)
class ResidualSample:
    """One residual measurement between mesh and XODR."""

    label: str
    category: str
    residual_m: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "label", validate_identifier(self.label, "label"))
        object.__setattr__(self, "category", validate_identifier(self.category, "category"))
        _non_negative(self.residual_m, "residual_m")


@dataclass(frozen=True)
class AlignmentMetrics(SerializableContract):
    """Computed alignment metrics between mesh and XODR."""

    scale_error_relative: float = 0.0
    heading_error_degrees: float = 0.0
    translation_error_m: float = 0.0
    y_inversion_detected: bool = False
    control_point_rms_error_m: float = 0.0
    road_centre_residual_max_m: float = 0.0
    road_centre_residual_mean_m: float = 0.0
    lane_edge_residual_max_m: float = 0.0
    lane_edge_residual_mean_m: float = 0.0
    junction_residual_max_m: float = 0.0
    junction_residual_mean_m: float = 0.0
    vertical_residual_max_m: float = 0.0
    vertical_residual_mean_m: float = 0.0
    grounded_object_residual_max_m: float = 0.0
    tile_origin_offset_max_m: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "scale_error_relative", "heading_error_degrees", "translation_error_m",
            "control_point_rms_error_m", "road_centre_residual_max_m", "road_centre_residual_mean_m",
            "lane_edge_residual_max_m", "lane_edge_residual_mean_m",
            "junction_residual_max_m", "junction_residual_mean_m",
            "vertical_residual_max_m", "vertical_residual_mean_m",
            "grounded_object_residual_max_m", "tile_origin_offset_max_m",
        ):
            _non_negative(getattr(self, name), name)


@dataclass(frozen=True)
class AlignmentResult(SerializableContract):
    """Complete alignment validation result."""

    result_id: str
    mesh_sha256: str
    xodr_sha256: str
    metrics: AlignmentMetrics
    control_points: tuple[ControlPoint, ...] = ()
    residuals: tuple[ResidualSample, ...] = ()
    aligned: bool = False
    notes: tuple[str, ...] = ()
    generated_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        object.__setattr__(self, "result_id", validate_identifier(self.result_id, "result_id"))
        object.__setattr__(self, "mesh_sha256", validate_sha256(self.mesh_sha256, "mesh_sha256"))
        object.__setattr__(self, "xodr_sha256", validate_sha256(self.xodr_sha256, "xodr_sha256"))
        object.__setattr__(self, "control_points", tuple(self.control_points))
        object.__setattr__(self, "residuals", tuple(self.residuals))
        object.__setattr__(self, "notes", tuple(str(n) for n in self.notes))


def compute_control_point_fit(points: Sequence[ControlPoint]) -> float:
    """Compute RMS error of control-point alignment in metres."""
    if not points:
        return 0.0
    total = sum(cp.horizontal_error_m ** 2 for cp in points)
    return math.sqrt(total / len(points))


def compute_scale_error(mesh_extent: float, xodr_extent: float) -> float:
    """Compute relative scale error between mesh and XODR extents."""
    if xodr_extent == 0:
        return float("inf") if mesh_extent != 0 else 0.0
    return abs(mesh_extent - xodr_extent) / abs(xodr_extent)


def detect_y_inversion(points: Sequence[ControlPoint]) -> bool:
    """Detect systematic Y-axis inversion between mesh and XODR.

    Checks if all Y-coordinates are negated, which indicates a Y-axis
    flip (common in Unreal Engine vs. OpenDRIVE convention mismatch).
    """
    if len(points) < 2:
        return False
    signs = []
    for cp in points:
        diff_y = cp.y_mesh - cp.y_xodr
        if abs(diff_y) < 1e-9:
            signs.append(0)
        else:
            signs.append(1 if diff_y > 0 else -1)
    non_zero = [s for s in signs if s != 0]
    if not non_zero:
        return False
    return all(s == non_zero[0] for s in non_zero) and abs(non_zero[0]) == 1 and len(non_zero) == len(points)


def compute_heading_error(points: Sequence[ControlPoint]) -> float:
    """Compute systematic heading error in degrees from control points."""
    if len(points) < 2:
        return 0.0
    angles_mesh: list[float] = []
    angles_xodr: list[float] = []
    for i in range(len(points) - 1):
        cp_a = points[i]
        cp_b = points[i + 1]
        angle_mesh = math.atan2(cp_b.y_mesh - cp_a.y_mesh, cp_b.x_mesh - cp_a.x_mesh)
        angle_xodr = math.atan2(cp_b.y_xodr - cp_a.y_xodr, cp_b.x_xodr - cp_a.x_xodr)
        angles_mesh.append(angle_mesh)
        angles_xodr.append(angle_xodr)
    diffs = [abs(a_m - a_x) for a_m, a_x in zip(angles_mesh, angles_xodr)]
    diffs = [min(d, 2 * math.pi - d) for d in diffs]
    if not diffs:
        return 0.0
    return _radians_to_degrees(sum(diffs) / len(diffs))


def compute_translation_error(points: Sequence[ControlPoint]) -> float:
    """Compute mean translation offset in metres."""
    if not points:
        return 0.0
    total = sum(
        math.sqrt(
            (cp.x_mesh - cp.x_xodr) ** 2
            + (cp.y_mesh - cp.y_xodr) ** 2
            + (cp.z_mesh - cp.z_xodr) ** 2
        )
        for cp in points
    )
    return total / len(points)


def compute_residual_stats(residuals: Sequence[ResidualSample], category: str) -> tuple[float, float]:
    """Compute max and mean residual for a given category."""
    filtered = [r.residual_m for r in residuals if r.category == category]
    if not filtered:
        return 0.0, 0.0
    return max(filtered), sum(filtered) / len(filtered)


def validate_scale_error(metrics: AlignmentMetrics) -> tuple[str, ...]:
    """Validate scale relative error is within tolerance."""
    errors: list[str] = []
    if metrics.scale_error_relative > SCALE_RELATIVE_TOLERANCE:
        errors.append(
            f"scale relative error {metrics.scale_error_relative:.6e} > "
            f"tolerance {SCALE_RELATIVE_TOLERANCE:.1e}"
        )
    return tuple(errors)


def validate_heading_error(metrics: AlignmentMetrics) -> tuple[str, ...]:
    """Validate systematic heading error is within tolerance."""
    errors: list[str] = []
    if metrics.heading_error_degrees > HEADING_ERROR_DEGREES_TOLERANCE:
        errors.append(
            f"heading error {metrics.heading_error_degrees:.4f} deg > "
            f"tolerance {HEADING_ERROR_DEGREES_TOLERANCE} deg"
        )
    return tuple(errors)


def validate_road_centre_residual(metrics: AlignmentMetrics) -> tuple[str, ...]:
    """Validate road-centre residual is within tolerance."""
    errors: list[str] = []
    if metrics.road_centre_residual_max_m > ROAD_CENTRE_RESIDUAL_TOLERANCE_M:
        errors.append(
            f"road-centre residual max {metrics.road_centre_residual_max_m:.4f} m > "
            f"tolerance {ROAD_CENTRE_RESIDUAL_TOLERANCE_M} m"
        )
    if metrics.road_centre_residual_max_m > ROAD_CENTRE_RESIDUAL_TARGET_M:
        errors.append(
            f"road-centre residual max {metrics.road_centre_residual_max_m:.4f} m > "
            f"target {ROAD_CENTRE_RESIDUAL_TARGET_M} m (informational)"
        )
    return tuple(errors)


def validate_lane_edge_residual(metrics: AlignmentMetrics) -> tuple[str, ...]:
    """Validate lane-edge residual is within tolerance."""
    errors: list[str] = []
    if metrics.lane_edge_residual_max_m > LANE_EDGE_RESIDUAL_TOLERANCE_M:
        errors.append(
            f"lane-edge residual max {metrics.lane_edge_residual_max_m:.4f} m > "
            f"tolerance {LANE_EDGE_RESIDUAL_TOLERANCE_M} m"
        )
    return tuple(errors)


def validate_junction_residual(metrics: AlignmentMetrics) -> tuple[str, ...]:
    """Validate junction-surface residual is within tolerance."""
    errors: list[str] = []
    if metrics.junction_residual_max_m > GROUNDED_SIGN_LIGHT_RESIDUAL_TOLERANCE_M:
        errors.append(
            f"junction residual max {metrics.junction_residual_max_m:.4f} m > "
            f"tolerance {GROUNDED_SIGN_LIGHT_RESIDUAL_TOLERANCE_M} m"
        )
    return tuple(errors)


def validate_vertical_residual(metrics: AlignmentMetrics) -> tuple[str, ...]:
    """Validate vertical residual is within tolerance."""
    errors: list[str] = []
    if metrics.vertical_residual_max_m > VERTICAL_RESIDUAL_TOLERANCE_M:
        errors.append(
            f"vertical residual max {metrics.vertical_residual_max_m:.4f} m > "
            f"tolerance {VERTICAL_RESIDUAL_TOLERANCE_M} m"
        )
    return tuple(errors)


def validate_translation_error(metrics: AlignmentMetrics) -> tuple[str, ...]:
    """Validate translation error is within tolerance."""
    errors: list[str] = []
    if metrics.translation_error_m > TRANSLATION_RESIDUAL_TOLERANCE_M:
        errors.append(
            f"translation error {metrics.translation_error_m:.4f} m > "
            f"tolerance {TRANSLATION_RESIDUAL_TOLERANCE_M} m"
        )
    return tuple(errors)


def validate_y_inversion(metrics: AlignmentMetrics) -> tuple[str, ...]:
    """Flag Y inversion as an error requiring investigation."""
    errors: list[str] = []
    if metrics.y_inversion_detected:
        errors.append(
            "Y-axis inversion detected between mesh and XODR: "
            "this indicates a coordinate convention mismatch"
        )
    return tuple(errors)


def validate_tile_origin_offsets(metrics: AlignmentMetrics) -> tuple[str, ...]:
    """Validate no unexplained tile-origin offset exists."""
    errors: list[str] = []
    if metrics.tile_origin_offset_max_m > TRANSLATION_RESIDUAL_TOLERANCE_M:
        errors.append(
            f"tile origin offset max {metrics.tile_origin_offset_max_m:.4f} m > "
            f"tolerance {TRANSLATION_RESIDUAL_TOLERANCE_M} m"
        )
    return tuple(errors)


def validate_control_point_fit(points: Sequence[ControlPoint]) -> tuple[str, ...]:
    """Validate control-point fit quality."""
    errors: list[str] = []
    if not points:
        errors.append("no control points provided for alignment validation")
        return tuple(errors)
    rms = compute_control_point_fit(points)
    if rms > ROAD_CENTRE_RESIDUAL_TOLERANCE_M:
        errors.append(
            f"control-point RMS error {rms:.4f} m > "
            f"tolerance {ROAD_CENTRE_RESIDUAL_TOLERANCE_M} m"
        )
    return tuple(errors)


def validate_alignment_result(result: AlignmentResult) -> tuple[str, ...]:
    """Run all alignment validation checks on a result."""
    all_errors: list[str] = []
    all_errors.extend(validate_scale_error(result.metrics))
    all_errors.extend(validate_heading_error(result.metrics))
    all_errors.extend(validate_translation_error(result.metrics))
    all_errors.extend(validate_y_inversion(result.metrics))
    all_errors.extend(validate_control_point_fit(result.control_points))
    all_errors.extend(validate_road_centre_residual(result.metrics))
    all_errors.extend(validate_lane_edge_residual(result.metrics))
    all_errors.extend(validate_junction_residual(result.metrics))
    all_errors.extend(validate_vertical_residual(result.metrics))
    all_errors.extend(validate_tile_origin_offsets(result.metrics))
    return tuple(all_errors)


@dataclass(frozen=True)
class AlignmentValidation:
    """Structured result of alignment validation."""

    result_id: str
    valid: bool
    errors: tuple[str, ...]
    validated_at: str = field(default_factory=utc_now_iso)


def validate_alignment_result_structured(result: AlignmentResult) -> AlignmentValidation:
    """Run alignment checks and return structured validation result."""
    errors = validate_alignment_result(result)
    return AlignmentValidation(
        result_id=result.result_id,
        valid=len(errors) == 0,
        errors=errors,
    )


__all__ = [
    "AlignmentMetrics",
    "AlignmentResult",
    "AlignmentValidation",
    "ControlPoint",
    "HEADING_ERROR_DEGREES_TOLERANCE",
    "LANE_EDGE_RESIDUAL_TOLERANCE_M",
    "ROAD_CENTRE_RESIDUAL_TARGET_M",
    "ROAD_CENTRE_RESIDUAL_TOLERANCE_M",
    "ResidualSample",
    "SCALE_RELATIVE_TOLERANCE",
    "VERTICAL_RESIDUAL_TOLERANCE_M",
    "compute_control_point_fit",
    "compute_heading_error",
    "compute_residual_stats",
    "compute_scale_error",
    "compute_translation_error",
    "detect_y_inversion",
    "validate_alignment_result",
    "validate_alignment_result_structured",
    "validate_control_point_fit",
    "validate_heading_error",
    "validate_junction_residual",
    "validate_lane_edge_residual",
    "validate_road_centre_residual",
    "validate_scale_error",
    "validate_tile_origin_offsets",
    "validate_translation_error",
    "validate_vertical_residual",
    "validate_y_inversion",
]
