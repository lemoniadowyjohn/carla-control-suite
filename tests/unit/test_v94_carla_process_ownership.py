"""V94 offline process ownership and safety regressions; no CARLA runtime required."""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import psutil as _real_psutil
import pytest

from ultimate_pipeline.core import carla_utils as cu
from ultimate_pipeline.carla_tools import carla_server as cs


@pytest.fixture(autouse=True)
def _safety_trap_real_process_control(monkeypatch):
    """SAFETY FIRST (V94 round 3): no test in this file may ever reach the
    REAL psutil.process_iter or subprocess.run (e.g. taskkill), whether the
    code under test is HEAD or an overlay of an older, vulnerable commit.
    A round-2 test called real psutil kill-by-name when run against base
    because its trap only patched a local reference; patching the real,
    shared module objects here closes that hole regardless of which SUT
    module did `import psutil`/`import subprocess`. Tests that need to
    exercise a (fake) kill-by-name code path must supply their own
    psutil/subprocess fakes at the call site -- never rely on the real
    modules for anything in this file.
    """
    def _trap_process_iter(*a, **k):
        raise AssertionError("REAL psutil.process_iter must never be called by a test in this file")

    def _trap_run(*a, **k):
        raise AssertionError(f"REAL subprocess.run must never be called by a test in this file (args={a!r})")

    monkeypatch.setattr(_real_psutil, "process_iter", _trap_process_iter)
    monkeypatch.setattr(subprocess, "run", _trap_run)


class FakeProcess:
    def __init__(self, *, dead=False, stuck=False):
        self.exit_code = 0 if dead else None
        self.stuck = stuck
        self.terminated = 0
        self.killed = 0
        self.waited = 0

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.terminated += 1
        if not self.stuck:
            self.exit_code = 0

    def kill(self):
        self.killed += 1
        self.exit_code = -9

    def wait(self, timeout=None):
        self.waited += 1
        if self.stuck and self.exit_code is None:
            raise subprocess.TimeoutExpired("CARLA", timeout)
        return self.exit_code


def test_kill_without_owned_handle_refuses_and_never_enumerates(monkeypatch):
    class TrapPS:
        @staticmethod
        def process_iter(*args, **kwargs):
            raise AssertionError("must not enumerate other CARLA instances")
    monkeypatch.setattr(cu, "psutil", TrapPS)
    monkeypatch.setattr(
        subprocess, "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("taskkill/pkill prohibited")),
    )
    assert cu._kill_stuck_carla() is False


def test_kill_exact_handle_does_not_touch_unrelated_process():
    owned = FakeProcess()
    unrelated = FakeProcess()
    assert cu._kill_stuck_carla(owned) is True
    assert owned.terminated == 1 and owned.killed == 0
    assert unrelated.terminated == 0 and unrelated.killed == 0


def test_exited_handle_pid_reuse_cannot_kill_another_process():
    original = FakeProcess(dead=True)
    later_pid_reuse = FakeProcess()
    assert cu._kill_stuck_carla(original) is True
    assert original.terminated == original.killed == 0
    assert later_pid_reuse.terminated == later_pid_reuse.killed == 0


def test_unresponsive_owned_child_escalates_only_same_handle():
    owned = FakeProcess(stuck=True)
    foreign = FakeProcess()
    assert cu._kill_stuck_carla(owned) is True
    assert owned.terminated == 1 and owned.killed == 1
    assert owned.waited == 2
    assert foreign.terminated == foreign.killed == 0


# ---------------------------------------------------------------------------
# V94 round 2/3, item 3: reap the owned descendant tree (CarlaUE4.exe spawns
# a Shipping child after launch -- a one-time children() snapshot at Popen
# time can never see it). Preferred path is a Windows Job Object; ALSO
# always kill the psutil-children snapshot (P2-2: psutil 7.2.1 guards
# against PID reuse, and a child could join between the job snapshot and
# its termination); neither path may ever enumerate or match by name.
# ---------------------------------------------------------------------------

class FakeTreeMember:
    """A fake process-tree node (owned child or an unrelated same-name proc)."""

    def __init__(self, pid: int, name: str):
        self.pid = pid
        self.name = name
        self.killed = 0

    def kill(self):
        self.killed += 1


