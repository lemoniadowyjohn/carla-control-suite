"""
V137 targeted F03 — RQ3 per-arm runtime identity.

Exercises actual callable manifest seams in ``rq3_capture_contract``
(``build_pair_manifest`` / ``validate_pair_manifest``) with independently
constructed manual/auto arm receipts and synthetic applied-rig fixtures.

This module does NOT modify Codex-owned runtime source
(``run_perception_capture_pair.py``). The script's post-capture arm-identity
assembly is embedded in ``main()`` with CARLA/live dependencies and has no
extractable callable seam; see ``SEAM_EXTRACTION_PLAN_FOR_CODEX`` and the
red-before evidence section.

No expected identities are fabricated to force digests to differ: when a
distinction is required, it is created by an independently constructed receipt/
runtime-evidence binding or by an explicit configuration mutation.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ultimate_pipeline.perception import rq3_capture_contract as rq3
from ultimate_pipeline.sensors.applied_sensor_rig import canonical_sha256
from ultimate_pipeline.tests.unit.rq3_v2_test_receipts import (
    CALIBRATION_PATH,
    CALIBRATION_SHA256,
    TEST_COMMIT,
    complete_synthetic_arm,
)

SEAM_EXTRACTION_PLAN_FOR_CODEX = """
F03 seam/extraction plan (precise, no runtime source modified by this lane):
- Callable seams exercised here (actual production implementation):
  - rq3_capture_contract.build_pair_manifest(...)
  - rq3_capture_contract.validate_pair_manifest(...)
  - calibration_identity / sensor_rig_from_calib and receipt helpers used to
    construct independently observed arm identities.
- Defective production path WITHOUT a testable offline seam:
  - run_perception_capture_pair.py:main() assembles manual/auto arm identity
    fields after live capture (around runtime_sensor_rig_sha = manual_rig[...],
    loop copying manual_calib/manual_rig/runtime_sensor_rig_sha onto both arms).
  - main() depends on CARLA client/world load, LocalPerceptionRunner execution,
    filesystem side effects, and global SETTINGS; arm assembly is inline (not
    extracted).
- Codex extraction/fix target:
  1) Extract a pure/offline-callable helper, e.g.
     build_arm_identity_fields(manual_rig, auto_rig, manual_calib, auto_calib,
     manual_applied_rig, auto_applied_rig, manual_weather, auto_weather, ...)
     that returns per-arm identity dicts without cross-arm copying.
  2) Compute auto runtime/rig/calibration identity from auto's own observed
     artifacts/receipt (and own calib context if ever distinct), not manual's.
  3) Keep per-arm applied_sensor_rig_v2/runtime evidence bindings arm-faithful;
     reject or fail closed when an arm's identity fields do not correspond to
     its observed dataset/receipt/measurements.
  4) Add a seam callable from tests with synthetic arm dirs/receipts so the
     production assembly path can be exercised offline.
