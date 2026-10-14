"""Tests for O16 RQ3 pairing preflight."""
from tools.rq3_pairing_preflight import REQUIRED_SHARED, preflight


def _world(identity):
    base = {
        "expected_map_identity": identity,
        "expected_map_hash": "h",
        "expected_map_version": "v",
        "available_in_runtime": True,
    }
    # Populate REQUIRED_SHARED fields with realistic values
    # These represent what a real capture manifest would record
    base.update({
        "carla_server_version": "0.9.16",
        "sensor_rig": "rig_v1",
        "sensor_transforms": {"camera_front": [0, 0, 0, 0, 0, 0]},
        "camera_intrinsics": {"camera_front": [800, 800, 320, 240]},
        "lidar_parameters": {"channels": 64, "range": 100},
        "weather": "ClearNoon",
        "synchronous_mode": True,
        "fixed_delta": 0.05,
        "seed": 42,
        "route_definition": "route_001",
        "class_map": "cityscapes",
        "frame_count": 100,
        "warm_up": 10,
        "exclusion_policy": "strict",
    })
    return base


def _shared():
    return {field: "same" for field in REQUIRED_SHARED}


def test_matching_contract_passes_without_starting_capture():
    report = preflight(_world("manual"), _world("auto"), _shared())
    assert report["status"] == "PASS"
    assert report["claim"] == "RQ3_PREFLIGHT_PASS"
    assert report["capture_started"] is False


def test_missing_shared_field_blocks():
    shared = _shared()
    del shared["weather"]
    report = preflight(_world("manual"), _world("auto"), shared)
    assert report["status"] == "FAIL"
    assert "shared missing weather" in report["failures"]


def test_runtime_unavailable_blocks():
    manual = _world("manual")
    automatic = _world("auto")
    automatic["available_in_runtime"] = False
    report = preflight(manual, automatic, _shared())
    assert report["status"] == "FAIL"
    assert "both worlds must be available in runtime" in report["mismatches"]


def test_same_map_identity_is_rejected():
    report = preflight(_world("same"), _world("same"), _shared())
    assert report["status"] == "FAIL"
    assert any("must be distinct" in item for item in report["mismatches"])


def test_required_shared_missing_from_both_manual_and_automatic_fails():
    """GAP-032: REQUIRED_SHARED fields must be present on manual/automatic, not just shared.
    
    Current bug: if a required field (e.g. 'seed') is absent from BOTH manual and automatic
    capture manifests, but present in the shared declared-contract dict, the preflight
    wrongly passes because the parity check only fires when a field is present on BOTH sides.
    """
    manual = _world("manual")
    automatic = _world("auto")
    shared = _shared()
    # Remove 'seed' from BOTH manual and automatic (simulating captures that never recorded it)
    # but leave it in shared (the declared contract says it's required)
    # Current code: only checks shared for presence, only compares manual vs automatic when both have it
    # So this wrongly passes
    del manual["seed"]
    del automatic["seed"]
    report = preflight(manual, automatic, shared)
    # After fix: should FAIL because 'seed' is missing from manual AND automatic
    assert report["status"] == "FAIL"
    assert any("manual missing seed" in f for f in report["failures"])
    assert any("automatic missing seed" in f for f in report["failures"])
