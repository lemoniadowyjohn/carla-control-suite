# -*- coding: utf-8 -*-
"""Tests for the pure/socket-level helpers in
ultimate_pipeline/carla_tools/carla_recovery.py -- the CARLA connection
recovery manager used live by main_pipeline.py::get_reliable_client().

Zero prior test coverage. The full get_reliable_client() orchestration
(process killing, cache purging, CARLA process startup) needs real CARLA/OS
process state to test meaningfully and is intentionally not covered here --
these tests target only the pure env-flag parsing and real-socket probing
helpers that the orchestration is built on.
"""
from __future__ import annotations

import socket
import subprocess

import psutil as _real_psutil
import pytest

from ultimate_pipeline.carla_tools import carla_recovery as cr


@pytest.fixture(autouse=True)
def _safety_trap_real_process_control(monkeypatch):
    """SAFETY FIRST (V94 round 3): no test in this file may ever reach the
    REAL psutil.process_iter or subprocess.run (e.g. taskkill), whether the
    code under test is HEAD or an overlay of an older, vulnerable commit.
    Patching the real, shared module objects here closes that hole
    regardless of which SUT module did `import psutil`/`import subprocess`.
    """
    def _trap_process_iter(*a, **k):
        raise AssertionError("REAL psutil.process_iter must never be called by a test in this file")

    def _trap_run(*a, **k):
        raise AssertionError(f"REAL subprocess.run must never be called by a test in this file (args={a!r})")

    monkeypatch.setattr(_real_psutil, "process_iter", _trap_process_iter)
    monkeypatch.setattr(subprocess, "run", _trap_run)


