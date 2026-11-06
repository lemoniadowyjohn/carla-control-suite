#!/usr/bin/env python3
"""
Task 2 (Step 2) — Builder false-PASS regression suite.
Ten rejection cases + failure-reason survival across serialization.
All fixtures are synthetic and clearly labeled; never registered as real captures.
"""
import json
from pathlib import Path

import ultimate_pipeline.perception.experiment_map_pair_authority as auth

CLAIM_PAIRED_INGOLSTADT_CAPTURE = "PAIRED_INGOLSTADT_CAPTURE"

MANUAL_MAP = {
    "map_type": "cooked_manual",
    "requested_map_name": "Grid0828",
    "grid0828_source_xodr_sha256": "sha_grid0828_source",
    "grid0828_cooked_package_sha256": "sha_grid0828_cooked",
    "grid0828_runtime_identity_sha256": "sha_grid0828_runtime",
}
AUTO_MAP = {
    "map_type": "xodr",
    "xodr_sha256": "sha_auto_xodr",
    "xodr_path": "/synthetic/auto.xodr",
}

IDENTITY = {
    "calibration_sha256": "sha_cal",
    "sensor_rig_sha256": "sha_rig",
    "weather_sha256": "sha_weather",
    "capture_config_sha256": "sha_cfg",
    "route_manifest_sha256": "sha_route",
    "camera_response_sha256": "sha_cam",
    "traffic_manager_sha256": "sha_tm",
    "simulation_physics_sha256": "sha_phys",
    "runtime_sensor_rig_sha256": "sha_rt_rig",
    "vehicle_calibration_binding_sha256": "sha_vcb",
    "sim_timing_sha256": "sha_timing",
    "pair_frame_index": "0",
}


def _eligible(monkeypatch):
    """Emulate MAP_PAIR_ELIGIBLE offline (registry-pinned auto map unavailable)."""
    monkeypatch.setattr(
        auth, "validate_ingolstadt_pair",
        lambda manual_arm, auto_arm: {"valid": True, "errors": [], "warnings": []},
    )


def _build(monkeypatch, **overrides):
    _eligible(monkeypatch)
    kwargs = dict(
        pair_id="builder_regression",
        manual_map_identity=MANUAL_MAP,
        auto_map_identity=AUTO_MAP,
        software_git_sha="sha_sw",
        carla_client_version="0.9.16",
        carla_server_version="0.9.16",
        calibration_sha256=IDENTITY["calibration_sha256"],
        sensor_rig_sha256=IDENTITY["sensor_rig_sha256"],
        weather_sha256=IDENTITY["weather_sha256"],
        capture_config_sha256=IDENTITY["capture_config_sha256"],
        camera_response_sha256=IDENTITY["camera_response_sha256"],
        traffic_manager_sha256=IDENTITY["traffic_manager_sha256"],
        simulation_physics_sha256=IDENTITY["simulation_physics_sha256"],
        runtime_sensor_rig_sha256=IDENTITY["runtime_sensor_rig_sha256"],
        vehicle_calibration_binding_sha256=IDENTITY["vehicle_calibration_binding_sha256"],
        sim_timing_sha256=IDENTITY["sim_timing_sha256"],
        route_manifest_path="/verified/route.json",
        route_manifest_sha256=IDENTITY["route_manifest_sha256"],
        manual_arm=dict(IDENTITY),
        auto_arm=dict(IDENTITY),
        capture_completion_receipt_sha256="sha_receipt",
        dataset_content_sha256="sha_dataset",
        terminal_status="COMPLETED",
        accepted_pairing_keys=[0, 1],
    )
    kwargs.update(overrides)
    return auth.create_experiment_manifest(**kwargs)


def _assert_not_promoted(manifest, expect_reason=None):
    assert manifest["pair_valid"] is False, "builder emitted a false pair_valid"
    assert manifest["claim_level"] != CLAIM_PAIRED_INGOLSTADT_CAPTURE, "claim was promoted"
    assert manifest["invalid_reasons"], "failure reasons were discarded"
    if expect_reason:
        assert any(expect_reason in r for r in manifest["invalid_reasons"]), manifest["invalid_reasons"]


def test_01_missing_calibration_rejected(monkeypatch):
    arm = dict(IDENTITY)
    del arm["calibration_sha256"]
    m = _build(monkeypatch, manual_arm=arm)
    _assert_not_promoted(m, "manual_arm_missing_identity:calibration_sha256")
    print("PASS: 01_missing_calibration_rejected")


