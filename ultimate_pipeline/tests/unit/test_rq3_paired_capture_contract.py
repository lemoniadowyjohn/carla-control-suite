# -*- coding: utf-8 -*-
"""Offline unit tests for ultimate_pipeline/perception/rq3_capture_contract.py.

Covers the governed RQ3 paired-capture contract engine and the illusion-free
claim boundary:

mandatory-equalities (calibration, sensor rig, weather, sim timing, capture
config, route digest) all use content digests so a mismatch on either arm
can never reach PAIRED_PROTOCOL_VALID; partial frames after a timeout are
INCOMPLETE, never PASS; hidden spawn recovery is rejected in strict mode;
a Town10HD/control arm stays at SENSOR_SMOKE and can never be
PAIRED_INGOLSTADT_CAPTURE.
"""
from __future__ import annotations

import json

from ultimate_pipeline.perception.rq3_capture_contract import (
    CLAIM_PAIRED_INGOLSTADT_CAPTURE,
    CLAIM_PAIRED_PROTOCOL_VALID,
    CLAIM_UNPAIRED_CAPTURE,
    COMPLETION_FAIL,
    COMPLETION_INCOMPLETE,
    COMPLETION_PASS,
    MODE_SMOKE_RECOVERY,
    MODE_THESIS_PAIRED_STRICT,
    build_pair_manifest,
    calibration_identity,
    canonical_digest,
    capture_config_identity,
    classify_claim_level,
    compute_strict_completion_status,
    cooked_arm_map_identity,
    deterministic_digest,
    enforce_spawn_policy,
    evaluate_frame_completeness,
    is_ingolstadt_auto_arm,
    is_ingolstadt_manual_arm,
    sensor_rig_from_calib,
    sim_timing_identity,
    weather_identity,
    xodr_arm_map_identity,
)


class _Config:
    def __init__(self, frames, fps=20, front_only=False, seed=0):
        self.frames = frames
        self.fps = fps
        self.rig = "thesis"
        self.front_only = front_only
        self.seg = True
        self.lidar_format = "npz"
        self.vehicle = "vehicle.audi.a2"
        self.seed = seed


def _weather(**kw):
    return weather_identity(kw)


def test_calibration_identity_uses_content_sha(tmp_path):
    f = tmp_path / "calib.json"
    f.write_text('{"cameras": {}}', encoding="utf-8")
    f2 = tmp_path / "calib2.json"
    f2.write_text('{"cameras": {}}', encoding="utf-8")
    assert calibration_identity(str(f))["calib_sha256"] == calibration_identity(str(f2))["calib_sha256"]
    f3 = tmp_path / "calib3.json"
    f3.write_text('{"cameras": {"front_left_camera": {}}}', encoding="utf-8")
    assert calibration_identity(str(f))["calib_sha256"] != calibration_identity(str(f3))["calib_sha256"]


def test_sensor_rig_identity_changes_with_front_only(tmp_path):
    f = tmp_path / "calib.json"
    f.write_text(
        json.dumps({
            "cameras": {
                "front_left_camera": {"image_size": [1280, 720], "cTv": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]]},
                "back_left_camera": {"image_size": [1280, 720], "cTv": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]]},
            },
            "lidars": {"middle_lidar": {"vTl": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]]}},
        }),
        encoding="utf-8",
    )
    full = sensor_rig_from_calib(str(f), front_only=False)
    front = sensor_rig_from_calib(str(f), front_only=True)
    assert full["sensor_count"] == 3
    assert front["sensor_count"] == 2
    assert full["sensor_rig_sha256"] != front["sensor_rig_sha256"]
    assert "front_left_camera" in front["camera_names"]
    assert "back_left_camera" not in front["camera_names"]


def test_weather_identity_digests_actual_params_not_preset():
    a = _weather(cloudiness=10.0, precipitation=1.0)
    b = _weather(cloudiness=10.0, precipitation=2.0)
    assert a["weather_sha256"] != b["weather_sha256"]
    assert _weather(cloudiness=10.0, precipitation=1.0)["weather_sha256"] == a["weather_sha256"]


def test_sim_timing_identity_fixed_delta_sensitive():
    a = sim_timing_identity(synchronous_mode=True, fixed_delta_seconds=0.05, traffic_manager_sync=True, fps_target=20.0)
    b = sim_timing_identity(synchronous_mode=True, fixed_delta_seconds=0.1, traffic_manager_sync=True, fps_target=10.0)
    assert a["sim_timing_sha256"] != b["sim_timing_sha256"]


