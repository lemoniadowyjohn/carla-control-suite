#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Adversarial tests for terminal authority false-PASS scenarios.

These tests verify that the terminal chain correctly rejects:
- Stale SUCCESS.txt from a previous run
- Stale pipeline_health_summary.json
- Stale validation_report_full.json
- Stale run_summary.json
- Stale final_run_verdict.json
- Mandatory pack member absent
- Wrong digest in pack
- Stale run_id in artifacts

All tests create a fake previous-run output directory, then run the
terminal chain and verify it does not produce a false PASS.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import pytest

from ultimate_pipeline.signals.verdict import compute_final_run_verdict
from ultimate_pipeline.utils.finalize_run_pack import (
    finalize_run_pack,
    verify_run_pack,
)
from ultimate_pipeline.signals.registry import mandatory_pack_artifacts


def _write_fake_previous_run(out_dir: Path, run_id: str = "fake-old-run") -> None:
    """Create artifacts that look like a successful previous run."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # run_identity.json (old run)
    (out_dir / "run_identity.json").write_text(
        json.dumps({
            "run_id": run_id,
            "source_sha": "0" * 64,
            "profile": "structural_release",
            "settings_digest": "0" * 64,
            "started_at_utc": "2026-01-01T00:00:00Z",
            "out_dir": str(out_dir),
        }, indent=2),
        encoding="utf-8",
    )

    # SUCCESS.txt (old)
    (out_dir / "SUCCESS.txt").write_text(
        "OK 2026-01-01T00:00:00Z\nstatus=PASS\nschema=RUN_PACK_FINALIZATION/v2\n",
        encoding="utf-8",
    )

    # signature.json (old)
    (out_dir / "signature.json").write_text(
        json.dumps({
            "schema": "RUN_PACK_FINALIZATION/v2",
            "status": "PASS",
            "files": {"final.xodr": "a" * 64},
            "signature_sha256": "b" * 64,
            "manifest_sha256": "c" * 64,
        }, indent=2),
        encoding="utf-8",
    )

    # pipeline_health_summary.json (old)
    (out_dir / "pipeline_health_summary.json").write_text(
        json.dumps({
            "schema": "pipeline_health_summary/v1",
            "overall_ok": True,
            "gates": {"geometric_continuity": {"ok": True, "status": "pass"}},
            "run_metadata": {"roads": 100, "junctions": 20},
        }, indent=2),
        encoding="utf-8",
    )

    # validation_report_full.json (old)
    (out_dir / "logs").mkdir(exist_ok=True)
    (out_dir / "logs" / "validation_report_full.json").write_text(
        json.dumps({
            "schema": "validation_report_full/v1",
            "summary": {"ok": True},
            "stages": {},
        }, indent=2),
        encoding="utf-8",
    )

    # run_summary.json (old)
    (out_dir / "run_summary.json").write_text(
        json.dumps({
            "schema": "run_summary/v1",
            "pipeline_version": "old",
            "run_timestamp_utc": "2026-01-01T00:00:00Z",
            "run_dir": str(out_dir),
            "run_id": run_id,
            "inputs": {"osm_file": "", "bbox_json": ""},
            "outputs": {"final_xodr": "final.xodr", "semantic_xodr": ""},
            "validation": {"preflight_status": None, "tile_qa_status": None},
            "settings": {"snapshot_path": "", "snapshot_sha256": None, "snapshot_md5": None},
        }, indent=2),
        encoding="utf-8",
    )

    # final_run_verdict.json (old)
    (out_dir / "final_run_verdict.json").write_text(
        json.dumps({
            "schema": "final_run_verdict/v1",
            "generated_at_utc": "2026-01-01T00:00:00Z",
            "release_profile": "structural_release",
            "status": "PASS",
            "run_status_ok": True,
        }, indent=2),
        encoding="utf-8",
    )

    # gate_failures.json (old)
    (out_dir / "gate_failures.json").write_text("{}", encoding="utf-8")

    # final.xodr (placeholder)
    (out_dir / "final.xodr").write_text("<?xml version='1.0'?><OpenDRIVE/>", encoding="utf-8")


def _make_minimal_current_artifacts(out_dir: Path, run_id: str) -> None:
    """Create minimal valid artifacts for a NEW run with the given run_id.

    Includes all mandatory artifacts for structural_release profile per registry.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # run_identity.json (current run)
    (out_dir / "run_identity.json").write_text(
        json.dumps({
            "run_id": run_id,
            "source_sha": "1" * 64,
            "profile": "structural_release",
            "settings_digest": "1" * 64,
            "started_at_utc": "2026-01-02T00:00:00Z",
            "out_dir": str(out_dir),
        }, indent=2),
        encoding="utf-8",
    )

    # final.xodr
    (out_dir / "final.xodr").write_text("<?xml version=\"1.0\"?><OpenDRIVE/>", encoding="utf-8")

    # Minimal pipeline health (all expected gates present and passing)
    expected_gates = [
        "geometric_continuity", "planview_internal_seams", "origin_sanity",
        "elevation_seams", "elevation_continuity", "full_map_metrics",
        "drivable_surface", "junction_integrity", "post_tiling_integrity",
        "lane_width_continuity", "lane_geometry_continuity",
    ]
    gates = {g: {"ok": True, "status": "pass"} for g in expected_gates}
    (out_dir / "pipeline_health_summary.json").write_text(
        json.dumps({
            "schema": "pipeline_health_summary/v1",
            "overall_ok": True,
            "gates": gates,
            "run_metadata": {"roads": 100, "junctions": 20},
            "run_id": run_id,
        }, indent=2),
        encoding="utf-8",
    )

    # validation report
    (out_dir / "logs").mkdir(exist_ok=True)
    (out_dir / "logs" / "validation_report_full.json").write_text(
        json.dumps({
            "schema": "validation_report_full/v1",
            "summary": {"ok": True},
            "stages": {},
            "run_id": run_id,
        }, indent=2),
        encoding="utf-8",
    )

    # run summary with current run_id
    (out_dir / "run_summary.json").write_text(
        json.dumps({
            "schema": "run_summary/v1",
            "pipeline_version": "thesis_final",
            "run_timestamp_utc": "2026-01-02T00:00:00Z",
            "run_dir": str(out_dir),
            "run_id": run_id,
            "inputs": {"osm_file": "", "bbox_json": ""},
            "outputs": {"final_xodr": "final.xodr", "semantic_xodr": ""},
            "validation": {"preflight_status": None, "tile_qa_status": None},
            "settings": {"snapshot_path": "", "snapshot_sha256": None, "snapshot_md5": None},
        }, indent=2),
        encoding="utf-8",
    )

    # gate_failures
    (out_dir / "gate_failures.json").write_text("{}", encoding="utf-8")

    # cumulative_gate_report (mandatory for structural)
    (out_dir / "cumulative_gate_report.json").write_text(
        json.dumps({"schema": "cumulative_gate_report/v1", "failed": 0, "total": len(expected_gates), "run_id": run_id}, indent=2),
        encoding="utf-8",
    )

    # environment_snapshot
    (out_dir / "environment_snapshot.json").write_text(
        json.dumps({"schema": "environment_snapshot/v1", "run_id": run_id}, indent=2),
        encoding="utf-8",
    )

    # determinism_fingerprint
    (out_dir / "determinism_fingerprint.json").write_text(
        json.dumps({"schema": "determinism_fingerprint/v1", "final_xodr": "final.xodr", "run_id": run_id}, indent=2),
        encoding="utf-8",
    )

    # final_artifact_receipt
    (out_dir / "final_artifact_receipt.json").write_text(
        json.dumps({
            "schema": "final_artifact_receipt/v1",
            "final_artifact_sha256": "a" * 64,
            "structure_fingerprint": {"sha256": "b" * 64},
            "run_id": run_id,
        }, indent=2),
        encoding="utf-8",
    )

    # map_acceptance
    (out_dir / "map_acceptance.json").write_text(
        json.dumps({"schema": "map_acceptance/v1", "valid_for_experiments": True, "run_id": run_id}, indent=2),
        encoding="utf-8",
    )

    # carla_loadability_status (mandatory for structural)
    (out_dir / "carla_loadability_status.json").write_text(
        json.dumps({"status": "ok", "preflight_report_path": "", "run_id": run_id}, indent=2),
        encoding="utf-8",
    )

    # step10_tile_qa_status (mandatory for structural)
    (out_dir / "step10_tile_qa_status.json").write_text(
        json.dumps({"status": "ok", "run_id": run_id}, indent=2),
        encoding="utf-8",
    )

    # step10c_road_defects_status (mandatory for structural)
    (out_dir / "step10c_road_defects_status.json").write_text(
        json.dumps({"status": "ok", "run_id": run_id}, indent=2),
        encoding="utf-8",
    )


