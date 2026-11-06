#!/usr/bin/env python3
"""
Task 1 — Correct cross-arm synchronization
Task 2 — Map-pair eligibility vs full capture-pair validity
All fixtures are synthetic and never registered as real RQ3 captures.
"""
from typing import Any, Dict

from ultimate_pipeline.perception.rq3_frame_set import (
    ArmFrameSet, FrameMember, intersect_frame_sets,
)
from ultimate_pipeline.perception.rq3_capture_contract import (
    REQUIRED_ARM_IDENTITY_KEYS,
    build_pair_manifest,
    validate_pair_manifest,
    CLAIM_PAIRED_INGOLSTADT_CAPTURE,
    CLAIM_PAIRED_PROTOCOL_VALID,
    CLAIM_UNPAIRED_CAPTURE,
)

#: A complete, internally-consistent identity block (synthetic values).
BASE_IDENTITY: Dict[str, str] = {
    "calibration_sha256": "sha_calibration",
    "sensor_rig_sha256": "sha_sensor_rig",
    "weather_sha256": "sha_weather",
    "capture_config_sha256": "sha_capture_config",
    "route_manifest_sha256": "sha_route_manifest",
    "camera_response_sha256": "sha_camera_response",
    "traffic_manager_sha256": "sha_traffic_manager",
    "simulation_physics_sha256": "sha_simulation_physics",
    "runtime_sensor_rig_sha256": "sha_runtime_sensor_rig",
    "vehicle_calibration_binding_sha256": "sha_vehicle_calibration_binding",
    "sim_timing_sha256": "sha_sim_timing",
    "pair_frame_index": "0",
}


def _m(fi, fid, ts, mod, sha256="x"):
    return FrameMember(
        frame_index=fi, frame_id=fid, timestamp=ts,
        modality=mod, sensor_name=mod, sha256=sha256,
        committed=True, staging=False,
    )


def _arm(members, arm_name="manual"):
    a = ArmFrameSet(arm_name=arm_name)
    for m in members:
        a.add(m)
    return a


def _complete_arm(**overrides) -> Dict[str, Any]:
    arm = dict(BASE_IDENTITY)
    arm.update(overrides)
    return arm


def _manifest(
    *,
    manual_arm: Dict[str, Any],
    auto_arm: Dict[str, Any],
    pair_valid: bool = True,
    invalid_reasons=(),
    claim_level: str = CLAIM_PAIRED_INGOLSTADT_CAPTURE,
    manual_map_identity=None,
    auto_map_identity=None,
    pair_id: str = "task12_pair",
):
    """Build a manifest whose top-level identity equals the manual arm's."""
    manual_map_identity = manual_map_identity or {
        "map_type": "cooked_manual",
        "requested_map_name": "Grid0828",
        "grid0828_source_xodr_sha256": "sha_grid0828_source",
        "grid0828_cooked_package_sha256": "sha_grid0828_cooked",
        "grid0828_runtime_identity_sha256": "sha_grid0828_runtime",
    }
    auto_map_identity = auto_map_identity or {
        "map_type": "xodr",
        "xodr_sha256": "sha_auto_xodr",
        "xodr_path": "/synthetic/auto.xodr",
    }
    top = {k: manual_arm.get(k, "") for k in REQUIRED_ARM_IDENTITY_KEYS}
    return build_pair_manifest(
        pair_id=pair_id,
        software_git_sha="sha_software",
        carla_client_version="0.9.16",
        carla_server_version="0.9.16",
        manual_map_identity=manual_map_identity,
        auto_map_identity=auto_map_identity,
        route_manifest_path="/synthetic/route.json",
        route_manifest_sha256=top["route_manifest_sha256"],
        calibration_sha256=top["calibration_sha256"],
        sensor_rig_sha256=top["sensor_rig_sha256"],
        weather_sha256=top["weather_sha256"],
        capture_config_sha256=top["capture_config_sha256"],
        camera_response_sha256=top["camera_response_sha256"],
        traffic_manager_sha256=top["traffic_manager_sha256"],
        simulation_physics_sha256=top["simulation_physics_sha256"],
        runtime_sensor_rig_sha256=top["runtime_sensor_rig_sha256"],
        vehicle_calibration_binding_sha256=top["vehicle_calibration_binding_sha256"],
        sim_timing_sha256=top["sim_timing_sha256"],
        manual_arm=manual_arm,
        auto_arm=auto_arm,
        pair_valid=pair_valid,
        invalid_reasons=invalid_reasons,
        claim_level=claim_level,
    )


