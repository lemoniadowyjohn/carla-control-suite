"""V94 round 2/3, item 4 + P2-6: ultimate_pipeline/tools/run_perception_safe.py's
_restart_carla_and_wait() used to automatically kill any process whose name
contained "CarlaUE4" (psutil.process_iter substring match), falling back to
`taskkill /F /IM CarlaUE4*.exe` / `CarlaUE4-Win64-Shipping.exe` when psutil
was unavailable. That automatic by-name kill is permanently removed: an
image name does not identify a launch owner, a run, or a port. These tests
confirm the fail-closed replacement (refuse + name the port holder) and its
positive control (ports free -> proceeds normally).

SAFETY FIRST (round 3): a round-2 version of these tests called REAL
psutil kill-by-name when run against an overlay of 9c4c0f26, for two
reasons that both had to be fixed:
  1. A *raising* trap on psutil.process_iter is silently swallowed by the
     vulnerable code's own `except Exception: pass` around that call, so
     the test "passed" without ever proving anything -- and, worse, if the
     trap were absent, nothing would stop a REAL kill.
  2. The vulnerable code's kill-by-name block runs unconditionally at the
     very top of the function, before any port-state check -- so even a
     test with no interest in kill-by-name (e.g. the "ports free" happy
     path) would still reach it when loaded against that version.
The fix is a file-wide autouse fixture that installs a RECORDING
(non-raising) fake psutil into sys.modules for every test (so it's picked
up by a fresh `import psutil` inside the function under test, regardless
of which version is loaded), plus a real-module trap as a backstop.
"""
from __future__ import annotations

import subprocess
import sys

import psutil as _real_psutil
import pytest

from ultimate_pipeline.tools import run_perception_safe as rps


@pytest.fixture(autouse=True)
def _safety_trap_real_process_control(monkeypatch):
    """Protect every test in this file from ever reaching a REAL
    psutil.process_iter or REAL subprocess.run (e.g. taskkill), whether the
    code under test is HEAD or an overlay of an older, vulnerable commit.
    Returns a `calls` dict tests can inspect; tests that don't care about
    kill-by-name simply ignore it.
    """
    calls = {"process_iter": 0, "killed_by_name": [], "subprocess_run": []}

    class _RecordingProcEntry:
        def __init__(self, name):
            self.info = {"name": name}

        def kill(self):
            calls["killed_by_name"].append(self.info["name"])

    class _RecordingPsutil:
        @staticmethod
        def process_iter(*_a, **_k):
            calls["process_iter"] += 1
            # A name that WOULD match the old "CarlaUE4" substring, so any
            # surviving kill-by-name path is caught here, never by
            # touching a real process.
            return [_RecordingProcEntry("CarlaUE4-Win64-Shipping.exe")]

    monkeypatch.setitem(sys.modules, "psutil", _RecordingPsutil)

    def _recording_run(cmd, **kwargs):
        calls["subprocess_run"].append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", _recording_run)

    # Backstop: also trap the real module's own attribute directly, in
    # case some code path reaches it without going through a fresh
    # `import psutil` (and thus without seeing the sys.modules override).
    def _trap_real_process_iter(*a, **k):
        raise AssertionError("REAL psutil.process_iter must never be called by a test in this file")

    monkeypatch.setattr(_real_psutil, "process_iter", _trap_real_process_iter)

    return calls


def test_restart_carla_and_wait_never_enumerates_or_kills_by_name(monkeypatch, _safety_trap_real_process_control):
    """P2-6 (replaces the vacuous/unsafe round-2 version of this test):
    must never call psutil.process_iter or subprocess.run (taskkill).
    Asserting on recorded calls AFTER the function returns -- rather than
    expecting an exception during it -- is what makes this test
    meaningful against a vulnerable version too: that version's own
    `except Exception: pass` cannot swallow a post-hoc assertion the way
    it swallowed a raising trap."""
    calls = _safety_trap_real_process_control
    monkeypatch.setattr(rps, "_tcp_port_open", lambda host, port, timeout_s=1.0: False)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: object())

    # Fake clock so the post-launch readiness wait loop (ports never report
    # open) exits on its first iteration instead of busy-waiting real time.
    fake_clock = {"t": 0.0}
    monkeypatch.setattr(rps.time, "time", lambda: fake_clock["t"])
    monkeypatch.setattr(rps.time, "sleep", lambda *_: fake_clock.__setitem__("t", fake_clock["t"] + 10.0))

    rps._restart_carla_and_wait(
        "C:/fake/CarlaUE4.exe", rpc_port=2000, stream_port=2001, startup_wait_s=0.0,
    )

    assert calls["process_iter"] == 0, "must never enumerate processes"
    assert calls["killed_by_name"] == [], "must never kill a process found by name"
    assert calls["subprocess_run"] == [], "must never call subprocess.run (e.g. taskkill)"


