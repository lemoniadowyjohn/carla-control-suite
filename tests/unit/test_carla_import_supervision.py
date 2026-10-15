"""Tests for tools/carla_import_supervision.py.

These assert executable behaviour, not source text. The three defects this module
exists to prevent are pinned by direct tests:

  * the prior run exited 0xC000013A and was unclassifiable;
  * the wrapper stayed resident at ~0 CPU with no terminal record, so a dead run
    looked alive;
  * the absence of UE4Editor-Cmd.exe was wrongly read as evidence, when the
    wrapper actually invokes UE4Editor.exe.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

from tools.carla_import_supervision import (
    CHILD_FAILED,
    CRASH,
    CLEAN_EXIT,
    EXTERNALLY_INTERRUPTED,
    NONZERO_EXIT,
    IllegalTransition,
    ImportState,
    StorageGate,
    classify_exit_status,
    detect_process_role,
    run_supervised,
    validate_transition,
)


# ---------------------------------------------------------------------------
# Exit status classification
# ---------------------------------------------------------------------------
class TestExitStatus:
    def test_prior_run_status_is_externally_interrupted(self):
        # 3221225786 from ingolstadt_import_20261004T001601Z.log.err
        r = classify_exit_status(3221225786)
        assert r["returncode_hex"] == "0xC000013A"
        assert r["ntstatus_name"] == "STATUS_CONTROL_C_EXIT"
        assert r["classification"] == EXTERNALLY_INTERRUPTED
        assert r["is_interrupted"] is True
        assert r["is_crash"] is False
        assert r["is_success"] is False

    def test_ctrl_break_also_interrupted(self):
        r = classify_exit_status(0xC000003A)
        assert r["classification"] == EXTERNALLY_INTERRUPTED
        assert r["is_crash"] is False

    def test_access_violation_is_a_crash_not_an_interrupt(self):
        r = classify_exit_status(0xC0000005)
        assert r["classification"] == CRASH
        assert r["is_crash"] is True
        assert r["is_interrupted"] is False

    @pytest.mark.parametrize("code", [0xC0000135, 0xC0000139, 0xC0000142,
                                      0xC0000006, 0xC0000374, 0xC0000409])
    def test_known_fault_statuses_are_crashes(self, code):
        r = classify_exit_status(code)
        assert r["is_crash"] is True, code

    def test_zero_is_clean_exit(self):
        r = classify_exit_status(0)
        assert r["classification"] == CLEAN_EXIT
        assert r["is_success"] is True

    def test_small_nonzero_is_nonzero_exit(self):
        r = classify_exit_status(3)
        assert r["classification"] == NONZERO_EXIT
        assert r["is_success"] is False
        assert r["is_interrupted"] is False

    def test_none_return_code_is_not_success(self):
        r = classify_exit_status(None)
        assert r["is_success"] is False
        assert r["classification"] == "UNKNOWN_NO_RETURN_CODE"

    def test_unknown_ntstatus_is_not_called_a_crash(self):
        r = classify_exit_status(0xDEADBEEF)
        assert r["ntstatus_name"] == "UNKNOWN_NTSTATUS"
        assert r["is_crash"] is False
        assert r["classification"] == NONZERO_EXIT


# ---------------------------------------------------------------------------
# Process role
# ---------------------------------------------------------------------------
class TestProcessRole:
    def test_ue4editor_with_run_switch_is_commandlet(self):
        # This is exactly how the prior wrapper invoked the engine.
        r = detect_process_role(
            r"G:\UnrealEngine_4.26_CARLA\Engine\Binaries\Win64\UE4Editor.exe",
            ["CarlaUE4.uproject", "-run=ImportAssets", "-nosourcecontrol"])
        assert r["role"] == "COMMANDLET"
        assert r["is_commandlet"] is True
        assert r["never_use_interactive_as_import_evidence"] is False

    def test_ue4editor_cmd_exe_is_commandlet(self):
        r = detect_process_role("UE4Editor-Cmd.exe", ["proj.uproject"])
        assert r["role"] == "COMMANDLET"

    def test_plain_ue4editor_is_interactive(self):
        r = detect_process_role("UE4Editor.exe", [])
        assert r["role"] == "INTERACTIVE_EDITOR"
        assert r["never_use_interactive_as_import_evidence"] is True

    def test_unknown_executable_is_unknown(self):
        assert detect_process_role("python.exe", ["x.py"])["role"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------
class TestStateMachine:
    def test_happy_path(self, tmp_path):
        st = ImportState(state_path=str(tmp_path / "active_import_state.json"),
                         run_id="r1", parent_pid=1)
        st.transition("STARTING")
        st.transition("RUNNING", executable="UE4Editor-Cmd.exe")
        st.transition("VALIDATING_OUTPUT")
        st.transition("PASS")
        assert st.state == "PASS"
        assert st.is_terminal()

    def test_running_to_interrupted(self, tmp_path):
        st = ImportState(state_path=str(tmp_path / "s.json"))
        st.transition("STARTING")
        st.transition("RUNNING")
        st.transition("INTERRUPTED", terminal_reason="EXTERNALLY_INTERRUPTED")
        assert st.state == "INTERRUPTED"
        assert st.terminal_reason == "EXTERNALLY_INTERRUPTED"

    def test_no_transition_out_of_interrupted(self, tmp_path):
        st = ImportState(state_path=str(tmp_path / "s.json"))
        st.transition("STARTING")
        st.transition("RUNNING")
        st.transition("INTERRUPTED")
        with pytest.raises(IllegalTransition):
            st.transition("RUNNING")

    def test_illegal_transition_rejected(self, tmp_path):
        st = ImportState(state_path=str(tmp_path / "s.json"))
        with pytest.raises(IllegalTransition):
            st.transition("PASS")

    def test_unknown_state_rejected(self, tmp_path):
        st = ImportState(state_path=str(tmp_path / "s.json"))
        with pytest.raises(IllegalTransition):
            st.transition("NOT_A_STATE")

    def test_state_file_is_atomic_and_complete(self, tmp_path):
        p = tmp_path / "active_import_state.json"
        st = ImportState(state_path=str(p))
        st.transition("STARTING")
        st.transition("RUNNING")
        # no .tmp residue
        assert not (tmp_path / "active_import_state.json.tmp").exists()
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["state"] == "RUNNING"
        assert data["history"][-1]["to"] == "RUNNING"

    def test_history_records_every_transition(self, tmp_path):
        st = ImportState(state_path=str(tmp_path / "s.json"))
        st.transition("STARTING")
        st.transition("RUNNING")
        st.transition("CHILD_FAILED", terminal_reason="x")
        assert [h["to"] for h in st.history] == \
            ["STARTING", "RUNNING", "CHILD_FAILED"]


# ---------------------------------------------------------------------------
# Supervised invocation
# ---------------------------------------------------------------------------
class TestRunSupervised:
    def _state(self, tmp_path, name="s.json"):
        st = ImportState(state_path=str(tmp_path / name), run_id="t",
                         parent_pid=os.getpid())
        st.transition("STARTING")
        return st

    def test_clean_child_moves_to_validating_output(self, tmp_path):
        st = self._state(tmp_path)
        rec = run_supervised([sys.executable, "-c", "print('ok')"], state=st)
        assert rec["child_return_code"] == 0
        assert rec["termination_classification"]["classification"] == CLEAN_EXIT
        assert st.state == "VALIDATING_OUTPUT"
        assert rec["process_role"]["role"] == "UNKNOWN"

    def test_nonzero_child_moves_to_child_failed_and_writes_receipt(self, tmp_path):
        st = self._state(tmp_path)
        rec = run_supervised([sys.executable, "-c", "raise SystemExit(4)"], state=st)
        assert rec["child_return_code"] == 4
        assert rec["termination_classification"]["classification"] == NONZERO_EXIT
        assert st.state == CHILD_FAILED
        receipt = tmp_path / "COMMANDLET_EXECUTION_RECEIPT.json"
        assert receipt.exists()
        payload = json.loads(receipt.read_text(encoding="utf-8"))
        assert payload["termination_classification"]["is_success"] is False

    def test_interrupt_child_moves_to_interrupted(self, tmp_path):
        # A child that dies on SIGINT-like abort yields a control-event status
        # on Windows; simulate by having the child abort itself.
        st = self._state(tmp_path)
        rec = run_supervised(
            [sys.executable, "-c", "import os,signal;os.kill(os.getpid(),signal.SIGINT)"],
            state=st)
        cls = rec["termination_classification"]
        assert cls["is_success"] is False
        assert st.state in ("INTERRUPTED", CHILD_FAILED)
        # on non-Windows SIGINT gives -2; either way it is never PASS
        assert st.state != "PASS"

    def test_receipt_written_on_every_path(self, tmp_path):
        st = self._state(tmp_path)
        run_supervised([sys.executable, "-c", "pass"], state=st)
        assert (tmp_path / "COMMANDLET_EXECUTION_RECEIPT.json").exists()

    def test_command_and_role_recorded(self, tmp_path):
        st = self._state(tmp_path)
        rec = run_supervised([sys.executable, "-c", "pass"], state=st)
        assert rec["command"][0] == sys.executable
        assert rec["parent_pid"] == os.getpid()
        assert rec["child_pid"] is not None
        assert rec["start_utc"] and rec["end_utc"]


# ---------------------------------------------------------------------------
# Storage gate
# ---------------------------------------------------------------------------
class TestStorageGate:
    def test_no_invented_thresholds(self, tmp_path):
        g = StorageGate()
        res = g.evaluate()
        assert res["thresholds_supplied_by_caller"] is True
        assert res["pass"] is True          # nothing required -> nothing to fail
        assert res["failures"] == []

    def test_impossible_requirement_fails_closed(self):
        g = StorageGate(minimum_free_gb={"Z": 99999})
        res = g.evaluate()
        assert res["pass"] is False
        assert any(f["volume"] == "Z" for f in res["failures"])

    def test_unmeasurable_volume_fails_closed(self):
        g = StorageGate(minimum_free_gb={"Q": 1})
        res = g.evaluate()
        assert res["pass"] is False
        assert any(f.get("reason") == "unmeasurable" for f in res["failures"])

    def test_real_volume_measures_free_space(self):
        g = StorageGate(minimum_free_gb={"C": 0.001})
        res = g.evaluate()
        assert "C" in res["satisfied"]
        assert res["pass"] is True