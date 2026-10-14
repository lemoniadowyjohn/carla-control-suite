#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ultimate_pipeline/perception/route_execution.py

Strict route execution engine for RQ3 paired perception capture.

This module replaces the legacy apply_transform-based movement with the
governed CARLA actor transform API (set_transform) and enforces
per-pose verification with strict thresholds.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Thresholds for pose verification
STRICT_POSITION_THRESHOLD_M = 0.10  # 10 cm
STRICT_YAW_THRESHOLD_DEG = 1.0      # 1 degree

ROUTE_EXECUTION_FAILED = "ROUTE_EXECUTION_FAILED"


@dataclass(frozen=True)
class PoseEvidence:
    """Per-pose evidence record for strict route execution."""
    sequence_index: int
    requested: Dict[str, float]
    observed: Dict[str, float]
    position_error_m: float
    yaw_error_deg: float
    movement_command: str
    verified: bool
    error_reason: Optional[str] = None


def pose_from_carla_transform(transform: Any) -> Dict[str, float]:
    """Extract pose dict from a CARLA Transform."""
    loc = transform.location
    rot = transform.rotation
    return {
        "x": float(loc.x),
        "y": float(loc.y),
        "z": float(loc.z),
        "yaw": float(rot.yaw),
        "pitch": float(rot.pitch),
        "roll": float(rot.roll),
    }


def compute_position_error(requested: Dict[str, float], observed: Dict[str, float]) -> float:
    """Compute Euclidean position error between requested and observed poses."""
    dx = float(requested["x"]) - float(observed["x"])
    dy = float(requested["y"]) - float(observed["y"])
    dz = float(requested["z"]) - float(observed["z"])
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def compute_yaw_error(requested: Dict[str, float], observed: Dict[str, float]) -> float:
    """Compute wrapped yaw error in degrees."""
    yaw_r = float(requested["yaw"]) % 360.0
    yaw_o = float(observed["yaw"]) % 360.0
    diff = (yaw_r - yaw_o + 180.0) % 360.0 - 180.0
    return abs(diff)


def carla_transform_from_pose(pose: Dict[str, float], z_offset: float = 0.0) -> Any:
    """Build a CARLA Transform from a pose dict."""
    import carla  # type: ignore
    return carla.Transform(
        carla.Location(
            x=float(pose["x"]),
            y=float(pose["y"]),
            z=float(pose["z"]) + float(z_offset),
        ),
        carla.Rotation(
            yaw=float(pose["yaw"]),
            pitch=float(pose.get("pitch", 0.0)),
            roll=float(pose.get("roll", 0.0)),
        ),
    )


def execute_route_strict(
    ego: Any,
    world: Any,
    route_poses: List[Dict[str, Any]],
    *,
    z_offset: float = 0.0,
    position_threshold_m: float = STRICT_POSITION_THRESHOLD_M,
    yaw_threshold_deg: float = STRICT_YAW_THRESHOLD_DEG,
    tick_timeout_s: float = 5.0,
) -> Tuple[List[PoseEvidence], Optional[str]]:
    """
    Execute a strict route by commanding each pose via set_transform and verifying.

    Returns:
        Tuple of (pose_evidence_list, failure_reason).
        If failure_reason is not None, execution halted at that pose.
    """
    evidence_list: List[PoseEvidence] = []

    # Verify ego actor has set_transform
    if not hasattr(ego, "set_transform"):
        return [], f"ego_actor_missing_set_transform:{type(ego).__name__}"

    for pose in route_poses:
        seq = int(pose["sequence_index"])
        requested = {
            "x": float(pose["x"]),
            "y": float(pose["y"]),
            "z": float(pose["z"]),
            "yaw": float(pose["yaw"]),
            "pitch": float(pose.get("pitch", 0.0)),
            "roll": float(pose.get("roll", 0.0)),
        }

        # 1. Command the transform
        target_tf = carla_transform_from_pose(requested, z_offset)
        try:
            ego.set_transform(target_tf)
        except Exception as exc:
            evidence = PoseEvidence(
                sequence_index=seq,
                requested=requested,
                observed={},
                position_error_m=float("inf"),
                yaw_error_deg=float("inf"),
                movement_command="set_transform",
                verified=False,
                error_reason=f"set_transform_raised:{type(exc).__name__}:{exc}",
            )
            evidence_list.append(evidence)
            return evidence_list, f"set_transform_failed_at_seq_{seq}:{exc}"

        # 2. Advance simulation exactly once (synchronous mode assumed)
        try:
            world.tick()
        except Exception as exc:
            evidence = PoseEvidence(
                sequence_index=seq,
                requested=requested,
                observed={},
                position_error_m=float("inf"),
                yaw_error_deg=float("inf"),
                movement_command="set_transform",
                verified=False,
                error_reason=f"world_tick_failed:{type(exc).__name__}:{exc}",
            )
            evidence_list.append(evidence)
            return evidence_list, f"world_tick_failed_at_seq_{seq}:{exc}"

        # 3. Read observed transform
        try:
            observed_tf = ego.get_transform()
        except Exception as exc:
            evidence = PoseEvidence(
                sequence_index=seq,
                requested=requested,
                observed={},
                position_error_m=float("inf"),
                yaw_error_deg=float("inf"),
                movement_command="set_transform",
                verified=False,
                error_reason=f"get_transform_failed:{type(exc).__name__}:{exc}",
            )
            evidence_list.append(evidence)
            return evidence_list, f"observed_transform_unavailable_at_seq_{seq}:{exc}"

        observed = pose_from_carla_transform(observed_tf)

        # 4. Compute errors
        pos_err = compute_position_error(requested, observed)
        yaw_err = compute_yaw_error(requested, observed)

        # 5. Compare with strict thresholds
        pos_ok = pos_err <= position_threshold_m
        yaw_ok = yaw_err <= yaw_threshold_deg
        verified = pos_ok and yaw_ok

        evidence = PoseEvidence(
            sequence_index=seq,
            requested=requested,
            observed=observed,
            position_error_m=pos_err,
            yaw_error_deg=yaw_err,
            movement_command="set_transform",
            verified=verified,
            error_reason=None if verified else (
                f"pos_err_{pos_err:.6f}>{position_threshold_m}"
                if not pos_ok else
                f"yaw_err_{yaw_err:.6f}>{yaw_threshold_deg}"
            ),
        )
        evidence_list.append(evidence)

        if not verified:
            return evidence_list, f"pose_verification_failed_at_seq_{seq}:{evidence.error_reason}"

    return evidence_list, None


def write_pose_evidence(path: str, evidence_list: List[PoseEvidence]) -> None:
    """Write per-pose evidence to JSON file."""
    data = {
        "schema_version": "route_execution_evidence_v1",
        "pose_count": len(evidence_list),
        "all_verified": all(e.verified for e in evidence_list),
        "poses": [
            {
                "sequence_index": e.sequence_index,
                "requested": e.requested,
                "observed": e.observed,
                "position_error_m": e.position_error_m,
                "yaw_error_deg": e.yaw_error_deg,
                "movement_command": e.movement_command,
                "verified": e.verified,
                "error_reason": e.error_reason,
            }
            for e in evidence_list
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def validate_route_execution_evidence(evidence_list: List[PoseEvidence]) -> List[str]:
    """Validate that all poses were verified. Returns list of failure reasons."""
    reasons = []
    for e in evidence_list:
        if not e.verified:
            reasons.append(f"seq_{e.sequence_index}: {e.error_reason}")
    return reasons