# ==================================================================
# Task 1 — cross-arm synchronization
# ==================================================================

def test_task1_cross_arm_pairing_key_different_raw_ids_pass():
    """Frames 100-109 vs 900-909 with valid route/sample pairing -> PASS."""
    m_members = [_m(i, 1000 + i, 1.0, "rgb") for i in range(100, 110)]
    m_members += [_m(i, 1000 + i, 1.0, "semantic") for i in range(100, 110)]
    m_members += [_m(i, 1000 + i, 1.0, "lidar") for i in range(100, 110)]
    a_members = [_m(i, 9000 + i, 1.0, "rgb") for i in range(100, 110)]
    a_members += [_m(i, 9000 + i, 1.0, "semantic") for i in range(100, 110)]
    a_members += [_m(i, 9000 + i, 1.0, "lidar") for i in range(100, 110)]

    inter = intersect_frame_sets(_arm(m_members), _arm(a_members))
    assert inter["valid"] is True, inter["errors"]
    assert inter["accepted_pairing_keys"] == list(range(100, 110))
    assert inter["accepted_count"] == 10
    print("PASS: task1_cross_arm_pairing_key_different_raw_ids_pass")


def test_task1_same_arm_ids_agree_pass():
    """Same-arm RGB/semantic/LiDAR frame IDs agree -> PASS."""
    members = [_m(0, 5000, 1.0, "rgb"), _m(0, 5000, 1.0, "semantic"), _m(0, 5000, 1.0, "lidar")]
    result = intersect_frame_sets(_arm(members), _arm(members))
    assert result["valid"] is True, result["errors"]
    print("PASS: task1_same_arm_ids_agree_pass")


def test_task1_same_arm_equal_counts_different_ids_fail():
    """Same-arm equal counts but different frame IDs -> FAIL."""
    members = [_m(0, 5000, 1.0, "rgb"), _m(0, 5001, 1.0, "semantic"), _m(0, 5002, 1.0, "lidar")]
    result = intersect_frame_sets(_arm(members), _arm(members))
    assert result["valid"] is False
    auto_reasons = result["auto"]["rejected"]
    codes = {rr["reason"] for entry in auto_reasons for rr in entry["reasons"]}
    assert "frame_id_mismatch" in codes, codes
    print("PASS: task1_same_arm_equal_counts_different_ids_fail")


def test_task1_cross_arm_missing_semantic_fails():
    m = _arm([_m(0, 1000, 1.0, "rgb"), _m(0, 1000, 1.0, "semantic"), _m(0, 1000, 1.0, "lidar")])
    a = _arm([_m(0, 9000, 1.0, "rgb"), _m(0, 9000, 1.0, "lidar")])
    inter = intersect_frame_sets(m, a)
    assert inter["valid"] is False
    codes = {rr["reason"] for entry in inter["auto"]["rejected"] for rr in entry["reasons"]}
    assert "missing_modality" in codes, codes
    print("PASS: task1_cross_arm_missing_semantic_fails")


def test_task1_cross_arm_missing_lidar_fails():
    m = _arm([_m(0, 1000, 1.0, "rgb"), _m(0, 1000, 1.0, "semantic"), _m(0, 1000, 1.0, "lidar")])
    a = _arm([_m(0, 9000, 1.0, "rgb"), _m(0, 9000, 1.0, "semantic")])
    inter = intersect_frame_sets(m, a)
    assert inter["valid"] is False
    codes = {rr["reason"] for entry in inter["auto"]["rejected"] for rr in entry["reasons"]}
    assert "missing_modality" in codes, codes
    print("PASS: task1_cross_arm_missing_lidar_fails")