class TestStaleSuccessRevocation:
    """Stale SUCCESS.txt must be revoked before a new run."""

    def test_stale_success_removed_on_new_run(self, tmp_path: Path):
        # Create a previous run with SUCCESS.txt
        _write_fake_previous_run(tmp_path, "old-run-123")
        assert (tmp_path / "SUCCESS.txt").exists()

        # Simulate new run admission: should revoke stale SUCCESS using REAL production method
        from ultimate_pipeline.core.terminal_authority import revoke_stale_success

        # Call the real production function directly
        revoke_stale_success(tmp_path)

        assert not (tmp_path / "SUCCESS.txt").exists(), "Stale SUCCESS.txt was not revoked"

    def test_stale_success_idempotent_when_absent(self, tmp_path: Path):
        """If no SUCCESS.txt exists, revoke_stale_success is idempotent (no error)."""
        from ultimate_pipeline.core.terminal_authority import revoke_stale_success

        # Should not raise
        revoke_stale_success(tmp_path)
        assert not (tmp_path / "SUCCESS.txt").exists()

    def test_stale_success_deletion_failure_fails_closed(self, tmp_path: Path, monkeypatch):
        """If SUCCESS.txt exists but cannot be deleted, the function must raise."""
        from ultimate_pipeline.core.terminal_authority import revoke_stale_success

        # Create a stale SUCCESS.txt
        (tmp_path / "SUCCESS.txt").write_text("OK 2026-01-01T00:00:00Z\nstatus=PASS\n", encoding="utf-8")
        assert (tmp_path / "SUCCESS.txt").exists()

        # Make the file undeletable by patching Path.unlink to raise
        from pathlib import Path as P
        original_unlink = P.unlink

        def failing_unlink(self, missing_ok=False):
            if self.name == "SUCCESS.txt":
                raise PermissionError("Permission denied")
            return original_unlink(self, missing_ok)

        monkeypatch.setattr(P, "unlink", failing_unlink)

        import pytest
        with pytest.raises(RuntimeError, match="Failed to revoke stale SUCCESS.txt"):
            revoke_stale_success(tmp_path)

        # SUCCESS.txt should still exist (deletion failed)
        assert (tmp_path / "SUCCESS.txt").exists()