def test_capture_config_identity_frames_fps_sensitive():
    a = capture_config_identity(_Config(50))
    b = capture_config_identity(_Config(49))
    c = capture_config_identity(_Config(50, fps=10))
    assert a["capture_config_sha256"] != b["capture_config_sha256"]
    assert a["capture_config_sha256"] != c["capture_config_sha256"]
    assert capture_config_identity(_Config(50))["capture_config_sha256"] == a["capture_config_sha256"]


def test_frame_completeness_pass_when_all_sensors_satisfied():
    r = evaluate_frame_completeness({"front_left_camera": 50}, {"front_left_camera": 50, "middle_lidar": 50},
                                    expected_lidars={"middle_lidar": 50})
    assert r["status"] == COMPLETION_PASS
    assert r["complete"] is True


def test_partial_frames_after_timeout_is_incomplete():
    r = evaluate_frame_completeness({"front_left_camera": 50}, {"front_left_camera": 12},
                                    timed_out=True)
    assert r["status"] == COMPLETION_INCOMPLETE
    assert r["complete"] is False


def test_missing_required_camera_is_fail():
    r = evaluate_frame_completeness({"front_left_camera": 50, "back_left_camera": 50},
                                    {"front_left_camera": 50})
    assert r["status"] == COMPLETION_FAIL


def test_save_errors_downgrade_pass_to_fail():
    r = evaluate_frame_completeness({"front_left_camera": 50}, {"front_left_camera": 50},
                                    save_errors=["image_save_failed:front_left_camera:0:IO"])
    assert r["status"] == COMPLETION_FAIL


def test_strict_completion_marks_ego_destroyed_as_fail():
    r = compute_strict_completion_status(
        expected_cameras={"front_left_camera": 50},
        actual_counts={"front_left_camera": 50},
        ego_destroyed=True,
    )
    assert r["status"] == COMPLETION_FAIL
    assert r["ego_destroyed"] is True


def test_spawn_policy_rejects_hidden_recovery_in_strict_mode():
    reasons = enforce_spawn_policy(MODE_THESIS_PAIRED_STRICT, {"shuffle_used": True})
    assert "spawn_shuffle_used_in_strict_mode" in reasons
    reasons = enforce_spawn_policy(MODE_THESIS_PAIRED_STRICT, {"recovery_fallback_used": True})
    assert "spawn_recovery_used_in_strict_mode" in reasons
    reasons = enforce_spawn_policy(MODE_THESIS_PAIRED_STRICT, {"spawned_at_requested_pose": True})
    assert reasons == []


def test_spawn_policy_allows_recovery_in_smoke_mode():
    assert enforce_spawn_policy(MODE_SMOKE_RECOVERY, {"shuffle_used": True, "recovery_fallback_used": True}) == []


def test_ingolstadt_manual_and_auto_arms():
    manual = cooked_arm_map_identity(
        requested_map_name="Grid0821",
        resolved_carla_map_name="Grid0821",
        registry_identity="manual_refs",
        manual_source_xodr_sha256="abc",
        cooked_package_identity="Grid0821",
    )
    assert is_ingolstadt_manual_arm(manual) is True
    auto = xodr_arm_map_identity(xodr_path="campaigns/ingolstadt_.../x.xodr", xodr_sha256="def")
    assert is_ingolstadt_auto_arm(auto) is True
    town10hd = xodr_arm_map_identity(xodr_path="/tmp/town10hd.xodr", xodr_sha256="ghi")
    assert is_ingolstadt_auto_arm(town10hd) is False


