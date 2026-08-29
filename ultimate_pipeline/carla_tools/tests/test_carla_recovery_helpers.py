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

import pytest

from ultimate_pipeline.carla_tools import carla_recovery as cr


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