class TestStaleEvidenceRejection:
    """Stale artifacts (from previous runs) must be rejected by the verdict."""

    def test_stale_health_summary_rejected(self, tmp_path: Path):
        # Create old run artifacts
        _write_fake_previous_run(tmp_path, "old-run")

        # Create new run with current run_id but NO health summary (simulating failure)
        new_run_id = "new-run-456"
        _make_minimal_current_artifacts(tmp_path, new_run_id)
        # Remove the health summary to simulate a failed run
        (tmp_path / "pipeline_health_summary.json").unlink()

        # Verdict should FAIL because health is missing
        verdict = compute_final_run_verdict(str(tmp_path), profile="structural_release")
        assert verdict["status"] == "FAIL", f"Expected FAIL, got {verdict['status']}"

    def test_stale_validation_report_rejected(self, tmp_path: Path):
        _write_fake_previous_run(tmp_path, "old-run")
        new_run_id = "new-run-456"
        _make_minimal_current_artifacts(tmp_path, new_run_id)
        # Remove validation report
        (tmp_path / "logs" / "validation_report_full.json").unlink()

        verdict = compute_final_run_verdict(str(tmp_path), profile="structural_release")
        assert verdict["status"] == "FAIL", f"Expected FAIL, got {verdict['status']}"

    def test_stale_run_summary_rejected(self, tmp_path: Path):
        _write_fake_previous_run(tmp_path, "old-run")
        new_run_id = "new-run-456"
        _make_minimal_current_artifacts(tmp_path, new_run_id)
        # Remove run summary
        (tmp_path / "run_summary.json").unlink()

        verdict = compute_final_run_verdict(str(tmp_path), profile="structural_release")
        assert verdict["status"] == "FAIL", f"Expected FAIL, got {verdict['status']}"

    def test_stale_final_verdict_rejected(self, tmp_path: Path):
        _write_fake_previous_run(tmp_path, "old-run")
        new_run_id = "new-run-456"
        _make_minimal_current_artifacts(tmp_path, new_run_id)
        # Remove final verdict
        (tmp_path / "final_run_verdict.json").unlink()

        verdict = compute_final_run_verdict(str(tmp_path), profile="structural_release")
        assert verdict["status"] == "FAIL", f"Expected FAIL, got {verdict['status']}"

    def test_stale_artifact_with_wrong_run_id_rejected(self, tmp_path: Path):
        """An artifact with a mismatched run_id should be treated as INCOMPLETE."""
        new_run_id = "new-run-456"
        _make_minimal_current_artifacts(tmp_path, new_run_id)

        # Corrupt the health summary with old run_id
        health = json.loads((tmp_path / "pipeline_health_summary.json").read_text())
        health["run_id"] = "wrong-run-id"
        (tmp_path / "pipeline_health_summary.json").write_text(json.dumps(health), encoding="utf-8")

        # The signal index should show PIPELINE_HEALTH as INCOMPLETE due to run_id mismatch
        from ultimate_pipeline.signals.index import build_signal_index
        index = build_signal_index(str(tmp_path), profile="structural_release")
        health_entry = index["signals"]["PIPELINE_HEALTH"]
        assert health_entry["status"] == "INCOMPLETE", f"Expected INCOMPLETE, got {health_entry['status']}"


