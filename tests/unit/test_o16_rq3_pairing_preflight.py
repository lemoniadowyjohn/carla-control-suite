"""Tests for O16 RQ3 pairing preflight."""
from tools.rq3_pairing_preflight import REQUIRED_SHARED, preflight


def _world(identity):
    return {"expected_map_identity": identity, "expected_map_hash": "h", "expected_map_version": "v", "available_in_runtime": True}


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
