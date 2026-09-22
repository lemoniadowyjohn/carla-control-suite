# -*- coding: utf-8 -*-
"""Offline unit tests for ultimate_pipeline/tools/capture_perception_pair_safe.py.

Regression: the pre-contract version reported `ok=True` whenever *any* frames
were written; a 60s-budget pair attempt that produced partial frames masqueraded
as success. Now `ok` is derived from the governed
`rq3_capture_contract.evaluate_frame_completeness`, so a timeout with partial
frames is INCOMPLETE (never PASS) and `_capture_arm` exits non-successfully.

These tests run fully offline with a duck-typed fake world / fake sensors; the
CARLA spawn and sensor-attach helpers are monkeypatched.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ultimate_pipeline.tools import capture_perception_pair_safe as tool
from ultimate_pipeline.perception.rq3_capture_contract import (
    COMPLETION_INCOMPLETE,
    COMPLETION_PASS,
    MODE_SMOKE_RECOVERY,
    MODE_THESIS_PAIRED_STRICT,
)


class _Clock:
    """Fake time source so the bounded wait loops terminate immediately."""

    def __init__(self):
        self.t = 0.0

    def time(self):
        return self.t

    def sleep(self, seconds):
        self.t += float(seconds)


class _Data:
    def __init__(self):
        self.saved = []

    def save_to_disk(self, path):
        self.saved.append(str(path))


class _FakeActor:
    def __init__(self, name, type_id):
        self.name = name
        self.type_id = type_id
        self._cb = None
        self.destroyed = False

    def listen(self, cb):
        self._cb = cb

    def emit(self, data):
        if self._cb is not None:
            self._cb(data)

    def stop(self):
        self._cb = None

    def destroy(self):
        self.destroyed = True


class _FakeWorld:
    """A world that emits one camera frame and ZERO lidar frames per tick."""

    def __init__(self, sensors, emit_lidar=True, camera_emit=1):
        self._sensors = sensors
        self._emit_lidar = emit_lidar
        self._camera_emit = camera_emit
        self.tick_count = 0

    def tick(self):
        for actor in self._sensors.values():
            if actor.type_id.startswith("sensor.camera"):
                for _ in range(self._camera_emit):
                    actor.emit(_Data())
            elif actor.type_id.startswith("sensor.lidar") and self._emit_lidar:
                actor.emit(_Data())
        self.tick_count += 1

    def get_settings(self):
        return SimpleNamespace(synchronous_mode=False, no_rendering_mode=False,
                               fixed_delta_seconds=0.05, max_substep_delta_time=0.01,
                               max_substeps=10)

    def apply_settings(self, settings):
        return None


def _sensor_dict():
    sensors = {
        "front_left_camera": _FakeActor("front_left_camera", "sensor.camera.rgb"),
        "middle_lidar": _FakeActor("middle_lidar", "sensor.lidar.ray_cast"),
    }
    return sensors


def _patch(monkeypatch, clock, sensors):
    tool.time = clock
    monkeypatch.setattr(
        tool,
        "safe_spawn_ego",
        lambda world, spawn_index, z_offset, report_path: (
            _FakeActor("ego", "vehicle.tesla.model3"),
            {"spawn_index": spawn_index, "spawn_selected_from_fallback": False},
        ),
    )
    monkeypatch.setattr(
        tool,
        "spawn_ego_strict_exact",
        lambda world, pose, z_offset, report_path: (
            _FakeActor("ego", "vehicle.tesla.model3"),
            {"spawned_at_requested_pose": True, "shuffle_used": False,
             "recovery_fallback_used": False, "poses_adjusted": []},
        ),
    )
    monkeypatch.setattr(
        tool,
        "attach_sensors_safe",
        lambda world, ego, calib_path, out_dir, camera_optical_frame: (
            sensors,
            {"attached": len(sensors)},
        ),
    )


def _poses(n):
    return [
        {"x": float(i * 2.0), "y": 0.0, "z": 0.0, "yaw": 0.0, "pitch": 0.0,
         "roll": 0.0, "sequence_index": i}
        for i in range(n)
    ]


@pytest.fixture(autouse=True)
def _reset():
    yield
    tool.time = __import__("time")


def test_strict_partial_frames_after_timeout_is_incomplete(tmp_path, monkeypatch):
    clock = _Clock()
    frames = 2
    sensors = _sensor_dict()
    world = _FakeWorld(sensors, emit_lidar=False)
    _patch(monkeypatch, clock, sensors)

    calib = tmp_path / "calib.json"
    calib.write_text('{"cameras": {}, "lidars": {}}', encoding="utf-8")

    report = tool._capture_arm(
        arm_name="manual",
        world=world,
        calib_path=str(calib),
        out_dir=tmp_path / "out",
        frames=frames,
        spawn_index=0,
        z_offset=0.0,
        camera_optical_frame=False,
        sync=False,
        route_mode=MODE_THESIS_PAIRED_STRICT,
        route_poses=_poses(2),
    )

    # Camera reached its frames, lidar stayed at 0 -> INCOMPLETE, never PASS.
    assert report["timed_out"] is True
    assert report["status"] == COMPLETION_INCOMPLETE
    assert report["ok"] is False
    assert report["completeness"]["complete"] is False
    assert report["sensor_frame_counts"]["front_left_camera"] == frames
    assert report["sensor_frame_counts"].get("middle_lidar", 0) == 0

    arm_report = json.loads((tmp_path / "out" / "arm_report.json").read_text(encoding="utf-8"))
    assert arm_report["ok"] is False
    assert arm_report["status"] == COMPLETION_INCOMPLETE


def test_strict_full_completion_is_pass(tmp_path, monkeypatch):
    clock = _Clock()
    frames = 2
    sensors = _sensor_dict()
    world = _FakeWorld(sensors, emit_lidar=True)
    _patch(monkeypatch, clock, sensors)

    calib = tmp_path / "calib.json"
    calib.write_text('{"cameras": {}, "lidars": {}}', encoding="utf-8")

    report = tool._capture_arm(
        arm_name="auto",
        world=world,
        calib_path=str(calib),
        out_dir=tmp_path / "out",
        frames=frames,
        spawn_index=0,
        z_offset=0.0,
        camera_optical_frame=False,
        sync=False,
        route_mode=MODE_THESIS_PAIRED_STRICT,
        route_poses=_poses(frames),
    )

    assert report["timed_out"] is False
    assert report["status"] == COMPLETION_PASS
    assert report["ok"] is True


def test_smoke_diagnostic_partial_frames_not_reported_ok(tmp_path, monkeypatch):
    """Smoke mode keeps the old loop but must still not claim full success."""
    clock = _Clock()
    frames = 5
    sensors = _sensor_dict()
    world = _FakeWorld(sensors, emit_lidar=False)
    _patch(monkeypatch, clock, sensors)

    calib = tmp_path / "calib.json"
    calib.write_text('{"cameras": {}, "lidars": {}}', encoding="utf-8")

    report = tool._capture_arm(
        arm_name="manual",
        world=world,
        calib_path=str(calib),
        out_dir=tmp_path / "out",
        frames=frames,
        spawn_index=0,
        z_offset=0.0,
        camera_optical_frame=False,
        sync=False,
        route_mode=MODE_SMOKE_RECOVERY,
    )

    assert report["ok"] is False
    assert report["status"] != COMPLETION_PASS