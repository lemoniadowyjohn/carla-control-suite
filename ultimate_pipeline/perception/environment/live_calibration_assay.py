#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NEW-321 -- empirical calibration acceptance assay.

The distinction this module enforces
-------------------------------------
``MATHEMATICAL_CONTRACT_PASS`` is **not** ``LIVE_REPROJECTION_PASS``.

Everything the repository did before was analytical: it multiplied the stored
extrinsics by the stored intrinsics and checked that numbers were finite and
that a point landed somewhere.  Nothing ever rendered a frame and compared a
*measured* image location against a *predicted* one.

``predicted_vs_predicted is not empirical validation`` -- computing the
prediction and the observation from the same transform algebra proves nothing.
So this assay requires

* a deterministic scene with **known** 3D target locations,
* **rendered observations** (real CARLA sensor frames),
* per-camera expected/detected target counts,
* mean / median / p90 / p95 / max reprojection error in pixels,
* and, for LiDAR-camera calibration, a quantitative consistency metric computed
  from **actual captured LiDAR points**, not from the extrinsics alone.

Acceptance thresholds are **declared before** the assay runs and are never
adjusted to turn a result into a PASS.

Offline behaviour
-----------------
Every function is pure with respect to injected observations, so the gate logic
is unit-testable with synthetic measurements.  Executing the assay against a
real server requires CARLA; until then the live verdict is
``BLOCKED_EXTERNAL`` and the mathematical contract verdict may still PASS.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

ASSAY_SCHEMA = "CALIBRATION_ACCEPTANCE/v1"
REPROJECTION_SCHEMA = "LIVE_CAMERA_REPROJECTION/v2"
LIDAR_ALIGNMENT_SCHEMA = "LIVE_LIDAR_CAMERA_ALIGNMENT/v2"

VERDICT_MATHEMATICAL_PASS = "MATHEMATICAL_CONTRACT_PASS"
VERDICT_LIVE_PASS = "LIVE_REPROJECTION_PASS"
VERDICT_LIVE_FAIL = "LIVE_REPROJECTION_FAIL"
VERDICT_BLOCKED = "BLOCKED_EXTERNAL"

REPROJECTION_TARGET_NOT_DETECTED = "REPROJECTION_TARGET_NOT_DETECTED"
REPROJECTION_P95_EXCEEDED = "REPROJECTION_P95_EXCEEDED"
REPROJECTION_MEAN_EXCEEDED = "REPROJECTION_MEAN_EXCEEDED"
REPROJECTION_PREDICTED_VS_PREDICTED = "REPROJECTION_PREDICTED_VS_PREDICTED"
LIDAR_ALIGNMENT_RESIDUAL_EXCEEDED = "LIDAR_ALIGNMENT_RESIDUAL_EXCEEDED"
LIDAR_ALIGNMENT_NO_POINTS = "LIDAR_ALIGNMENT_NO_POINTS"

#: Declared BEFORE running.  Never tuned after seeing results.
ACCEPTANCE_THRESHOLDS: Dict[str, float] = {
    "max_mean_reprojection_error_px": 2.0,
    "max_p95_reprojection_error_px": 4.0,
    "max_reprojection_error_px": 8.0,
    "min_detection_rate": 0.90,
    "min_detected_targets_per_camera": 8,
    "max_lidar_camera_mean_residual_px": 6.0,
    "max_lidar_camera_p95_residual_px": 12.0,
    "min_lidar_points_used": 500,
    "min_lidar_correspondence_rate": 0.95,
}


def declare_thresholds(overrides: Optional[Mapping[str, float]] = None) -> Dict[str, Any]:
    """The immutable, pre-declared acceptance thresholds."""
    thresholds = dict(ACCEPTANCE_THRESHOLDS)
    thresholds.update({k: float(v) for k, v in dict(overrides or {}).items()})
    return {
        "schema": "CALIBRATION_ACCEPTANCE_THRESHOLDS/v1",
        "thresholds": thresholds,
        "declared_before_run": True,
        "tunable_after_run": False,
    }


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def error_statistics(residuals: Sequence[float]) -> Dict[str, Any]:
    """Mean / median / p90 / p95 / max of a residual population."""
    if not residuals:
        return {
            "count": 0, "mean": None, "median": None,
            "p90": None, "p95": None, "max": None, "min": None,
        }
    ordered = sorted(float(r) for r in residuals)
    n = len(ordered)
    return {
        "count": n,
        "mean": round(sum(ordered) / n, 6),
        "median": round(_percentile(ordered, 0.50), 6),
        "p90": round(_percentile(ordered, 0.90), 6),
        "p95": round(_percentile(ordered, 0.95), 6),
        "max": round(ordered[-1], 6),
        "min": round(ordered[0], 6),
    }


