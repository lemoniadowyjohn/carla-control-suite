"""V94 round 2, item 4: ultimate_pipeline/tools/run_perception_safe.py's
_restart_carla_and_wait() used to automatically kill any process whose name
contained "CarlaUE4" (psutil.process_iter substring match), falling back to
`taskkill /F /IM CarlaUE4*.exe` / `CarlaUE4-Win64-Shipping.exe` when psutil
was unavailable. That automatic by-name kill is permanently removed: an
image name does not identify a launch owner, a run, or a port. These tests
confirm the fail-closed replacement (refuse + name the port holder) and its
positive control (ports free -> proceeds normally), and that neither
`subprocess.run` (taskkill) nor `psutil.process_iter` is ever invoked by
this function anymore.
"""
from __future__ import annotations

import subprocess

import pytest

from ultimate_pipeline.tools import run_perception_safe as rps


def test_restart_carla_and_wait_never_calls_subprocess_run(monkeypatch):
    """No taskkill (or any other subprocess.run) call site remains in this
    function; it may only use subprocess.Popen (to launch)."""
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("taskkill/subprocess.run prohibited")),
    )
    monkeypatch.setattr(rps, "_tcp_port_open", lambda host, port, timeout_s=1.0: False)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: object())

    # Fake clock so the post-launch readiness wait loop (ports never report
    # open) exits on its first iteration instead of busy-waiting real time.
    fake_clock = {"t": 0.0}
    monkeypatch.setattr(rps.time, "time", lambda: fake_clock["t"])
    monkeypatch.setattr(rps.time, "sleep", lambda *_: fake_clock.__setitem__("t", fake_clock["t"] + 10.0))

    result = rps._restart_carla_and_wait(
        "C:/fake/CarlaUE4.exe", rpc_port=2000, stream_port=2001, startup_wait_s=0.0,
    )
    assert result is False


def test_restart_carla_and_wait_fails_closed_when_rpc_port_already_occupied(monkeypatch):
    """Item 4 fail-closed path: if the RPC port is already open, refuse to
    launch (and never call psutil.process_iter or taskkill to clear it)."""
    monkeypatch.setattr(
        rps, "_tcp_port_open",
        lambda host, port, timeout_s=1.0: port == 2000,
    )
    monkeypatch.setattr(
        subprocess, "Popen",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not launch into an occupied port")),
    )
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("taskkill prohibited")),
    )

    class TrapPS:
        @staticmethod
        def process_iter(*_a, **_k):
            raise AssertionError("must not enumerate processes")

    import sys
    monkeypatch.setitem(sys.modules, "psutil", TrapPS)

    assert rps._restart_carla_and_wait(
        "C:/fake/CarlaUE4.exe", rpc_port=2000, stream_port=2001,
    ) is False


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


def test_restart_carla_and_wait_proceeds_normally_when_ports_free(monkeypatch):
    """Positive control: when neither target port is occupied, the function
    proceeds straight to launching (and succeeds once ports open), with no
    kill-by-name step in between."""
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
