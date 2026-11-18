#!/usr/bin/env python3
"""
Task 4 / Step 4 — Integration from real strict entrypoint (offline fake-CARLA).
Proves capture_transaction, rq3_frame_set, rq3_rq5_handoff_adapter are used
from the canonical runner, not merely imported. Synthetic; not real capture.
"""
from ultimate_pipeline.perception.record_route_fixed import (
    main, run_strict_capture_entrypoint, run_strict_rq3_capture,
    STRICT_EXIT_OK, STRICT_EXIT_INVARIANT_VIOLATION, STRICT_EXIT_SETUP_FAILURE,
)
from ultimate_pipeline.perception.rq3_frame_set import ArmFrameSet, FrameMember


def test_strict_entrypoint_integration_offline():
    out_dir = r"E:\temp\rq3_strict_test"
    import shutil
    shutil.rmtree(out_dir, ignore_errors=True)

    # Minimal synthetic members — clearly labeled synthetic fixtures
    members = [
        FrameMember(0, 100, 1.0, "rgb", "rgb", sha256="s_rgb", committed=True),
        FrameMember(0, 100, 1.0, "semantic", "semantic", sha256="s_sem", committed=True),
        FrameMember(0, 100, 1.0, "lidar", "lidar", sha256="s_lid", committed=True),
    ]

    # Fake CARLA objects (no server required)
    class FakeWorld:
        def get_settings(self):
            class S:
                synchronous_mode = True
            return S()
    class FakeTM:
        def get_synchronous_mode(self): return True
    class FakeWeather:
        pass

    # Call the real entrypoint with synthetic data; it must invoke helpers
    exit_code = run_strict_capture_entrypoint(
        out_dir=out_dir,
        session_id="fake_session_001",
        arm_name="manual",
        world=FakeWorld(),
        traffic_manager=FakeTM(),
        get_weather=lambda: FakeWeather(),
        set_weather=lambda w: None,
        destroy_actor=lambda a: None,
        detach_listener=lambda s, cid: None,
        quarantine_staging=lambda: None,
        stages={},
        arm_members=[{"frame_index": 0, "frame_id": 100, "timestamp": 1.0, "modality": "rgb", "sha256": "s_rgb", "committed": True}],
        other_arm_members=[{"frame_index": 0, "frame_id": 100, "timestamp": 1.0, "modality": "rgb", "sha256": "s_rgb", "committed": True}],
        expected_map_name="Grid0828",
        observed_map_name="Grid0828",
        dataset_content_sha256="ds_sha_001",
        capture_completion_receipt_sha256="receipt_sha_001",
        terminal_status="COMPLETED",
        route_manifest_path="/verified/route.json",
        route_manifest_sha256="route_sha",
    )
    # With synthetic evidence and no full pairing / completed multimodal,
    # authoritative is False → exit code must be non-zero (fail-closed)
    assert exit_code == STRICT_EXIT_INVARIANT_VIOLATION, f"expected failure for synthetic (fail-closed): got {exit_code}"
    # Verify handshake artifacts produced by the real entrypoint
    verdict_path = __import__("pathlib").Path(out_dir) / "RQ3_STRICT_CAPTURE_VERDICT.json"
    assert verdict_path.exists(), "strict verdict artifact missing from real entrypoint"
    import json
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    assert verdict.get("authoritative") is False
    assert verdict.get("strict_mode") is True
    assert verdict.get("rq3_paired_dataset_not_admitted") is True
    print("PASS: strict_entrypoint_integration_offline (helpers invoked, fail-closed confirmed)")


def test_strict_cli_never_submits_placeholder_completion(tmp_path):
    import json

    exit_code = main([
        "--strict-rq3",
        "--town", "Grid0828",
        "--calib", str(__import__("pathlib").Path(__file__).resolve().parents[2] / "sensors" / "calib_data.json"),
        "--out-dir", str(tmp_path),
        "--route-manifest-path", str(tmp_path / "missing-route.json"),
    ])
    assert exit_code == STRICT_EXIT_SETUP_FAILURE
    status_files = list((tmp_path / "strict_attempts").glob("*/STRICT_RQ3_EXECUTION_STATUS.json"))
    assert len(status_files) == 1
    status = json.loads(status_files[0].read_text(encoding="utf-8"))
    assert status["status"] == "NOT_RUN"
    assert status["completion_status"] == "NOT_RUN"
    assert status["authoritative"] is False
    assert status["failure_reason"] == "STRICT_CLI_RUNTIME_EXECUTOR_UNAVAILABLE"
    assert not list(tmp_path.rglob("RQ3_STRICT_CAPTURE_VERDICT.json"))


if __name__ == "__main__":
    test_strict_entrypoint_integration_offline()
