"""V94 offline process ownership and safety regressions; no CARLA runtime required."""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from ultimate_pipeline.core import carla_utils as cu
from ultimate_pipeline.carla_tools import carla_server as cs


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
# V94 round 2, item 3: reap the owned descendant tree (CarlaUE4.exe spawns a
# Shipping child after launch -- a one-time children() snapshot at Popen time
# can never see it). Preferred path is a Windows Job Object; fallback is
# psutil children(), captured while the parent is alive; neither path may
# ever enumerate or match processes by name.
# ---------------------------------------------------------------------------

class FakeTreeMember:
    """A fake process-tree node (owned child or an unrelated same-name proc)."""

    def __init__(self, pid: int, name: str):
        self.pid = pid
        self.name = name
        self.killed = 0

    def kill(self):
        self.killed += 1


def test_psutil_fallback_reaps_owned_child_but_spares_unrelated_same_name_process(monkeypatch):
    """No job object available -- the psutil-children fallback must kill only
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
    # Force the job-object path unavailable so the psutil fallback is exercised.
    monkeypatch.setattr(cu, "_terminate_job_object", lambda job_handle: False)

    assert cu._kill_stuck_carla(owned) is True
    assert owned.terminated == 1
    assert shipping_child.killed == 1
    assert unrelated_same_name.killed == 0


def test_job_object_success_takes_precedence_over_psutil_children(monkeypatch):
    """When the job-object termination succeeds, the psutil-children fallback
    must not also run (it would be redundant and, if the snapshot were ever
    stale, unsafe)."""
    owned = FakeProcess()
    owned.pid = 5000
    captured_child = FakeTreeMember(5001, "CarlaUE4-Win64-Shipping.exe")

    class FakePsutilProcess:
        def __init__(self, pid):
            self._pid = pid

        def children(self, recursive=False):
            return [captured_child]

    monkeypatch.setattr(cu, "psutil", SimpleNamespace(Process=FakePsutilProcess))
    terminated_jobs = []
    monkeypatch.setattr(
        cu, "_terminate_job_object",
        lambda job_handle: terminated_jobs.append(job_handle) or True,
    )

    assert cu._kill_stuck_carla(owned, job_handle=777) is True
    assert terminated_jobs == [777]
    assert captured_child.killed == 0


def test_create_and_terminate_job_object_drive_kernel32_api_in_order(monkeypatch):
    """_create_job_object_for_pid/_terminate_job_object must call the Win32
    Job Object API (CreateJobObjectW -> SetInformationJobObject ->
    OpenProcess -> AssignProcessToJobObject, then TerminateJobObject on
    teardown) scoped to exactly the given PID -- never enumerating."""
    calls: list[tuple] = []

    class FakeKernel32:
        def CreateJobObjectW(self, _sec, _name):
            calls.append(("CreateJobObjectW",))
            return 111

        def SetInformationJobObject(self, job, info_class, info, size):
            calls.append(("SetInformationJobObject", job))
            return 1

        def OpenProcess(self, access, inherit, pid):
            calls.append(("OpenProcess", pid))
            return 222

        def AssignProcessToJobObject(self, job, hproc):
            calls.append(("AssignProcessToJobObject", job, hproc))
            return 1

        def CloseHandle(self, handle):
            calls.append(("CloseHandle", handle))
            return 1

        def TerminateJobObject(self, job, exit_code):
            calls.append(("TerminateJobObject", job, exit_code))
            return 1

    monkeypatch.setattr(cu, "_IS_WINDOWS", True)
    monkeypatch.setattr(cu, "_kernel32", FakeKernel32())

    job = cu._create_job_object_for_pid(1234)
    assert job == 111
    assert ("OpenProcess", 1234) in calls
    assert ("AssignProcessToJobObject", 111, 222) in calls

    assert cu._terminate_job_object(job) is True
    assert ("TerminateJobObject", 111, 1) in calls


def test_job_object_path_skipped_with_a_reason_off_windows(monkeypatch, capsys):
    """Off Windows, the job-object path must be skipped (never raise, never
    attempted), with a printed reason, so _kill_stuck_carla silently falls
    back to psutil children()."""
    monkeypatch.setattr(cu, "_IS_WINDOWS", False)
    assert cu._create_job_object_for_pid(1234) is None
    out = capsys.readouterr().out
    assert "skipped" in out
    assert cu._terminate_job_object(999) is False


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
    assert "taskkill" in out


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
