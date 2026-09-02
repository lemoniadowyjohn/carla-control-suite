# ultimate_pipeline/perception/rig_verifier.py -- zero prior test coverage on
# its own module (a pure re-export of tools/run_perception_safe.py's
# rig/manifest gate helpers). _classify_record_route_failure is already
# covered under the source module's own name
# (test_run_perception_safe_failure_classification.py); this closes
# coverage on the other two re-exported functions:
# enforce_manifest_gate_for_capture and derive_sync_settings_evidence.
# (refresh_thesis_contract_artifacts is intentionally not covered here --
# its dependency graph (classify_single_perception_result,
# build_visual_qa_contract) is large enough to warrant its own dedicated
# pass rather than being folded into this one.)
from __future__ import annotations

from pathlib import Path

import pytest

from ultimate_pipeline.perception.rig_verifier import (
    derive_sync_settings_evidence,
    enforce_manifest_gate_for_capture,
)


# ---------------------------------------------------------------------------
# derive_sync_settings_evidence
# ---------------------------------------------------------------------------

def test_derive_sync_settings_prefers_world_settings_applied():
    result = derive_sync_settings_evidence(
        capture_summary={
            "world_settings_applied": {"synchronous_mode": True, "fixed_delta_seconds": 0.05},
            "settings_applied_before_tick": True,
        },
        run_info_payload={"synchronous_mode": False, "fixed_delta_seconds": 0.1},
        recorder_cfg={"synchronous": False, "fixed_delta_seconds": 0.2},
    )
    assert result["synchronous_mode"] is True
    assert result["fixed_delta_seconds"] == 0.05
    assert result["settings_applied_before_tick"] is True
    assert result["applied_settings"] == {"synchronous_mode": True, "fixed_delta_seconds": 0.05}


def test_derive_sync_settings_falls_back_to_run_info_when_world_settings_missing():
    result = derive_sync_settings_evidence(
        capture_summary={},
        run_info_payload={"synchronous_mode": True, "fixed_delta_seconds": 0.033},
        recorder_cfg={"synchronous": False, "fixed_delta_seconds": 0.2},
    )
    assert result["synchronous_mode"] is True
    assert result["fixed_delta_seconds"] == 0.033


def test_derive_sync_settings_falls_back_to_recorder_cfg_last():
    result = derive_sync_settings_evidence(
        capture_summary={},
        run_info_payload={},
        recorder_cfg={"synchronous": True, "fixed_delta_seconds": 0.02},
    )
    assert result["synchronous_mode"] is True
    assert result["fixed_delta_seconds"] == 0.02


def test_derive_sync_settings_defaults_are_falsy_and_zero():
    result = derive_sync_settings_evidence(
        capture_summary={}, run_info_payload={}, recorder_cfg={}
    )
    assert result["synchronous_mode"] is False
    assert result["fixed_delta_seconds"] == 0.0
    assert result["settings_applied_before_tick"] is False


# ---------------------------------------------------------------------------
# enforce_manifest_gate_for_capture
# ---------------------------------------------------------------------------

def _write_manifest(path: Path) -> None:
    import json

    path.write_text(
        json.dumps(
            {
                "counts": {"total_files": 3},
                "sensors": [{"id": "cam_front"}],
                "carla_map_name": "Town_Ingolstadt",
                "carla_map_basename": "Town_Ingolstadt",
                "carla_world_settings": {"synchronous_mode": True},
            }
        ),
        encoding="utf-8",
    )


def test_gate_disabled_returns_empty_string_without_checking_manifest(tmp_path: Path):
    result = enforce_manifest_gate_for_capture(
        require_manifest_gate=False,
        recording_dir=tmp_path / "does_not_exist",
        out_dir=tmp_path / "also_missing",
        manifest_sync=None,
        capture_status_payload=None,
    )
    assert result == ""


def test_gate_enabled_passes_with_valid_manifest(tmp_path: Path):
    recording_dir = tmp_path / "recording"
    recording_dir.mkdir()
    _write_manifest(recording_dir / "recorder_manifest.json")

    result = enforce_manifest_gate_for_capture(
        require_manifest_gate=True,
        recording_dir=recording_dir,
        out_dir=tmp_path / "out",
        manifest_sync=None,
        capture_status_payload=None,
    )
    assert result == ""


def test_gate_enabled_raises_on_missing_manifest(tmp_path: Path):
    with pytest.raises(RuntimeError, match="MISSING_RECORDER_MANIFEST"):
        enforce_manifest_gate_for_capture(
            require_manifest_gate=True,
            recording_dir=tmp_path / "recording",
            out_dir=tmp_path / "out",
            manifest_sync=None,
            capture_status_payload=None,
        )


def test_gate_bypasses_on_known_capture_failure_reason(tmp_path: Path):
    # A known, classified capture failure short-circuits the manifest
    # integrity check entirely and returns the bypass reason instead of
    # raising -- there's nothing meaningful to validate if capture itself
    # already failed for a known reason.
    result = enforce_manifest_gate_for_capture(
        require_manifest_gate=True,
        recording_dir=tmp_path / "recording",
        out_dir=tmp_path / "out",
        manifest_sync=None,
        capture_status_payload={"status": "FAIL", "failure_reason": "SENSOR_SPAWN_TIMEOUT"},
    )
    assert result == "sensor_spawn_timeout"


def test_gate_bypasses_on_explicit_runtime_failure_hint(tmp_path: Path):
    result = enforce_manifest_gate_for_capture(
        require_manifest_gate=True,
        recording_dir=tmp_path / "recording",
        out_dir=tmp_path / "out",
        manifest_sync=None,
        capture_status_payload=None,
        runtime_failure_hint="record_route_timeout",
    )
    assert result == "record_route_timeout"