class FakeOwnedJob:
    def __init__(self):
        self.terminated = 0

    def terminate_owned(self):
        self.terminated += 1


def test_psutil_fallback_reaps_owned_child_but_spares_unrelated_same_name_process(monkeypatch):
    """No job object given -- the psutil-children fallback must kill only
    the owned PID's own children, never a same-named process that merely
    happens to exist elsewhere (that would be name-matching in disguise)."""
    owned = FakeProcess()
    owned.pid = 4242
    shipping_child = FakeTreeMember(4243, "CarlaUE4-Win64-Shipping.exe")
    unrelated_same_name = FakeTreeMember(9999, "CarlaUE4-Win64-Shipping.exe")

    class FakePsutilProcess:
        def __init__(self, pid):
            assert pid == owned.pid, "must query the owned PID only, never enumerate"

        def children(self, recursive=False):
            assert recursive is True
            return [shipping_child]

    class FakePsutil:
        Process = FakePsutilProcess

        @staticmethod
        def process_iter(*_a, **_k):
            raise AssertionError("must not enumerate all processes")

    monkeypatch.setattr(cu, "psutil", FakePsutil)

    assert cu._kill_stuck_carla(owned) is True
    assert owned.terminated == 1
    assert shipping_child.killed == 1
    assert unrelated_same_name.killed == 0


def test_job_termination_still_also_kills_snapshot_children(monkeypatch):
    """P2-2: even when the job terminates successfully, the psutil-captured
    children must ALSO be killed -- round 2 skipped this fallback whenever
    the job path succeeded, which this test used to lock in as correct; it
    was wrong (psutil 7.2.1 guards PID reuse, so this is cheap and safe, and
    a child could join between the job snapshot and its termination)."""
    owned = FakeProcess()
    owned.pid = 5000
    captured_child = FakeTreeMember(5001, "CarlaUE4-Win64-Shipping.exe")

    class FakePsutilProcess:
        def __init__(self, pid):
            self._pid = pid

        def children(self, recursive=False):
            return [captured_child]

    monkeypatch.setattr(cu, "psutil", SimpleNamespace(Process=FakePsutilProcess))
    job = FakeOwnedJob()

    assert cu._kill_stuck_carla(owned, job=job) is True
    assert job.terminated == 1
    assert captured_child.killed == 1, "snapshot children must be killed even when the job succeeded"


def test_create_job_for_launch_assigns_via_proc_handle_no_kill_on_close(monkeypatch):
    """_create_job_for_launch must create a plain job (reusing
    job_supervision.create_job) and assign the launch-owned process via its
    own handle (proc._handle -- P2-3: no OpenProcess call, no extra rights
    requested). P1-1: no JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE -- CARLA must
    outlive its launcher -- so SetInformationJobObject must never be called
    for this use (create_job(kill_on_close=False) skips it entirely)."""
    from ultimate_pipeline.governance.single_writer import job_supervision as job_sup

    calls: list[tuple] = []

    class FakeKernel32:
        def CreateJobObjectW(self, _sec, _name):
            calls.append(("CreateJobObjectW",))
            return 111

        def SetInformationJobObject(self, *a, **k):
            calls.append(("SetInformationJobObject", a))
            return 1

        def AssignProcessToJobObject(self, job, handle):
            calls.append(("AssignProcessToJobObject", job, handle))
            return 1

        def CloseHandle(self, handle):
            calls.append(("CloseHandle", handle))
            return 1

    monkeypatch.setattr(cu, "_IS_WINDOWS", True)
    monkeypatch.setattr(job_sup, "_kernel32", FakeKernel32())

    proc = SimpleNamespace(pid=1234, _handle=777)
    job = cu._create_job_for_launch(proc)

    assert job is not None
    assert ("CreateJobObjectW",) in calls
    assert ("AssignProcessToJobObject", job.handle, 777) in calls
    assert not any(c[0] == "OpenProcess" for c in calls), "must use proc._handle, not OpenProcess"
    assert not any(c[0] == "SetInformationJobObject" for c in calls), (
        "no KILL_ON_JOB_CLOSE flag must ever be requested for an owned CARLA job"
    )
    assert job.root_pid == 1234


