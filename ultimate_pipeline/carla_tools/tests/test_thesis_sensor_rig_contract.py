#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests thesis sensor rig contract (camera no inversion, LiDAR inversion) and rig_verification.json."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ultimate_pipeline.carla_tools.thesis_sensor_rig import (
    ThesisSensorRig,
    RigVerification,
    SpawnedSensor,
    RIG_VERIFICATION_FILENAME,
    _guard_thesis_inversion_env,
)


def _make_test_calib() -> dict:
    """Create a standard test calibration dict."""
    return {
        "cameras": {
            "cam0": {
                "K_undistortion": [
                    [1000.0, 0.0, 640.0],
                    [0.0, 1000.0, 360.0],
                    [0.0, 0.0, 1.0],
                ],
                "image_size": [1280, 720],
                "cTv": [[1, 0, 0, 1], [0, 1, 0, 2], [0, 0, 1, 3], [0, 0, 0, 1]],
            }
        },
        "lidars": {
            "lidar0": {
                "vTl": [[1, 0, 0, 1], [0, 1, 0, 2], [0, 0, 1, 3], [0, 0, 0, 1]],
            }
        },
    }


def test_thesis_sensor_rig_no_inversion(tmp_path: Path) -> None:
    calib = _make_test_calib()
    calib_path = tmp_path / "calib.json"
    calib_path.write_text(json.dumps(calib), encoding="utf-8")

    rig = ThesisSensorRig(calib_path)
    reports = rig.reports_from_calib_only()

    cam = reports["cam0"]
    assert cam["ctv_inverted"] is False
    assert cam["inversion_applied"] is False
    assert cam["raw_direction_label"] == "vehicle_to_camera"

    lidar = reports["lidar0"]
    assert lidar["vtl_inverted"] is True
    assert lidar["inversion_applied"] is True
    assert lidar["raw_direction_label"] == "lidar_to_vehicle"
    assert lidar["used_direction_label"] == "vehicle_to_lidar"


def test_rig_verification_to_dict() -> None:
    """Test RigVerification.to_dict() produces correct structure."""
    verification = RigVerification(
        use_K_undistortion_only=True,
        ignored_K_and_D=False,
        cTv_inverted=False,
        vTl_inverted=True,
        cameras_count=2,
        lidars_count=1,
        timestamp_utc="2024-01-01T00:00:00Z",
        calib_path="/path/to/calib.json",
        map_identity={"world_map_name": "TestMap"},
        sensors={"cam0": {"type": "camera", "ctv_inverted": False}},
        compliance_notes=["OK: All cameras use K_undistortion only"],
        sensor_contract={
            "camera_intrinsics_source": "K_undistortion",
            "ignore_fields": ["K", "D"],
            "cTv_definition": "vehicle->camera",
            "vTl_definition": "lidar->vehicle",
            "cTv_inverted": False,
            "vTl_inverted": True,
            "cTv_inversion_forbidden": True,
            "vTl_inversion_required": True,
        },
        applied_carla_transforms={"ego_vehicle_world": None, "sensors": {}},
    )

    data = verification.to_dict()

    # Check schema version
    assert data["schema_version"] == 1

    # Check thesis_compliance block
    assert "thesis_compliance" in data
    tc = data["thesis_compliance"]
    assert tc["use_K_undistortion_only"] is True
    assert tc["ignored_K_and_D"] is False
    assert tc["ctv_inverted"] is False
    assert tc["vtl_inverted"] is True

    # Check sensors_summary
    assert data["sensors_summary"]["cameras_count"] == 2
    assert data["sensors_summary"]["lidars_count"] == 1

    # Check other fields
    assert data["timestamp_utc"] == "2024-01-01T00:00:00Z"
    assert data["calib_path"] == "/path/to/calib.json"
    assert data["map_identity"]["world_map_name"] == "TestMap"
    assert len(data["compliance_notes"]) == 1


def test_build_rig_verification_from_reports(tmp_path: Path) -> None:
    """Test build_rig_verification extracts correct compliance flags."""
    calib = _make_test_calib()
    calib_path = tmp_path / "calib.json"
    calib_path.write_text(json.dumps(calib), encoding="utf-8")

    rig = ThesisSensorRig(calib_path)

    # Create mock SpawnedSensor objects from reports
    reports = rig.reports_from_calib_only()
    spawned = {}
    for name, report in reports.items():
        # Use None for actor since we're not testing CARLA interaction
        spawned[name] = SpawnedSensor(actor=None, report=report)

    verification = rig.build_rig_verification(spawned)

    assert verification.use_K_undistortion_only is True
    assert verification.cTv_inverted is False
    assert verification.vTl_inverted is True
    assert verification.cameras_count == 1
    assert verification.lidars_count == 1