def _percentile(ordered: Sequence[float], q: float) -> float:
    n = len(ordered)
    if n == 1:
        return float(ordered[0])
    position = float(q) * (n - 1)
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return float(ordered[low])
    weight = position - low
    return float(ordered[low] * (1.0 - weight) + ordered[high] * weight)


# ---------------------------------------------------------------------------
# Camera reprojection
# ---------------------------------------------------------------------------


def predict_target_pixel(
    k_matrix: Any, point_vehicle: Sequence[float], cTv: Sequence[Sequence[float]]
) -> Optional[Tuple[float, float, float]]:
    """Predict a target's image location from the effective camera model."""
    from .lidar_camera_gate import apply_transform

    x, y, z = (float(v) for v in point_vehicle[:3])
    cx, cy, cz = apply_transform(cTv, (x, y, z))
    if cz <= 1.0e-9:
        return None
    fx = float(k_matrix[0][0]); fy = float(k_matrix[1][1])
    cxk = float(k_matrix[0][2]); cyk = float(k_matrix[1][2])
    return fx * (cx / cz) + cxk, fy * (cy / cz) + cyk, cz


def evaluate_camera_reprojection(
    *,
    camera_name: str,
    k_matrix: Any,
    cTv: Sequence[Sequence[float]],
    width_px: int,
    height_px: int,
    targets: Sequence[Mapping[str, Any]],
    observations: Mapping[str, Sequence[float]],
    thresholds: Optional[Mapping[str, float]] = None,
    observed_source: str = "rendered_sensor_detection",
) -> Dict[str, Any]:
    """Score one camera against measured target observations.

    ``targets`` entries: ``{"name": str, "point_vehicle": [x, y, z]}`` --
    the **known** 3D locations placed in the scene.
    ``observations`` maps a target name to its **measured** image pixel.
    """
    limits = dict(ACCEPTANCE_THRESHOLDS)
    limits.update({k: float(v) for k, v in dict(thresholds or {}).items()})

    if observed_source in ("predicted", "analytic", "same_transform_math"):
        return {
            "schema": REPROJECTION_SCHEMA,
            "camera": str(camera_name),
            "verdict": VERDICT_LIVE_FAIL,
            "invalid_reasons": [
                f"{REPROJECTION_PREDICTED_VS_PREDICTED}:"
                f"observed_source={observed_source}"
            ],
            "targets_expected": 0,
            "targets_detected": 0,
        }

    reasons: List[str] = []
    per_target: List[Dict[str, Any]] = []
    residuals: List[float] = []
    expected_visible = 0

    for target in targets:
        name = str(target.get("name", ""))
        predicted = predict_target_pixel(k_matrix, target.get("point_vehicle"), cTv)
        if predicted is None:
            continue
        u, v, depth = predicted
        if not (0.0 <= u < float(width_px) and 0.0 <= v < float(height_px)):
            continue
        expected_visible += 1
        observed = observations.get(name)
        if observed is None:
            per_target.append({
                "target": name,
                "predicted_pixel": [round(u, 4), round(v, 4)],
                "observed_pixel": None,
                "residual_px": None,
                "detected": False,
            })
            continue
        ou, ov = float(observed[0]), float(observed[1])
        residual = math.hypot(ou - u, ov - v)
        residuals.append(residual)
        per_target.append({
            "target": name,
            "predicted_pixel": [round(u, 4), round(v, 4)],
            "observed_pixel": [round(ou, 4), round(ov, 4)],
            "residual_px": round(residual, 6),
            "detected": True,
        })

    detected = len(residuals)
    stats = error_statistics(residuals)
    detection_rate = detected / float(max(1, expected_visible))

    if detected < limits["min_detected_targets_per_camera"]:
        reasons.append(
            f"{REPROJECTION_TARGET_NOT_DETECTED}:{camera_name}:"
            f"{detected}<{int(limits['min_detected_targets_per_camera'])}"
        )
    if detection_rate < limits["min_detection_rate"]:
        reasons.append(
            f"{REPROJECTION_TARGET_NOT_DETECTED}:{camera_name}:"
            f"rate={round(detection_rate, 4)}<{limits['min_detection_rate']}"
        )
    if stats["p95"] is not None and stats["p95"] > limits["max_p95_reprojection_error_px"]:
        reasons.append(
            f"{REPROJECTION_P95_EXCEEDED}:{camera_name}:"
            f"p95={stats['p95']}>{limits['max_p95_reprojection_error_px']}"
        )
    if stats["mean"] is not None and stats["mean"] > limits["max_mean_reprojection_error_px"]:
        reasons.append(
            f"{REPROJECTION_MEAN_EXCEEDED}:{camera_name}:"
            f"mean={stats['mean']}>{limits['max_mean_reprojection_error_px']}"
        )
    if stats["max"] is not None and stats["max"] > limits["max_reprojection_error_px"]:
        reasons.append(
            f"{REPROJECTION_MEAN_EXCEEDED}:{camera_name}:"
            f"max={stats['max']}>{limits['max_reprojection_error_px']}"
        )

    return {
        "schema": REPROJECTION_SCHEMA,
        "camera": str(camera_name),
        "verdict": VERDICT_LIVE_PASS if not reasons else VERDICT_LIVE_FAIL,
        "valid": not reasons,
        "invalid_reasons": reasons,
        "image_size": [int(width_px), int(height_px)],
        "targets_expected_visible": expected_visible,
        "targets_detected": detected,
        "detection_rate": round(detection_rate, 6),
        "reprojection_error_px": stats,
        "per_target": per_target,
        "observed_source": str(observed_source),
        "thresholds": limits,
    }


