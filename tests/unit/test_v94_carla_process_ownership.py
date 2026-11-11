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