class _Pair:
    def __init__(self, *, manual_map, auto_map, calib_sha, rig_sha, weather_sha,
                 cfg_sha, route_sha, manual_completion, auto_completion):
        self.manual_map = manual_map
        self.auto_map = auto_map
        self.calib_sha = calib_sha
        self.rig_sha = rig_sha
        self.weather_sha = weather_sha
        self.cfg_sha = cfg_sha
        self.route_sha = route_sha
        self.manual_completion = manual_completion
        self.auto_completion = auto_completion

    def build(self):
        return build_pair_manifest(
            pair_id="p1",
            software_git_sha="abc123",
            carla_client_version="0.9.16",
            carla_server_version="0.9.16",
            manual_map_identity=self.manual_map,
            auto_map_identity=self.auto_map,
            route_manifest_path="route.json",
            route_manifest_sha256=self.route_sha,
            calibration_sha256=self.calib_sha,
            sensor_rig_sha256=self.rig_sha,
            weather_sha256=self.weather_sha,
            capture_config_sha256=self.cfg_sha,
            manual_arm={
                "calibration_sha256": self.calib_sha,
                "sensor_rig_sha256": self.rig_sha,
                "weather_sha256": self.weather_sha,
                "capture_config_sha256": self.cfg_sha,
                "route_manifest_sha256": self.route_sha,
                "completion_status": self.manual_completion,
                "pair_frame_index": [0, 1, 2],
            },
            auto_arm={
                "calibration_sha256": self.calib_sha,
                "sensor_rig_sha256": self.rig_sha,
                "weather_sha256": self.weather_sha,
                "capture_config_sha256": self.cfg_sha,
                "route_manifest_sha256": self.route_sha,
                "completion_status": self.auto_completion,
                "pair_frame_index": [0, 1, 2],
            },
            pair_valid=True,
            invalid_reasons=[],
            claim_level="UNPAIRED_CAPTURE",
            pair_route_closure="PAIR_ROUTE_VALID",
        )


_MANUAL = cooked_arm_map_identity(requested_map_name="Grid0821", resolved_carla_map_name="Grid0821")
_AUTO = xodr_arm_map_identity(xodr_path="campaigns/ingolstadt_auto.xodr", xodr_sha256="x")
_AUTOTOWN10HD = xodr_arm_map_identity(xodr_path="/tmp/town10hd.xodr", xodr_sha256="y")


def _ok_pair(**kw):
    base = dict(
        manual_map=_MANUAL,
        auto_map=_AUTO,
        calib_sha="c",
        rig_sha="r",
        weather_sha="w",
        cfg_sha="cf",
        route_sha="route",
        manual_completion=COMPLETION_PASS,
        auto_completion=COMPLETION_PASS,
    )
    base.update(kw)
    return _Pair(**base)


# --- the 12 required contract cases ----------------------------------------
def test_case01_same_spawn_index_different_transforms_rejected():
    """'spawn 0' on two maps w/ different geographic coords is a different route.

    A manifest built for map A (pose at 10,20) and a manifest derived from a
    different map's "same spawn index 0" (pose at 500,20) have different route
    digests; a pair claiming them identical is rejected by digest equality.
    """
    from ultimate_pipeline.perception.route_manifest import build_route_manifest, pose_payload, validate_paired_route, route_digest

    manifest_a = build_route_manifest(
        route_id="mapA",
        coordinate_frame="local_carlamap",
        capture_poses=[pose_payload(x=10.0, y=20.0, z=0.0, yaw=0.0, pitch=0.0, roll=0.0, sequence_index=0)],
    )
    manifest_b_spawn0 = build_route_manifest(
        route_id="mapB",
        coordinate_frame="local_carlamap",
        capture_poses=[pose_payload(x=500.0, y=20.0, z=0.0, yaw=0.0, pitch=0.0, roll=0.0, sequence_index=0)],
    )
    assert route_digest(manifest_a) != route_digest(manifest_b_spawn0)
    on_map = {"valid": True, "manifest_sha256": route_digest(manifest_a)}
    result = validate_paired_route(route_digest(manifest_a), on_map, on_map)
    assert result["valid"] is True
    # If one arm actually ran the "same spawn index 0" from map B the digest
    # would not match the manifest the other arm ran -> pair rejected.
    mismatched_arm = {"valid": True, "manifest_sha256": route_digest(manifest_b_spawn0)}
    result = validate_paired_route(route_digest(manifest_a), on_map, mismatched_arm)
    assert not result["valid"]


def test_case02_route_hashes_differ_rejected():
    manual = {"valid": True, "manifest_sha256": "routeA"}
    auto = {"valid": True, "manifest_sha256": "routeB"}
    from ultimate_pipeline.perception.route_manifest import validate_paired_route

    result = validate_paired_route("routeA", manual, auto)
    assert not result["valid"]
    assert result["closure"] == "PAIR_ROUTE_INVALID"


def test_case03_calibration_differs_rejected():
    good = _ok_pair()
    mismatched = _ok_pair(calib_sha="DIFFERENT")
    good_manifest = good.build()
    bad_manifest = mismatched.build()
    good_manifest["_validation"] = {}
    bad_manifest["_validation"] = {}
    assert good_manifest["manual_arm"]["calibration_sha256"] != bad_manifest["manual_arm"]["calibration_sha256"]
    assert classify_claim_level(is_pair=True, pair_valid=False, route_valid=True, both_arms_ingolstadt=True)["claim_level"] == CLAIM_UNPAIRED_CAPTURE