def test_job_created_without_kill_on_close_closing_terminates_nothing(monkeypatch):
    """P1-1 (main-agent decision): closing/dropping the job handle must
    never terminate anything, because it was created without
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE. The fake kernel32 records no
    SetInformationJobObject call at all (there is no flag to set), and
    close() must never call TerminateJobObject."""
    from ultimate_pipeline.governance.single_writer import job_supervision as job_sup

    calls: list[tuple] = []

    class FakeKernel32:
        def CreateJobObjectW(self, _sec, _name):
            calls.append(("CreateJobObjectW",))
            return 222

        def SetInformationJobObject(self, *a, **k):
            calls.append(("SetInformationJobObject", a))
            return 1

        def CloseHandle(self, handle):
            calls.append(("CloseHandle", handle))
            return 1

        def TerminateJobObject(self, job, exit_code):
            calls.append(("TerminateJobObject", job, exit_code))
            return 1

    monkeypatch.setattr(job_sup, "_kernel32", FakeKernel32())

    job = job_sup.create_job(kill_on_close=False)
    assert not any(c[0] == "SetInformationJobObject" for c in calls), (
        "no KILL_ON_JOB_CLOSE flag must ever be requested for an owned CARLA job"
    )
    job.close()
    assert not any(c[0] == "TerminateJobObject" for c in calls), (
        "closing/dropping the handle must never terminate anything"
    )
    assert ("CloseHandle", 222) in calls


def test_job_object_path_skipped_with_a_reason_off_windows(monkeypatch, capsys):
    """Off Windows, the job-object path must be skipped (never raise, never
    attempted), with a printed reason, so _kill_stuck_carla silently falls
    back to psutil children()."""
    monkeypatch.setattr(cu, "_IS_WINDOWS", False)
    proc = SimpleNamespace(pid=1234, _handle=1)
    assert cu._create_job_for_launch(proc) is None
    out = capsys.readouterr().out
    assert "skipped" in out


# ---------------------------------------------------------------------------
# V94 round 3, P3-7: return a truthful status when the descendant tree
# cannot be verified at all (e.g. the launcher PID has already exited --
# an orphaned Shipping child may still be alive and unaccounted for), with
# no job to fall back on -- do not claim success we cannot back up.
# ---------------------------------------------------------------------------

def test_kill_reports_unverified_when_tree_enumeration_fails_with_no_job(monkeypatch):
    owned = FakeProcess(dead=True)
    owned.pid = 6000

    class FakePsutilProcess:
        def __init__(self, pid):
            raise RuntimeError("process no longer exists (simulated NoSuchProcess)")

    monkeypatch.setattr(cu, "psutil", SimpleNamespace(Process=FakePsutilProcess))

    assert cu._kill_stuck_carla(owned) is False


def test_kill_reports_true_when_tree_enumeration_succeeds_even_if_empty(monkeypatch):
    """Positive control for the test above: same dead-launcher scenario, but
    psutil enumeration itself succeeds (even with zero children) -- must
    report True."""
    owned = FakeProcess(dead=True)
    owned.pid = 6001

    class FakePsutilProcess:
        def __init__(self, pid):
            self._pid = pid

        def children(self, recursive=False):
            return []

    monkeypatch.setattr(cu, "psutil", SimpleNamespace(Process=FakePsutilProcess))

    assert cu._kill_stuck_carla(owned) is True


def test_kill_reports_true_without_pid_info_legacy_contract():
    """Positive control: no .pid attribute at all (legacy owned-handle-only
    fakes, as used elsewhere in this file) -- tree verification does not
    apply, so the pre-existing handle-only contract is kept."""
    owned = FakeProcess()  # no .pid set
    assert cu._kill_stuck_carla(owned) is True


# ---------------------------------------------------------------------------
# V94 round 2, item 6: no automatic orphan recovery, but the fail-closed
# message must name the PID holding a busy port (when determinable) plus
# an operator command. Read-only: never selects a kill target.
# ---------------------------------------------------------------------------

