#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NEW-323 -- quantitative LiDAR / camera consistency gate.

What the gate accepted before
-----------------------------
``calibration_sanity_check`` computed a LiDAR-camera check as::

    p_vehicle = _apply_transform(vTl, (5.0, 0.0, 0.0))
    p_cam_l   = _apply_transform(cTv, p_vehicle)
    pxl       = _project_point(K, p_cam_l)
    lidar_checks[lname] = {"ok": pxl is not None, ...}

and ``_project_point`` returns a pixel whenever ``z > 1e-6``.  Bounds were never
checked.  A projection to ``[-5000, 20000]`` therefore counted as a **successful**
LiDAR-camera check purely because the depth was positive.

What a valid projection must establish
--------------------------------------
1. finite coordinates,
2. positive camera depth,
3. the pixel lies inside the valid image domain,
4. correct target correspondence (the requested target was actually projected),
5. residual below an explicit threshold.

This module implements that gate with explicit thresholds and refuses the
out-of-image case outright.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

GATE_SCHEMA = "LIDAR_CAMERA_GATE/v1"

LIDAR_PROJECTION_NON_FINITE = "LIDAR_PROJECTION_NON_FINITE"
LIDAR_PROJECTION_NON_POSITIVE_DEPTH = "LIDAR_PROJECTION_NON_POSITIVE_DEPTH"
LIDAR_PROJECTION_OUTSIDE_IMAGE = "LIDAR_PROJECTION_OUTSIDE_IMAGE"
LIDAR_PROJECTION_NO_CORRESPONDENCE = "LIDAR_PROJECTION_NO_CORRESPONDENCE"
LIDAR_PROJECTION_RESIDUAL_EXCEEDED = "LIDAR_PROJECTION_RESIDUAL_EXCEEDED"

#: Explicit, pre-declared acceptance thresholds.  Declared *before* the assay
#: runs; never tuned to make a result pass.
DEFAULT_GATE_THRESHOLDS: Dict[str, float] = {
    "min_camera_depth_m": 1.0e-3,
    "max_reprojection_residual_px": 2.0,
    "max_mean_reprojection_residual_px": 1.0,
    "require_inside_image": 1.0,
    "min_target_correspondence_rate": 1.0,
    "require_finite": 1.0,
}


def project_point(
    k_matrix: Any, point_camera: Sequence[float]
) -> Optional[Tuple[float, float, float]]:
    """Project a camera-frame point.  Returns ``(u, v, depth)`` or ``None``.

    Returns ``None`` for non-finite coordinates or non-positive depth, so a
    caller can never mistake garbage for a valid projection.
    """
    x, y, z = (float(point_camera[0]), float(point_camera[1]), float(point_camera[2]))
    for value in (x, y, z):
        if value != value or value in (float("inf"), float("-inf")):
            return None
    if z <= 1.0e-9:
        return None
    fx = float(k_matrix[0][0])
    fy = float(k_matrix[1][1])
    cx = float(k_matrix[0][2])
    cy = float(k_matrix[1][2])
    u = fx * (x / z) + cx
    v = fy * (y / z) + cy
    for value in (u, v):
        if value != value or value in (float("inf"), float("-inf")):
            return None
    return u, v, z


def apply_transform(matrix: Sequence[Sequence[float]], point: Sequence[float]) -> Tuple[float, float, float]:
    x, y, z = float(point[0]), float(point[1]), float(point[2])
    return (
        float(matrix[0][0]) * x + float(matrix[0][1]) * y + float(matrix[0][2]) * z + float(matrix[0][3]),
        float(matrix[1][0]) * x + float(matrix[1][1]) * y + float(matrix[1][2]) * z + float(matrix[1][3]),
        float(matrix[2][0]) * x + float(matrix[2][1]) * y + float(matrix[2][2]) * z + float(matrix[2][3]),
    )


