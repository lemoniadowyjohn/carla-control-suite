from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import control_plane as cp


def test_win32_mutex_backend_fails_explicitly_when_unavailable(monkeypatch):
    monkeypatch.setattr(cp, "_kernel32", None)
    with pytest.raises(cp.ArbitrationError) as exc:
        cp.MutexHandle().try_acquire()
    assert exc.value.reason == "UNSUPPORTED_PLATFORM"
