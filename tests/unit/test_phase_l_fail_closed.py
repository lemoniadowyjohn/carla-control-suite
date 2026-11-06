"""P0-F mutation tests: phase-L fabricated PASS evidence must be retired.

Import ``phase_l_validation`` from the repository ROOT (not a package copy):
sys.path manipulation is required because the module sits at the repo root.

The tests drive every previously-fabricated step with a minimal fake CARLA
client where the mandatory producer is ABSENT and assert the step MUST NOT be
PASS. This is the exact mutation scenario that used to produce fabricated
L7/L8/L9/L10/L11 evidence.
"""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _LaneType:
    name = "Driving"


class _Waypoint:
    def __init__(self, road_id=1, is_junction=False):
        self.road_id = road_id
        self.is_junction = is_junction
        self.lane_type = _LaneType()


class _FakeMap:
    name = "Carla/Maps/OpenDriveMap"

    def to_opendrive(self):
        return "<OpenDRIVE/>" * 10

    def get_all_landmarks(self):
        return []

    def generate_waypoints(self, spacing):
        assert spacing == 2.0
        return [_Waypoint(), _Waypoint()]

    def get_topology(self):
        return [(_Waypoint(1, False), _Waypoint(2, True))]

    def get_spawn_points(self):
        return []

    def get_crosswalks(self):
        return []

    def get_spawn_points(self):
        return []


class _FakeActors:
    def filter(self, pattern):
        return []


class _FakeWorld:
    def get_map(self):
        return _FakeMap()

    def get_actors(self):
        return _FakeActors()


class _FakeClient:
    def get_world(self):
        return _FakeWorld()


@pytest.fixture(scope="module")
def plv():
    import phase_l_validation as mod

    return mod


# ---------------------------------------------------------------------------
# The core mutation contract: producer disabled -> status must NOT be PASS.
# ---------------------------------------------------------------------------


def test_l9_no_sensor_rig_must_not_be_pass(plv):
    result = plv.step_l9_sensor_validation(_FakeClient())
    assert result["status"] == "NOT_RUN"
    assert result["synchronization_status"] != "PASS"
    for sensor, data in result["sensor_data"].items():
        assert data["status"] != "CAPTURED"
        assert data["status"] == "NOT_RUN_NO_SENSOR_RIG"
        assert data["frame_non_empty"] is None
        assert data["timestamp_valid"] is None
    if "gnss" in result["sensor_data"]:
        assert result["sensor_data"]["gnss"]["gnss_agreement"] is None


def test_l7_zero_spawn_attempts_must_not_be_pass(plv):
    result = plv.step_l7_drivability(_FakeClient())
    assert result["status"] == "NOT_RUN"
    assert result["drivability_status"] != "PASS"
    assert result["vehicle_spawn_attempts"] == 0


def test_l8_no_signal_validator_flags_not_run(plv):
    result = plv.step_l8_signal_validation(_FakeClient())
    assert result["status"] == "NOT_RUN"
    assert result["signal_orientation_valid"] == "NOT_RUN"
    assert result["signal_associations_valid"] == "NOT_RUN"
    assert result["signal_validity_intervals_valid"] == "NOT_RUN"
    assert result["turn_lane_directions_valid"] == "NOT_RUN"
    assert result["signal_validation_status"] != "PASS"


def test_l10_no_frame_profiler_not_pass(plv):
    result = plv.step_l10_performance(_FakeClient())
    assert result["status"] == "NOT_RUN"
    assert result["performance_status"] != "PASS"
    assert result["fps"] is None
    # map_load_time_ms remains a REAL measured value (a number)
    assert isinstance(result["map_load_time_ms"], float)


def test_l11_no_comparison_rig_identical_flags_none(plv):
    result = plv.step_l11_old_vs_new(_FakeClient())
    assert result["status"] == "NOT_RUN"
    assert result["comparison_status"] != "PASS"
    for key in (
        "identical_cameras",
        "identical_vehicle",
        "identical_routes",
        "identical_weather",
        "identical_time",
        "identical_sensor_rig",
    ):
        assert result[key] is None


def test_l3_no_log_capture_not_ok(plv):
    result = plv.step_l3_parser_logs(_FakeClient())
    assert result["status"] == "NOT_RUN"
    assert result["parse_status"] != "OK"
    assert result["log_capture_source"] == "none"


def test_l5_no_camera_replay_not_pass(plv):
    result = plv.step_l5_visual_regression(_FakeClient())
    assert result["status"] == "NOT_RUN"
    assert result["visual_defect_regression_status"] != "PASS"


def test_l6_fixtures_never_assumed_pass(plv):
    result = plv.step_l6_waypoint_topology(_FakeClient())
    assert result["status"] == "NOT_RUN"
    for fixture in result["fixtures"].values():
        assert fixture["status"] != "PASS"
    # real RPC measurements still recorded
    assert result["waypoint_count"] == 2


def test_l4_no_landmarks_alignment_not_pass(plv):
    result = plv.step_l4_alignment(_FakeClient())
    assert result["status"] == "NOT_RUN"
    assert result["alignment_status"] != "ALIGNED"
    assert result["residual_max"] is None


def test_governed_status_helper(plv):
    assert plv.governed_status(producer_ran=False) == "NOT_RUN"
    assert plv.governed_status(producer_ran=True, evidence=True) == "PASS"
    assert plv.governed_status(producer_ran=True, evidence=False) == "NOT_RUN"


def test_l13_provenance_is_dynamic_not_hardcoded(plv):
    result = plv.step_l13_outputs(_FakeClient(), {"L1": {"status": "PASS"}})
    ident = result["git_identity"]
    assert "branch" in ident and "commit" in ident
    # The previously-fabricated constants must never reappear.
    assert result["branch"] != "fix/post-audit-phase-e-junctions-roundabouts-20260803"
    if result["commit"] is not None:
        assert result["commit"] != "f5aabc0a4f170e564aa03efcb906966880859a9f"
        assert len(result["commit"]) == 40


def test_l13_verdict_fails_closed_on_not_run(plv):
    all_results = {
        "L1": {"status": "PASS"},
        "L9": {"status": "NOT_RUN"},
    }
    result = plv.step_l13_outputs(_FakeClient(), all_results)
    assert result["verdict"] == "L_SOME_FAIL"
    assert "L9=NOT_RUN" in result["details"]


def test_repo_git_identity_reports_true_tree(plv):
    import subprocess

    ident = plv.repo_git_identity()
    if os.path.exists(str(ROOT / ".git")):
        cp = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT),
            capture_output=True, text=True, timeout=15,
        )
        if cp.returncode == 0:
            assert ident["commit"] == cp.stdout.strip()
    # never fabricates: missing git => explicit None
    if ident["commit"] is None:
        assert ident["branch"] is None
