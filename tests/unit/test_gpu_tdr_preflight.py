from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

from ultimate_pipeline.core.gpu_tdr_preflight import windows_gpu_tdr_preflight


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(
        args=["powershell"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_gpu_tdr_preflight_skips_on_non_windows() -> None:
    report = windows_gpu_tdr_preflight(platform="linux")

    assert report["ok"] is True
    assert report["skipped"] is True
    assert report["reason"] == "non_windows"


def test_gpu_tdr_preflight_passes_when_no_recent_events(monkeypatch) -> None:
    monkeypatch.delenv("UP_DISABLE_CARLA", raising=False)

    report = windows_gpu_tdr_preflight(
        platform="win32",
        runner=lambda *a, **k: _completed(stdout="[]"),
    )

    assert report["ok"] is True
    assert report["reason"] == "no_recent_livekernelevent_141"


def test_gpu_tdr_preflight_blocks_on_recent_livekernelevent_141(monkeypatch) -> None:
    monkeypatch.delenv("UP_DISABLE_CARLA", raising=False)
    event = {
        "timeCreated": "2026-08-21T10:00:00.0000000+02:00",
        "Id": 1001,
        "ProviderName": "Windows Error Reporting",
        "message": "Problem Event Name: LiveKernelEvent\nP1: 141",
    }

    report = windows_gpu_tdr_preflight(
        platform="win32",
        runner=lambda *a, **k: _completed(stdout=json.dumps(event)),
    )

    assert report["ok"] is False
    assert report["reason"] == "recent_livekernelevent_141"
    assert report["event_count_sampled"] == 1


def test_gpu_tdr_preflight_fails_closed_when_event_log_query_fails(monkeypatch) -> None:
    monkeypatch.delenv("UP_DISABLE_CARLA", raising=False)

    report = windows_gpu_tdr_preflight(
        platform="win32",
        runner=lambda *a, **k: _completed(stderr="access denied", returncode=1),
    )

    assert report["ok"] is False
    assert report["reason"] == "event_log_query_failed"


def test_gpu_tdr_preflight_skips_when_carla_is_disabled(monkeypatch) -> None:
    monkeypatch.setenv("UP_DISABLE_CARLA", "1")
    called = []

    def _runner(*args, **kwargs):
        called.append(SimpleNamespace(args=args, kwargs=kwargs))
        return _completed(stdout="[]")

    report = windows_gpu_tdr_preflight(platform="win32", runner=_runner)

    assert report["ok"] is True
    assert report["skipped"] is True
    assert report["reason"] == "carla_disabled"
    assert called == []
