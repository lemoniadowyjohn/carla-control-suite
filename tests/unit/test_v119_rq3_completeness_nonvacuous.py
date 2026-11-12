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