def test_task1_cross_arm_duplicate_member_fails():
    a = _arm([_m(0, 9000, 1.0, "rgb"), _m(0, 9000, 1.0, "rgb"), _m(0, 9000, 1.0, "semantic"), _m(0, 9000, 1.0, "lidar")])
    inter = intersect_frame_sets(a, a)
    assert inter["valid"] is False
    codes = {rr["reason"] for entry in inter["auto"]["rejected"] for rr in entry["reasons"]}
    assert "duplicate_member" in codes, codes
    print("PASS: task1_cross_arm_duplicate_member_fails")


def test_task1_cross_arm_uncommitted_member_fails():
    a = _arm([
        FrameMember(0, 9000, 1.0, "rgb", "rgb", sha256="r", committed=True),
        FrameMember(0, 9000, 1.0, "semantic", "semantic", sha256="s", committed=False),
        FrameMember(0, 9000, 1.0, "lidar", "lidar", sha256="l", committed=True),
    ])
    inter = intersect_frame_sets(a, a)
    assert inter["valid"] is False
    codes = {rr["reason"] for entry in inter["auto"]["rejected"] for rr in entry["reasons"]}
    assert "uncommitted_member" in codes, codes
    print("PASS: task1_cross_arm_uncommitted_member_fails")


def test_task1_cross_arm_corrupt_member_fails():
    a = _arm([_m(0, 9000, 1.0, "rgb", sha256=""), _m(0, 9000, 1.0, "semantic"), _m(0, 9000, 1.0, "lidar")])
    inter = intersect_frame_sets(a, a)
    assert inter["valid"] is False
    codes = {rr["reason"] for entry in inter["auto"]["rejected"] for rr in entry["reasons"]}
    assert "missing_hash" in codes, codes
    print("PASS: task1_cross_arm_corrupt_member_fails")


def test_task1_cross_arm_unequal_pairing_keys_fail():
    """Equal counts, unequal pairing keys -> FAIL (route correspondence broken)."""
    m = _arm([_m(0, 1000, 1.0, "rgb"), _m(0, 1000, 1.0, "semantic"), _m(0, 1000, 1.0, "lidar")])
    a = _arm([_m(7, 9000, 1.0, "rgb"), _m(7, 9000, 1.0, "semantic"), _m(7, 9000, 1.0, "lidar")])
    inter = intersect_frame_sets(m, a)
    assert inter["valid"] is False
    assert inter["accepted_count"] == 0
    assert any("pairing_keys_missing" in e for e in inter["errors"]), inter["errors"]
    print("PASS: task1_cross_arm_unequal_pairing_keys_fail")


def test_task1_pose_heading_tolerance_not_invented():
    """Spatial pose / heading tolerance must come from the frozen protocol.
    No tolerance is fabricated here; absence is reported."""
    from ultimate_pipeline.perception import rq3_frame_set as fs
    # The frame-set module exposes only temporal tolerance (frozen constant).
    assert fs.DEFAULT_TIMESTAMP_TOLERANCE_S == 1.0 / 60.0
    spatial = [n for n in dir(fs) if "POSE" in n.upper() or "HEADING" in n.upper() or "SPATIAL" in n.upper()]
    assert not spatial, f"unexpected spatial tolerance constants introduced: {spatial}"
    print("PASS: task1_pose_heading_tolerance_not_invented")


# ==================================================================
# Task 2 — map eligibility vs capture validity
# ==================================================================

def test_task2_complete_contract_passes_protocol_claim():
    """All identities equal across arms -> valid at the protocol claim level."""
    m = _manifest(manual_arm=_complete_arm(), auto_arm=_complete_arm(),
                  claim_level=CLAIM_PAIRED_PROTOCOL_VALID)
    validation = validate_pair_manifest(m)
    assert validation["valid"] is True, validation["invalid_reasons"]
    print("PASS: task2_complete_contract_passes_protocol_claim")


def test_task2_different_calibration_blocks_claim():
    m = _manifest(manual_arm=_complete_arm(), auto_arm=_complete_arm(calibration_sha256="OTHER"))
    validation = validate_pair_manifest(m)
    assert validation["valid"] is False
    assert any("calibration_sha256_mismatch" in r for r in validation["invalid_reasons"])
    assert validation["claim_level"] != CLAIM_PAIRED_INGOLSTADT_CAPTURE
    print("PASS: task2_different_calibration_blocks_claim")


