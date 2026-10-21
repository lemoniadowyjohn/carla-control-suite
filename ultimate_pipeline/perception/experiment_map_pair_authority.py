#!/usr/bin/env python3
"""
Experiment Map Pair Authority — Remediated (Step 2, P0 fix).

Separated MAP_PAIR_ELIGIBLE from capture-pair validity:
A valid manual/automatic map pair does NOT imply a valid experiment.
The builder now constructs the complete candidate from real supplied data,
performs all independent predicates before proposing affirmative validity, and
only promotes an accepted claim after the strict downstream contract accepts.
Synthetic fixtures are clearly labeled; never registered as real captures.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map
from ultimate_pipeline.perception.rq3_capture_contract import (
    CLAIM_PAIRED_INGOLSTADT_CAPTURE,
    CLAIM_UNPAIRED_CAPTURE,
    CLAIM_PAIRED_PROTOCOL_VALID,
    REQUIRED_ARM_IDENTITY_KEYS,
    build_pair_manifest,
    validate_pair_manifest,
)
from ultimate_pipeline.perception.rq3_capture_contract import (  # noqa: F401  re-import strictness names
    is_ingolstadt_auto_arm,
    is_ingolstadt_manual_arm,
)


def validate_manual_arm(arm_identity: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Validate a manual arm as the governed Grid0828 reference.
    ...
    """
    errors = []
    warnings = []
    if not is_ingolstadt_manual_arm(arm_identity):
        return {"valid": False, "errors": ["Not a governed Ingolstadt manual arm (must be Grid08828)"]}
    required_fields = [
        "grid0828_source_xodr_sha256",
        "grid0828_cooked_package_sha256",
        "grid0828_runtime_identity_sha256",
    ]
    for field in required_fields:
        if not arm_identity.get(field):
            return {"valid": False, "errors": [f"Missing governed identity field: {field}"]}
    return {
        "valid": True,
        "errors": [],
        "warnings": warnings,
        "identity": dict(arm_identity),
    }


def validate_auto_arm(arm_identity: Mapping[str, Any]) -> Dict[str, Any]:
    if arm_identity.get("map_type") != "xodr":
        return {"valid": False, "errors": ["Auto arm must have map_type='xodr'"]}
    pinned = verify_pinned_map("auto_map_of_record")
    if pinned.get("verification_status") != "VERIFIED":
        return {"valid": False, "errors": ["Pinned auto_map_of_record not verified"]}
    expected_sha = pinned["sha256_actual"].lower()
    actual_sha = str(arm_identity.get("xodr_sha256", "")).lower()
    if actual_sha != expected_sha:
        return {
            "valid": False,
            "errors": [
                f"Auto arm xodr_sha256 {actual_sha} does not match pinned auto_map_of_record SHA {expected_sha}"
            ],
        }
    return {"valid": True, "errors": []}


def validate_ingolstadt_pair(
    manual_arm: Mapping[str, Any],
    auto_arm: Mapping[str, Any],
) -> Dict[str, Any]:
    errors = []
    warnings = []
    manual_result = validate_manual_arm(manual_arm)
    if not manual_result["valid"]:
        errors.extend([f"manual: {e}" for e in manual_result["errors"]])
    auto_result = validate_auto_arm(auto_arm)
    if not auto_result["valid"]:
        errors.extend([f"auto: {e}" for e in auto_result["errors"]])
    if errors:
        return {"valid": False, "errors": errors, "warnings": []}
    return {
        "valid": True,
        "errors": [],
        "warnings": [],
        "pair_identity": {"manual_arm": dict(manual_arm), "auto_arm": dict(auto_arm)},
    }


def _arm_identity_keys() -> tuple:
    return tuple(REQUIRED_ARM_IDENTITY_KEYS)