def test_write_rig_verification_creates_file(tmp_path: Path) -> None:
    """Test write_rig_verification creates rig_verification.json."""
    calib = _make_test_calib()
    calib_path = tmp_path / "calib.json"
    calib_path.write_text(json.dumps(calib), encoding="utf-8")

    out_dir = tmp_path / "run_output"
    out_dir.mkdir()

    rig = ThesisSensorRig(calib_path)
    reports = rig.reports_from_calib_only()
    spawned = {
        name: SpawnedSensor(actor=None, report=report)
        for name, report in reports.items()
    }

    result_path = rig.write_rig_verification(out_dir, spawned)

    assert result_path.exists()
    assert result_path.name == RIG_VERIFICATION_FILENAME

    # Verify file content
    data = json.loads(result_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert "thesis_compliance" in data
    assert data["thesis_compliance"]["use_K_undistortion_only"] is True
    assert data["thesis_compliance"]["ctv_inverted"] is False
    assert data["thesis_compliance"]["vtl_inverted"] is True


def test_write_rig_verification_with_extra(tmp_path: Path) -> None:
    """Test write_rig_verification includes extra fields."""
    calib = _make_test_calib()
    calib_path = tmp_path / "calib.json"
    calib_path.write_text(json.dumps(calib), encoding="utf-8")

    out_dir = tmp_path / "run_output"
    out_dir.mkdir()

    rig = ThesisSensorRig(calib_path)
    reports = rig.reports_from_calib_only()
    spawned = {
        name: SpawnedSensor(actor=None, report=report)
        for name, report in reports.items()
    }

    extra_info = {
        "spawn_index": 42,
        "stage": "attach_sensors",
        "success": True,
    }

    result_path = rig.write_rig_verification(out_dir, spawned, extra=extra_info)

    data = json.loads(result_path.read_text(encoding="utf-8"))
    assert "extra" in data
    assert data["extra"]["spawn_index"] == 42
    assert data["extra"]["stage"] == "attach_sensors"
    assert data["extra"]["success"] is True


def test_write_rig_verification_early_abort_marker(tmp_path: Path) -> None:
    """Test write_rig_verification with early_abort marker."""
    calib = _make_test_calib()
    calib_path = tmp_path / "calib.json"
    calib_path.write_text(json.dumps(calib), encoding="utf-8")

    out_dir = tmp_path / "run_output"
    out_dir.mkdir()

    rig = ThesisSensorRig(calib_path)
    reports = rig.reports_from_calib_only()
    spawned = {
        name: SpawnedSensor(actor=None, report=report)
        for name, report in reports.items()
    }

    result_path = rig.write_rig_verification(
        out_dir,
        spawned,
        extra={
            "stage": "teardown",
            "success": False,
            "early_abort": True,
        },
    )

    data = json.loads(result_path.read_text(encoding="utf-8"))
    assert data["extra"]["early_abort"] is True
    assert data["extra"]["success"] is False


def test_rig_verification_detects_k_and_d_ignored(tmp_path: Path) -> None:
    """Test that ignored_K_and_D is True when K and D are present but unused."""
    calib = {
        "cameras": {
            "cam0": {
                "K_undistortion": [
                    [1000.0, 0.0, 640.0],
                    [0.0, 1000.0, 360.0],
                    [0.0, 0.0, 1.0],
                ],
                "K": [
                    [1000.0, 0.0, 640.0],
                    [0.0, 1000.0, 360.0],
                    [0.0, 0.0, 1.0],
                ],  # Present but ignored
                "D": [0.1, 0.01, 0.0, 0.0, 0.0],  # Present but ignored
                "image_size": [1280, 720],
                "cTv": [[1, 0, 0, 1], [0, 1, 0, 2], [0, 0, 1, 3], [0, 0, 0, 1]],
            }
        },
        "lidars": {},
    }
    calib_path = tmp_path / "calib.json"
    calib_path.write_text(json.dumps(calib), encoding="utf-8")

    rig = ThesisSensorRig(calib_path)
    reports = rig.reports_from_calib_only()
    spawned = {
        name: SpawnedSensor(actor=None, report=report)
        for name, report in reports.items()
    }

    verification = rig.build_rig_verification(spawned)

    # K_undistortion is present, so use_K_undistortion_only should be True
    assert verification.use_K_undistortion_only is True
    # K and D are present but ignored by thesis mode
    assert verification.ignored_K_and_D is True


def test_thesis_strict_raises_on_non_canonical_env_vars(monkeypatch) -> None:
    """UP_THESIS_STRICT=1 must raise RuntimeError for non-canonical override values.

    Per T-036 governance ruling:
    - UP_CAMERA_CTV_ATTACH=direct is PERMITTED (canonical)
    - UP_CAMERA_CTV_ATTACH=<other> is FORBIDDEN
    - UP_CAMERA_CTV_INVERT, UP_CAMERA_CTV_CONVENTION are ALWAYS FORBIDDEN
    - UP_LIDAR_VTL_ATTACH=invert is PERMITTED (canonical)
    - UP_LIDAR_VTL_ATTACH=<other> is FORBIDDEN
    """
    monkeypatch.setenv("UP_THESIS_STRICT", "1")

    # Test always-forbidden vars (any value triggers failure)
    always_forbidden_vars = [
        "UP_CAMERA_CTV_INVERT",
        "UP_CAMERA_CTV_CONVENTION",
    ]

    for var in always_forbidden_vars:
        monkeypatch.setenv(var, "any_value")

        with pytest.raises(RuntimeError) as exc_info:
            _guard_thesis_inversion_env()

        assert "non-canonical inversion override" in str(exc_info.value)
        assert var in str(exc_info.value)

        monkeypatch.delenv(var)

    # Test non-canonical UP_CAMERA_CTV_ATTACH value
    monkeypatch.setenv("UP_CAMERA_CTV_ATTACH", "invert")  # non-canonical
    with pytest.raises(RuntimeError) as exc_info:
        _guard_thesis_inversion_env()
    assert "non-canonical inversion override" in str(exc_info.value)
    assert "UP_CAMERA_CTV_ATTACH" in str(exc_info.value)
    monkeypatch.delenv("UP_CAMERA_CTV_ATTACH")

    # Lidar override must be rejected if it disables inversion.
    monkeypatch.setenv("UP_LIDAR_VTL_ATTACH", "direct")  # non-canonical
    with pytest.raises(RuntimeError) as exc_info:
        _guard_thesis_inversion_env()
    assert "non-canonical inversion override" in str(exc_info.value)
    assert "UP_LIDAR_VTL_ATTACH" in str(exc_info.value)
    monkeypatch.delenv("UP_LIDAR_VTL_ATTACH")


def test_thesis_strict_passes_without_inversion_vars(monkeypatch) -> None:
    """UP_THESIS_STRICT=1 passes when no inversion env vars are set."""
    monkeypatch.setenv("UP_THESIS_STRICT", "1")
    # Ensure no inversion vars are set
    for var in [
        "UP_CAMERA_CTV_ATTACH",
        "UP_CAMERA_CTV_INVERT",
        "UP_LIDAR_VTL_ATTACH",
        "UP_CAMERA_CTV_CONVENTION",
    ]:
        monkeypatch.delenv(var, raising=False)

    # Should not raise
    _guard_thesis_inversion_env()


def test_thesis_strict_permits_canonical_camera_ctv_direct(monkeypatch) -> None:
    """UP_THESIS_STRICT=1 permits canonical UP_CAMERA_CTV_ATTACH=direct (T-036)."""
    monkeypatch.setenv("UP_THESIS_STRICT", "1")
    # Ensure no other override vars are set
    for var in ["UP_CAMERA_CTV_INVERT", "UP_LIDAR_VTL_ATTACH", "UP_CAMERA_CTV_CONVENTION"]:
        monkeypatch.delenv(var, raising=False)

    # All canonical synonyms for "direct" should pass
    canonical_values = ["direct", "ctv_direct", "vehicle_to_camera", "no_invert", "0", "false", "off"]
    for val in canonical_values:
        monkeypatch.setenv("UP_CAMERA_CTV_ATTACH", val)
        _guard_thesis_inversion_env()  # Should not raise


def test_thesis_strict_permits_canonical_lidar_vtl_invert(monkeypatch) -> None:
    """UP_THESIS_STRICT=1 permits canonical UP_LIDAR_VTL_ATTACH=invert (T-036)."""
    monkeypatch.setenv("UP_THESIS_STRICT", "1")
    # Ensure no other override vars are set
    for var in ["UP_CAMERA_CTV_ATTACH", "UP_CAMERA_CTV_INVERT", "UP_CAMERA_CTV_CONVENTION"]:
        monkeypatch.delenv(var, raising=False)

    # All canonical synonyms for "invert" should pass
    canonical_values = ["invert", "inverse", "vehicle_to_lidar", "vtl_invert", "auto", "1", "true", "yes", "on"]
    for val in canonical_values:
        monkeypatch.setenv("UP_LIDAR_VTL_ATTACH", val)
        _guard_thesis_inversion_env()  # Should not raise


def test_thesis_strict_permits_both_canonical_env_vars(monkeypatch) -> None:
    """UP_THESIS_STRICT=1 permits both canonical env vars set simultaneously (T-036).

    This is the canonical handoff command:
    $env:UP_THESIS_STRICT = "1"
    $env:UP_CAMERA_CTV_ATTACH = "direct"
    $env:UP_LIDAR_VTL_ATTACH = "invert"
    """
    monkeypatch.setenv("UP_THESIS_STRICT", "1")
    monkeypatch.setenv("UP_CAMERA_CTV_ATTACH", "direct")
    monkeypatch.setenv("UP_LIDAR_VTL_ATTACH", "invert")
    # Ensure forbidden vars are not set
    for var in ["UP_CAMERA_CTV_INVERT", "UP_CAMERA_CTV_CONVENTION"]:
        monkeypatch.delenv(var, raising=False)

    # Should not raise - this is the canonical thesis operator configuration
    _guard_thesis_inversion_env()


def test_thesis_invariant_ctv_vtl_never_inverted(tmp_path: Path) -> None:
    """Verify thesis invariant: ctv_inverted=false and vtl_inverted=true always."""
    calib = {
        "cameras": {
            "front_camera": {
                "K_undistortion": [
                    [800.0, 0.0, 320.0],
                    [0.0, 800.0, 240.0],
                    [0.0, 0.0, 1.0],
                ],
                "image_size": [640, 480],
                "cTv": [[1, 0, 0, 0.5], [0, 1, 0, 0], [0, 0, 1, 1.5], [0, 0, 0, 1]],
            },
            "rear_camera": {
                "K_undistortion": [
                    [600.0, 0.0, 320.0],
                    [0.0, 600.0, 240.0],
                    [0.0, 0.0, 1.0],
                ],
                "image_size": [640, 480],
                "cTv": [[1, 0, 0, -0.5], [0, 1, 0, 0], [0, 0, 1, 1.5], [0, 0, 0, 1]],
            },
        },
        "lidars": {
            "top_lidar": {
                "vTl": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 2.0], [0, 0, 0, 1]],
            },
        },
    }
    calib_path = tmp_path / "calib.json"
    calib_path.write_text(json.dumps(calib), encoding="utf-8")

    rig = ThesisSensorRig(calib_path)
    reports = rig.reports_from_calib_only()

    # All cameras must have ctv_inverted=False and inversion_applied=False
    for cam_name in ["front_camera", "rear_camera"]:
        assert cam_name in reports
        assert reports[cam_name]["ctv_inverted"] is False
        assert reports[cam_name]["inversion_applied"] is False
        assert reports[cam_name]["raw_direction_label"] == "vehicle_to_camera"
        assert (
            "FORBIDDEN" in reports[cam_name]["transform_convention"]
            or "directly" in reports[cam_name]["transform_convention"]
        )

    # All lidars must have vtl_inverted=True and inversion_applied=True
    assert "top_lidar" in reports
    assert reports["top_lidar"]["vtl_inverted"] is True
    assert reports["top_lidar"]["inversion_applied"] is True
    assert reports["top_lidar"]["raw_direction_label"] == "lidar_to_vehicle"
    assert reports["top_lidar"]["used_direction_label"] == "vehicle_to_lidar"