def test_restart_carla_and_wait_never_taskkills_when_psutil_unavailable(monkeypatch, _safety_trap_real_process_control):
    """Same regression as above, but for the "psutil unavailable" branch
    (the taskkill-by-/IM fallback) -- the previous test's sys.modules fake
    makes `import psutil` succeed, so it alone never exercises this
    branch. Forces a real ImportError for "psutil" specifically."""
    calls = _safety_trap_real_process_control
    monkeypatch.delitem(sys.modules, "psutil", raising=False)

    import builtins
    real_import = builtins.__import__

    def _fake_import(name, *a, **k):
        if name == "psutil":
            raise ImportError("psutil forced unavailable for this test")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    monkeypatch.setattr(rps, "_tcp_port_open", lambda host, port, timeout_s=1.0: False)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: object())

    fake_clock = {"t": 0.0}
    monkeypatch.setattr(rps.time, "time", lambda: fake_clock["t"])
    monkeypatch.setattr(rps.time, "sleep", lambda *_: fake_clock.__setitem__("t", fake_clock["t"] + 10.0))

    rps._restart_carla_and_wait(
        "C:/fake/CarlaUE4.exe", rpc_port=2000, stream_port=2001, startup_wait_s=0.0,
    )

    assert calls["subprocess_run"] == [], "must never call subprocess.run/taskkill even when psutil is unavailable"


def test_restart_carla_and_wait_fails_closed_when_rpc_port_already_occupied(monkeypatch, _safety_trap_real_process_control):
    """Item 4 fail-closed path: if the RPC port is already open, refuse to
    launch (and never call psutil.process_iter or taskkill to clear it)."""
    calls = _safety_trap_real_process_control
    monkeypatch.setattr(
        rps, "_tcp_port_open",
        lambda host, port, timeout_s=1.0: port == 2000,
    )
    monkeypatch.setattr(
        subprocess, "Popen",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not launch into an occupied port")),
    )

    assert rps._restart_carla_and_wait(
        "C:/fake/CarlaUE4.exe", rpc_port=2000, stream_port=2001,
    ) is False
    assert calls["process_iter"] == 0
    assert calls["killed_by_name"] == []
    assert calls["subprocess_run"] == []


def test_restart_carla_and_wait_fails_closed_message_names_the_holder(monkeypatch, capsys):
    from ultimate_pipeline.core import carla_utils as cu

    monkeypatch.setattr(rps, "_tcp_port_open", lambda host, port, timeout_s=1.0: port == 2000)
    monkeypatch.setattr(cu, "describe_port_occupant", lambda port: f"port {port} is held by PID 1357")
    monkeypatch.setattr(
        subprocess, "Popen",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not launch")),
    )

    assert rps._restart_carla_and_wait(
        "C:/fake/CarlaUE4.exe", rpc_port=2000, stream_port=2001,
    ) is False
    out = capsys.readouterr().out
    assert "1357" in out
    assert "no automatic kill-by-name" in out


def test_restart_carla_and_wait_proceeds_normally_when_ports_free(monkeypatch, _safety_trap_real_process_control):
    """Positive control: when neither target port is occupied, the function
    proceeds straight to launching (and succeeds once ports open), with no
    kill-by-name step in between."""
    calls = _safety_trap_real_process_control
    launched = []

    def _fake_popen(cmd, **kwargs):
        launched.append(cmd)
        return object()

    port_state = {"up": False}

    def _fake_tcp_port_open(host, port, timeout_s=1.0):
        return port_state["up"]

    monkeypatch.setattr(rps, "_tcp_port_open", _fake_tcp_port_open)
    monkeypatch.setattr(subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(rps.time, "sleep", lambda *_: port_state.__setitem__("up", True))

    assert rps._restart_carla_and_wait(
        "C:/fake/CarlaUE4.exe", rpc_port=2000, stream_port=2001, startup_wait_s=5.0,
    ) is True
    assert launched, "Popen must have been called once ports were confirmed free"
    assert calls["process_iter"] == 0
    assert calls["killed_by_name"] == []
