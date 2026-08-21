"""C20 Tier 3 — carla_utils.py hardening: honest RPC readiness, a kept
server log, and a VRAM preflight. Everything here is mocked (no real
CARLA process, no real GPU query) -- these test the launcher's own logic,
not CARLA itself.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import ultimate_pipeline.core.carla_utils as cu


# ---------------------------------------------------------------------------
# _carla_ready_timeout_s
# ---------------------------------------------------------------------------

def test_ready_timeout_defaults_to_600(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UP_CARLA_READY_TIMEOUT_S", raising=False)
    assert cu._carla_ready_timeout_s() == 600.0


def test_ready_timeout_respects_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UP_CARLA_READY_TIMEOUT_S", "45")
    assert cu._carla_ready_timeout_s() == 45.0


def test_ready_timeout_falls_back_on_garbage_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UP_CARLA_READY_TIMEOUT_S", "not-a-number")
    assert cu._carla_ready_timeout_s() == 600.0


# ---------------------------------------------------------------------------
# _resolve_carla_log_path_for_launch -- log is never discarded
# ---------------------------------------------------------------------------

def test_log_path_prefers_explicit_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = str(tmp_path / "explicit.log")
    monkeypatch.setenv("UP_CARLA_LOG_PATH", target)
    assert cu._resolve_carla_log_path_for_launch() == target


def test_log_path_defaults_to_a_real_path_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UP_CARLA_LOG_PATH", raising=False)
    monkeypatch.setattr(cu.SETTINGS, "CARLA_SERVER_LOG", None, raising=False)
    path = cu._resolve_carla_log_path_for_launch()
    assert path  # never None/empty -- this is the whole point of the fix
    assert "carla_server_" in path


# ---------------------------------------------------------------------------
# ensure_carla_ready -- timeout_s overrides the fixed retry count
# ---------------------------------------------------------------------------

class _FlakyClient:
    """Fails N times then succeeds -- simulates a slow-starting server."""
    def __init__(self, fail_count: int) -> None:
        self._remaining = fail_count

    def get_world(self):
        if self._remaining > 0:
            self._remaining -= 1
            raise RuntimeError("not ready yet")
        return SimpleNamespace(get_map=lambda: SimpleNamespace())

    def get_server_version(self):
        return "0.9.16"

    def get_client_version(self):
        return "0.9.16"

    def set_timeout(self, seconds: float) -> None:
        pass


class _NeverReadyClient:
    def get_world(self):
        raise RuntimeError("permanently stuck")

    def set_timeout(self, seconds: float) -> None:
        pass


def test_ensure_carla_ready_succeeds_within_default_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    assert cu.ensure_carla_ready(_FlakyClient(fail_count=3), retries=5, delay_s=0.0) is True


def test_ensure_carla_ready_negative_control_never_ready_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    assert cu.ensure_carla_ready(_NeverReadyClient(), retries=3, delay_s=0.0) is False


def test_ensure_carla_ready_timeout_s_overrides_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """A client that needs more attempts than `retries` allows must still
    succeed if timeout_s gives it enough wall-clock time."""
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    client = _FlakyClient(fail_count=50)
    # retries=1 would fail immediately without timeout_s; timeout_s must win.
    assert cu.ensure_carla_ready(client, retries=1, delay_s=0.0, timeout_s=5.0) is True


def test_ensure_carla_ready_timeout_s_expires_eventually(monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative control: timeout_s must actually bound the wait, not loop forever."""
    fake_now = [0.0]
    monkeypatch.setattr(time, "time", lambda: fake_now[0])

    def _fake_sleep(seconds: float) -> None:
        fake_now[0] += seconds

    monkeypatch.setattr(time, "sleep", _fake_sleep)
    assert cu.ensure_carla_ready(_NeverReadyClient(), delay_s=1.0, timeout_s=3.0) is False


# ---------------------------------------------------------------------------
# _vram_preflight
# ---------------------------------------------------------------------------

def test_vram_preflight_no_action_when_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    killed = []
    monkeypatch.setattr(cu, "_kill_stuck_carla", lambda: killed.append(True))
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: SimpleNamespace(stdout="0\n"),
    )
    cu._vram_preflight()
    assert killed == []


def test_vram_preflight_kills_stale_instance_when_dirty(monkeypatch: pytest.MonkeyPatch) -> None:
    killed = []
    monkeypatch.setattr(cu, "_kill_stuck_carla", lambda: killed.append(True))
    monkeypatch.setattr(cu.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: SimpleNamespace(stdout="5923\n"),
    )
    cu._vram_preflight()
    assert killed == [True]


