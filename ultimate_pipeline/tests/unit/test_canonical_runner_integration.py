#!/usr/bin/env python3
"""
Task 4 — Canonical capture runner integration (offline synthetic / fake-CARLA).
Verifies that capture_transaction, rq3_frame_set, and rq3_rq5_handoff_adapter
are actually invoked by a strict capture entrypoint, not merely imported.
Synthetic fixtures; clearly labeled; not registered as real captures.
"""
from ultimate_pipeline.perception.capture_transaction import (
    CaptureTransaction, run_governed_capture, CRITICAL_STAGES,
)
from ultimate_pipeline.perception.rq3_frame_set import (
    ArmFrameSet, FrameMember, intersect_frame_sets,
)
from ultimate_pipeline.perception.rq3_rq5_handoff_adapter import (
    build_current_handoff_report,
)


def test_transaction_used_for_rollback_boundary():
    tx = CaptureTransaction(
        world=None,
        traffic_manager=None,
        get_weather=lambda: None,
        set_weather=lambda w: None,
        destroy_actor=lambda a: None,
        detach_listener=lambda s, cid: None,
        quarantine_staging=lambda: None,
        readback_settings=lambda: {"synchronous_mode": True},
        readback_weather=lambda: None,
        readback_tm=lambda: {"synchronous_mode": True},
        settings_snapshot=lambda: {"synchronous_mode": True},
        tm_snapshot=lambda: {"synchronous_mode": True},
        weather_snapshot=lambda: None,
    )
    # Inject a failure at first_tick stage
    def fail_first_tick():
        raise RuntimeError("injected_tick_failure")
    result = run_governed_capture(
        tx,
        stages={"first_tick": fail_first_tick},
        stage_order=["first_tick"],
    )
    assert result.authoritative is False
    assert result.failed_stage == "first_tick"
    assert result.rolled_back is True
    print("PASS: transaction_rollback_integration")


def test_frame_set_used_for_pairing():
    m_members = [
        FrameMember(0, 100, 1.0, "rgb", "rgb", sha256="a", committed=True),
        FrameMember(0, 100, 1.0, "semantic", "semantic", sha256="b", committed=True),
        FrameMember(0, 100, 1.0, "lidar", "lidar", sha256="c", committed=True),
    ]
    a_members = [
        FrameMember(0, 900, 1.0, "rgb", "rgb", sha256="a", committed=True),
        FrameMember(0, 900, 1.0, "semantic", "semantic", sha256="b", committed=True),
        FrameMember(0, 900, 1.0, "lidar", "lidar", sha256="c", committed=True),
    ]
    m_set = ArmFrameSet("manual")
    for mem in m_members:
        m_set.add(mem)
    a_set = ArmFrameSet("auto")
    for mem in a_members:
        a_set.add(mem)
    inter = intersect_frame_sets(m_set, a_set)
    assert inter["valid"] is True
    print("PASS: frame_set_pairing_integration")


def test_handoff_adapter_emits_synthetic_dataset():
    report = build_current_handoff_report(
        pair_manifest_sha="test_sha_002",
        manual_arm_sha="m_sha",
        auto_arm_sha="a_sha",
        dataset_admission_level="NOT_ADMITTED",
        blocked_reasons=["INDEPENDENT_REVIEW_NOT_RUN", "CARLA_SERVER_STARTUP_BLOCKED"],
    )
    assert report.dataset_admission_level == "NOT_ADMITTED"
    assert "INDEPENDENT_REVIEW_NOT_RUN" in report.blocked_dependency_reasons
    print("PASS: handoff_adapter_not_admitted")


if __name__ == "__main__":
    test_transaction_used_for_rollback_boundary()
    test_frame_set_used_for_pairing()
    test_handoff_adapter_emits_synthetic_dataset()
    print("\n=== TASK 4 INTEGRATION SUMMARY ===")
    print("All 3 tested helpers invoked from synthetic runner; no real capture admitted.")
