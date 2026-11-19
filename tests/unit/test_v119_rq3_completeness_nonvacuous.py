"""V119: completeness verdict may not pass vacuous or malformed sensor counts."""
from __future__ import annotations

import pytest

from ultimate_pipeline.perception.rq3_capture_contract import (
    COMPLETION_FAIL,
    COMPLETION_PASS,
    compute_strict_completion_status,
    evaluate_frame_completeness,
)


@pytest.mark.parametrize(
    ("expected", "actual", "lidars"),
    [
        ({}, {}, None),
        ({}, {"unregistered": 50}, None),
        ({"front_camera": 0}, {}, None),
        ({"front_camera": -1}, {}, None),
        ({"front_camera": True}, {"front_camera": 1}, None),
        ({"front_camera": 1.0}, {"front_camera": 1}, None),
        ({"front_camera": float("nan")}, {}, None),
        ({"front_camera": "1"}, {"front_camera": 1}, None),
        ({"front_camera": 2}, {"front_camera": -1}, None),
        ({"front_camera": 2}, {"front_camera": True}, None),
        ({"front_camera": 2}, {"front_camera": float("nan")}, None),
        ({"front_camera": 2}, {"front_camera": "2"}, None),
        ({"front_camera": 2}, {"front_camera": 2}, {"front_camera": 2}),
    ],
)
def test_invalid_sensor_requirements_never_pass(expected, actual, lidars):
    out = evaluate_frame_completeness(expected, actual, expected_lidars=lidars)
    assert out["status"] == COMPLETION_FAIL
    assert out["complete"] is False
    assert out["invalid_requirements"]


def test_valid_combined_camera_and_lidar_completion_still_passes():
    out = evaluate_frame_completeness(
        {"front_camera": 3},
        {"front_camera": 3, "middle_lidar": 3},
        expected_lidars={"middle_lidar": 3},
    )
    assert out["status"] == COMPLETION_PASS
    assert out["complete"] is True


def test_missing_required_positive_sensor_does_not_pass():
    out = evaluate_frame_completeness({"front_camera": 3}, {})
    assert out["status"] == COMPLETION_FAIL
    assert out["missing_sensors"] == ["front_camera"]


def test_strict_wrapper_cannot_relabel_vacuous_requirement_as_success():
    out = compute_strict_completion_status(
        expected_cameras={}, actual_counts={}, sensor_failures=[]
    )
    assert out["status"] == COMPLETION_FAIL
    assert out["complete"] is False


def test_empty_frame_set_cannot_pass_synchronization():
    from ultimate_pipeline.perception.rq3_frame_set import (
        ArmFrameSet,
        validate_arm_frame_set,
        intersect_frame_sets,
    )

    empty_manual = ArmFrameSet(arm_name="manual")
    empty_auto = ArmFrameSet(arm_name="auto")
    per_arm = validate_arm_frame_set(empty_manual)
    assert per_arm["valid"] is False
    assert per_arm["accepted_count"] == 0
    paired = intersect_frame_sets(empty_manual, empty_auto)
    assert paired["valid"] is False
    assert paired["accepted_count"] == 0


def test_empty_required_modalities_cannot_pass_with_captured_members():
    from ultimate_pipeline.perception.rq3_frame_set import (
        ArmFrameSet,
        FrameMember,
        validate_arm_frame_set,
    )

    arm = ArmFrameSet(arm_name="manual")
    arm.add(
        FrameMember(
            frame_index=0,
            frame_id=100,
            timestamp=1.0,
            modality="rgb",
            sensor_name="front_rgb",
            sha256="a" * 64,
            committed=True,
        )
    )
    result = validate_arm_frame_set(arm, required_modalities=())
    assert result["valid"] is False
    assert result["accepted_count"] == 0
