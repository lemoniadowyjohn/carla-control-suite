# -*- coding: utf-8 -*-
"""Wiring tests for run_perception_safe.py: the new perception modules must be
imported and invoked by the capture runner, not just importable.

The runner is mostly CARLA-dependent, so this file pins the *structural*
wiring (imports + call sites) and the pure side-effects of the helpers.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ultimate_pipeline.tools import run_perception_safe as rps
from ultimate_pipeline.perception.dataset_acceptance import (
    ACCEPTANCE_FILENAME,
    GATE_ORDER,
    Gate,
    evaluate_acceptance,
    software_provenance,
    write_acceptance,
)

SOURCE = (
    Path(__file__).resolve().parents[2]
    / "ultimate_pipeline"
    / "tools"
    / "run_perception_safe.py"
)


def test_journal_record_helpers_are_exposed():
    assert callable(rps._journal_record)


def test_journal_record_is_a_noop_without_a_journal():
    rps._journal_record(None, "MAP_LOAD_BEGIN", town="Grid0828")
    rps._journal_record("not-a-journal", "MAP_LOAD_RETURN")


def test_journal_record_swallows_a_broken_journal():
    class _Broken:
        def record(self, phase, **fields):
            raise OSError("disk full")

    rps._journal_record(_Broken(), "RUN_BEGIN")


def test_journal_record_writes_when_the_journal_is_healthy(tmp_path):
    from ultimate_pipeline.perception.phase_journal import PhaseJournal

    journal = PhaseJournal(tmp_path / "phase_journal.jsonl")
    rps._journal_record(journal, "MAP_LOAD_BEGIN", requested_town="Grid0828")
    rps._journal_record(journal, "MAP_LOAD_RETURN", map_name="Grid0828")
    journal.close()
    lines = (tmp_path / "phase_journal.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert "MAP_LOAD_BEGIN" in lines[0]
    assert "Grid0828" in lines[1]


def test_runner_source_journals_the_run_boundary_phases():
    source = SOURCE.read_text(encoding="utf-8")
    for phase in (
        "RUN_BEGIN",
        "MAP_LOAD_BEGIN",
        "MAP_LOAD_RETURN",
        "CAPTURE_BEGIN",
        "CAPTURE_END",
        "FLUSH_BEGIN",
        "FLUSH_END",
        "TEARDOWN_BEGIN",
        "COMPLETE",
    ):
        assert f'"{phase}"' in source, f"missing phase journal entry: {phase}"
    assert "PhaseJournal(" in source
    assert source.index("PhaseJournal(") < source.index('"RUN_BEGIN"')
    assert "_journal_record(phase_journal" in source


def test_runner_source_writes_a_crash_bundle_on_unexpected_exception():
    source = SOURCE.read_text(encoding="utf-8")
    assert "write_crash_bundle(" in source
    handler = source.index("except Exception as exc:")
    bundle = source.index("write_crash_bundle(")
    assert bundle > handler, "crash bundle must be written from the exception handler"
    assert "phase_journal_path=phase_journal_path" in source
    assert 'client_stderr_path=out_dir / "stderr.log"' in source


def test_runner_source_wires_runtime_map_identity():
    source = SOURCE.read_text(encoding="utf-8")
    assert "capture_runtime_map_identity" in source
    assert "expected_xodr_text" in source
    assert "registry_key" in source


def test_runner_source_wires_postload_stability():
    source = SOURCE.read_text(encoding="utf-8")
    assert "run_postload_soak" in source
    assert "min_ticks" in source
    assert "tick_timeout_s" in source


def test_runner_source_wires_frame_sync():
    source = SOURCE.read_text(encoding="utf-8")
    assert "scan_recording_directory" in source
    assert "evaluate_capture_completeness" in source
    assert "write_frame_correspondence" in source
    assert "assert_capture_complete" in source


def test_runner_source_wires_dataset_acceptance():
    source = SOURCE.read_text(encoding="utf-8")
    assert "evaluate_acceptance" in source
    assert "write_acceptance" in source


def _runner_gates(perception_status):
    """Mirror the gate construction that run_perception_safe performs."""
    ri = perception_status.get("runtime_map_identity", {})
    ri_pass = bool(ri.get("runtime_identity_pass", False))
    ps = perception_status.get("postload_stability", {})
    ps_gate = str(ps.get("gate", ""))
    cc = perception_status.get("capture_completeness_report", {})
    fc = perception_status.get("frame_correspondence", {})
    return {
        "map_identity": Gate(
            "map_identity",
            "PASS" if ri_pass else "FAIL",
            {
                "layer1": ri.get("layer1_name_identity", {}),
                "layer2": ri.get("layer2_structural_identity", {}),
            },
        ),
        "runtime_stability": Gate(
            "runtime_stability",
            "PASS" if ps_gate == "MAP_STABLE" else "FAIL",
            {"gate": ps_gate},
        ),
        "frame_synchronization": Gate(
            "frame_synchronization",
            fc.get("verdict", "FAIL"),
            {"verdict": fc.get("verdict")},
        ),
        "requested_frame_completeness": Gate(
            "requested_frame_completeness",
            cc.get("verdict", "FAIL"),
            {
                "complete_frames": cc.get("complete_frames"),
                "requested_frames": cc.get("requested_frames"),
            },
        ),
        "software_provenance": Gate("software_provenance", "PASS"),
    }


def test_acceptance_payload_from_a_simulated_perception_status(tmp_path):
    perception_status = {
        "runtime_map_identity": {
            "runtime_identity_pass": True,
            "layer1_name_identity": {"passed": True},
            "layer2_structural_identity": {"passed": True},
        },
        "postload_stability": {"gate": "MAP_STABLE"},
        "capture_completeness_report": {
            "verdict": "PASS",
            "complete_frames": 4,
            "requested_frames": 4,
        },
        "frame_correspondence": {"verdict": "PASS"},
    }

    gates = _runner_gates(perception_status)
    acceptance = evaluate_acceptance(
        gates,
        dataset_root=str(tmp_path),
        software_provenance=software_provenance(git_sha="abc123"),
    )
    path = write_acceptance(acceptance, tmp_path)
    assert path.exists()
    assert path.name == ACCEPTANCE_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    # The runner supplies only 5 of the 14 gates, so the others must stay
    # NOT_RUN and the dataset must not be promoted by a single boolean.
    assert payload["status"] != "TRAINING_DATASET_READY"
    assert payload["training_dataset_ready"] is False
    assert payload["failed_gates"] == []
    supplied = {
        "map_identity",
        "runtime_stability",
        "frame_synchronization",
        "requested_frame_completeness",
        "software_provenance",
    }
    expected_not_run = [g for g in GATE_ORDER if g not in supplied]
    assert payload["not_run_gates"] == expected_not_run
    assert payload["single_boolean_promotion_forbidden"] is True
    # The gates the runner DID supply all read PASS.
    supplied_statuses = {
        g["gate"]: g["status"] for g in payload["gates"] if g["gate"] in supplied
    }
    assert all(status == "PASS" for status in supplied_statuses.values())


def test_acceptance_fails_when_a_gate_fails():
    perception_status = {
        "runtime_map_identity": {"runtime_identity_pass": False},
        "postload_stability": {"gate": "MAP_STABLE"},
        "capture_completeness_report": {"verdict": "PASS"},
        "frame_correspondence": {"verdict": "PASS"},
    }
    gates = _runner_gates(perception_status)
    payload = evaluate_acceptance(gates)
    assert payload["status"] != "TRAINING_DATASET_READY"
    assert payload["failed_gates"] == ["map_identity"]
    assert payload["training_dataset_ready"] is False