def create_experiment_manifest(
    *,
    pair_id: str,
    manual_map_identity: Mapping[str, Any],
    auto_map_identity: Mapping[str, Any],
    software_git_sha: str,
    carla_client_version: str,
    carla_server_version: str,
    calibration_sha256: str,
    sensor_rig_sha256: str,
    weather_sha256: str,
    capture_config_sha256: str,
    camera_response_sha256: str = "",
    traffic_manager_sha256: str = "",
    simulation_physics_sha256: str = "",
    runtime_sensor_rig_sha256: str = "",
    vehicle_calibration_binding_sha256: str = "",
    sim_timing_sha256: str = "",
    weather_schema_version: str = "",
    route_manifest_path: str,
    route_manifest_sha256: str,
    manual_arm: Dict[str, Any],
    auto_arm: Dict[str, Any],
    pair_valid: bool = False,
    claim_level: str = CLAIM_UNPAIRED_CAPTURE,
    invalid_reasons: Sequence[str] = (),
    capture_completion_receipt_sha256: str = "",
    terminal_status: str = "",
    accepted_pairing_keys: Optional[Sequence[int]] = None,
    dataset_content_sha256: str = "",
) -> Dict[str, Any]:
    """
    Strict manifest builder.

    Map eligibility (validate_ingolstadt_pair) is independent of capture
    completion, frame pairing identity and final paired claim. This builder
    constructs the complete candidate, validates against the strict downstream
    contract, and only publishes an accepted claim after all checks succeed.
    """
    invalid_reasons = list(invalid_reasons)

    # 1. Map-pair eligibility (independent of everything else)
    pair_validation = validate_ingolstadt_pair(manual_map_identity, auto_map_identity)
    if not pair_validation.get("valid"):
        invalid_reasons.append(f"map_pair_ineligible:{pair_validation.get('errors', [])}")
        candidate = build_pair_manifest(
            pair_id=pair_id,
            software_git_sha=software_git_sha,
            carla_client_version=carla_client_version,
            carla_server_version=carla_server_version,
            manual_map_identity=manual_map_identity,
            auto_map_identity=auto_map_identity,
            route_manifest_path=route_manifest_path,
            route_manifest_sha256=route_manifest_sha256,
            calibration_sha256=calibration_sha256,
            sensor_rig_sha256=sensor_rig_sha256,
            weather_sha256=weather_sha256,
            capture_config_sha256=capture_config_sha256,
            camera_response_sha256=camera_response_sha256,
            traffic_manager_sha256=traffic_manager_sha256,
            simulation_physics_sha256=simulation_physics_sha256,
            runtime_sensor_rig_sha256=runtime_sensor_rig_sha256,
            vehicle_calibration_binding_sha256=vehicle_calibration_binding_sha256,
            sim_timing_sha256=sim_timing_sha256,
            weather_schema_version=weather_schema_version,
            manual_arm=dict(manual_arm),
            auto_arm=dict(auto_arm),
            pair_valid=False,
            invalid_reasons=list(invalid_reasons) + ["map_pair_ineligible"],
            claim_level=CLAIM_UNPAIRED_CAPTURE,
            route_mode="THESIS_PAIRED_STRICT",
            pair_route_closure="PAIR_ROUTE_INVALID",
        )
        return candidate

    # 2. Capture-arm identity completeness (mandatory keys on BOTH arms)
    arm_identity_keys = list(_arm_identity_keys())
    for key in arm_identity_keys:
        if not manual_arm.get(key):
            invalid_reasons.append(f"manual_arm_missing_identity:{key}")
        if not auto_arm.get(key):
            invalid_reasons.append(f"auto_arm_missing_identity:{key}")
    if any("missing_identity" in r for r in invalid_reasons):
        candidate = build_pair_manifest(
            pair_id=pair_id, software_git_sha=software_git_sha,
            carla_client_version=carla_client_version, carla_server_version=carla_server_version,
            manual_map_identity=manual_map_identity, auto_map_identity=auto_map_identity,
            route_manifest_path=route_manifest_path, route_manifest_sha256=route_manifest_sha256,
            calibration_sha256=calibration_sha256, sensor_rig_sha256=sensor_rig_sha256,
            weather_sha256=weather_sha256, capture_config_sha256=capture_config_sha256,
            camera_response_sha256=camera_response_sha256,
            traffic_manager_sha256=traffic_manager_sha256,
            simulation_physics_sha256=simulation_physics_sha256,
            runtime_sensor_rig_sha256=runtime_sensor_rig_sha256,
            vehicle_calibration_binding_sha256=vehicle_calibration_binding_sha256,
            sim_timing_sha256=sim_timing_sha256, weather_schema_version=weather_schema_version,
            manual_arm=dict(manual_arm), auto_arm=dict(auto_arm),
            pair_valid=False, invalid_reasons=list(invalid_reasons),
            claim_level=CLAIM_UNPAIRED_CAPTURE, route_mode="THESIS_PAIRED_STRICT",
            pair_route_closure="PAIR_ROUTE_INVALID",
        )
        return candidate

    # 3. Cross-arm identity equality + top-level binding (strict)
    top_keys = [k for k in arm_identity_keys if locals().get(k, "") != ""]
    for key in arm_identity_keys:
        ml = manual_arm.get(key)
        al = auto_arm.get(key)
        top = locals().get(key, "")
        if ml and al and str(ml) != str(al):
            invalid_reasons.append(f"arm_identity_mismatch:{key}:{ml}!={al}")
        if top and ml and str(top) != str(ml):
            invalid_reasons.append(f"manual_vs_top_mismatch:{key}:{ml}!={top}")
        if top and al and str(top) != str(al):
            invalid_reasons.append(f"auto_vs_top_mismatch:{key}:{al}!={top}")

    # 4. Route must come from a verified artifact (no synthesized fallback path)
    if not route_manifest_path or route_manifest_path.startswith("/reference/"):
        invalid_reasons.append("route_manifest_path_synthesized_or_missing")
    if not route_manifest_sha256:
        invalid_reasons.append("route_manifest_sha256_missing")

    # 5. Capture completion / dataset identity
    if not capture_completion_receipt_sha256:
        invalid_reasons.append("capture_completion_missing")
    if not dataset_content_sha256:
        invalid_reasons.append("dataset_content_sha256_missing")
    if terminal_status and terminal_status not in ("COMPLETED", ""):
        invalid_reasons.append(f"terminal_status_invalid:{terminal_status}")

    # 6. Pairing keys must be present (not inferred from empty lists)
    if accepted_pairing_keys is None or len(accepted_pairing_keys) == 0:
        invalid_reasons.append("accepted_frame_pairing_keys_empty")

    # 7. Derive pair-validity from evidence predicates (never trust caller flag)
    derived_pair_valid = (
        len(invalid_reasons) == 0
        and bool(route_manifest_sha256)
        and bool(capture_completion_receipt_sha256)
        and (terminal_status == "COMPLETED" or not terminal_status)
        and bool(dataset_content_sha256)
        and (accepted_pairing_keys is not None and len(accepted_pairing_keys) > 0)
    )

    # 8. Build candidate with DERIVED predicate, then validate
    candidate = build_pair_manifest(
        pair_id=pair_id, software_git_sha=software_git_sha,
        carla_client_version=carla_client_version, carla_server_version=carla_server_version,
        manual_map_identity=manual_map_identity, auto_map_identity=auto_map_identity,
        route_manifest_path=route_manifest_path, route_manifest_sha256=route_manifest_sha256,
        calibration_sha256=calibration_sha256, sensor_rig_sha256=sensor_rig_sha256,
        weather_sha256=weather_sha256, capture_config_sha256=capture_config_sha256,
        camera_response_sha256=camera_response_sha256,
        traffic_manager_sha256=traffic_manager_sha256,
        simulation_physics_sha256=simulation_physics_sha256,
        runtime_sensor_rig_sha256=runtime_sensor_rig_sha256,
        vehicle_calibration_binding_sha256=vehicle_calibration_binding_sha256,
        sim_timing_sha256=sim_timing_sha256, weather_schema_version=weather_schema_version,
        manual_arm=dict(manual_arm), auto_arm=dict(auto_arm),
        pair_valid=derived_pair_valid, invalid_reasons=list(invalid_reasons),
        claim_level=CLAIM_UNPAIRED_CAPTURE,
    )
    validation = validate_pair_manifest(candidate, require_governed_environment=True)

    # 9. Only promote when the STRICT validator accepts the DERIVED candidate
    #    AND every evidence predicate holds. The caller's claim flag is never
    #    used to derive validity.
    if validation["valid"] and derived_pair_valid \
            and capture_completion_receipt_sha256 and terminal_status == "COMPLETED" \
            and dataset_content_sha256 and accepted_pairing_keys:
        candidate["pair_valid"] = True
        candidate["claim_level"] = CLAIM_PAIRED_INGOLSTADT_CAPTURE
        candidate["invalid_reasons"] = []
    else:
        candidate["pair_valid"] = False
        candidate["claim_level"] = CLAIM_UNPAIRED_CAPTURE
        merged = sorted(set(str(r) for r in (invalid_reasons + validation.get("invalid_reasons", []))))
        candidate["invalid_reasons"] = merged
    return candidate


def main() -> int:
    """CLI for validating a pair from JSON files."""
    import argparse
    parser = argparse.ArgumentParser(description="Validate an Ingolstadt experiment pair")
    parser.add_argument("--manual", type=Path, required=True, help="Manual arm identity JSON")
    parser.add_argument("--auto", type=Path, required=True, help="Auto arm identity JSON")
    args = parser.parse_args()
    from ultimate_pipeline.perception.rq3_capture_contract import MANIFEST_SCHEMA_VERSION  # noqa: F401
    manual = json.loads(args.manual.read_text(encoding="utf-8"))
    auto = json.loads(args.auto.read_text(encoding="utf-8"))
    result = validate_ingolstadt_pair(manual, auto)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