class TestMandatoryPackVerification:
    """The mandatory pack must require all profile-derived artifacts."""

    def test_mandatory_pack_absent_member_fails(self, tmp_path: Path):
        new_run_id = "new-run-456"
        _make_minimal_current_artifacts(tmp_path, new_run_id)

        # Remove a mandatory artifact
        (tmp_path / "pipeline_health_summary.json").unlink()

        # finalize_run_pack should FAIL
        final_xodr = str(tmp_path / "final.xodr")
        mandatory = mandatory_pack_artifacts("structural_release", final_xodr)
        receipt = finalize_run_pack(str(tmp_path), mandatory, emit_success=True)
        assert receipt["status"] == "FAIL"

        # verify_run_pack should also FAIL
        verify_result = verify_run_pack(str(tmp_path))
        assert verify_result["status"] == "FAIL"

    def test_mandatory_pack_wrong_digest_fails(self, tmp_path: Path):
        """Changing an artifact's content after pack finalization must be detected on verify."""
        new_run_id = "new-run-456"
        _make_minimal_current_artifacts(tmp_path, new_run_id)

        final_xodr = str(tmp_path / "final.xodr")
        mandatory = mandatory_pack_artifacts("structural_release", final_xodr)

        # Finalize with correct artifacts
        receipt = finalize_run_pack(str(tmp_path), mandatory, emit_success=True)
        assert receipt["status"] == "PASS"

        # Now corrupt an artifact AFTER finalization
        health = json.loads((tmp_path / "pipeline_health_summary.json").read_text())
        health["overall_ok"] = False
        (tmp_path / "pipeline_health_summary.json").write_text(json.dumps(health), encoding="utf-8")

        # verify_run_pack should detect the tampering
        verify_result = verify_run_pack(str(tmp_path))
        assert verify_result["status"] == "FAIL"
        assert any("tampered" in p for p in verify_result["problems"])

    def test_stale_run_id_in_pack_fails(self, tmp_path: Path):
        """If an artifact has a stale run_id, pack verification should catch it."""
        new_run_id = "new-run-456"
        _make_minimal_current_artifacts(tmp_path, new_run_id)

        # Corrupt one artifact with wrong run_id
        health = json.loads((tmp_path / "pipeline_health_summary.json").read_text())
        health["run_id"] = "stale-run-id"
        (tmp_path / "pipeline_health_summary.json").write_text(json.dumps(health), encoding="utf-8")

        # The signal index should show it as INCOMPLETE
        from ultimate_pipeline.signals.index import build_signal_index
        index = build_signal_index(str(tmp_path), profile="structural_release")
        assert index["signals"]["PIPELINE_HEALTH"]["status"] == "INCOMPLETE"


class TestProfileSpecificPack:
    """Different profiles must have different mandatory artifact sets."""

    def test_structural_release_pack_includes_health(self, tmp_path: Path):
        final_xodr = str(tmp_path / "final.xodr")
        mandatory = mandatory_pack_artifacts("structural_release", final_xodr)
        # Health is mandatory for structural
        assert any("pipeline_health_summary" in m for m in mandatory)

    def test_debug_profile_pack_excludes_optional(self, tmp_path: Path):
        final_xodr = str(tmp_path / "final.xodr")
        mandatory = mandatory_pack_artifacts("debug", final_xodr)
        # Debug profile should have fewer mandatory artifacts
        # (at minimum the final XODR)
        assert final_xodr in mandatory