def _closed_port() -> int:
    """A TCP port on localhost guaranteed to be closed: bind, learn the OS
    assigned free port, then close it immediately."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _ListeningServer:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]

    def close(self):
        self.sock.close()


@pytest.fixture
def listening_server():
    server = _ListeningServer()
    yield server
    server.close()


# ---------------------------------------------------------------------------
# _env_flag / _streaming_disabled
# ---------------------------------------------------------------------------

def test_env_flag_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("UP_TEST_FLAG", raising=False)
    assert cr._env_flag("UP_TEST_FLAG", default=False) is False
    assert cr._env_flag("UP_TEST_FLAG", default=True) is True


@pytest.mark.parametrize("raw", ["1", "true", "True", "YES", "y", "on", " on "])
def test_env_flag_truthy_values(monkeypatch, raw):
    monkeypatch.setenv("UP_TEST_FLAG", raw)
    assert cr._env_flag("UP_TEST_FLAG") is True


@pytest.mark.parametrize("raw", ["0", "false", "no", "", "garbage"])
def test_env_flag_falsy_values(monkeypatch, raw):
    monkeypatch.setenv("UP_TEST_FLAG", raw)
    assert cr._env_flag("UP_TEST_FLAG") is False


def test_streaming_disabled_checks_either_env_var(monkeypatch):
    monkeypatch.delenv("UP_DISABLE_STREAMING", raising=False)
    monkeypatch.delenv("UP_TILE_QA_DISABLE_STREAMING", raising=False)
    assert cr._streaming_disabled() is False

    monkeypatch.setenv("UP_DISABLE_STREAMING", "1")
    assert cr._streaming_disabled() is True

    monkeypatch.delenv("UP_DISABLE_STREAMING", raising=False)
    monkeypatch.setenv("UP_TILE_QA_DISABLE_STREAMING", "1")
    assert cr._streaming_disabled() is True


# ---------------------------------------------------------------------------
# _port_open
# ---------------------------------------------------------------------------

def test_port_open_true_for_listening_socket(listening_server):
    assert cr._port_open("127.0.0.1", listening_server.port) is True


def test_port_open_false_for_closed_port():
    assert cr._port_open("127.0.0.1", _closed_port()) is False


# ---------------------------------------------------------------------------
# probe_streaming_port
# ---------------------------------------------------------------------------

def test_probe_streaming_port_disabled_short_circuits(monkeypatch):
    monkeypatch.setenv("UP_DISABLE_STREAMING", "1")
    status = cr.probe_streaming_port("127.0.0.1", _closed_port())
    assert status["disabled"] is True
    assert status["status"] == "disabled"
    assert status["attempts"] == 0


def test_probe_streaming_port_ok_when_listening(monkeypatch, listening_server):
    monkeypatch.delenv("UP_DISABLE_STREAMING", raising=False)
    monkeypatch.delenv("UP_TILE_QA_DISABLE_STREAMING", raising=False)
    status = cr.probe_streaming_port("127.0.0.1", listening_server.port)
    assert status["status"] == "ok"
    assert status["attempts"] == 1


def test_probe_streaming_port_refused_when_closed(monkeypatch):
    monkeypatch.delenv("UP_DISABLE_STREAMING", raising=False)
    monkeypatch.delenv("UP_TILE_QA_DISABLE_STREAMING", raising=False)
    status = cr.probe_streaming_port(
        "127.0.0.1", _closed_port(), timeout_s=0.1, max_attempts=2,
    )
    assert status["status"] == "refused"
    assert status["attempts"] == 2
    assert status["error"] is not None


# ---------------------------------------------------------------------------
# _wait_for_ports
# ---------------------------------------------------------------------------

def test_wait_for_ports_true_when_rpc_open_and_streaming_not_required(listening_server):
    assert cr._wait_for_ports(
        "127.0.0.1", listening_server.port, _closed_port(),
        timeout_s=0.5, require_streaming=False,
    ) is True


def test_wait_for_ports_false_when_rpc_closed():
    assert cr._wait_for_ports(
        "127.0.0.1", _closed_port(), _closed_port(),
        timeout_s=0.3, require_streaming=False,
    ) is False


def test_wait_for_ports_requires_streaming_when_flagged(listening_server):
    # RPC open, streaming closed, require_streaming=True -> must fail.
    assert cr._wait_for_ports(
        "127.0.0.1", listening_server.port, _closed_port(),
        timeout_s=0.3, require_streaming=True,
    ) is False


# ---------------------------------------------------------------------------
# V94 round 2, item 4: automatic by-name kill is permanently removed from
# restart_carla() and get_reliable_client(). They must fail closed instead
# (naming the port holder via carla_utils.describe_port_occupant), never
# calling psutil.process_iter or killing by image name.
# ---------------------------------------------------------------------------

def test_kill_stale_processes_by_name_removed():
    """The old substring-match kill (which matched UE4Editor too) is gone
    entirely, not merely unreachable -- nothing can accidentally call it."""
    assert not hasattr(cr, "_kill_stale_processes")


def test_restart_carla_fails_closed_when_port_already_held(monkeypatch):
    """P2-4: occupancy is decided by _port_open (both the RPC and the
    streaming port), never by whether a holding PID could be resolved."""
    from ultimate_pipeline.core import carla_utils as cu

    monkeypatch.setattr(cr.SETTINGS, "CARLA_KILL_ON_FAIL", True, raising=False)
    monkeypatch.setattr(cr, "_port_open", lambda host, port: True)
    monkeypatch.setattr(cu, "describe_port_occupant", lambda port: f"port {port} is held by PID 4321")

    class TrapPS:
        @staticmethod
        def process_iter(*_a, **_k):
            raise AssertionError("must not enumerate processes")

    monkeypatch.setattr(cr, "psutil", TrapPS)
    purged = []
    started = []
    monkeypatch.setattr(cr, "_purge_temp_dirs", lambda: purged.append(True))
    monkeypatch.setattr(cr, "_start_carla", lambda: started.append(True))

    assert cr.restart_carla(host="127.0.0.1", port=2000) is False
    assert purged == []
    assert started == []


def test_restart_carla_fails_closed_when_port_open_but_holder_pid_unknown(monkeypatch):
    """P2-4 (the exact regression): an open port whose holding PID cannot
    be resolved (AccessDenied, or no psutil) must NOT be treated as "port
    free" -- that previously purged %LOCALAPPDATA%\\CarlaUE4 and the Carla
    temp dirs underneath a live simulator, then started a second instance
    into its namespace. describe_port_occupant is used only for the
    message; it must not influence the occupancy decision itself."""
    from ultimate_pipeline.core import carla_utils as cu

    monkeypatch.setattr(cr.SETTINGS, "CARLA_KILL_ON_FAIL", True, raising=False)
    monkeypatch.setattr(cr, "_port_open", lambda host, port: True)
    monkeypatch.setattr(cu, "_port_holder_pid", lambda port: None)  # unresolvable PID
    monkeypatch.setattr(cu, "describe_port_occupant", lambda port: f"port {port} occupied (holder unknown)")

    purged = []
    started = []
    monkeypatch.setattr(cr, "_purge_temp_dirs", lambda: purged.append(True))
    monkeypatch.setattr(cr, "_start_carla", lambda: started.append(True))

    assert cr.restart_carla(host="127.0.0.1", port=2000) is False
    assert purged == [], "must not purge when the port is occupied, even with an unknown holder"
    assert started == [], "must not start a second instance when the port is occupied"


def test_restart_carla_purges_and_starts_when_port_free(monkeypatch):
    """Positive control for the test above: when nothing holds the port,
    restart proceeds normally (purge + start) without any kill-by-name."""
    from ultimate_pipeline.core import carla_utils as cu

    monkeypatch.setattr(cr.SETTINGS, "CARLA_KILL_ON_FAIL", True, raising=False)
    monkeypatch.setattr(cu, "_port_holder_pid", lambda port: None)

    purged = []
    started = []
    monkeypatch.setattr(cr, "_purge_temp_dirs", lambda: purged.append(True))
    monkeypatch.setattr(cr, "_start_carla", lambda: started.append(True))
    monkeypatch.setattr(cr, "_wait_for_ports", lambda *a, **k: True)

    assert cr.restart_carla(host="127.0.0.1", port=2000, retries=1, startup_wait_s=0.01) is True
    assert purged == [True]
    assert started == [True]


def test_get_reliable_client_fails_closed_on_broken_but_listening_port(monkeypatch):
    """If the port is open but the world is unavailable, get_reliable_client
    must raise naming the holder instead of killing by name."""
    from ultimate_pipeline.core import carla_utils as cu

    monkeypatch.setattr(cr.SETTINGS, "CARLA_KILL_ON_FAIL", True, raising=False)
    monkeypatch.setattr(cr.SETTINGS, "CARLA_HOST", "127.0.0.1", raising=False)
    monkeypatch.setattr(cr.SETTINGS, "CARLA_PORT", 2000, raising=False)
    monkeypatch.setattr(cr, "probe_streaming_port", lambda *a, **k: {"status": "disabled"})
    monkeypatch.setattr(cr, "_port_open", lambda host, port: True)

    def _broken_client():
        raise RuntimeError("world unavailable")

    monkeypatch.setattr(cr, "_create_client", _broken_client)
    monkeypatch.setattr(cu, "describe_port_occupant", lambda port: f"port {port} is held by PID 999")

    with pytest.raises(RuntimeError, match="refusing automatic image-wide kill-by-name"):
        cr.get_reliable_client()


def test_get_reliable_client_skips_kill_when_port_not_open(monkeypatch):
    """Positive control: when the port isn't even open, there's nothing to
    kill -- no process_iter/kill-by-name call, just purge + start."""
    monkeypatch.setattr(cr.SETTINGS, "CARLA_KILL_ON_FAIL", True, raising=False)
    monkeypatch.setattr(cr.SETTINGS, "CARLA_HOST", "127.0.0.1", raising=False)
    monkeypatch.setattr(cr.SETTINGS, "CARLA_PORT", 2000, raising=False)
    monkeypatch.setattr(cr.SETTINGS, "CARLA_CONNECT_RETRIES", 1, raising=False)
    monkeypatch.setattr(cr.SETTINGS, "CARLA_STARTUP_WAIT", 0.01, raising=False)
    monkeypatch.setattr(cr, "probe_streaming_port", lambda *a, **k: {"status": "disabled"})
    monkeypatch.setattr(cr, "_port_open", lambda host, port: False)

    class TrapPS:
        @staticmethod
        def process_iter(*_a, **_k):
            raise AssertionError("must not enumerate processes")

    monkeypatch.setattr(cr, "psutil", TrapPS)
    purged = []
    started = []
    monkeypatch.setattr(cr, "_purge_temp_dirs", lambda: purged.append(True))
    monkeypatch.setattr(cr, "_start_carla", lambda: started.append(True))
    monkeypatch.setattr(cr, "dump_carla_crash", lambda *a, **k: None)

    with pytest.raises(RuntimeError):
        cr.get_reliable_client()
    assert purged == [True]
    assert started == [True]


def test_get_reliable_client_retries_its_own_just_launched_instance(monkeypatch):
    """P2-5: a CARLA this loop itself just launched can still be loading --
    that is not a foreign holder. It must keep retrying (and keep that
    process's handle, not abandon it for a second launch) until the world
    becomes available, instead of raising on the first transient error."""
    monkeypatch.setattr(cr.SETTINGS, "CARLA_KILL_ON_FAIL", True, raising=False)
    monkeypatch.setattr(cr.SETTINGS, "CARLA_HOST", "127.0.0.1", raising=False)
    monkeypatch.setattr(cr.SETTINGS, "CARLA_PORT", 2000, raising=False)
    monkeypatch.setattr(cr.SETTINGS, "CARLA_STARTUP_WAIT", 0.0, raising=False)
    monkeypatch.setattr(cr, "probe_streaming_port", lambda *a, **k: {"status": "disabled"})
    monkeypatch.setattr(cr, "_purge_temp_dirs", lambda: None)
    monkeypatch.setattr(cr.time, "sleep", lambda *_: None)

    class FakeOwnedProc:
        def __init__(self):
            self.alive = True

        def poll(self):
            return None if self.alive else 0

    launched: list = []

    def _fake_start_carla():
        p = FakeOwnedProc()
        launched.append(p)
        return p

    monkeypatch.setattr(cr, "_start_carla", _fake_start_carla)
    # Port "opens" only once this loop has launched something itself.
    monkeypatch.setattr(cr, "_port_open", lambda host, port: bool(launched))

    attempts = {"n": 0}
    sentinel_client = object()

    def _fake_create_client():
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise RuntimeError("still loading")
        return sentinel_client

    monkeypatch.setattr(cr, "_create_client", _fake_create_client)

    client = cr.get_reliable_client()
    assert client is sentinel_client
    assert len(launched) == 1, "must not start a second instance while its own launch is still loading"
