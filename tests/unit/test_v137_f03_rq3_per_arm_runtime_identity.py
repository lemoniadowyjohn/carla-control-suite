"""
V137 F03 — RQ3 per-arm runtime identity (test-only reproducer/verification).

Covers:
- Each arm binds independently observed sensor receipts.
- Auto-arm rig mutation cannot be hidden by copying the manual-arm identity.
- Swapped receipt identities are rejected.
- Missing dataset bindings fail closed.
- Identical configurations may legitimately have identical configuration hashes.
- Runtime evidence identities cannot be copied without corresponding observations.

Red-before reproducer included for the script-level laundering defect in
ultimate_pipeline.experiments.thesis.run_perception_capture_pair (Codex-owned
source; no runtime/source fix in this lane). Do not integrate deliberately
failing regressions into a green staging candidate before corresponding source
repair is available.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from ultimate_pipeline.perception import rq3_capture_contract as rq3
from ultimate_pipeline.perception.environment.weather_spec import read_arm_weather_identity
from ultimate_pipeline.sensors.applied_sensor_rig import canonical_sha256
from ultimate_pipeline.tests.unit.rq3_v2_test_receipts import (
    CALIBRATION_PATH,
    CALIBRATION_SHA256,
    TEST_COMMIT,
    complete_synthetic_arm,
)

BATCH9_REQUIRED = tuple(rq3.REQUIRED_ARM_IDENTITY_KEYS)


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
    verification_path = arm_dir / "rig_verification.json"
    verification = json.loads(verification_path.read_text(encoding="utf-8")) if verification_path.is_file() else {}
    receipt = verification.get("applied_sensor_rig_v2") if isinstance(verification, dict) else None
    return receipt if isinstance(receipt, dict) else {}


def _valid_pair_manifest(*, manual_dataset="manual-dataset", auto_dataset="auto-dataset",
                         manual_sha="c" * 64, auto_sha="d" * 64, rig_sha=None):
    manual = complete_synthetic_arm(
        {"dataset_identity": manual_dataset, "dataset_artifact_sha256": manual_sha},
        code_commit=TEST_COMMIT, label="manual",
    )
    auto = complete_synthetic_arm(
        {"dataset_identity": auto_dataset, "dataset_artifact_sha256": auto_sha},
        code_commit=TEST_COMMIT, label="auto",
    )
    if rig_sha is None:
        rig_sha = manual["sensor_rig_sha256"]
    base = {k: "v" for k in BATCH9_REQUIRED}
    base["calibration_sha256"] = CALIBRATION_SHA256
    base["sensor_rig_sha256"] = rig_sha
    manifest = {
        "schema_version": rq3.MANIFEST_SCHEMA_VERSION,
        "pair_id": "p-v137-f03",
        "claim_level": rq3.CLAIM_PAIRED_PROTOCOL_VALID,
        "pair_frame_index": [0, 1, 2],
        "software_git_sha": TEST_COMMIT,
        "manual_map_identity": rq3.cooked_arm_map_identity(
            requested_map_name="Grid0828", resolved_carla_map_name="Grid0828",
        ),
        "auto_map_identity": rq3.xodr_arm_map_identity(
            xodr_path="campaigns/ingolstadt_auto.xodr", xodr_sha256="x",
        ),
        "pair_valid": True,
        "invalid_reasons": [],
        "manual_arm": dict(
            base, completion_status=rq3.COMPLETION_PASS,
            dataset_identity=manual_dataset, dataset_artifact_sha256=manual_sha,
            applied_sensor_rig_v2=manual["applied_sensor_rig_v2"],
            applied_sensor_rig_v2_sha256=manual["applied_sensor_rig_v2_sha256"],
            calibration_path=str(CALIBRATION_PATH),
        ),
        "auto_arm": dict(
            base, completion_status=rq3.COMPLETION_PASS,
            dataset_identity=auto_dataset, dataset_artifact_sha256=auto_sha,
            applied_sensor_rig_v2=auto["applied_sensor_rig_v2"],
            applied_sensor_rig_v2_sha256=auto["applied_sensor_rig_v2_sha256"],
            calibration_path=str(CALIBRATION_PATH),
        ),
        **{k: "v" for k in BATCH9_REQUIRED},
        "calibration_sha256": CALIBRATION_SHA256,
        "calibration_path": str(CALIBRATION_PATH),
        "sensor_rig_sha256": rig_sha,
    }
    return manifest, manual, auto


# --- Red-before reproducer (defect in run_perception_capture_pair.py) ---

def test_red_before_script_launders_auto_arm_rig_runtime_identity_from_manual(tmp_path):
    """
    RED-BEFORE (current script defect): run_perception_capture_pair copies
    manual-derived sensor_rig_sha256/runtime_sensor_rig_sha256 onto the auto arm.
    Correct behavior: auto arm must retain its own independently computed rig/runtime
    identity bound to its own observed/applied receipt.
    """
    calib_path = str(CALIBRATION_PATH)
    manual_dir = tmp_path / "manual"
    auto_dir = tmp_path / "auto"

    manual_receipt = {"arm": "manual", "nonce": "m"}
    auto_receipt = {"arm": "auto", "nonce": "a"}
    _write_rig_verification(manual_dir, manual_receipt)
    _write_rig_verification(auto_dir, auto_receipt)
    _write_weather(manual_dir, "1" * 64, "ClearNoon")
    _write_weather(auto_dir, "2" * 64, "CloudyNoon")

    manual_applied_rig = _applied_rig_receipt(manual_dir)
    auto_applied_rig = _applied_rig_receipt(auto_dir)
    assert manual_applied_rig != auto_applied_rig

    manual_calib = rq3.calibration_identity(calib_path)
    manual_rig = rq3.sensor_rig_from_calib(calib_path, applied_sensor_rig_v2=manual_applied_rig)
    auto_rig = rq3.sensor_rig_from_calib(calib_path, applied_sensor_rig_v2=auto_applied_rig)
    if manual_rig["sensor_rig_sha256"] == auto_rig["sensor_rig_sha256"]:
        auto_rig = dict(auto_rig)
        auto_rig["sensor_rig_sha256"] = "a" * 64  # distinct independently observed rig

    runtime_sensor_rig_sha = manual_rig["sensor_rig_sha256"]
    manual_weather = read_arm_weather_identity(manual_dir)
    auto_weather = read_arm_weather_identity(auto_dir)

    manual_arm, auto_arm = {}, {}
    # Current script laundering pattern (run_perception_capture_pair.py)
    for arm, weather_sha in (
        (manual_arm, manual_weather["weather_sha256"]),
        (auto_arm, auto_weather["weather_sha256"]),
    ):
        arm["weather_sha256"] = weather_sha
        arm["camera_response_sha256"] = "cam"
        arm["simulation_physics_sha256"] = "phys"
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

    # Correct/desired behavior (RED before source repair): auto keeps its own identity.
    assert auto_arm["sensor_rig_sha256"] == auto_rig["sensor_rig_sha256"], (
        "auto arm rig identity was copied from manual instead of bound to auto's independently observed rig"
    )
    assert auto_arm["runtime_sensor_rig_sha256"] != runtime_sensor_rig_sha or auto_rig["sensor_rig_sha256"] == manual_rig["sensor_rig_sha256"]


# --- Required verification properties ---

def test_each_arm_binds_independently_observed_sensor_receipts():
    manifest, manual, auto = _valid_pair_manifest()
    # Each arm carries its own receipt and bound identity/dataset, not a shared copy.
    assert manifest["manual_arm"]["applied_sensor_rig_v2"] is not manifest["auto_arm"]["applied_sensor_rig_v2"]
    assert manifest["manual_arm"]["applied_sensor_rig_v2_sha256"] != manifest["auto_arm"]["applied_sensor_rig_v2_sha256"]
    assert manifest["manual_arm"]["dataset_identity"] != manifest["auto_arm"]["dataset_identity"]
    assert manifest["manual_arm"]["dataset_artifact_sha256"] != manifest["auto_arm"]["dataset_artifact_sha256"]
    r = rq3.validate_pair_manifest(manifest)
    assert r["valid"] is True, r["invalid_reasons"]


def test_auto_arm_rig_mutation_cannot_be_hidden_by_copying_manual_identity():
    """If auto rig/receipt is mutated but arm identity fields are copied from manual,
    validation must reject the inconsistency (cannot be hidden)."""
    manifest, manual, auto = _valid_pair_manifest()
    mutated_receipt = copy.deepcopy(manifest["auto_arm"]["applied_sensor_rig_v2"])
    mutated_receipt["applied_configuration_sha256"] = "b" * 64
    mutated_receipt_sha = canonical_sha256(mutated_receipt)
    manifest["auto_arm"]["applied_sensor_rig_v2"] = mutated_receipt
    manifest["auto_arm"]["applied_sensor_rig_v2_sha256"] = mutated_receipt_sha
    # Copying manual's identity onto auto does not hide the mutation.
    manifest["auto_arm"]["sensor_rig_sha256"] = manifest["manual_arm"]["sensor_rig_sha256"]
    manifest["auto_arm"]["runtime_sensor_rig_sha256"] = manifest["manual_arm"]["runtime_sensor_rig_sha256"]
    r = rq3.validate_pair_manifest(manifest)
    assert r["valid"] is False
    reasons = " ".join(r["invalid_reasons"])
    assert "auto" in reasons and ("mismatch" in reasons or "applied_sensor_rig_v2" in reasons)


def test_swapped_receipt_identities_are_rejected():
    manifest, manual, auto = _valid_pair_manifest()
    ma = manifest["manual_arm"]["applied_sensor_rig_v2"]
    aa = manifest["auto_arm"]["applied_sensor_rig_v2"]
    manifest["manual_arm"]["applied_sensor_rig_v2"] = aa
    manifest["manual_arm"]["applied_sensor_rig_v2_sha256"] = canonical_sha256(aa)
    manifest["auto_arm"]["applied_sensor_rig_v2"] = ma
    manifest["auto_arm"]["applied_sensor_rig_v2_sha256"] = canonical_sha256(ma)
    r = rq3.validate_pair_manifest(manifest)
    assert r["valid"] is False
    reasons = " ".join(r["invalid_reasons"])
    assert "applied_rig_dataset_identity_mismatch" in reasons or "applied_rig_dataset_digest_mismatch" in reasons


def test_missing_dataset_bindings_fail_closed():
    # Missing arm dataset identity/digest binding (runtime evidence identity absent)
    manifest, _, _ = _valid_pair_manifest()
    manifest["auto_arm"]["dataset_identity"] = ""
    manifest["auto_arm"]["dataset_artifact_sha256"] = ""
    r = rq3.validate_pair_manifest(manifest)
    assert r["valid"] is False
    reasons = " ".join(r["invalid_reasons"])
    assert "dataset" in reasons.lower() or "binding" in reasons.lower() or "mismatch" in reasons.lower()


def test_missing_dataset_bindings_fail_closed_when_receipt_measurements_unbound():
    manifest, _, _ = _valid_pair_manifest()
    # Remove dataset binding from receipt runtime measurements without corresponding observations.
    mutated = copy.deepcopy(manifest["auto_arm"]["applied_sensor_rig_v2"])
    for sample in (mutated.get("runtime_measurements") or {}).values():
        sample["dataset_identity"] = ""
        sample["dataset_artifact_sha256"] = ""
    manifest["auto_arm"]["applied_sensor_rig_v2"] = mutated
    manifest["auto_arm"]["applied_sensor_rig_v2_sha256"] = canonical_sha256(mutated)
    r = rq3.validate_pair_manifest(manifest)
    assert r["valid"] is False
    reasons = " ".join(r["invalid_reasons"])
    assert "applied_rig_dataset_identity_mismatch" in reasons or "applied_rig_dataset_digest_mismatch" in reasons


def test_identical_configurations_may_legitimately_have_identical_configuration_hashes():
    # Same calibration/rig/config hashes across arms are legitimate when configurations are identical.
    manifest, manual, auto = _valid_pair_manifest()
    assert manifest["manual_arm"]["sensor_rig_sha256"] == manifest["auto_arm"]["sensor_rig_sha256"]
    assert manifest["manual_arm"]["calibration_sha256"] == manifest["auto_arm"]["calibration_sha256"]
    r = rq3.validate_pair_manifest(manifest)
    assert r["valid"] is True, r["invalid_reasons"]


def test_runtime_evidence_identities_cannot_be_copied_without_corresponding_observations():
    """Copying auto's runtime dataset evidence identity onto manual (without matching
    manual receipt runtime measurements/observations) must be rejected."""
    manifest, _, _ = _valid_pair_manifest()
    # Copy runtime evidence identity fields from auto to manual arm.
    manifest["manual_arm"]["dataset_identity"] = manifest["auto_arm"]["dataset_identity"]
    manifest["manual_arm"]["dataset_artifact_sha256"] = manifest["auto_arm"]["dataset_artifact_sha256"]
    # Manual receipt still contains manual's runtime measurement bindings -> mismatch.
    r = rq3.validate_pair_manifest(manifest)
    assert r["valid"] is False
    reasons = " ".join(r["invalid_reasons"])
    assert "applied_rig_dataset_identity_mismatch" in reasons or "applied_rig_dataset_digest_mismatch" in reasons
