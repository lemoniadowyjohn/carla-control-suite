#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NEW-324 -- bind the calibration to the ego vehicle geometry.

``calib_data.json`` declares a physical calibration vehicle::

    "vehicle": {"dimension": [4.915, 1.937, 1.633]}      # L, W, H in metres

Nothing in the repository ever read that field, and the perception runner
accepts any CARLA vehicle blueprint (the recorder's default is
``vehicle.audi.a2``; the pair orchestrator's is ``vehicle.tesla.model3``).
Extrinsics were therefore applied to a body whose dimensions may differ from
the body they were measured on, and the capture manifest never said so.

This module produces ``vehicle_calibration_binding.json`` and defines explicit
claim levels:

``PAIRWISE_SIM_COMPARABILITY``
    The **same** simulated vehicle on both arms.  Adequate when the research
    question is manual-vs-automatic on identical virtual geometry, even though
    that geometry differs from the physical calibration vehicle -- provided the
    limitation is recorded.

``REAL_SENSOR_RIG_GEOMETRY_REPLICA``
    Claims the simulation reproduces the physical rig's geometry.  This **must
    fail** when the blueprint is incompatible.

An arbitrary Tesla/Audi blueprint may never silently inherit the physical-rig
fidelity claim.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence

BINDING_SCHEMA = "VEHICLE_CALIBRATION_BINDING/v1"
BINDING_FILENAME = "vehicle_calibration_binding.json"
BINDING_DIGEST_FIELD = "vehicle_calibration_binding_sha256"

CLAIM_PAIRWISE_SIM = "PAIRWISE_SIM_COMPARABILITY"
CLAIM_RIG_REPLICA = "REAL_SENSOR_RIG_GEOMETRY_REPLICA"

VEHICLE_DIMENSION_MISSING = "VEHICLE_DIMENSION_MISSING"
VEHICLE_BLUEPRINT_UNKNOWN = "VEHICLE_BLUEPRINT_UNKNOWN"
VEHICLE_DIMENSION_INCOMPATIBLE = "VEHICLE_DIMENSION_INCOMPATIBLE"
VEHICLE_RIG_REPLICA_FORBIDDEN = "VEHICLE_RIG_REPLICA_FORBIDDEN"
VEHICLE_ORIGIN_ASSUMPTION_UNDECLARED = "VEHICLE_ORIGIN_ASSUMPTION_UNDECLARED"

#: Relative dimension tolerance for a geometry-replica claim.
DEFAULT_DIMENSION_TOLERANCE_PCT = 5.0
#: Absolute tolerance in metres (accounts for blueprint bounding-box padding).
DEFAULT_DIMENSION_TOLERANCE_M = 0.10

#: Assumed frame origins.  These are *assumptions*, recorded so a reviewer can
#: see them; they are not derived from the calibration file.
DEFAULT_FRAME_ORIGIN_ASSUMPTIONS: Dict[str, str] = {
    "calibration_vehicle_origin": (
        "rear-axle-centre projected onto the ground plane, vehicle x forward, "
        "y left, z up (ROS/vehicle convention)"
    ),
    "carla_actor_origin": (
        "centre of the actor bounding box at spawn (CARLA convention); "
        "NOT the rear axle"
    ),
    "origin_offset_is_undocumented_residual": (
        "the difference between the two origins is unquantified by "
        "calib_data.json and shifts every extrinsic translation"
    ),
}


def calibration_vehicle_dimension(calib_data: Mapping[str, Any]) -> Dict[str, Any]:
    """Read the declared calibration vehicle dimensions."""
    vehicle = dict(calib_data.get("vehicle") or {})
    dim = vehicle.get("dimension")
    if dim is None or len(list(dim)) < 3:
        return {
            "present": False,
            "failure_code": VEHICLE_DIMENSION_MISSING,
            "length_m": None, "width_m": None, "height_m": None,
        }
    values = [float(v) for v in list(dim)[:3]]
    return {
        "present": True,
        "failure_code": None,
        "length_m": values[0],
        "width_m": values[1],
        "height_m": values[2],
        "axis_convention": "length,width,height in metres",
    }


def blueprint_bounding_box_dimension(actor_or_bbox: Any) -> Dict[str, Any]:
    """Actual bounding-box dimensions of the spawned actor (or a bbox)."""
    bbox = getattr(actor_or_bbox, "bounding_box", actor_or_bbox)
    extent = getattr(bbox, "extent", None)
    if extent is None:
        return {"available": False, "length_m": None, "width_m": None, "height_m": None}
    try:
        x = float(extent.x) * 2.0
        y = float(extent.y) * 2.0
        z = float(extent.z) * 2.0
    except Exception:
        return {"available": False, "length_m": None, "width_m": None, "height_m": None}
    # CARLA extent axes: x forward, y right, z up.
    return {
        "available": True,
        "length_m": round(x, 6),
        "width_m": round(y, 6),
        "height_m": round(z, 6),
        "axis_convention": "carla_bounding_box_extent x2 (x fwd, y right, z up)",
    }


def compare_dimensions(
    declared: Mapping[str, Any],
    actual: Mapping[str, Any],
    *,
    tolerance_pct: float = DEFAULT_DIMENSION_TOLERANCE_PCT,
    tolerance_m: float = DEFAULT_DIMENSION_TOLERANCE_M,
) -> Dict[str, Any]:
    """Per-axis deltas between declared and actual dimensions."""
    axes = ("length_m", "width_m", "height_m")
    per_axis: List[Dict[str, Any]] = []
    worst_pct = 0.0
    comparable = True
    for axis in axes:
        want = declared.get(axis)
        got = actual.get(axis)
        if want is None or got is None:
            comparable = False
            per_axis.append({"axis": axis, "declared_m": want, "actual_m": got,
                             "delta_m": None, "delta_pct": None,
                             "within_tolerance": False})
            continue
        delta = float(got) - float(want)
        pct = (delta / float(want) * 100.0) if abs(float(want)) > 1e-9 else None
        if pct is not None:
            worst_pct = max(worst_pct, abs(pct))
        within = abs(delta) <= float(tolerance_m)
        if pct is not None and not within:
            within = abs(pct) <= float(tolerance_pct)
        per_axis.append({
            "axis": axis,
            "declared_m": round(float(want), 6),
            "actual_m": round(float(got), 6),
            "delta_m": round(delta, 6),
            "delta_pct": None if pct is None else round(pct, 4),
            "within_tolerance": bool(within),
        })
    return {
        "comparable": comparable,
        "tolerance_pct": float(tolerance_pct),
        "tolerance_m": float(tolerance_m),
        "worst_delta_pct": round(worst_pct, 4),
        "per_axis": per_axis,
        "dimensions_compatible": bool(comparable) and all(
            a["within_tolerance"] for a in per_axis
        ),
    }


def build_binding(
    calib_data: Mapping[str, Any],
    *,
    blueprint_id: str,
    spawned_actor_type_id: Optional[str] = None,
    actual_dimension: Optional[Mapping[str, Any]] = None,
    manual_blueprint_id: Optional[str] = None,
    auto_blueprint_id: Optional[str] = None,
    requested_claim: str = CLAIM_PAIRWISE_SIM,
    frame_origin_assumptions: Optional[Mapping[str, str]] = None,
    tolerance_pct: float = DEFAULT_DIMENSION_TOLERANCE_PCT,
    tolerance_m: float = DEFAULT_DIMENSION_TOLERANCE_M,
) -> Dict[str, Any]:
    """Build ``vehicle_calibration_binding.json`` for one capture arm."""
    declared = calibration_vehicle_dimension(calib_data)
    actual = dict(actual_dimension or {})
    if not actual.get("available") and actual_dimension is None:
        actual = {"available": False, "length_m": None, "width_m": None, "height_m": None}

    reasons: List[str] = []
    if not declared.get("present"):
        reasons.append(f"{VEHICLE_DIMENSION_MISSING}:calibration vehicle.dimension")
    if not str(blueprint_id or ""):
        reasons.append(f"{VEHICLE_BLUEPRINT_UNKNOWN}:blueprint_id empty")

    comparison = compare_dimensions(
        declared, actual, tolerance_pct=tolerance_pct, tolerance_m=tolerance_m
    )
    if declared.get("present") and actual.get("available") and not comparison["dimensions_compatible"]:
        reasons.append(
            f"{VEHICLE_DIMENSION_INCOMPATIBLE}:"
            f"{comparison['per_axis']}"
        )

    same_simulated_vehicle = True
    if manual_blueprint_id is not None and auto_blueprint_id is not None:
        same_simulated_vehicle = str(manual_blueprint_id) == str(auto_blueprint_id)

    assumptions = dict(frame_origin_assumptions or DEFAULT_FRAME_ORIGIN_ASSUMPTIONS)
    resolved_claim = str(requested_claim)
    claim_reasons: List[str] = []

    if resolved_claim == CLAIM_RIG_REPLICA:
        if not comparison.get("dimensions_compatible", False):
            claim_reasons.append(
                f"{VEHICLE_RIG_REPLICA_FORBIDDEN}:"
                f"blueprint={blueprint_id}:"
                f"dimensions_incompatible={comparison.get('per_axis')}"
            )
        if not str(assumptions.get("calibration_vehicle_origin")):
            claim_reasons.append(VEHICLE_ORIGIN_ASSUMPTION_UNDECLARED)
    elif resolved_claim == CLAIM_PAIRWISE_SIM:
        if not same_simulated_vehicle:
            claim_reasons.append(
                f"{VEHICLE_DIMENSION_INCOMPATIBLE}:"
                f"pairwise_sim_requires_same_simulated_vehicle:"
                f"{manual_blueprint_id}!={auto_blueprint_id}"
            )
    else:
        claim_reasons.append(f"unknown_claim_level:{resolved_claim}")

    binding: Dict[str, Any] = {
        "schema": BINDING_SCHEMA,
        "calibration_vehicle_dimension": declared,
        "carla_blueprint_id": str(blueprint_id),
        "spawned_actor_type_id": (
            str(spawned_actor_type_id) if spawned_actor_type_id is not None else None
        ),
        "spawned_type_id_matches_blueprint": (
            bool(spawned_actor_type_id == blueprint_id)
            if spawned_actor_type_id is not None
            else None
        ),
        "actual_bounding_box_dimension": actual,
        "dimensional_comparison": comparison,
        "vehicle_frame_origin_assumptions": assumptions,
        "calibration_frame_origin_assumptions": assumptions,
        "same_simulated_vehicle_both_arms": bool(same_simulated_vehicle),
        "manual_blueprint_id": manual_blueprint_id,
        "auto_blueprint_id": auto_blueprint_id,
        "requested_claim": resolved_claim,
        "claim_granted": not claim_reasons,
        "claim_reasons": claim_reasons,
        "resolved_claim": resolved_claim if not claim_reasons else "UNCLAIMED",
        "invalid_reasons": reasons + claim_reasons,
        "valid": not (reasons or claim_reasons),
        "limitation_statement": (
            "Extrinsics were measured on the declared calibration vehicle. "
            "Applying them to a different CARLA blueprint does not reproduce "
            "the physical rig geometry unless the bounding boxes are compatible "
            "and the frame-origin assumption is explicitly accepted."
        ),
    }
    binding[BINDING_DIGEST_FIELD] = _sha(
        {k: v for k, v in binding.items() if k != BINDING_DIGEST_FIELD}
    )
    return binding


def validate_claim_level(
    binding: Mapping[str, Any], *, requested_claim: str
) -> Dict[str, Any]:
    """Fail-closed: an incompatible rig must never grant rig-replica fidelity.

    In particular, using the **same** invalid calibration on both arms does not
    turn it into physical-rig PASS: pairwise comparability and physical
    fidelity are different claims.
    """
    reasons: List[str] = []
    if str(requested_claim) == CLAIM_RIG_REPLICA:
        if not bool(binding.get("dimensional_comparison", {}).get("dimensions_compatible", False)):
            reasons.append(
                f"{VEHICLE_RIG_REPLICA_FORBIDDEN}:dimensions_incompatible"
            )
        if not bool(binding.get("claim_granted", False)):
            reasons.append(f"{VEHICLE_RIG_REPLICA_FORBIDDEN}:claim_not_granted")
    elif str(requested_claim) == CLAIM_PAIRWISE_SIM:
        if not bool(binding.get("same_simulated_vehicle_both_arms", False)):
            reasons.append(
                f"{VEHICLE_DIMENSION_INCOMPATIBLE}:different_simulated_vehicle_per_arm"
            )
    else:
        reasons.append(f"unknown_claim_level:{requested_claim}")
    return {
        "valid": not reasons,
        "invalid_reasons": reasons,
        "requested_claim": str(requested_claim),
        "granted_claim": binding.get("resolved_claim"),
    }


def validate_binding_equality(
    manual: Mapping[str, Any], auto: Mapping[str, Any]
) -> Dict[str, Any]:
    """Pair arms must use the same vehicle binding digest."""
    reasons: List[str] = []
    m = str(manual.get(BINDING_DIGEST_FIELD) or "")
    a = str(auto.get(BINDING_DIGEST_FIELD) or "")
    if not m:
        reasons.append(f"{VEHICLE_DIMENSION_MISSING}:manual_{BINDING_DIGEST_FIELD}")
    if not a:
        reasons.append(f"{VEHICLE_DIMENSION_MISSING}:auto_{BINDING_DIGEST_FIELD}")
    if m and a and m != a:
        reasons.append(f"{VEHICLE_DIMENSION_INCOMPATIBLE}:binding_digest:{m}!={a}")
    return {
        "valid": not reasons,
        "invalid_reasons": reasons,
        "manual_vehicle_calibration_binding_sha256": m,
        "auto_vehicle_calibration_binding_sha256": a,
    }


def _sha(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()