def test_vram_preflight_gracefully_skips_when_nvidia_smi_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a, **k):
        raise FileNotFoundError("nvidia-smi not found")
    killed = []
    monkeypatch.setattr(cu, "_kill_stuck_carla", lambda: killed.append(True))
    monkeypatch.setattr(subprocess, "run", _raise)
    cu._vram_preflight()  # must not raise
    assert killed == []


# ---------------------------------------------------------------------------
# restart_carla -- render flags + honest RPC-aware success reporting
# ---------------------------------------------------------------------------

class _FakeCarlaModule:
    def __init__(self, client) -> None:
        self._client = client

    def Client(self, host, port):
        return self._client


def _patch_restart_common(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, client) -> list:
    exe = tmp_path / "CarlaUE4.exe"
    exe.write_text("stub")
    monkeypatch.setattr(cu.SETTINGS, "CARLA_EXE", str(exe), raising=False)
    monkeypatch.setattr(cu.SETTINGS, "CARLA_HOST", "127.0.0.1", raising=False)
    monkeypatch.setattr(cu.SETTINGS, "CARLA_PORT", 2000, raising=False)
    monkeypatch.setattr(cu.SETTINGS, "CARLA_STREAMING_PORT", 2001, raising=False)
    monkeypatch.setattr(cu, "_cleanup_carla_crash_artifacts", lambda: None)
    monkeypatch.setattr(cu, "_kill_stuck_carla", lambda: None)
    monkeypatch.setattr(cu, "_gpu_tdr_preflight", lambda: {"ok": True, "skipped": True})
    monkeypatch.setattr(cu.time, "sleep", lambda *_: None)
    monkeypatch.setattr(cu, "_vram_preflight", lambda: None)
    monkeypatch.setattr(cu, "_carla_module", lambda: _FakeCarlaModule(client))
    monkeypatch.chdir(tmp_path)

    captured_cmds: list = []

    def _fake_popen(cmd, **kwargs):
        captured_cmds.append(cmd)
        return SimpleNamespace()

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)
    return captured_cmds


def test_restart_carla_rejects_port_open_but_rpc_never_ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The exact C20 bug: port opens, RPC never responds -- must NOT report success."""
    _patch_restart_common(monkeypatch, tmp_path, client=_NeverReadyClient())
    monkeypatch.setattr(cu, "_wait_for_ports", lambda *a, **k: True)
    monkeypatch.setenv("UP_CARLA_READY_TIMEOUT_S", "0.01")
    assert cu.restart_carla() is False


def test_restart_carla_blocks_when_gpu_tdr_preflight_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cmds = _patch_restart_common(monkeypatch, tmp_path, client=_FlakyClient(fail_count=0))
    monkeypatch.setattr(
        cu,
        "_gpu_tdr_preflight",
        lambda: {
            "ok": False,
            "reason": "recent_livekernelevent_141",
            "event_count_sampled": 1,
            "lookback_hours": 24.0,
        },
    )

    assert cu.restart_carla() is False
    assert cmds == []


def test_restart_carla_succeeds_when_rpc_actually_responds(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_restart_common(monkeypatch, tmp_path, client=_FlakyClient(fail_count=0))
    monkeypatch.setattr(cu, "_wait_for_ports", lambda *a, **k: True)
    assert cu.restart_carla() is True


def test_restart_carla_uses_nullrhi_flags_when_env_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cmds = _patch_restart_common(monkeypatch, tmp_path, client=_FlakyClient(fail_count=0))
    monkeypatch.setattr(cu, "_wait_for_ports", lambda *a, **k: True)
    monkeypatch.setenv("UP_CARLA_NULLRHI", "1")
    assert cu.restart_carla() is True
    assert "-nullrhi" in cmds[0]
    assert "-RenderOffScreen" not in cmds[0]


def test_restart_carla_writes_a_server_log_not_devnull(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("UP_CARLA_LOG_PATH", raising=False)
    _patch_restart_common(monkeypatch, tmp_path, client=_FlakyClient(fail_count=0))
    monkeypatch.setattr(cu, "_wait_for_ports", lambda *a, **k: True)
    assert cu.restart_carla() is True
    log_dir = tmp_path / "reports" / "post_audit_hardening" / "_carla_server_logs"
    assert log_dir.is_dir()
    assert list(log_dir.glob("carla_server_*.log"))
