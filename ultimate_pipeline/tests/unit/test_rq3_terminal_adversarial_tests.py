#!/usr/bin/env python3
"""
Task 6 — Terminal completion adversarial negative controls.
All synthetic fixtures; clearly labeled; not registered as real captures.
Each failure must prevent authoritative capture completion.
"""
from pathlib import Path
from ultimate_pipeline.perception.record_route_fixed import (
    run_strict_capture_entrypoint, run_strict_rq3_capture,
    STRICT_EXIT_OK, STRICT_EXIT_INVARIANT_VIOLATION,
)


class _FakeWorld:
    def get_settings(self):
        class S:
            synchronous_mode = True
        return S()


class _FakeTM:
    def get_synchronous_mode(self): return True


def _run_scenario(name, **kwargs):
    out_dir = Path(r"E:\temp\rq3_adversarial")
    out_dir.mkdir(parents=True, exist_ok=True)
    exit_code = run_strict_capture_entrypoint(
        out_dir=out_dir,
        session_id=f"adv_{name}",
        arm_name="manual",
        world=_FakeWorld(),
        traffic_manager=_FakeTM(),
        get_weather=lambda: None,
        set_weather=lambda w: None,
        destroy_actor=lambda a: None,
        detach_listener=lambda s, cid: None,
        quarantine_staging=lambda: None,
        stages={},
        **kwargs,
    )
    assert exit_code == STRICT_EXIT_INVARIANT_VIOLATION, f"{name}: expected invariant violation, got {exit_code}"
    import json
    verdict_path = out_dir / "RQ3_STRICT_CAPTURE_VERDICT.json"
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    assert verdict.get("authoritative") is False
    print(f"PASS: adversarial_{name}")


def test_sensor_timeout_fails():
    _run_scenario("sensor_timeout", terminal_status="TIMEOUT")


def test_missing_rgb_fails():
    members = [
        {"frame_index": 0, "frame_id": 1, "timestamp": 1.0, "modality": "semantic", "sha256": "s", "committed": True},
        {"frame_index": 0, "frame_id": 1, "timestamp": 1.0, "modality": "lidar", "sha256": "l", "committed": True},
    ]
    _run_scenario("missing_rgb", arm_members=members)


def test_missing_semantic_fails():
    members = [
        {"frame_index": 0, "frame_id": 1, "timestamp": 1.0, "modality": "rgb", "sha256": "r", "committed": True},
        {"frame_index": 0, "frame_id": 1, "timestamp": 1.0, "modality": "lidar", "sha256": "l", "committed": True},
    ]
    _run_scenario("missing_semantic", arm_members=members)


def test_missing_lidar_fails():
    members = [
        {"frame_index": 0, "frame_id": 1, "timestamp": 1.0, "modality": "rgb", "sha256": "r", "committed": True},
        {"frame_index": 0, "frame_id": 1, "timestamp": 1.0, "modality": "semantic", "sha256": "s", "committed": True},
    ]
    _run_scenario("missing_lidar", arm_members=members)


def test_session_collision_fails():
    # Simulate existing authoritative session
    out_dir = Path(r"E:\temp\rq3_adversarial")
    session_dir = out_dir / "rq3_strict_sessions" / "adv_session_collision"
    session_dir.mkdir(parents=True, exist_ok=True)
    import json
    (session_dir / "session_lock.json").write_text(json.dumps({"authoritative": True}), encoding="utf-8")
    exit_code = run_strict_capture_entrypoint(
        out_dir=out_dir, session_id="adv_session_collision", arm_name="manual",
        world=_FakeWorld(), traffic_manager=_FakeTM(),
        get_weather=lambda: None, set_weather=lambda w: None,
        destroy_actor=lambda a: None, detach_listener=lambda s, cid: None,
        quarantine_staging=lambda: None, stages={},
        arm_members=[], other_arm_members=[], expected_map_name="Grid0828", observed_map_name="Grid0828",
        dataset_content_sha256="ds", capture_completion_receipt_sha256="cr", terminal_status="COMPLETED",
        route_manifest_path="/v/r.json", route_manifest_sha256="r",
    )
    assert exit_code == STRICT_EXIT_INVARIANT_VIOLATION
    print("PASS: adversarial_session_collision")


def test_duplicate_frame_fails():
    members = [
        {"frame_index": 0, "frame_id": 1, "timestamp": 1.0, "modality": "rgb", "sha256": "r", "committed": True},
        {"frame_index": 0, "frame_id": 1, "timestamp": 1.0, "modality": "rgb", "sha256": "r", "committed": True},
        {"frame_index": 0, "frame_id": 1, "timestamp": 1.0, "modality": "semantic", "sha256": "s", "committed": True},
        {"frame_index": 0, "frame_id": 1, "timestamp": 1.0, "modality": "lidar", "sha256": "l", "committed": True},
    ]
    _run_scenario("duplicate_frame", arm_members=members)


def test_invalid_map_identity_fails():
    _run_scenario("invalid_map_identity", expected_map_name="Grid0828", observed_map_name="WRONG_MAP")


def test_failed_world_restoration_fails():
    # Transaction rollback with failed restoration prevents authoritative claim
    # We pass a synthetic terminal_status that indicates failure
    _run_scenario("failed_world_restoration", terminal_status="FAILED")


def test_failed_tm_restoration_fails():
    _run_scenario("failed_tm_restoration", terminal_status="FAILED_TM")


def test_missing_dataset_sha_fails():
    members = [
        {"frame_index": 0, "frame_id": 1, "timestamp": 1.0, "modality": "rgb", "sha256": "r", "committed": True},
        {"frame_index": 0, "frame_id": 1, "timestamp": 1.0, "modality": "semantic", "sha256": "s", "committed": True},
        {"frame_index": 0, "frame_id": 1, "timestamp": 1.0, "modality": "lidar", "sha256": "l", "committed": True},
    ]
    out_dir = Path(r"E:\temp\rq3_adversarial")
    exit_code = run_strict_capture_entrypoint(
        out_dir=out_dir, session_id="adv_missing_ds", arm_name="manual",
        world=_FakeWorld(), traffic_manager=_FakeTM(),
        get_weather=lambda: None, set_weather=lambda w: None,
        destroy_actor=lambda a: None, detach_listener=lambda s, cid: None,
        quarantine_staging=lambda: None, stages={},
        arm_members=members, other_arm_members=members,
        dataset_content_sha256="", capture_completion_receipt_sha256="cr",
        terminal_status="COMPLETED", route_manifest_path="/v/r.json", route_manifest_sha256="r",
        expected_map_name="Grid0828", observed_map_name="Grid0828",
    )
    assert exit_code == STRICT_EXIT_INVARIANT_VIOLATION
    print("PASS: adversarial_missing_dataset_sha")


if __name__ == "__main__":
    test_sensor_timeout_fails()
    test_missing_rgb_fails()
    test_missing_semantic_fails()
    test_missing_lidar_fails()
    test_session_collision_fails()
    test_duplicate_frame_fails()
    test_invalid_map_identity_fails()
    test_failed_world_restoration_fails()
    test_failed_tm_restoration_fails()
    test_missing_dataset_sha_fails()
    print("\n=== TASK 6 TERMINAL ADVERSARIAL CONTROLS: 10/10 BLOCKED ===")
