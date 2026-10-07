#!/usr/bin/env python3
"""Batch 9 step 18 regression tests for the RQ3 pair contract.

Two properties are asserted:

1. Every one of the 11 mandatory identity SHAs from Batch 9 section 18 is
   enforced by the governed pair validator -- present on both arms and at pair
   level, and equal across arms and against the pair level.
2. ``pair_valid=False`` can never surface as ``valid=True``.
"""
from __future__ import annotations

import sys
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKTREE))

import pytest

from ultimate_pipeline.perception import rq3_capture_contract as rq3

BATCH9_REQUIRED = (
    "calibration_sha256",
    "sensor_rig_sha256",
    "weather_sha256",
    "capture_config_sha256",
    "route_manifest_sha256",
    "camera_response_sha256",
    "traffic_manager_sha256",
    "simulation_physics_sha256",
    "runtime_sensor_rig_sha256",
    "vehicle_calibration_binding_sha256",
    "sim_timing_sha256",
)


def _base_manifest(**overrides):
    arms = {k: "v" for k in BATCH9_REQUIRED}
    manifest = {
        "schema_version": rq3.MANIFEST_SCHEMA_VERSION,
        "pair_id": "p-batch9",
        "claim_level": rq3.CLAIM_PAIRED_PROTOCOL_VALID,
        "pair_frame_index": [0, 1, 2],
        "manual_map_identity": rq3.cooked_arm_map_identity(
            requested_map_name="Grid0828", resolved_carla_map_name="Grid0828"),
        "auto_map_identity": rq3.xodr_arm_map_identity(
            xodr_path="campaigns/ingolstadt_auto.xodr", xodr_sha256="x"),
        "pair_valid": True,
        "invalid_reasons": [],
        "manual_arm": dict(arms, completion_status=rq3.COMPLETION_PASS),
        "auto_arm": dict(arms, completion_status=rq3.COMPLETION_PASS),
        **{k: "v" for k in BATCH9_REQUIRED},
    }
    manifest.update(overrides)
    return manifest


# --- 1. the full Batch 9 list is enforced -----------------------------------

def test_all_eleven_batch9_identities_are_governed_keys():
    missing = [k for k in BATCH9_REQUIRED if k not in rq3.REQUIRED_ARM_IDENTITY_KEYS]
    assert not missing, f"not enforced as arm identities: {missing}"


@pytest.mark.parametrize("key", BATCH9_REQUIRED)
def test_identity_absent_from_an_arm_invalidates_the_pair(key):
    arm = {k: "v" for k in BATCH9_REQUIRED}
    arm.pop(key)
    r = rq3.validate_pair_manifest(_base_manifest(manual_arm=arm))
    assert r["valid"] is False, f"missing {key} on the manual arm still validated"


@pytest.mark.parametrize("key", BATCH9_REQUIRED)
def test_identity_absent_at_pair_level_invalidates_the_pair(key):
    manifest = _base_manifest()
    manifest.pop(key)
    r = rq3.validate_pair_manifest(manifest)
    assert r["valid"] is False, f"missing {key} at pair level still validated"


@pytest.mark.parametrize("key", BATCH9_REQUIRED)
def test_arm_to_arm_mismatch_invalidates_the_pair(key):
    auto = {k: "v" for k in BATCH9_REQUIRED}
    auto[key] = "different"
    r = rq3.validate_pair_manifest(_base_manifest(auto_arm=auto))
    assert r["valid"] is False, f"manual/auto mismatch on {key} still validated"


@pytest.mark.parametrize("key", BATCH9_REQUIRED)
def test_arm_to_pair_mismatch_invalidates_the_pair(key):
    manifest = _base_manifest()
    manifest[key] = "different"
    r = rq3.validate_pair_manifest(manifest)
    assert r["valid"] is False, f"arm/pair mismatch on {key} still validated"


def test_fully_matching_manifest_validates():
    r = rq3.validate_pair_manifest(_base_manifest())
    assert r["valid"] is True, r.get("invalid_reasons")


# --- 2. pair_valid=False can never surface as valid=True -------------------

def test_pair_valid_false_never_surfaces_as_valid_true():
    for claim in (
        rq3.CLAIM_PAIRED_PROTOCOL_VALID,
        rq3.CLAIM_PAIRED_INGOLSTADT_CAPTURE,
        rq3.CLAIM_UNPAIRED_CAPTURE,
    ):
        r = rq3.validate_pair_manifest(_base_manifest(pair_valid=False, claim_level=claim))
        assert r["valid"] is False, f"pair_valid=False reported valid=True for {claim}"


def test_pair_valid_false_with_invalid_reasons_still_invalid():
    r = rq3.validate_pair_manifest(
        _base_manifest(pair_valid=False, invalid_reasons=["INCOMPLETE_PAIR"])
    )
    assert r["valid"] is False


def test_pair_valid_true_with_missing_arm_identity_still_invalid():
    """A hand-set pair_valid=True must not rescue a pair with a missing arm identity."""
    arm = {k: "v" for k in BATCH9_REQUIRED}
    arm.pop("sim_timing_sha256")
    r = rq3.validate_pair_manifest(_base_manifest(manual_arm=arm, pair_valid=True))
    assert r["valid"] is False


def test_sim_timing_identity_is_compared_not_just_present():
    """Two differently-timed arms must not validate as the same experiment."""
    a = rq3.sim_timing_identity(
        synchronous_mode=True, fixed_delta_seconds=0.05,
        traffic_manager_sync=True, fps_target=20.0)
    b = rq3.sim_timing_identity(
        synchronous_mode=True, fixed_delta_seconds=0.1,
        traffic_manager_sync=True, fps_target=10.0)
    assert a["sim_timing_sha256"] != b["sim_timing_sha256"]
    arms = {k: "v" for k in BATCH9_REQUIRED}
    auto = dict(arms, sim_timing_sha256=b["sim_timing_sha256"])
    manifest = _base_manifest(auto_arm=auto)
    manifest["sim_timing_sha256"] = a["sim_timing_sha256"]
    manifest["manual_arm"]["sim_timing_sha256"] = a["sim_timing_sha256"]
    assert rq3.validate_pair_manifest(manifest)["valid"] is False