def test_describe_port_occupant_names_pid_and_operator_command(monkeypatch):
    class FakeConn:
        def __init__(self, port, pid, status):
            self.laddr = SimpleNamespace(ip="0.0.0.0", port=port)
            self.pid = pid
            self.status = status

    class FakeProc:
        def __init__(self, pid):
            self._pid = pid

        def name(self):
            return "CarlaUE4-Win64-Shipping.exe"

    fake_psutil = SimpleNamespace(
        net_connections=lambda kind="tcp": [
            FakeConn(2000, 4321, "LISTEN"),
            FakeConn(55000, 1, "ESTABLISHED"),  # unrelated port: must be ignored
        ],
        CONN_LISTEN="LISTEN",
        Process=lambda pid: FakeProc(pid),
    )
    monkeypatch.setattr(cu, "psutil", fake_psutil)
    monkeypatch.setattr(cu, "_IS_WINDOWS", True)

    msg = cu.describe_port_occupant(2000)
    assert "4321" in msg
    assert "CarlaUE4-Win64-Shipping.exe" in msg
    assert "taskkill" in msg and "4321" in msg.split("taskkill", 1)[1]


def test_describe_port_occupant_degrades_gracefully_without_psutil(monkeypatch):
    monkeypatch.setattr(cu, "psutil", None)
    msg = cu.describe_port_occupant(2000)
    assert "2000" in msg
    assert "could not be determined" in msg


def test_restart_rejects_foreign_port_and_names_the_holder(monkeypatch, tmp_path: Path, capsys):
    """Positive control for describe_port_occupant: restart_carla's existing
    fail-closed-on-occupied-port message (already covered without this
    detail by test_restart_rejects_foreign_port_before_popen) must now also
    name the holding PID when psutil can determine one."""
    exe = tmp_path / "CarlaUE4.exe"
    exe.write_bytes(b"stub")
    monkeypatch.setattr(cu.SETTINGS, "CARLA_EXE", str(exe), raising=False)
    monkeypatch.setattr(cu, "_require_gpu_tdr_clean_for_carla", lambda: None)
    monkeypatch.setattr(cu, "_port_open", lambda host, port, timeout=1.0: port == 2000)

    class FakeConn:
        def __init__(self, port, pid, status):
            self.laddr = SimpleNamespace(ip="0.0.0.0", port=port)
            self.pid = pid
            self.status = status

    class FakeProc:
        def name(self):
            return "CarlaUE4.exe"

    fake_psutil = SimpleNamespace(
        net_connections=lambda kind="tcp": [FakeConn(2000, 8675, "LISTEN")],
        CONN_LISTEN="LISTEN",
        Process=lambda pid: FakeProc(),
    )
    monkeypatch.setattr(cu, "psutil", fake_psutil)
    monkeypatch.setattr(
        subprocess, "Popen",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not launch into occupied port")),
    )
    assert cu.restart_carla(host="127.0.0.1", port=2000) is False
    out = capsys.readouterr().out
    assert "8675" in out
    expected_command = "taskkill" if cu._IS_WINDOWS else "kill 8675"
    assert expected_command in out


def test_crash_cache_cleanup_never_deletes_shared_directories(monkeypatch, tmp_path: Path):
    saved = tmp_path / "CarlaUE4" / "Saved"
    for name in ("Crashes", "Temp", "DerivedDataCache"):
        d = saved / name
        d.mkdir(parents=True)
        (d / "keep.txt").write_text("owned by another simulator", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import shutil
    monkeypatch.setattr(
        shutil, "rmtree",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("shared deletion prohibited")),
    )
    cu._cleanup_carla_crash_artifacts()
    for name in ("Crashes", "Temp", "DerivedDataCache"):
        assert (saved / name / "keep.txt").exists()


def test_restart_rejects_foreign_port_before_popen(monkeypatch, tmp_path: Path):
    exe = tmp_path / "CarlaUE4.exe"
    exe.write_bytes(b"stub")
    monkeypatch.setattr(cu.SETTINGS, "CARLA_EXE", str(exe), raising=False)
    monkeypatch.setattr(cu, "_require_gpu_tdr_clean_for_carla", lambda: None)
    monkeypatch.setattr(cu, "_port_open", lambda host, port, timeout=1.0: port == 2000)
    monkeypatch.setattr(
        subprocess, "Popen",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not launch into occupied port")),
    )
    assert cu.restart_carla(host="127.0.0.1", port=2000) is False


