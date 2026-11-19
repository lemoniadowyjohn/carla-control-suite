"""V133: the shared synthetic arm must carry the complete calibrated rig.

The complete fixture must pass live admission; every omission, addition,
mount change, identity collision or digest drift must fail. The one-camera
fixture is retained only as an explicit negative.
"""
from __future__ import annotations

import copy

import pytest

from ultimate_pipeline.sensors.applied_sensor_rig import (
    seal_applied_sensor_rig_v2,
    validate_applied_sensor_rig_v2,
)
from ultimate_pipeline.tests.unit.rq3_v2_test_receipts import (
    ACTIVE_LIDAR_NAMES,
    CALIBRATION_SHA256,
    CAMERA_NAMES,
    COMPLETE_MOUNTS,
    COMPLETE_SENSOR_NAMES,
    INCOMPLETE_FIXTURE_VALID_FOR_LIVE_ADMISSION,
    INCOMPLETE_ONE_CAMERA,
    complete_synthetic_arm,
    make_synthetic_rq3_arm_receipt,
)

_REQUIRED_FIELDS = (
    "requested_parent_relative_matrices",
    "applied_parent_relative_matrices",
    "sensor_identities",
    "blueprint_configuration",
    "runtime_measurements",
    "effective_camera_configuration",
    "residuals",
)


def _receipt(**kwargs):
    return make_synthetic_rq3_arm_receipt({}, label="manual", **kwargs)


def _revalidate(receipt):
    return validate_applied_sensor_rig_v2(
        receipt,
        require_live=True,
        expected_source_calibration_sha256=CALIBRATION_SHA256,
    )


def _drop(receipt, name):
    for field in _REQUIRED_FIELDS:
        receipt.get(field, {}).pop(name, None)
    return seal_applied_sensor_rig_v2(receipt)


def test_fixture_is_the_complete_calibrated_rig():
    assert len(CAMERA_NAMES) == 6
    assert ACTIVE_LIDAR_NAMES == ("middle_lidar",), ACTIVE_LIDAR_NAMES
    receipt = _receipt()
    assert set(receipt["requested_parent_relative_matrices"]) == set(COMPLETE_SENSOR_NAMES)
    assert _revalidate(receipt) == []


@pytest.mark.parametrize("omitted", COMPLETE_SENSOR_NAMES)
def test_omitting_any_calibrated_sensor_fails_live_admission(omitted):
    errors = _revalidate(_drop(_receipt(), omitted))
    assert "requested_sensor_set_does_not_match_trusted_calibration" in errors, (
        f"omitting {omitted} must be rejected, got {errors}"
    )


@pytest.mark.parametrize("omitted", ACTIVE_LIDAR_NAMES)
def test_omitting_the_active_lidar_is_not_a_camera_only_rig(omitted):
    receipt = _drop(_receipt(), omitted)
    assert set(receipt["effective_camera_configuration"]) == set(CAMERA_NAMES)
    assert "requested_sensor_set_does_not_match_trusted_calibration" in _revalidate(receipt)


def test_adding_an_untrusted_sensor_fails_live_admission():
    receipt = copy.deepcopy(_receipt())
    extra = "roof_lidar_unknown"
    mount = COMPLETE_MOUNTS["middle_lidar"].tolist()
    receipt["requested_parent_relative_matrices"][extra] = mount
    receipt["applied_parent_relative_matrices"][extra] = mount
    receipt["sensor_identities"][extra] = {
        "actor_id": 999,
        "type_id": "sensor.lidar.ray_cast",
    }
    receipt["blueprint_configuration"][extra] = {"range": "100"}
    receipt["runtime_measurements"][extra] = copy.deepcopy(
        receipt["runtime_measurements"]["middle_lidar"]
    )
    receipt = seal_applied_sensor_rig_v2(receipt)
    errors = _revalidate(receipt)
    assert "requested_sensor_set_does_not_match_trusted_calibration" in errors
    assert "receipt_contains_sensor_without_trusted_calibration_mount" in errors


def test_altered_mount_is_rejected_against_raw_calibration_bytes():
    receipt = copy.deepcopy(_receipt())
    name = "left_camera"
    wrong = copy.deepcopy(receipt["requested_parent_relative_matrices"][name])
    wrong[1][3] += 0.25
    receipt["requested_parent_relative_matrices"][name] = wrong
    receipt["applied_parent_relative_matrices"][name] = copy.deepcopy(wrong)
    receipt = seal_applied_sensor_rig_v2(receipt)
    errors = _revalidate(receipt)
    assert f"{name}:requested_mount_does_not_match_source_calibration" in errors, errors


def test_duplicate_actor_ids_are_rejected():
    receipt = copy.deepcopy(_receipt())
    names = list(receipt["sensor_identities"])
    receipt["sensor_identities"][names[1]]["actor_id"] = receipt["sensor_identities"][names[0]]["actor_id"]
    errors = _revalidate(seal_applied_sensor_rig_v2(receipt))
    assert "duplicate_sensor_actor_ids" in errors, errors


def test_renamed_sensor_identity_is_rejected():
    receipt = copy.deepcopy(_receipt())
    names = list(receipt["sensor_identities"])
    receipt["sensor_identities"]["renamed_camera"] = receipt["sensor_identities"].pop(names[0])
    errors = _revalidate(seal_applied_sensor_rig_v2(receipt))
    assert "sensor_identity_set_mismatch" in errors, errors


def test_tampered_receipt_without_reseal_is_rejected():
    receipt = copy.deepcopy(_receipt())
    receipt["sensor_identities"]["front_right_camera"]["actor_id"] = 12345
    errors = _revalidate(receipt)
    assert "receipt_digest_mismatch" in errors, errors


def test_source_calibration_sha_drift_is_rejected():
    receipt = copy.deepcopy(_receipt())
    receipt["source_calibration_sha256"] = "d" * 64
    receipt = seal_applied_sensor_rig_v2(receipt)
    errors = _revalidate(receipt)
    assert "source_calibration_sha256_mismatch" in errors, errors


def test_one_camera_fixture_is_explicitly_invalid_for_live_admission():
    assert INCOMPLETE_FIXTURE_VALID_FOR_LIVE_ADMISSION is False
    receipt = _receipt(incomplete=True)
    assert list(receipt["requested_parent_relative_matrices"]) == [INCOMPLETE_ONE_CAMERA]
    source_only = validate_applied_sensor_rig_v2(receipt, require_live=False)
    assert source_only == [], source_only
    assert "requested_sensor_set_does_not_match_trusted_calibration" in _revalidate(receipt)


def test_complete_arm_wrapper_is_valid_for_live_admission():
    arm = complete_synthetic_arm({"weather_sha256": "w1"}, label="manual")
    assert _revalidate(arm["applied_sensor_rig_v2"]) == []
    assert arm["calibration_sha256"] == CALIBRATION_SHA256
