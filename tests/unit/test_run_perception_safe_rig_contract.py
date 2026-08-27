"""ultimate_pipeline/tools/run_perception_safe.py::_rig_verification_contract_errors --
validates the sensor-rig calibration contract (cTv/vTl inversion conventions, per-sensor
applied-transform completeness) that gates whether captured perception evidence is trustworthy.
The thesis itself cites this as a contribution ("sensor-rig capability proofs under a unified,
mathematically verified calibration contract"). run_perception_safe.py is 6,576 lines and mostly
CARLA-dependent -- this pass targets only this one pure, safety-critical function rather than
attempting broad coverage of the whole file (found via the orphaned-.pyc sweep: 8 different
test_run_perception_safe*.py variants existed at some point, none currently on this branch).
"""
from __future__ import annotations

from ultimate_pipeline.tools.run_perception_safe import _rig_verification_contract_errors


def _valid_verification(sensor_names=("rgb_front",)):
    sensors = {name: {} for name in sensor_names}
    applied_sensors = {name: {"relative_to_vehicle": {"x": 1.5, "y": 0.0, "z": 2.4}} for name in sensor_names}
    return {
        "cTv_inverted": False,
        "vTl_inverted": True,
        "use_K_undistortion_only": True,
        "sensors": sensors,
        "applied_carla_transforms": {"sensors": applied_sensors},
    }


def test_fully_valid_contract_has_no_errors():
    assert _rig_verification_contract_errors(_valid_verification()) == []


def test_ctv_inverted_true_is_an_error():
    v = _valid_verification()
    v["cTv_inverted"] = True
    errors = _rig_verification_contract_errors(v)
    assert "cTv_inverted must be false" in errors


def test_ctv_inverted_missing_is_an_error():
    v = _valid_verification()
    del v["cTv_inverted"]
    errors = _rig_verification_contract_errors(v)
    assert "cTv_inverted must be false" in errors


def test_ctv_inverted_accepts_lowercase_key_fallback():
    v = _valid_verification()
    del v["cTv_inverted"]
    v["ctv_inverted"] = False  # lowercase fallback key
    errors = _rig_verification_contract_errors(v)
    assert "cTv_inverted must be false" not in errors


def test_vtl_inverted_false_is_an_error():
    v = _valid_verification()
    v["vTl_inverted"] = False
    errors = _rig_verification_contract_errors(v)
    assert "vTl_inverted must be true" in errors


def test_vtl_inverted_accepts_lowercase_key_fallback():
    v = _valid_verification()
    del v["vTl_inverted"]
    v["vtl_inverted"] = True
    errors = _rig_verification_contract_errors(v)
    assert "vTl_inverted must be true" not in errors


def test_use_k_undistortion_only_not_true_is_an_error():
    v = _valid_verification()
    v["use_K_undistortion_only"] = False
    errors = _rig_verification_contract_errors(v)
    assert "use_K_undistortion_only must be true" in errors


def test_sensors_missing_is_an_error():
    v = _valid_verification()
    del v["sensors"]
    errors = _rig_verification_contract_errors(v)
    assert "sensors must be a non-empty object" in errors


def test_sensors_empty_dict_is_an_error():
    v = _valid_verification()
    v["sensors"] = {}
    errors = _rig_verification_contract_errors(v)
    assert "sensors must be a non-empty object" in errors


def test_applied_carla_transforms_missing_is_an_error():
    v = _valid_verification()
    del v["applied_carla_transforms"]
    errors = _rig_verification_contract_errors(v)
    assert "applied_carla_transforms missing or invalid" in errors


def test_applied_transforms_sensors_missing_is_an_error():
    v = _valid_verification()
    v["applied_carla_transforms"] = {}
    errors = _rig_verification_contract_errors(v)
    assert "applied_carla_transforms.sensors missing or invalid" in errors


def test_sensor_missing_from_applied_transforms_names_it_in_the_error():
    v = _valid_verification(sensor_names=("rgb_front", "lidar_top"))
    del v["applied_carla_transforms"]["sensors"]["lidar_top"]
    errors = _rig_verification_contract_errors(v)
    assert any("lidar_top" in e for e in errors)
    assert not any("rgb_front" in e for e in errors)


def test_sensor_missing_relative_to_vehicle_is_an_error():
    v = _valid_verification()
    del v["applied_carla_transforms"]["sensors"]["rgb_front"]["relative_to_vehicle"]
    errors = _rig_verification_contract_errors(v)
    assert any("relative_to_vehicle" in e and "rgb_front" in e for e in errors)


def test_multiple_independent_errors_all_accumulate():
    v = {
        "cTv_inverted": True, "vTl_inverted": False, "use_K_undistortion_only": False,
        "sensors": {}, "applied_carla_transforms": None,
    }
    errors = _rig_verification_contract_errors(v)
    # cTv, vTl, use_K, sensors, applied_carla_transforms, and (since resetting
    # applied_carla_transforms to {} still lacks a "sensors" key) applied_carla_transforms.
    # sensors -- 6 independent violations, none short-circuits the rest.
    assert len(errors) == 6