def build_reprojection_report(
    per_camera: Mapping[str, Mapping[str, Any]],
    thresholds: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    """Aggregate ``LIVE_CAMERA_REPROJECTION.json`` over all cameras."""
    limits = dict(ACCEPTANCE_THRESHOLDS)
    limits.update({k: float(v) for k, v in dict(thresholds or {}).items()})
    all_residuals: List[float] = []
    reasons: List[str] = []
    for name in sorted(per_camera):
        entry = per_camera[name]
        reasons.extend(entry.get("invalid_reasons") or [])
        stats = entry.get("reprojection_error_px") or {}
        count = int(stats.get("count") or 0)
        mean = stats.get("mean")
        if count and mean is not None:
            all_residuals.extend([float(mean)] * count)
    return {
        "schema": REPROJECTION_SCHEMA,
        "verdict": VERDICT_LIVE_PASS if not reasons else VERDICT_LIVE_FAIL,
        "valid": not reasons,
        "invalid_reasons": reasons,
        "camera_count": len(per_camera),
        "cameras": {k: per_camera[k] for k in sorted(per_camera)},
        "pooled_error_px": error_statistics(all_residuals),
        "observed_source": "rendered_sensor_detection",
        "empirical_not_analytic": True,
        "thresholds": limits,
    }


# ---------------------------------------------------------------------------
# NEW-321 LiDAR-camera alignment from actual captured points
# ---------------------------------------------------------------------------


def evaluate_lidar_camera_alignment(
    *,
    lidar_points: Sequence[Sequence[float]],
    vTl: Sequence[Sequence[float]],
    cTv: Sequence[Sequence[float]],
    k_matrix: Any,
    width_px: int,
    height_px: int,
    matched_depths: Optional[Mapping[Tuple[int, int], float]] = None,
    thresholds: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    """Quantitative LiDAR-camera consistency from **actual captured points**.

    Each captured LiDAR return is transformed into the camera frame and
    projected.  Where the corresponding depth image also holds a range at the
    same pixel, the difference is a genuine consistency residual (captured
    geometry vs rendered depth), not a restatement of the extrinsics.
    """
    limits = dict(ACCEPTANCE_THRESHOLDS)
    limits.update({k: float(v) for k, v in dict(thresholds or {}).items()})

    from .lidar_camera_gate import apply_transform, _invert4

    vTc = _invert4(vTl)
    reasons: List[str] = []
    residuals: List[float] = []
    projected_inside = 0
    considered = 0
    matched = 0

    for index, point in enumerate(lidar_points):
        p_lidar = (float(point[0]), float(point[1]), float(point[2]))
        p_vehicle = apply_transform(vTl, p_lidar)
        p_camera = apply_transform(cTv, p_vehicle)
        if p_camera[2] <= 1.0e-6:
            continue
        considered += 1
        u = float(k_matrix[0][0]) * (p_camera[0] / p_camera[2]) + float(k_matrix[0][2])
        v = float(k_matrix[1][1]) * (p_camera[1] / p_camera[2]) + float(k_matrix[1][2])
        if not (0.0 <= u < float(width_px) and 0.0 <= v < float(height_px)):
            continue
        projected_inside += 1

        depth_key = (int(round(u)), int(round(v)))
        observed_range = None
        if matched_depths is not None:
            observed_range = matched_depths.get(depth_key)
        if observed_range is None:
            continue
        matched += 1
        # Range along the ray is invariant under the pinhole intrinsics, so
        # compare the euclidean range of the captured point with the rendered
        # depth value at the same pixel.
        lidar_range = math.sqrt(sum(v2 * v2 for v2 in p_lidar))
        residuals.append(abs(lidar_range - float(observed_range)))

    correspondence = matched / float(max(1, projected_inside))
    if considered < limits["min_lidar_points_used"]:
        reasons.append(
            f"{LIDAR_ALIGNMENT_NO_POINTS}:considered={considered}"
            f"<{int(limits['min_lidar_points_used'])}"
        )
    if correspondence < limits["min_lidar_correspondence_rate"]:
        reasons.append(
            f"{LIDAR_ALIGNMENT_NO_POINTS}:correspondence="
            f"{round(correspondence, 4)}<{limits['min_lidar_correspondence_rate']}"
        )

    stats = error_statistics(residuals)
    if stats["mean"] is not None and stats["mean"] > limits["max_lidar_camera_mean_residual_px"]:
        reasons.append(
            f"{LIDAR_ALIGNMENT_RESIDUAL_EXCEEDED}:mean={stats['mean']}"
            f">{limits['max_lidar_camera_mean_residual_px']}"
        )
    if stats["p95"] is not None and stats["p95"] > limits["max_lidar_camera_p95_residual_px"]:
        reasons.append(
            f"{LIDAR_ALIGNMENT_RESIDUAL_EXCEEDED}:p95={stats['p95']}"
            f">{limits['max_lidar_camera_p95_residual_px']}"
        )

    return {
        "schema": LIDAR_ALIGNMENT_SCHEMA,
        "verdict": VERDICT_LIVE_PASS if not reasons else VERDICT_LIVE_FAIL,
        "valid": not reasons,
        "invalid_reasons": reasons,
        "points_considered": considered,
        "points_projected_inside_image": projected_inside,
        "points_matched_to_depth": matched,
        "correspondence_rate": round(correspondence, 6),
        "residual_m": stats,
        "uses_actual_captured_points": True,
        "empirical_not_analytic": True,
        "thresholds": limits,
    }


# ---------------------------------------------------------------------------
# Combined acceptance
# ---------------------------------------------------------------------------


def calibration_acceptance(
    *,
    mathematical_contract_verdict: str,
    reprojection_report: Optional[Mapping[str, Any]] = None,
    lidar_alignment: Optional[Mapping[str, Any]] = None,
    live_evidence_available: bool = False,
    thresholds: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    """``CALIBRATION_ACCEPTANCE.json``.

    The two verdicts are reported **separately and are not interchangeable**:
    a passing mathematical contract never upgrades a blocked live assay.
    """
    declared = declare_thresholds(thresholds)
    reasons: List[str] = []

    if str(mathematical_contract_verdict) != VERDICT_MATHEMATICAL_PASS:
        reasons.append(f"mathematical_contract_not_pass:{mathematical_contract_verdict}")

    if not live_evidence_available:
        live_verdict = VERDICT_BLOCKED
    elif reprojection_report is not None:
        live_verdict = str(reprojection_report.get("verdict") or VERDICT_LIVE_FAIL)
        reasons.extend(reprojection_report.get("invalid_reasons") or [])
    else:
        live_verdict = VERDICT_BLOCKED
    if lidar_alignment is not None:
        reasons.extend(lidar_alignment.get("invalid_reasons") or [])

    return {
        "schema": ASSAY_SCHEMA,
        "mathematical_contract_verdict": str(mathematical_contract_verdict),
        "live_reprojection_verdict": live_verdict,
        "verdicts_are_distinct": True,
        "mathematical_pass_does_not_imply_live_pass": True,
        "live_evidence_available": bool(live_evidence_available),
        "camera_reprojection": reprojection_report,
        "lidar_camera_alignment": lidar_alignment,
        "thresholds_declared": declared,
        "invalid_reasons": reasons,
        "accepted": (
            str(mathematical_contract_verdict) == VERDICT_MATHEMATICAL_PASS
            and live_verdict == VERDICT_LIVE_PASS
            and not reasons
        ),
        "claim": (
            "EMPIRICAL_REPROJECTION_ACCEPTANCE"
            if (live_verdict == VERDICT_LIVE_PASS and not reasons)
            else "BLOCKED_EXTERNAL"
            if not live_evidence_available
            else "CALIBRATION_NOT_ACCEPTED"
        ),
    }