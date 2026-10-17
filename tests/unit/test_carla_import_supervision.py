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
import signal
import subprocess
import sys
import time
from pathlib import Path

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

    def test_posix_sigint_returncode_is_externally_interrupted(self):
        # The contract gap: -SIGINT used to fall through to UNKNOWN_NTSTATUS
        # and read as a plain nonzero exit, so a signal-killed child was
        # reported as a failure instead of an interruption.
        r = classify_exit_status(-signal.SIGINT)
        assert r["classification"] == EXTERNALLY_INTERRUPTED
        assert r["is_interrupted"] is True
        assert r["is_crash"] is False
        assert r["signal_name"] == "SIGINT"
        assert r["returncode"] == -signal.SIGINT

    def test_posix_sigterm_returncode_is_externally_interrupted(self):
        r = classify_exit_status(-signal.SIGTERM)
        assert r["classification"] == EXTERNALLY_INTERRUPTED
        assert r["is_interrupted"] is True

    def test_posix_fault_signal_is_a_crash_not_an_interrupt(self):
        r = classify_exit_status(-signal.SIGSEGV)
        assert r["classification"] == CRASH
        assert r["is_crash"] is True
        assert r["is_interrupted"] is False
        assert r["signal_name"] == "SIGSEGV"

    def test_unlisted_negative_signal_is_a_plain_nonzero_exit(self):
        # SIGKILL is deliberately not promoted to interrupted without evidence.
        r = classify_exit_status(-9)
        assert r["classification"] == NONZERO_EXIT
        assert r["is_interrupted"] is False
        assert r["is_crash"] is False
        assert "signal 9" in r["detail"]


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
        #
        # The child must reset SIGINT to SIG_DFL before raising it. A process
        # started as a background job of a non-interactive shell inherits
        # SIGINT=SIG_IGN, and children inherit that disposition, so a child that
        # merely calls os.kill(SIGINT) is left untouched, exits 0 and is
        # classified CLEAN_EXIT. That silently turns this into a test of the
        # launcher's signal disposition instead of the exit classifier, and made
        # the test fail or pass purely as a function of how pytest was started.
        st = self._state(tmp_path)
        rec = run_supervised(
            [sys.executable, "-c",
             "import os,signal;"
             "signal.signal(signal.SIGINT,signal.SIG_DFL);"
             "os.kill(os.getpid(),signal.SIGINT)"],
            state=st)
        cls = rec["termination_classification"]
        # Assert the child actually died from the signal, not merely that the
        # outcome was "not a success": on POSIX a signal death reports -SIGINT.
        if os.name == "posix":
            assert cls["returncode"] == -signal.SIGINT
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
# Interrupt contract (T_int latch / T_done first-wins)
# ---------------------------------------------------------------------------
def _pid_alive(pid: int) -> bool:
    """Liveness probe that never signals the pid.

    os.kill(pid, 0) is POSIX-only; on Windows any nonzero sig passed to
    os.kill is a TerminateProcess call, which would kill the very process
    under test. Windows therefore uses OpenProcess/GetExitCodeProcess.
    """
    if os.name == "posix":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    import ctypes
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return code.value == 259      # STILL_ACTIVE
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


class _FakeChild:
    """Popen-compatible stand-in: deterministic, no real process, no timing."""

    def __init__(self):
        self.pid = 424242
        self.returncode = None
        self._rc = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls = 0

    def poll(self):
        return self._rc

    def _die(self, rc):
        self._rc = rc
        self.returncode = rc

    def terminate(self):
        self.terminate_calls += 1

    def kill(self):
        self.kill_calls += 1

    def wait(self, timeout=None):
        self.wait_calls += 1
        return self._rc

    def communicate(self, timeout=None):
        raise NotImplementedError


class _InterruptibleChild(_FakeChild):
    """Spawned, then interrupted while waiting (post-readiness, pre-execution)."""

    def communicate(self, timeout=None):
        raise KeyboardInterrupt

    def terminate(self):
        self.terminate_calls += 1
        self._die(-15)


class _UnkillableChild(_FakeChild):
    """Termination itself fails at every escalation step."""

    def communicate(self, timeout=None):
        raise KeyboardInterrupt

    def terminate(self):
        self.terminate_calls += 1
        raise OSError("terminate refused")

    def kill(self):
        self.kill_calls += 1
        raise OSError("kill refused")

    def wait(self, timeout=None):
        self.wait_calls += 1
        raise subprocess.TimeoutExpired("wait", timeout if timeout is not None else 0)