def test_legacy_image_wide_kill_is_disabled(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("image-wide kill prohibited")),
    )
    with pytest.raises(RuntimeError, match="image-wide kill is disabled"):
        cs.kill_stale_carla()


def test_launched_server_cleans_up_only_its_handle_on_readiness_failure(monkeypatch, tmp_path):
    child = FakeProcess()
    exe = tmp_path / "CarlaUE4.exe"
    exe.write_bytes(b"stub")
    monkeypatch.setattr(cs, "wait_for_port", lambda *a, **k: False)
    monkeypatch.setattr(cs, "start_carla", lambda *a, **k: child)
    with pytest.raises(RuntimeError, match="did not come up"):
        cs.ensure_carla_server(host="127.0.0.1", port=2200, carla_exe=exe, timeout_s=0.01)
    assert child.terminated == 1 and child.killed == 0


def test_external_server_is_never_terminated_by_ensure(monkeypatch, tmp_path):
    monkeypatch.setattr(cs, "wait_for_port", lambda *a, **k: True)
    monkeypatch.setattr(cs, "_handshake_carla_ready", lambda **kwargs: None)
    monkeypatch.setattr(
        cs, "start_carla",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected launch")),
    )
    assert cs.ensure_carla_server(
        host="127.0.0.1", port=2300, carla_exe=tmp_path / "CarlaUE4.exe"
    ) is None


def test_readonly_handshake_does_not_tick_externally_owned_sync_world(monkeypatch):
    class World:
        def get_map(self):
            return SimpleNamespace(name="Grid0828")

        def get_settings(self):
            return SimpleNamespace(synchronous_mode=True)

        def tick(self, *a, **k):
            raise AssertionError("a readiness probe must not steal tick ownership")

        def wait_for_tick(self, *a, **k):
            raise AssertionError("a readiness probe must not wait for owner ticks")

    class Client:
        def __init__(self, host, port):
            self.timeouts = []

        def set_timeout(self, seconds):
            self.timeouts.append(seconds)

        def get_world(self):
            return World()

    monkeypatch.setattr(cs, "_lazy_carla", lambda: SimpleNamespace(Client=Client))
    monkeypatch.setenv("UP_CARLA_READY_TIMEOUT_S", "0.2")
    cs._handshake_carla_ready(host="127.0.0.1", port=2000)


def test_invalid_ready_budget_fails_before_connect(monkeypatch):
    monkeypatch.setattr(
        cs, "_lazy_carla",
        lambda: (_ for _ in ()).throw(AssertionError("no client should start")),
    )
    monkeypatch.setenv("UP_CARLA_READY_TIMEOUT_S", "-1")
    with pytest.raises(ValueError, match="positive"):
        cs._handshake_carla_ready(host="127.0.0.1", port=2000)


def test_managed_capture_refuses_external_listener_without_opt_in(monkeypatch, tmp_path):
    monkeypatch.setattr(cs, "wait_for_port", lambda *a, **k: True)
    monkeypatch.setattr(cs, "_handshake_carla_ready",
                        lambda **kwargs: (_ for _ in ()).throw(
                            AssertionError("must refuse before handshake")))
    monkeypatch.setattr(cs, "start_carla",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("must not launch")))
    with pytest.raises(RuntimeError, match="refusing unowned attachment"):
        cs.ensure_carla_server(host="127.0.0.1", port=2000,
                               carla_exe=tmp_path / "CarlaUE4.exe",
                               attach_existing=False)


def test_deprecated_kill_stale_refused_even_when_server_reachable(monkeypatch, tmp_path):
    monkeypatch.setattr(cs, "wait_for_port", lambda *a, **k: True)
    monkeypatch.setattr(cs, "_handshake_carla_ready",
                        lambda **kwargs: (_ for _ in ()).throw(
                            AssertionError("must refuse before handshake")))
    with pytest.raises(RuntimeError, match="image-wide kill"):
        cs.ensure_carla_server(host="127.0.0.1", port=2000,
                               carla_exe=tmp_path / "CarlaUE4.exe",
                               kill_stale=True)