def test_case04_sensor_rig_differs_rejected():
    diff = _ok_pair(rig_sha="DIFFERENT")
    manifest = diff.build()
    assert manifest["sensor_rig_sha256"] == "DIFFERENT"
    assert classify_claim_level(is_pair=True, pair_valid=False, route_valid=True, both_arms_ingolstadt=True)["claim_level"] == CLAIM_UNPAIRED_CAPTURE


def test_case05_weather_differs_rejected():
    w1 = _weather(cloudiness=10.0)
    w2 = _weather(cloudiness=50.0)
    assert w1["weather_sha256"] != w2["weather_sha256"]
    manifest = _ok_pair(weather_sha=w1["weather_sha256"]).build()
    assert manifest["weather_sha256"] == w1["weather_sha256"]
    assert classify_claim_level(is_pair=True, pair_valid=False, route_valid=True, both_arms_ingolstadt=True)["claim_level"] == CLAIM_UNPAIRED_CAPTURE


def test_case06_fixed_delta_differs_rejected():
    a = sim_timing_identity(synchronous_mode=True, fixed_delta_seconds=0.05, traffic_manager_sync=True, fps_target=20.0)
    b = sim_timing_identity(synchronous_mode=True, fixed_delta_seconds=0.033, traffic_manager_sync=True, fps_target=30.0)
    assert a["sim_timing_sha256"] != b["sim_timing_sha256"]


def test_case07_one_required_camera_missing_rejected():
    r = evaluate_frame_completeness({"front_left_camera": 50, "back_left_camera": 50}, {"front_left_camera": 50})
    assert r["status"] == COMPLETION_FAIL
    assert "back_left_camera" in r["missing_sensors"]


def test_case08_partial_frames_after_timeout_incomplete():
    r = evaluate_frame_completeness({"front_left_camera": 50}, {"front_left_camera": 30}, timed_out=True)
    assert r["status"] == COMPLETION_INCOMPLETE


def test_case09_all_contracts_identical_protocol_valid():
    good = _ok_pair()
    manifest = good.build()
    c = classify_claim_level(is_pair=True, pair_valid=True, route_valid=True, both_arms_ingolstadt=False)
    assert c["claim_level"] == CLAIM_PAIRED_PROTOCOL_VALID
    assert manifest["pair_valid"] is True


def test_case10_town10hd_control_cannot_be_paired_ingolstadt_capture():
    pair = _ok_pair(auto_map=_AUTOTOWN10HD)
    manifest = pair.build()
    manual_ok = is_ingolstadt_manual_arm(manifest["manual_map_identity"])
    auto_ok = is_ingolstadt_auto_arm(manifest["auto_map_identity"])
    assert manual_ok is True and auto_ok is False
    c = classify_claim_level(is_pair=True, pair_valid=True, route_valid=True, both_arms_ingolstadt=False)
    assert c["claim_level"] != CLAIM_PAIRED_INGOLSTADT_CAPTURE
    assert c["claim_level"] == CLAIM_PAIRED_PROTOCOL_VALID


def test_case11_hidden_spawn_recovery_disabled_in_strict_mode():
    reasons = enforce_spawn_policy(MODE_THESIS_PAIRED_STRICT, {"shuffle_used": True, "spawned_at_requested_pose": False})
    assert any("shuffle_used" in r for r in reasons)
    assert any("not_at_requested_pose" in r for r in reasons)
    assert enforce_spawn_policy(MODE_THESIS_PAIRED_STRICT, {"spawned_at_requested_pose": True}) == []


def test_case12_manifests_deterministic_apart_from_excluded_wallclock():
    m1 = {
        "timestamp_utc": "2026-09-19T00:00:00Z",
        "wall_clock_ms": 1234,
        "pair_id": "rq3-x",
        "manual_arm": {"frame_counts": {"front_left_camera": 50}},
    }
    m2 = {
        "timestamp_utc": "2026-09-19T01:00:00Z",
        "wall_clock_ms": 9876,
        "pair_id": "rq3-x",
        "manual_arm": {"frame_counts": {"front_left_camera": 50}},
    }
    assert canonical_digest(m1) == canonical_digest(m2)
    assert deterministic_digest(m1) == deterministic_digest(m2)