"""

BATCH9_REQUIRED = tuple(rq3.REQUIRED_ARM_IDENTITY_KEYS)


def _base_manifest_and_arms(
    *,
    manual_dataset="manual-dataset",
    auto_dataset="auto-dataset",
    manual_sha="c" * 64,
    auto_sha="d" * 64,
    auto_incomplete=False,
):
    manual = complete_synthetic_arm(
        {"dataset_identity": manual_dataset, "dataset_artifact_sha256": manual_sha},
        code_commit=TEST_COMMIT, label="manual",
    )
    auto = complete_synthetic_arm(
        {"dataset_identity": auto_dataset, "dataset_artifact_sha256": auto_sha},
        code_commit=TEST_COMMIT, label="auto", incomplete=auto_incomplete,
    )
    # Shared config identities may legitimately be identical; runtime evidence differs per arm.
    rig_sha = manual["sensor_rig_sha256"]
    weather_sha = "w" * 64
    route_sha = "r" * 64
    capture_cfg_sha = "cfg" * 20  # arbitrary but consistent
    sim_timing_sha = "t" * 64
    base_ids = {k: "v" for k in BATCH9_REQUIRED}
    base_ids.update(
        {
            "calibration_sha256": CALIBRATION_SHA256,
            "sensor_rig_sha256": rig_sha,
            "runtime_sensor_rig_sha256": rig_sha,
            "weather_sha256": weather_sha,
            "route_manifest_sha256": route_sha,
            "capture_config_sha256": capture_cfg_sha,
            "camera_response_sha256": "cam" * 21 + "c",
            "traffic_manager_sha256": "tm" * 32,
            "simulation_physics_sha256": "ph" * 32,
            "vehicle_calibration_binding_sha256": "vb" * 32,
            "sim_timing_sha256": sim_timing_sha,
        }
    )

    manual_arm = dict(
        base_ids,
        completion_status=rq3.COMPLETION_PASS,
        dataset_identity=manual_dataset,
        dataset_artifact_sha256=manual_sha,
        applied_sensor_rig_v2=manual["applied_sensor_rig_v2"],
        applied_sensor_rig_v2_sha256=manual["applied_sensor_rig_v2_sha256"],
        calibration_path=str(CALIBRATION_PATH),
    )
    auto_arm = dict(
        base_ids,
        completion_status=rq3.COMPLETION_PASS,
        dataset_identity=auto_dataset,
        dataset_artifact_sha256=auto_sha,
        applied_sensor_rig_v2=auto["applied_sensor_rig_v2"],
        applied_sensor_rig_v2_sha256=auto["applied_sensor_rig_v2_sha256"],
        calibration_path=str(CALIBRATION_PATH),
    )
    # Build via actual production seam.
    manifest = rq3.build_pair_manifest(
        pair_id="p-v137t-f03",
        software_git_sha=TEST_COMMIT,
        carla_client_version="0.9.16",
        carla_server_version="0.9.16",
        manual_map_identity=rq3.cooked_arm_map_identity(
            requested_map_name="Grid0828", resolved_carla_map_name="Grid0828"
        ),
        auto_map_identity=rq3.xodr_arm_map_identity(
            xodr_path="campaigns/ingolstadt_auto.xodr", xodr_sha256="x"
        ),
        route_manifest_path="routes/ingolstadt_route.json",
        route_manifest_sha256=route_sha,
        calibration_sha256=CALIBRATION_SHA256,
        sensor_rig_sha256=rig_sha,
        weather_sha256=weather_sha,
        capture_config_sha256=capture_cfg_sha,
        manual_arm=manual_arm,
        auto_arm=auto_arm,
        pair_valid=True,
        invalid_reasons=[],
        claim_level=rq3.CLAIM_PAIRED_PROTOCOL_VALID,
        calibration_path=str(CALIBRATION_PATH),
        camera_response_sha256=base_ids["camera_response_sha256"],
        traffic_manager_sha256=base_ids["traffic_manager_sha256"],
        simulation_physics_sha256=base_ids["simulation_physics_sha256"],
        runtime_sensor_rig_sha256=rig_sha,
        vehicle_calibration_binding_sha256=base_ids["vehicle_calibration_binding_sha256"],
        sim_timing_sha256=sim_timing_sha,
        weather_schema_version=rq3.WEATHER_SCHEMA_VERSION,
        pair_route_closure="PAIR_ROUTE_VALID",
    )
    # Keep pair-level frame indices consistent for validator expectations.
    manifest.setdefault("pair_frame_index", [0, 1, 2])
    return manifest, manual, auto


def test_actual_build_and_validate_seam_accepts_independently_constructed_arm_receipts():
    """Exercises production build_pair_manifest + validate_pair_manifest with
    independently constructed per-arm receipts/runtime evidence."""
    manifest, _, _ = _base_manifest_and_arms()
    r = rq3.validate_pair_manifest(manifest)
    assert r["valid"] is True, r["invalid_reasons"]
    assert manifest["manual_arm"]["dataset_identity"] != manifest["auto_arm"]["dataset_identity"]
    assert manifest["manual_arm"]["applied_sensor_rig_v2_sha256"] != manifest["auto_arm"]["applied_sensor_rig_v2_sha256"]


def test_identical_shared_calibration_vs_independent_runtime_evidence_distinguished():
    """Shared calibration/config digests may be identical; runtime evidence/dataset
    bindings are independently obtained per arm and must not be conflated."""
    manifest, _, _ = _base_manifest_and_arms()
    assert manifest["manual_arm"]["calibration_sha256"] == manifest["auto_arm"]["calibration_sha256"] == CALIBRATION_SHA256
    # Independent runtime evidence identities differ.
    assert manifest["manual_arm"]["dataset_identity"] != manifest["auto_arm"]["dataset_identity"]
    assert manifest["manual_arm"]["dataset_artifact_sha256"] != manifest["auto_arm"]["dataset_artifact_sha256"]
    assert manifest["manual_arm"]["applied_sensor_rig_v2_sha256"] != manifest["auto_arm"]["applied_sensor_rig_v2_sha256"]
    r = rq3.validate_pair_manifest(manifest)
    assert r["valid"] is True, r["invalid_reasons"]


def test_auto_arm_configuration_mutation_affects_actual_per_arm_identity_and_is_detected():
    """An auto-arm configuration/runtime mutation changes its actual per-arm receipt
    identity; copying manual identity cannot hide the inconsistency (validator rejects)."""
    manifest, _, _ = _base_manifest_and_arms()
    mutated = copy.deepcopy(manifest["auto_arm"]["applied_sensor_rig_v2"])
    mutated["applied_configuration_sha256"] = "b" * 64  # real mutation to applied config
    mutated_sha = canonical_sha256(mutated)
    manifest["auto_arm"]["applied_sensor_rig_v2"] = mutated
    manifest["auto_arm"]["applied_sensor_rig_v2_sha256"] = mutated_sha
    # Attempt to hide by copying manual identity fields onto auto.
    manifest["auto_arm"]["sensor_rig_sha256"] = manifest["manual_arm"]["sensor_rig_sha256"]
    manifest["auto_arm"]["runtime_sensor_rig_sha256"] = manifest["manual_arm"]["runtime_sensor_rig_sha256"]
    r = rq3.validate_pair_manifest(manifest)
    assert r["valid"] is False
    reasons = " ".join(r["invalid_reasons"])
    assert "auto" in reasons and ("mismatch" in reasons or "applied_sensor_rig_v2" in reasons)


def test_swapped_arm_receipts_rejected_by_actual_validator():
    manifest, _, _ = _base_manifest_and_arms()
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


def test_absent_arm_receipt_fails_closed():
    manifest, _, _ = _base_manifest_and_arms()
    manifest["auto_arm"].pop("applied_sensor_rig_v2", None)
    manifest["auto_arm"].pop("applied_sensor_rig_v2_sha256", None)
    r = rq3.validate_pair_manifest(manifest)
    assert r["valid"] is False
    reasons = " ".join(r["invalid_reasons"])
    assert "applied_sensor_rig_v2" in reasons or "missing" in reasons.lower() or "mismatch" in reasons.lower()


def test_stale_or_inconsistent_arm_receipt_rejected():
    """Receipt whose runtime measurement binding is inconsistent with arm dataset
    evidence (stale/inconsistent) must be rejected."""
    manifest, _, _ = _base_manifest_and_arms()
    stale = copy.deepcopy(manifest["auto_arm"]["applied_sensor_rig_v2"])
    for sample in (stale.get("runtime_measurements") or {}).values():
        sample["dataset_identity"] = "stale-other-dataset"
        sample["dataset_artifact_sha256"] = "e" * 64
    manifest["auto_arm"]["applied_sensor_rig_v2"] = stale
    manifest["auto_arm"]["applied_sensor_rig_v2_sha256"] = canonical_sha256(stale)
    r = rq3.validate_pair_manifest(manifest)
    assert r["valid"] is False
    reasons = " ".join(r["invalid_reasons"])
    assert "applied_rig_dataset_identity_mismatch" in reasons or "applied_rig_dataset_digest_mismatch" in reasons


def test_missing_dataset_bindings_fail_closed():
    manifest, _, _ = _base_manifest_and_arms()
    manifest["auto_arm"]["dataset_identity"] = ""
    manifest["auto_arm"]["dataset_artifact_sha256"] = ""
    r = rq3.validate_pair_manifest(manifest)
    assert r["valid"] is False


def test_runtime_evidence_identity_cannot_be_copied_without_corresponding_observations():
    """Copying auto runtime dataset evidence onto manual without matching manual
    receipt runtime measurements is rejected by actual validator."""
    manifest, _, _ = _base_manifest_and_arms()
    manifest["manual_arm"]["dataset_identity"] = manifest["auto_arm"]["dataset_identity"]
    manifest["manual_arm"]["dataset_artifact_sha256"] = manifest["auto_arm"]["dataset_artifact_sha256"]
    r = rq3.validate_pair_manifest(manifest)
    assert r["valid"] is False
    reasons = " ".join(r["invalid_reasons"])
    assert "applied_rig_dataset_identity_mismatch" in reasons or "applied_rig_dataset_digest_mismatch" in reasons


def test_actual_validator_rejects_invalid_claims_and_downgrades():
    """Pair declared invalid or with invalid claims must not remain authoritative."""
    manifest, _, _ = _base_manifest_and_arms()
    manifest["pair_valid"] = False
    manifest["claim_level"] = rq3.CLAIM_PAIRED_INGOLSTADT_CAPTURE
    r = rq3.validate_pair_manifest(manifest)
    assert r["valid"] is False
    assert r["claim_level"] != rq3.CLAIM_PAIRED_INGOLSTADT_CAPTURE


def test_script_arm_assembly_has_no_offline_callable_seam_extraction_plan_required():
    """Production defect path (run_perception_capture_pair.py main arm-identity
    assembly) has no callable offline seam; Codex extraction/fix plan is required.
    This test documents the precise gap (not a copy of source logic)."""
    script = Path(__file__).resolve().parents[2] / "ultimate_pipeline" / "experiments" / "thesis" / "run_perception_capture_pair.py"
    src = script.read_text(encoding="utf-8")
    # Evidence of inline laundering in production script (not a test seam):
    assert 'arm["runtime_sensor_rig_sha256"] = runtime_sensor_rig_sha' in src
    assert 'arm["calibration_sha256"] = manual_calib["calib_sha256"]' in src
    assert 'arm["sensor_rig_sha256"] = manual_rig["sensor_rig_sha256"]' in src
    assert "runtime_sensor_rig_sha = manual_rig[\"sensor_rig_sha256\"]" in src
    # No extracted helper for offline arm-assembly testing.
    assert "def build_arm_identity_fields" not in src
    assert "def assemble_pair_arm_identities" not in src
    # Extraction plan provided for Codex.
    assert "build_arm_identity_fields" in SEAM_EXTRACTION_PLAN_FOR_CODEX
    assert "offline-callable" in SEAM_EXTRACTION_PLAN_FOR_CODEX
