# ultimate_pipeline/tools/carla_smoke_suite.py::run_smoke_suite() -- harden
# gating. Prompt 4 found harden_xodr (a full parse+rewrite of the entire
# XODR, 138MB on production maps) ran unconditionally BEFORE the map load,
# so the XML cost was paid even when CARLA was not running and the load
# could never succeed -- the expensive case being ENABLE_CARLA_TEST_EARLY
# runs that happen before the server is up. The hardener itself is pure
# xml.etree with no CARLA dependency; its only real ordering constraint is
# finishing before _load_world. These tests pin the cheap TCP reachability
# gate: probe first, skip the rewrite when nothing is listening, still run
# it when something is.
from __future__ import annotations

import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from ultimate_pipeline.tools import carla_smoke_suite
from ultimate_pipeline.tools.carla_smoke_suite import run_smoke_suite


XODR = """<?xml version="1.0"?>
<OpenDRIVE>
  <header revMajor="1" revMinor="6" name="test" version="1.00"
          date="2026-01-01" north="0" south="0" east="0" west="0"/>
  <roads/>
  <junctions/>
</OpenDRIVE>
"""


def _closed_port() -> int:
    """A port that was free a moment ago (nothing listening on it now)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def open_listener():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    yield s.getsockname()[1]
    s.close()


@pytest.fixture
def fake_carla(monkeypatch):
    """Replace the carla module import with an inert stand-in."""
    fake_client = SimpleNamespace(set_timeout=lambda t: None)
    fake_module = SimpleNamespace(Client=lambda host, port: fake_client)
    monkeypatch.setattr(carla_smoke_suite, "_get_carla", lambda: fake_module)
    return fake_module


@pytest.fixture
def harden_spy(monkeypatch):
    """Record harden_xodr calls; fail loudly if invoked unexpectedly."""
    calls: list[tuple] = []

    def spy(src, dst, report_path=None, repair_parampoly3_to_line=False):
        calls.append((str(src), str(dst)))
        Path(dst).write_text(XODR, encoding="utf-8")
        if report_path is not None:
            Path(report_path).write_text('{"stub": true}\n', encoding="utf-8")

    monkeypatch.setattr(
        "ultimate_pipeline.tools.xodr_carla_hardener.harden_xodr", spy
    )
    return calls


@pytest.fixture
def load_fails(monkeypatch):
    """Simulate the map load failing with a connection error."""
    def boom(client, xodr_path, timeout):
        raise RuntimeError("time-out: failed to connect to 127.0.0.1:2000")
    monkeypatch.setattr(carla_smoke_suite, "_load_world", boom)
    return boom


def _run(tmp_path: Path, port: int) -> dict:
    xodr = tmp_path / "map.xodr"
    xodr.write_text(XODR, encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    return run_smoke_suite(
        xodr_path=xodr,
        host="127.0.0.1",
        port=port,
        timeout=5.0,
        out_dir=out,
        spawn_ego=False,
        tick_frames=0,
        screenshot=False,
        screenshot_timeout=1.0,
    )


def test_harden_skipped_when_carla_unreachable(
    tmp_path, monkeypatch, fake_carla, harden_spy, load_fails
):
    monkeypatch.setenv("UP_ENABLE_XODR_HARDENER", "1")
    port = _closed_port()

    payload = _run(tmp_path, port)

    assert harden_spy == [], "harden_xodr must not run when CARLA port is closed"
    assert payload["carla_reachable"] is False
    assert payload["xodr_hardener"]["enabled"] is True
    assert payload["xodr_hardener"]["applied"] is False
    assert payload["xodr_hardener"]["skipped_reason"] == "carla_unreachable"
    assert payload["xodr_hardener"]["error"] is None
    assert not (tmp_path / "out" / "xodr_hardened.xodr").exists()
    assert not (tmp_path / "out" / "xodr_hardener_report.json").exists()
    # the load is still attempted (unchanged error semantics)
    assert payload["load_ok"] is False
    assert "time-out" in payload["error"]


def test_harden_runs_when_carla_reachable(
    tmp_path, monkeypatch, fake_carla, harden_spy, load_fails, open_listener
):
    monkeypatch.setenv("UP_ENABLE_XODR_HARDENER", "1")

    payload = _run(tmp_path, open_listener)

    assert len(harden_spy) == 1, "harden_xodr must run when the RPC port is open"
    assert payload["carla_reachable"] is True
    assert payload["xodr_hardener"]["applied"] is True
    assert payload["xodr_hardener"]["skipped_reason"] is None
    assert payload["xodr_used"].endswith("xodr_hardened.xodr")
    assert (tmp_path / "out" / "xodr_hardened.xodr").exists()


def test_probe_not_run_when_hardener_disabled(
    tmp_path, monkeypatch, fake_carla, harden_spy, load_fails
):
    monkeypatch.setenv("UP_ENABLE_XODR_HARDENER", "0")

    payload = _run(tmp_path, _closed_port())

    assert payload["xodr_hardener"]["enabled"] is False
    assert payload["carla_reachable"] is None
    assert harden_spy == []
    assert payload["load_ok"] is False


def test_carla_reachable_probe():
    assert carla_smoke_suite._carla_reachable("127.0.0.1", _closed_port()) is False

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        assert carla_smoke_suite._carla_reachable("127.0.0.1", s.getsockname()[1]) is True
    finally:
        s.close()