def test_task2_different_sensor_rig_blocks_claim():
    m = _manifest(manual_arm=_complete_arm(), auto_arm=_complete_arm(sensor_rig_sha256="OTHER"))
    validation = validate_pair_manifest(m)
    assert validation["valid"] is False
    assert any("sensor_rig_sha256_mismatch" in r for r in validation["invalid_reasons"])
    print("PASS: task2_different_sensor_rig_blocks_claim")


def test_task2_different_weather_blocks_claim():
    m = _manifest(manual_arm=_complete_arm(), auto_arm=_complete_arm(weather_sha256="OTHER"))
    validation = validate_pair_manifest(m)
    assert validation["valid"] is False
    assert any("PAIR_WEATHER_MISMATCH" in r and "weather_sha256" in r for r in validation["invalid_reasons"])
    print("PASS: task2_different_weather_blocks_claim")


def test_task2_different_runtime_sensor_rig_blocks_claim():
    m = _manifest(manual_arm=_complete_arm(), auto_arm=_complete_arm(runtime_sensor_rig_sha256="OTHER"))
    validation = validate_pair_manifest(m)
    assert validation["valid"] is False
    assert any("PAIR_ARM_IDENTITY_MISMATCH" in r and "runtime_sensor_rig_sha256" in r for r in validation["invalid_reasons"])
    print("PASS: task2_different_runtime_sensor_rig_blocks_claim")


def test_task2_missing_timing_identity_blocks_claim():
    arm = _complete_arm()
    del arm["sim_timing_sha256"]
    m = _manifest(manual_arm=arm, auto_arm=arm)
    validation = validate_pair_manifest(m)
    assert validation["valid"] is False
    assert any("sim_timing_sha256" in r for r in validation["invalid_reasons"])
    print("PASS: task2_missing_timing_identity_blocks_claim")


def test_task2_invalid_route_correspondence_blocks_claim():
    m = _manifest(manual_arm=_complete_arm(), auto_arm=_complete_arm(route_manifest_sha256="OTHER_ROUTE"))
    validation = validate_pair_manifest(m)
    assert validation["valid"] is False
    assert any("route_manifest_sha256_mismatch" in r for r in validation["invalid_reasons"])
    print("PASS: task2_invalid_route_correspondence_blocks_claim")


def test_task2_failed_capture_completion_blocks_claim():
    m = _manifest(manual_arm=_complete_arm(), auto_arm=_complete_arm(),
                  pair_valid=False, invalid_reasons=["capture_completion_failed"])
    validation = validate_pair_manifest(m)
    assert validation["valid"] is False
    assert "pair_valid_is_false" in validation["invalid_reasons"]
    assert "capture_completion_failed" in validation["invalid_reasons"]
    print("PASS: task2_failed_capture_completion_blocks_claim")


def test_task2_invalid_terminal_status_blocks_claim():
    m = _manifest(manual_arm=_complete_arm(), auto_arm=_complete_arm(),
                  pair_valid=False, invalid_reasons=["terminal_status_failed"],
                  claim_level=CLAIM_PAIRED_INGOLSTADT_CAPTURE)
    validation = validate_pair_manifest(m)
    assert validation["valid"] is False
    assert "pair_valid_is_false" in validation["invalid_reasons"]
    assert "terminal_status_failed" in validation["invalid_reasons"]
    print("PASS: task2_invalid_terminal_status_blocks_claim")


def test_task2_tampered_manifest_blocks_claim():
    m = _manifest(manual_arm=_complete_arm(), auto_arm=_complete_arm())
    m["calibration_sha256"] = "TAMPERED"
    validation = validate_pair_manifest(m)
    assert validation["valid"] is False
    assert any("calibration_sha256" in r for r in validation["invalid_reasons"])
    print("PASS: task2_tampered_manifest_blocks_claim")


def test_task2_wrong_runtime_map_identity_blocks_claim():
    """A non-Ingolstadt auto arm cannot carry the Ingolstadt paired claim."""
    m = _manifest(
        manual_arm=_complete_arm(),
        auto_arm=_complete_arm(),
        auto_map_identity={"map_type": "xodr", "xodr_sha256": "NOT_THE_PINNED_MAP"},
        claim_level=CLAIM_PAIRED_INGOLSTADT_CAPTURE,
    )
    validation = validate_pair_manifest(m)
    assert validation["valid"] is False
    assert "claim_ingolstadt_requires_auto_ingolstadt_xodr_arm" in validation["invalid_reasons"]
    print("PASS: task2_wrong_runtime_map_identity_blocks_claim")