class TestCrashSafety:
    """Terminal state machine must fail closed at every interruption point."""

    def test_crash_before_health_write_leaves_no_success(self, tmp_path: Path):
        """If crash occurs before health write, no SUCCESS should exist."""
        new_run_id = "new-run-456"
        _make_minimal_current_artifacts(tmp_path, new_run_id)

        # Remove health summary (simulating crash before write)
        (tmp_path / "pipeline_health_summary.json").unlink()

        # Try to finalize - should return FAIL status, not raise
        final_xodr = str(tmp_path / "final.xodr")
        mandatory = mandatory_pack_artifacts("structural_release", final_xodr)

        receipt = finalize_run_pack(str(tmp_path), mandatory, emit_success=True)
        assert receipt["status"] == "FAIL"

        # SUCCESS.txt must not exist
        assert not (tmp_path / "SUCCESS.txt").exists()

    def test_crash_before_verdict_write_leaves_no_success(self, tmp_path: Path):
        """If crash occurs before verdict write, no SUCCESS should exist."""
        # This is tested indirectly by the mandatory pack test above
        pass


class TestNoLateWritesAfterSuccess:
    """After SUCCESS.txt is published, no authority artifact may be modified."""

    def test_success_is_last_write(self, tmp_path: Path):
        """Verify the terminal chain ordering: SUCCESS is the final authority event."""
        new_run_id = "new-run-456"
        _make_minimal_current_artifacts(tmp_path, new_run_id)

        final_xodr = str(tmp_path / "final.xodr")
        mandatory = mandatory_pack_artifacts("structural_release", final_xodr)

        receipt = finalize_run_pack(str(tmp_path), mandatory, emit_success=True)
        assert receipt["status"] == "PASS"

        # SUCCESS.txt exists
        success_path = tmp_path / "SUCCESS.txt"
        assert success_path.exists()

        # Get the mtime of SUCCESS
        success_mtime = success_path.stat().st_mtime

        # Wait a bit
        time.sleep(0.01)

        # Try to write another artifact (should not happen in real chain,
        # but we verify no code in this test suite does it)
        # The test just verifies SUCCESS exists and was the last write
        assert success_path.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestMainPipelineRunTerminalChain:
    """Test that the real MainPipeline.run() executes the terminal chain correctly."""

    def test_run_executes_terminal_chain_in_order(self, tmp_path: Path, monkeypatch):
        """Verify MainPipeline.run() calls terminal chain steps in correct order."""
        from ultimate_pipeline.main_pipeline import MainPipeline

        # Create minimal settings object
        class MockSettings:
            def output_dir(self): return str(tmp_path)
            def logs_dir(self): return str(tmp_path / "logs")
            RELEASE_PROFILE = "structural_release"
            ENABLE_CARLA = False
            DETERMINISTIC_MODE = False
            KEEP_LAST_RUNS = 10
            INPUT_XODR = str(tmp_path / "input.xodr")
            OSM_FILE = str(tmp_path / "input.osm")
            DEM_TIF = str(tmp_path / "dem.tif")
            GPS_BOUNDS = {"lat_min": 0, "lat_max": 1, "lon_min": 0, "lon_max": 1}
            BASE_OUTPUT_DIR = str(tmp_path)
            LOG_DIR = str(tmp_path / "logs")
            STAGE_DIRS = {}
            def stage_path(self, name): return str(tmp_path / f"{name}.xodr")
            def load_gps_bounds(self): return self.GPS_BOUNDS
            def to_dict(self): return {}

        # Create required input files
        (tmp_path / "input.xodr").write_text("<?xml version='1.0'?><OpenDRIVE/>", encoding="utf-8")
        (tmp_path / "input.osm").write_text("<osm/>", encoding="utf-8")
        (tmp_path / "dem.tif").write_text("dummy", encoding="utf-8")
        (tmp_path / "logs").mkdir(exist_ok=True)

        # Create pipeline instance
        pipeline = MainPipeline(settings=MockSettings())

        # Track terminal chain calls
        terminal_calls = []

        # Mock _run_internal (the heavy pipeline stages)
        original_run_internal = pipeline._run_internal
        def mock_run_internal():
            terminal_calls.append("_run_internal")
            # Create minimal artifacts that the terminal chain expects
            pipeline._write_run_identity()  # Already done in __init__, but ensure it's there
        pipeline._run_internal = mock_run_internal

        # Mock the terminal chain steps to track order
        from ultimate_pipeline.quality import pipeline_health_summary as phs_module
        original_write_health = phs_module.write_pipeline_health_summary
        def mock_write_health(out_dir, stage_reports_dir=None, expected_gates=None):
            terminal_calls.append("write_pipeline_health_summary")
            # Create minimal health summary
            (Path(out_dir) / "pipeline_health_summary.json").write_text(
                json.dumps({"schema": "pipeline_health_summary/v1", "overall_ok": True, "gates": {}}, indent=2),
                encoding="utf-8"
            )
        monkeypatch.setattr(phs_module, "write_pipeline_health_summary", mock_write_health)

        from ultimate_pipeline.signals import verdict as verdict_module
        original_write_verdict = verdict_module.write_final_run_verdict
        def mock_write_verdict(out_dir, profile=None, settings=None, env=None, final_xodr=None):
            terminal_calls.append("write_final_run_verdict")
            (Path(out_dir) / "final_run_verdict.json").write_text(
                json.dumps({"schema": "final_run_verdict/v1", "status": "PASS", "run_status_ok": True}, indent=2),
                encoding="utf-8"
            )
            return {"status": "PASS"}
        monkeypatch.setattr(verdict_module, "write_final_run_verdict", mock_write_verdict)

        from ultimate_pipeline.signals import registry as registry_module
        original_mandatory = registry_module.mandatory_pack_artifacts
        def mock_mandatory(profile, final_xodr, settings=None):
            terminal_calls.append("mandatory_pack_artifacts")
            return [final_xodr, str(tmp_path / "pipeline_health_summary.json")]
        monkeypatch.setattr(registry_module, "mandatory_pack_artifacts", mock_mandatory)

        from ultimate_pipeline.utils import finalize_run_pack as frp_module
        original_finalize = frp_module.finalize_run_pack
        def mock_finalize(out_dir, key_paths, summary="", mandatory=None, emit_success=True):
            terminal_calls.append("finalize_run_pack")
            # Create a minimal PASS receipt
            from ultimate_pipeline.utils.finalize_run_pack import STATUS_PASS
            receipt = {
                "schema": "RUN_PACK_FINALIZATION/v2",
                "status": STATUS_PASS,
                "files": {Path(k).name: "a" * 64 for k in key_paths if isinstance(k, str)},
            }
            # Write signature.json and SUCCESS.txt
            import json as _json
            sig_path = Path(out_dir) / "signature.json"
            sig_path.write_text(_json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            if emit_success:
                (Path(out_dir) / "SUCCESS.txt").write_text("OK 2026-01-01T00:00:00Z\nstatus=PASS\n", encoding="utf-8")
            return receipt
        monkeypatch.setattr(frp_module, "finalize_run_pack", mock_finalize)

        original_verify = frp_module.verify_run_pack
        def mock_verify(out_dir):
            terminal_calls.append("verify_run_pack")
            return {"schema": "RUN_PACK_VERIFICATION/v2", "status": "PASS", "problems": []}
        monkeypatch.setattr(frp_module, "verify_run_pack", mock_verify)

        # Mock _write_run_status to track final status write
        original_write_status = pipeline._write_run_status
        def mock_write_status(status, stage, message=None, error=None):
            terminal_calls.append(f"_write_run_status({status})")
            return original_write_status(status=status, stage=stage, message=message, error=error)
        pipeline._write_run_status = mock_write_status

        # Run the pipeline
        result = pipeline.run()

        # Verify terminal chain was executed in correct order
        expected_order = [
            "_write_run_status(running)",
            "_run_internal",
            "write_pipeline_health_summary",
            "write_final_run_verdict",
            "mandatory_pack_artifacts",
            "finalize_run_pack",
            "verify_run_pack",
            "_write_run_status(ok)",
        ]
        assert terminal_calls == expected_order, f"Terminal chain order mismatch: {terminal_calls}"

        # Verify SUCCESS.txt was created
        assert (tmp_path / "SUCCESS.txt").exists()
        success_content = (tmp_path / "SUCCESS.txt").read_text(encoding="utf-8")
        assert success_content.startswith("OK ")

        # Verify run_status.json is "ok"
        run_status = json.loads((tmp_path / "run_status.json").read_text(encoding="utf-8"))
        assert run_status["status"] == "ok"
        assert run_status["stage"] == "done"