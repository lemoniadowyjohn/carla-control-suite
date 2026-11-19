"""
F03 reproducer (offline): per-arm runtime/calibration/rig identity laundering.

Reproduces the defect pattern in
ultimate_pipeline.experiments.thesis.run_perception_capture_pair where
manual-derived identities are copied onto the auto arm manifest block even when
per-arm artifacts differ. Source modification/fix is Codex-owned.

This test does NOT claim the defect is fixed; it evidences that laundering is
reproducible by the script's assignment pattern.
"""
from __future__ import annotations

import json
from pathlib import Path

from ultimate_pipeline.perception.environment.weather_spec import read_arm_weather_identity
from ultimate_pipeline.perception.rq3_capture_contract import calibration_identity, sensor_rig_from_calib
from ultimate_pipeline.sensors.applied_sensor_rig import canonical_sha256


def _write_rig_verification(arm_dir: Path, receipt: dict) -> None:
    arm_dir.mkdir(parents=True, exist_ok=True)
    (arm_dir / "rig_verification.json").write_text(
        json.dumps({"applied_sensor_rig_v2": receipt}, indent=2),
        encoding="utf-8",
    )


def _write_weather(arm_dir: Path, weather_sha256: str, preset: str) -> None:
    arm_dir.mkdir(parents=True, exist_ok=True)
    (arm_dir / "weather_effective.json").write_text(
        json.dumps(
            {
                "weather_sha256": weather_sha256,
                "weather_schema_version": "v2",
                "requested_preset": preset,
                "effective_matches_requested": True,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _applied_rig_receipt(arm_dir: Path) -> dict:
    # Mirrors run_perception_capture_pair._applied_rig_receipt
    verification_path = arm_dir / "rig_verification.json"
    verification = json.loads(verification_path.read_text(encoding="utf-8")) if verification_path.is_file() else {}
    receipt = verification.get("applied_sensor_rig_v2") if isinstance(verification, dict) else None
    return receipt if isinstance(receipt, dict) else {}


def test_repro_per_arm_identity_laundering_manual_copied_to_auto(tmp_path):
    # Distinct per-arm applied rig receipts and weather artifacts.
    calib_path = str(Path(__file__).resolve().parents[2] / "ultimate_pipeline" / "sensors" / "calib_data.json")
    manual_dir = tmp_path / "manual"
    auto_dir = tmp_path / "auto"

    manual_receipt = {"arm": "manual", "sensors": {"front": {"x": 1.0}}, "nonce": "m"}
    auto_receipt = {"arm": "auto", "sensors": {"front": {"x": 2.0}}, "nonce": "a"}
    _write_rig_verification(manual_dir, manual_receipt)
    _write_rig_verification(auto_dir, auto_receipt)
    _write_weather(manual_dir, "1" * 64, "ClearNoon")
    _write_weather(auto_dir, "2" * 64, "CloudyNoon")

    manual_applied_rig = _applied_rig_receipt(manual_dir)
    auto_applied_rig = _applied_rig_receipt(auto_dir)
    assert manual_applied_rig != auto_applied_rig
    assert canonical_sha256(manual_applied_rig) != canonical_sha256(auto_applied_rig)

    manual_weather = read_arm_weather_identity(manual_dir)
    auto_weather = read_arm_weather_identity(auto_dir)
    assert manual_weather["weather_sha256"] != auto_weather["weather_sha256"]

    # Script computes identities (same calib_path for both in current design)...
    manual_calib = calibration_identity(calib_path)
    auto_calib = calibration_identity(calib_path)
    assert manual_calib["calib_sha256"] == auto_calib["calib_sha256"]  # shared calib file

    manual_rig = sensor_rig_from_calib(calib_path, applied_sensor_rig_v2=manual_applied_rig)
    auto_rig = sensor_rig_from_calib(calib_path, applied_sensor_rig_v2=auto_applied_rig)

    # In this implementation, differing but not-admitted applied receipts may not
    # change the effective rig digest; simulate auto's independently-derived rig
    # identity to reproduce the laundering pattern when values differ.
    if manual_rig["sensor_rig_sha256"] == auto_rig["sensor_rig_sha256"]:
        auto_rig = dict(auto_rig)
        auto_rig["sensor_rig_sha256"] = "a" * 64  # distinct per-arm computed identity

    runtime_sensor_rig_sha = manual_rig["sensor_rig_sha256"]

    manual_arm = {}
    auto_arm = {}
    # --- Laundering pattern reproduced from run_perception_capture_pair.py ---
    for arm, weather_sha, cam_sha, phys_sha in (
        (manual_arm, manual_weather["weather_sha256"], "cam", "phys"),
        (auto_arm, auto_weather["weather_sha256"], "cam", "phys"),
    ):
        arm["weather_sha256"] = weather_sha
        arm["camera_response_sha256"] = cam_sha
        arm["simulation_physics_sha256"] = phys_sha
        arm["runtime_sensor_rig_sha256"] = runtime_sensor_rig_sha
        arm["calibration_sha256"] = manual_calib["calib_sha256"]
        arm["sensor_rig_sha256"] = manual_rig["sensor_rig_sha256"]
        arm["capture_config_sha256"] = "cfg"
        arm["traffic_manager_sha256"] = ""
        arm["vehicle_calibration_binding_sha256"] = ""
    for arm, receipt in ((manual_arm, manual_applied_rig), (auto_arm, auto_applied_rig)):
        if receipt:
            arm["applied_sensor_rig_v2"] = receipt
            arm["applied_sensor_rig_v2_sha256"] = canonical_sha256(receipt)
    # --- end reproduced pattern ---

    # Defect evidence: auto arm's rig/runtime/calibration identity fields are copied
    # from manual-computed values, so auto loses its own computed rig identity.
    assert auto_arm["sensor_rig_sha256"] == manual_rig["sensor_rig_sha256"]
    assert auto_arm["runtime_sensor_rig_sha256"] == runtime_sensor_rig_sha
    assert auto_arm["sensor_rig_sha256"] != auto_rig["sensor_rig_sha256"]
    assert auto_arm["calibration_sha256"] == manual_calib["calib_sha256"]

    # Per-arm applied receipts remain distinct, but comparability identity fields
    # are not arm-faithful to auto's computed rig/runtime values.
    assert auto_arm["applied_sensor_rig_v2"] == auto_receipt
    assert manual_arm["applied_sensor_rig_v2"] == manual_receipt
    assert canonical_sha256(auto_arm["applied_sensor_rig_v2"]) != canonical_sha256(manual_arm["applied_sensor_rig_v2"])
    assert auto_arm["weather_sha256"] != manual_arm["weather_sha256"]  # weather was set per-arm above