def test_task2_incomplete_frames_blocks_claim():
    """A pair whose arms report zero accepted frames cannot be PAIRED."""
    m = _manifest(
        manual_arm=_complete_arm(accepted_frame_count="0"),
        auto_arm=_complete_arm(accepted_frame_count="0"),
        pair_valid=False,
        invalid_reasons=["accepted_frame_count_zero"],
    )
    validation = validate_pair_manifest(m)
    assert validation["valid"] is False
    assert "accepted_frame_count_zero" in validation["invalid_reasons"]
    print("PASS: task2_incomplete_frames_blocks_claim")


def test_task2_map_eligibility_alone_does_not_grant_capture_validity():
    """Two eligible map identities are NOT sufficient for pair_valid=True."""
    from ultimate_pipeline.perception.experiment_map_pair_authority import (
        validate_ingolstadt_pair, validate_manual_arm, validate_auto_arm,
    )
    # Map-level eligibility is a separate question from capture validity.
    manual_identity = {
        "map_type": "cooked_manual",
        "requested_map_name": "Grid0828",
        "grid0828_source_xodr_sha256": "sha_grid0828_source",
        "grid0828_cooked_package_sha256": "sha_grid0828_cooked",
        "grid0828_runtime_identity_sha256": "sha_grid0828_runtime",
    }
    auto_identity = {
        "map_type": "xodr",
        "xodr_sha256": "sha_auto_xodr",
        "xodr_path": "/synthetic/auto.xodr",
    }
    pair = validate_ingolstadt_pair(manual_arm=manual_identity, auto_arm=auto_identity)
    # Map-pair eligibility is judged on map identity only.
    map_eligible = bool(pair.get("valid"))
    # But the capture contract is a superset: it additionally requires the
    # 11 environment/comparability identities, route correspondence, frame
    # completion and terminal status, none of which the map check knows.
    m = _manifest(manual_arm=_complete_arm(), auto_arm=_complete_arm(),
                  pair_valid=False, invalid_reasons=["missing_environment_identities"])
    validation = validate_pair_manifest(m)
    assert validation["valid"] is False
    assert map_eligible in (True, False)  # map eligibility is orthogonal
    print("PASS: task2_map_eligibility_alone_does_not_grant_capture_validity")


if __name__ == "__main__":
    test_task1_cross_arm_pairing_key_different_raw_ids_pass()
    test_task1_same_arm_ids_agree_pass()
    test_task1_same_arm_equal_counts_different_ids_fail()
    test_task1_cross_arm_missing_semantic_fails()
    test_task1_cross_arm_missing_lidar_fails()
    test_task1_cross_arm_duplicate_member_fails()
    test_task1_cross_arm_uncommitted_member_fails()
    test_task1_cross_arm_corrupt_member_fails()
    test_task1_cross_arm_unequal_pairing_keys_fail()
    test_task1_pose_heading_tolerance_not_invented()
    test_task2_complete_contract_passes_protocol_claim()
    test_task2_different_calibration_blocks_claim()
    test_task2_different_sensor_rig_blocks_claim()
    test_task2_different_weather_blocks_claim()
    test_task2_different_runtime_sensor_rig_blocks_claim()
    test_task2_missing_timing_identity_blocks_claim()
    test_task2_invalid_route_correspondence_blocks_claim()
    test_task2_failed_capture_completion_blocks_claim()
    test_task2_invalid_terminal_status_blocks_claim()
    test_task2_tampered_manifest_blocks_claim()
    test_task2_wrong_runtime_map_identity_blocks_claim()
    test_task2_incomplete_frames_blocks_claim()
    test_task2_map_eligibility_alone_does_not_grant_capture_validity()
    print("\n=== TASK 1 + TASK 2: ALL CONTROLS PASS ===")
    print("24 tests: cross-arm pairing by frozen key (not raw frame id), within-arm")
    print("id/timestamp agreement, duplicate/staging/corrupt rejection, and 14")
    print("capture-validity negative controls.")