def test_02_missing_effective_rig_rejected(monkeypatch):
    arm = dict(IDENTITY)
    del arm["sensor_rig_sha256"]
    m = _build(monkeypatch, auto_arm=arm)
    _assert_not_promoted(m, "auto_arm_missing_identity:sensor_rig_sha256")
    print("PASS: 02_missing_effective_rig_rejected")


def test_03_mismatched_weather_rejected(monkeypatch):
    m = _build(monkeypatch, auto_arm=dict(IDENTITY, weather_sha256="OTHER_WEATHER"))
    _assert_not_promoted(m, "arm_identity_mismatch:weather_sha256")
    print("PASS: 03_mismatched_weather_rejected")


def test_04_wrong_timing_rejected(monkeypatch):
    m = _build(monkeypatch, auto_arm=dict(IDENTITY, sim_timing_sha256="OTHER_TIMING"))
    _assert_not_promoted(m, "arm_identity_mismatch:sim_timing_sha256")
    print("PASS: 04_wrong_timing_rejected")


def test_05_invalid_route_rejected(monkeypatch):
    m = _build(monkeypatch, route_manifest_path="/reference/route/ingolstadt_v1.json")
    _assert_not_promoted(m, "route_manifest_path_synthesized_or_missing")
    print("PASS: 05_invalid_route_rejected")


def test_06_incomplete_frames_rejected(monkeypatch):
    m = _build(monkeypatch, accepted_pairing_keys=[])
    _assert_not_promoted(m, "accepted_frame_pairing_keys_empty")
    print("PASS: 06_incomplete_frames_rejected")


def test_07_failed_terminal_execution_rejected(monkeypatch):
    m = _build(monkeypatch, terminal_status="FAILED")
    _assert_not_promoted(m, "terminal_status")
    print("PASS: 07_failed_terminal_execution_rejected")


def test_08_missing_dataset_sha_rejected(monkeypatch):
    m = _build(monkeypatch, dataset_content_sha256="")
    _assert_not_promoted(m, "dataset_content_sha256_missing")
    print("PASS: 08_missing_dataset_sha_rejected")


def test_09_tampered_manifest_rejected(monkeypatch):
    m = _build(monkeypatch)
    m["calibration_sha256"] = "TAMPERED"
    from ultimate_pipeline.perception.rq3_capture_contract import validate_pair_manifest
    v = validate_pair_manifest(m)
    assert v["valid"] is False
    assert any("calibration_sha256" in r for r in v["invalid_reasons"]), v["invalid_reasons"]
    print("PASS: 09_tampered_manifest_rejected")


def test_10_asserted_positive_pair_valid_not_honoured(monkeypatch):
    """A caller asserting pair_valid=True must not promote the manifest."""
    m = _build(
        monkeypatch,
        pair_valid=True,
        claim_level=CLAIM_PAIRED_INGOLSTADT_CAPTURE,
        dataset_content_sha256="",
    )
    _assert_not_promoted(m, "dataset_content_sha256_missing")
    print("PASS: 10_asserted_positive_pair_valid_not_honoured")


def test_11_failure_reasons_survive_serialization(monkeypatch):
    m = _build(monkeypatch, auto_arm=dict(IDENTITY, weather_sha256="OTHER_WEATHER"))
    canonical = json.dumps(m, sort_keys=True, separators=(",", ":"))
    reloaded = json.loads(canonical)
    assert reloaded["invalid_reasons"], "reasons lost through canonical serialization"
    assert any("arm_identity_mismatch:weather_sha256" in r for r in reloaded["invalid_reasons"])
    assert reloaded["pair_valid"] is False
    assert reloaded["claim_level"] != CLAIM_PAIRED_INGOLSTADT_CAPTURE
    print("PASS: 11_failure_reasons_survive_serialization")


def test_12_validator_downgrades_claim_when_invalid(monkeypatch):
    from ultimate_pipeline.perception.rq3_capture_contract import validate_pair_manifest
    m = _build(monkeypatch, pair_valid=True, claim_level=CLAIM_PAIRED_INGOLSTADT_CAPTURE)
    v = validate_pair_manifest(m)
    assert v["valid"] is False
    assert v["claim_level"] != CLAIM_PAIRED_INGOLSTADT_CAPTURE, v
    print("PASS: 12_validator_downgrades_claim_when_invalid")


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