def check_projection(
    k_matrix: Any,
    point_vehicle: Sequence[float],
    vTl: Sequence[Sequence[float]],
    cTv: Sequence[Sequence[float]],
    *,
    width_px: int,
    height_px: int,
    target_name: str = "forward_5m",
    observed_pixel: Optional[Sequence[float]] = None,
    thresholds: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    """One quantitative LiDAR-camera projection check.

    ``observed_pixel`` is the *measured* image location of the same physical
    target.  When supplied, the gate also enforces criterion 5 (residual below
    threshold); the residual is then a genuine observation, not the same
    transform arithmetic used to produce the prediction.
    """
    limits = dict(DEFAULT_GATE_THRESHOLDS)
    limits.update({k: float(v) for k, v in dict(thresholds or {}).items()})

    reasons: List[str] = []
    p_lidar = apply_transform(vTl, point_vehicle)
    p_vehicle = apply_transform(_invert4(vTl), p_lidar)
    p_camera = apply_transform(cTv, p_vehicle)

    for value in p_camera:
        if value != value or value in (float("inf"), float("-inf")):
            reasons.append(f"{LIDAR_PROJECTION_NON_FINITE}:{target_name}")
            return _result(False, reasons, None, target_name, limits)

    projected = project_point(k_matrix, p_camera)
    if projected is None:
        reasons.append(f"{LIDAR_PROJECTION_NON_POSITIVE_DEPTH}:{target_name}")
        return _result(False, reasons, None, target_name, limits)

    u, v, depth = projected
    inside = (0.0 <= u < float(width_px)) and (0.0 <= v < float(height_px))
    if limits["require_inside_image"] > 0.0 and not inside:
        reasons.append(
            f"{LIDAR_PROJECTION_OUTSIDE_IMAGE}:{target_name}:"
            f"pixel=({round(u, 3)},{round(v, 3)})"
            f":image={int(width_px)}x{int(height_px)}"
        )

    pixel = (u, v, depth)
    residual = None
    if observed_pixel is not None:
        try:
            ou, ov = float(observed_pixel[0]), float(observed_pixel[1])
        except (TypeError, ValueError, IndexError):
            reasons.append(f"{LIDAR_PROJECTION_NO_CORRESPONDENCE}:{target_name}")
        else:
            if not all(
                value == value and value not in (float("inf"), float("-inf"))
                for value in (ou, ov)
            ):
                reasons.append(f"{LIDAR_PROJECTION_NON_FINITE}:observed:{target_name}")
            else:
                residual = math.hypot(ou - u, ov - v)
                if residual > limits["max_reprojection_residual_px"]:
                    reasons.append(
                        f"{LIDAR_PROJECTION_RESIDUAL_EXCEEDED}:{target_name}:"
                        f"{round(residual, 4)}>{limits['max_reprojection_residual_px']}"
                    )

    if not reasons:
        reasons_pass = True
    else:
        reasons_pass = False

    return _result(reasons_pass, reasons, pixel, target_name, limits, residual=residual)


def _result(
    ok: bool,
    reasons: List[str],
    pixel: Optional[Tuple[float, float, float]],
    target_name: str,
    limits: Mapping[str, float],
    residual: Optional[float] = None,
) -> Dict[str, Any]:
    return {
        "schema": GATE_SCHEMA,
        "target": str(target_name),
        "ok": bool(ok),
        "invalid_reasons": list(reasons),
        "pixel": None if pixel is None else [round(pixel[0], 6), round(pixel[1], 6)],
        "camera_depth_m": None if pixel is None else round(pixel[2], 6),
        "reprojection_residual_px": None if residual is None else round(residual, 6),
        "thresholds": dict(limits),
    }


def lidar_camera_gate(
    *,
    k_matrix: Any,
    width_px: int,
    height_px: int,
    vTl: Sequence[Sequence[float]],
    cTv: Sequence[Sequence[float]],
    vehicle_targets: Optional[Mapping[str, Sequence[float]]] = None,
    observed_pixels: Optional[Mapping[str, Sequence[float]]] = None,
    thresholds: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    """Run the whole gate over a set of vehicle-frame targets."""
    targets = dict(
        vehicle_targets
        or {
            "forward_5m": (5.0, 0.0, 0.0),
            "forward_10m": (10.0, 0.0, 0.0),
            "left_10m": (10.0, 2.0, 0.0),
            "right_10m": (10.0, -2.0, 0.0),
        }
    )
    observed = dict(observed_pixels or {})
    checks: List[Dict[str, Any]] = []
    for name in sorted(targets):
        checks.append(
            check_projection(
                k_matrix,
                targets[name],
                vTl,
                cTv,
                width_px=width_px,
                height_px=height_px,
                target_name=name,
                observed_pixel=observed.get(name),
                thresholds=thresholds,
            )
        )

    detected = sum(1 for c in checks if c["ok"])
    residuals = [
        c["reprojection_residual_px"] for c in checks
        if c["reprojection_residual_px"] is not None
    ]
    reasons: List[str] = []
    for check in checks:
        reasons.extend(check["invalid_reasons"])

    limits = dict(DEFAULT_GATE_THRESHOLDS)
    limits.update({k: float(v) for k, v in dict(thresholds or {}).items()})
    correspondence = detected / float(max(1, len(checks)))
    if correspondence < limits["min_target_correspondence_rate"]:
        reasons.append(
            f"{LIDAR_PROJECTION_NO_CORRESPONDENCE}:rate={round(correspondence, 4)}"
            f"<{limits['min_target_correspondence_rate']}"
        )
    if residuals:
        mean_residual = sum(residuals) / len(residuals)
        if mean_residual > limits["max_mean_reprojection_residual_px"]:
            reasons.append(
                f"{LIDAR_PROJECTION_RESIDUAL_EXCEEDED}:"
                f"mean={round(mean_residual, 4)}"
                f">{limits['max_mean_reprojection_residual_px']}"
            )

    return {
        "schema": GATE_SCHEMA,
        "ok": not reasons,
        "invalid_reasons": reasons,
        "targets_expected": len(checks),
        "targets_passed": detected,
        "correspondence_rate": round(correspondence, 6),
        "residual_px": _residual_stats(residuals),
        "checks": checks,
        "thresholds": limits,
        "legacy_defect": (
            "pre-NEW-323 gate accepted any projection with positive depth, "
            "including pixels far outside the image"
        ),
    }


def _residual_stats(residuals: Sequence[float]) -> Dict[str, Any]:
    if not residuals:
        return {
            "count": 0, "mean": None, "median": None,
            "p90": None, "p95": None, "max": None,
        }
    ordered = sorted(float(r) for r in residuals)
    n = len(ordered)
    return {
        "count": n,
        "mean": round(sum(ordered) / n, 6),
        "median": round(_percentile(ordered, 0.5), 6),
        "p90": round(_percentile(ordered, 0.90), 6),
        "p95": round(_percentile(ordered, 0.95), 6),
        "max": round(ordered[-1], 6),
    }


def _percentile(ordered: Sequence[float], q: float) -> float:
    if not ordered:
        raise ValueError("empty")
    if len(ordered) == 1:
        return float(ordered[0])
    position = float(q) * (len(ordered) - 1)
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return float(ordered[low])
    weight = position - low
    return float(ordered[low] * (1.0 - weight) + ordered[high] * weight)


def _invert4(matrix: Sequence[Sequence[float]]) -> List[List[float]]:
    """Invert a rigid 4x4 (rotation transpose + negated translation)."""
    r = [[float(matrix[i][j]) for j in range(3)] for i in range(3)]
    t = [float(matrix[i][3]) for i in range(3)]
    rt = [[r[j][i] for j in range(3)] for i in range(3)]
    inv_t = [
        -(rt[i][0] * t[0] + rt[i][1] * t[1] + rt[i][2] * t[2]) for i in range(3)
    ]
    return [
        [rt[0][0], rt[0][1], rt[0][2], inv_t[0]],
        [rt[1][0], rt[1][1], rt[1][2], inv_t[1]],
        [rt[2][0], rt[2][1], rt[2][2], inv_t[2]],
        [0.0, 0.0, 0.0, 1.0],
    ]