def test_healthcheck_stops_temporary_listeners() -> None:
    """Healthcheck must release temporary listeners before recorder attach."""

    class _FakeActor:
        def __init__(self) -> None:
            self._cb = None
            self.stop_calls = 0

        def listen(self, cb):
            self._cb = cb

        def emit_once(self) -> None:
            if self._cb is not None:
                self._cb(object())

        def stop(self) -> None:
            self.stop_calls += 1
            self._cb = None

    class _FakeWorld:
        def __init__(self, actors):
            self._actors = actors
            self.ticks = 0

        def tick(self):
            self.ticks += 1
            for actor in self._actors:
                actor.emit_once()
            return self.ticks

    a0 = _FakeActor()
    a1 = _FakeActor()
    sensors = {
        "cam0": SpawnedSensor(actor=a0, report={}),
        "cam1": SpawnedSensor(actor=a1, report={}),
    }
    world = _FakeWorld([a0, a1])

    ThesisSensorRig._healthcheck_sensor_streams(world, sensors, timeout_s=0.2)

    assert a0.stop_calls >= 1
    assert a1.stop_calls >= 1
    assert sensors["cam0"].report["healthcheck"]["first_measurement_ok"] is True
    assert sensors["cam1"].report["healthcheck"]["first_measurement_ok"] is True
