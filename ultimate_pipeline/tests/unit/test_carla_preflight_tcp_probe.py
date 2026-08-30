# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/tools/carla_preflight.py::_tcp_probe.

Live: run_preflight (which calls _tcp_probe) is imported by main_pipeline.py.
The rest of the file (server start/kill, CARLA API ticking) needs real
CARLA/OS process state to test meaningfully and is intentionally not
covered here, matching this session's carla_recovery.py judgment call.
"""
from __future__ import annotations

import socket

from ultimate_pipeline.tools.carla_preflight import _tcp_probe


def _closed_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_tcp_probe_true_for_listening_socket():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        assert _tcp_probe("127.0.0.1", port) is True
    finally:
        server.close()


def test_tcp_probe_false_for_closed_port():
    assert _tcp_probe("127.0.0.1", _closed_port()) is False