class TestInterruptContract:
    """The Phase B contract: one latch point, completion-first-wins, receipts."""

    def _state(self, tmp_path, name="s.json"):
        st = ImportState(state_path=str(tmp_path / name), run_id="t",
                         parent_pid=os.getpid())
        st.transition("STARTING")
        return st

    @staticmethod
    def _receipt(tmp_path):
        return json.loads(
            (tmp_path / "COMMANDLET_EXECUTION_RECEIPT.json").read_text(
                encoding="utf-8"))

    @staticmethod
    def _events(rec):
        return [e["event"] for e in rec["event_order"]]

    @staticmethod
    def _install_interrupting_communicate(monkeypatch, interrupts=1):
        real = subprocess.Popen.communicate

        def communicate_interrupting(self, timeout=None):
            handler = signal.getsignal(signal.SIGINT)
            for _ in range(interrupts):
                handler(signal.SIGINT, None)
            return real(self, timeout=timeout)

        monkeypatch.setattr(subprocess.Popen, "communicate",
                            communicate_interrupting)

    def test_interrupt_during_initialization_never_spawns_a_child(
            self, tmp_path, monkeypatch):
        st = self._state(tmp_path)

        def interrupt_at_spawn(*args, **kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr(subprocess, "Popen", interrupt_at_spawn)
        rec = run_supervised([sys.executable, "-c", "pass"], state=st)
        assert rec["interrupted"] is True
        assert rec["child_pid"] is None
        assert rec["child_alive_at_interrupt"] is None
        assert rec["completion_observed"] is False
        assert st.state == "INTERRUPTED"
        events = self._events(rec)
        assert "interrupt_latched" in events
        assert "spawned" not in events
        assert self._receipt(tmp_path)["interrupted"] is True

    def test_interrupt_after_readiness_terminates_and_reaps_child(
            self, tmp_path, monkeypatch):
        st = self._state(tmp_path)
        fake = _InterruptibleChild()
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: fake)
        rec = run_supervised([sys.executable, "-c", "pass"], state=st)
        assert rec["interrupted"] is True
        assert rec["child_alive_at_interrupt"] is True
        assert rec["termination_classification"]["ntstatus_name"] == \
            "PYTHON_KEYBOARDINTERRUPT"
        assert fake.terminate_calls == 1
        assert rec["cleanup"]["outcome"] == "already_exited"
        assert rec["child_return_code"] is not None
        assert st.state == "INTERRUPTED"
        events = self._events(rec)
        assert "spawned" in events
        assert "completion_observed" not in events

    def test_interrupt_during_execution_kills_child_and_latches_first(
            self, tmp_path, monkeypatch):
        st = self._state(tmp_path)
        self._install_interrupting_communicate(monkeypatch)
        rec = run_supervised(
            [sys.executable, "-c", "import time; time.sleep(30)"], state=st)
        assert rec["interrupted"] is True
        assert rec["child_alive_at_interrupt"] is True
        assert rec["termination_classification"]["classification"] == \
            EXTERNALLY_INTERRUPTED
        assert rec["cleanup"]["outcome"] in ("already_exited",
                                             "reaped_after_terminate")
        assert st.state == "INTERRUPTED"
        events = self._events(rec)
        # T_int precedes T_done in the recorded ordering.
        assert events.index("interrupt_latched") < \
            events.index("completion_observed")
        assert not _pid_alive(rec["child_pid"]), "interrupted child left running"

    def test_interrupt_after_completion_keeps_the_success_outcome(
            self, tmp_path, monkeypatch):
        st = self._state(tmp_path)
        real_classify = classify_exit_status
        calls = {"n": 0}

        def classify_raised_once(rc):
            if calls["n"] == 0:
                calls["n"] += 1
                raise KeyboardInterrupt
            return real_classify(rc)

        monkeypatch.setattr("tools.carla_import_supervision.classify_exit_status",
                            classify_raised_once)
        rec = run_supervised([sys.executable, "-c", "pass"], state=st)
        assert rec["interrupted"] is False
        assert rec["interrupt_after_completion"] is True
        assert rec["late_keyboard_interrupt"] is True
        assert rec["termination_classification"]["classification"] == CLEAN_EXIT
        assert rec["termination_classification"]["is_success"] is True
        assert st.state == "VALIDATING_OUTPUT"

    @pytest.mark.parametrize("ordering", ["interrupt_first", "completion_first"])
    def test_simultaneous_interrupt_and_completion_linearise_deterministically(
            self, tmp_path, monkeypatch, ordering):
        st = self._state(tmp_path)
        if ordering == "interrupt_first":
            # T_int before T_done: the latch fires while the child is alive.
            self._install_interrupting_communicate(monkeypatch)
            rec = run_supervised(
                [sys.executable, "-c", "import time; time.sleep(30)"], state=st)
            assert rec["interrupted"] is True
            assert rec["interrupt_after_completion"] is False
            assert rec["child_alive_at_interrupt"] is True
            assert st.state == "INTERRUPTED"
        else:
            # T_done before T_int: the child is reaped before the latch runs.
            real_classify = classify_exit_status

            def classify_after_child_exit(rc):
                signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
                return real_classify(rc)

            monkeypatch.setattr(
                "tools.carla_import_supervision.classify_exit_status",
                classify_after_child_exit)
            rec = run_supervised([sys.executable, "-c", "pass"], state=st)
            assert rec["interrupted"] is False
            assert rec["interrupt_after_completion"] is True
            assert rec["child_alive_at_interrupt"] is False
            assert rec["termination_classification"]["classification"] == \
                CLEAN_EXIT
            assert st.state == "VALIDATING_OUTPUT"

    def test_repeated_interrupts_produce_exactly_one_latched_outcome(
            self, tmp_path, monkeypatch):
        st = self._state(tmp_path)
        self._install_interrupting_communicate(monkeypatch, interrupts=3)
        rec = run_supervised(
            [sys.executable, "-c", "import time; time.sleep(30)"], state=st)
        assert rec["interrupted"] is True
        assert rec["interrupt_repeats"] == 2
        events = self._events(rec)
        assert events.count("interrupt_latched") == 1
        assert events.count("interrupt_repeated") == 2
        assert st.state == "INTERRUPTED"

    def test_startup_failure_writes_receipt_and_never_dangles_running(
            self, tmp_path, monkeypatch):
        st = self._state(tmp_path)

        def spawn_fails(*args, **kwargs):
            raise FileNotFoundError("UE4Editor-Cmd.exe not found")

        monkeypatch.setattr(subprocess, "Popen", spawn_fails)
        rec = run_supervised(["UE4Editor-Cmd.exe", "proj.uproject"], state=st)
        assert rec["interrupted"] is False
        assert rec["child_pid"] is None
        assert rec["termination_classification"]["classification"] == \
            "SPAWN_FAILURE"
        assert rec["terminal_reason"] == "SPAWN_FAILURE"
        assert st.state == CHILD_FAILED
        on_disk = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
        assert on_disk["state"] == CHILD_FAILED
        assert "spawn_failed" in self._events(rec)
        assert self._receipt(tmp_path)["terminal_reason"] == "SPAWN_FAILURE"

    def test_termination_failure_is_recorded_honestly(self, tmp_path,
                                                      monkeypatch):
        st = self._state(tmp_path)
        fake = _UnkillableChild()
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: fake)
        rec = run_supervised([sys.executable, "-c", "pass"], state=st)
        assert rec["interrupted"] is True
        assert rec["cleanup"]["outcome"] == "survived_escalation"
        events = self._events(rec)
        assert "terminate_failed" in events
        assert "kill_failed" in events
        assert "child_survived_escalation" in events
        assert st.state == "INTERRUPTED"
        assert self._receipt(tmp_path)["cleanup"]["outcome"] == \
            "survived_escalation"

    def test_interrupted_child_is_never_left_running(self, tmp_path,
                                                     monkeypatch):
        st = self._state(tmp_path)
        self._install_interrupting_communicate(monkeypatch)
        rec = run_supervised(
            [sys.executable, "-c", "import time; time.sleep(30)"], state=st)
        assert rec["child_pid"] is not None
        assert rec["cleanup"] is not None
        assert rec["cleanup"]["outcome"] != "survived_escalation"
        assert not _pid_alive(rec["child_pid"])
        assert st.state == "INTERRUPTED"

    @pytest.mark.parametrize(
        "child_code,return_code,expect_state,expect_class",
        [("pass", 0, "VALIDATING_OUTPUT", CLEAN_EXIT),
         ("raise SystemExit(4)", 4, CHILD_FAILED, NONZERO_EXIT)])
    def test_receipt_state_and_classification_agree(
            self, tmp_path, child_code, return_code, expect_state,
            expect_class):
        st = self._state(tmp_path)
        rec = run_supervised([sys.executable, "-c", child_code], state=st)
        cls = rec["termination_classification"]
        assert cls["classification"] == expect_class
        assert rec["terminal_reason"] == cls["classification"]
        assert rec["child_return_code"] == return_code
        assert st.state == expect_state
        assert cls["is_success"] is (expect_state == "VALIDATING_OUTPUT")
        assert cls["is_interrupted"] is (expect_state == "INTERRUPTED")
        assert rec["interrupted"] is (expect_state == "INTERRUPTED")

    @pytest.mark.skipif(os.name != "posix",
                        reason="POSIX reports signal deaths as -SIGINT")
    def test_posix_signal_death_is_interrupted_end_to_end(self, tmp_path):
        st = self._state(tmp_path)
        rec = run_supervised(
            [sys.executable, "-c",
             "import os, signal;"
             "signal.signal(signal.SIGINT, signal.SIG_DFL);"
             "os.kill(os.getpid(), signal.SIGINT)"],
            state=st)
        cls = rec["termination_classification"]
        assert cls["returncode"] == -signal.SIGINT
        assert cls["classification"] == EXTERNALLY_INTERRUPTED
        assert cls["is_interrupted"] is True
        assert rec["interrupted"] is True
        assert rec["terminal_reason"] == EXTERNALLY_INTERRUPTED
        assert st.state == "INTERRUPTED"

    @pytest.mark.skipif(os.name != "posix",
                        reason="POSIX signal delivery to a blocked supervisor")
    def test_real_sigint_latched_end_to_end(self, tmp_path):
        """One real-signal test: SIGINT to a blocked supervisor mid-child."""
        root = str(Path(__file__).resolve().parents[2])
        marker = tmp_path / "child_started.txt"
        state_path = tmp_path / "active_import_state.json"
        helper = tmp_path / "sigint_helper.py"
        helper.write_text(
            "import os, sys\n"
            f"sys.path.insert(0, {root!r})\n"
            "from tools.carla_import_supervision import ImportState, run_supervised\n"
            "state_path, marker = sys.argv[1], sys.argv[2]\n"
            "st = ImportState(state_path=state_path, run_id='sigint-e2e',\n"
            "                 parent_pid=os.getpid())\n"
            "st.transition('STARTING')\n"
            "child = [sys.executable, '-c',\n"
            "         'import os, pathlib, sys, time; '\n"
            "         'pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); '\n"
            "         'time.sleep(30)', marker]\n"
            "run_supervised(child, state=st)\n"
            "print('SUPERVISOR_DONE')\n",
            encoding="utf-8")
        helper_proc = subprocess.Popen(
            [sys.executable, str(helper), str(state_path), str(marker)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            cwd=root)
        # Rendezvous on the child-started event (bounded), not an outcome race:
        # the marker exists only after the child spawned, and the SIGINT handler
        # is installed before the spawn, so a live marker proves the handler.
        deadline = time.monotonic() + 20.0
        while not marker.exists() and time.monotonic() < deadline:
            if helper_proc.poll() is not None:
                break
            time.sleep(0.05)
        if not marker.exists():
            _out, err = helper_proc.communicate(timeout=30)
            pytest.fail("supervisor helper never started its child: %s" % err)
        os.kill(helper_proc.pid, signal.SIGINT)
        out, err = helper_proc.communicate(timeout=30)
        assert helper_proc.returncode == 0, (out, err)
        receipt = self._receipt(tmp_path)
        assert receipt["interrupted"] is True
        assert receipt["termination_classification"]["classification"] == \
            EXTERNALLY_INTERRUPTED
        assert receipt["termination_classification"]["is_success"] is False
        assert receipt["cleanup"]["outcome"] in ("already_exited",
                                                 "reaped_after_terminate",
                                                 "reaped_after_kill")
        on_disk = json.loads(state_path.read_text(encoding="utf-8"))
        assert on_disk["state"] == "INTERRUPTED"
        child_pid = int(marker.read_text())
        assert not _pid_alive(child_pid), "interrupted child was left running"


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

    def test_real_volume_measures_free_space(self, tmp_path):
        # The property under test is platform-neutral: a real, present volume
        # with enough free space must be measured and reported as satisfied.
        # A hard-coded "C" only names a drive on Windows, so the anchor of a
        # real temporary path is used instead -- "C:\" on Windows, "/" on POSIX.
        root = Path(tmp_path).anchor or os.path.abspath(os.sep)
        g = StorageGate(minimum_free_gb={root: 0.001})
        res = g.evaluate()
        assert root in res["satisfied"]
        assert res["satisfied"][root]["actual_free_gb"] >= 0.001
        assert res["pass"] is True