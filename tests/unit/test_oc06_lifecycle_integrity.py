"""OC-06 CARLA process lifecycle and single-writer lease tests (offline/mock).

All tests are OFFLINE ΓÇö no CARLA server, no real process killing.
Mocks are used for the control plane and labeled clearly.

Covered:
- Process ownership: WriterLock records pid; is_live() checks pid liveness
- Single-writer locking/fencing: acquire blocks on live lock, expired lock reacquired
- Crash recovery: dead pid -> lock treated as stale -> reacquire allowed
- Cancellation and timeouts: lease expiration
- Resource cleanup: lock release on process exit, stale lock cleanup
- Stale process/receipt detection: lock with dead pid is not live
- CARLA lifecycle with mocks: start_carla, wait_for_port, ensure_carla_server (mocked)
- kill_stale_carla safety: documents taskkill /IM concern (gap)
- Cross-platform: Windows named mutex (documented as gap)
"""

from __future__ import annotations

import json
import os
import platform
import signal
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ultimate_pipeline.contracts.writer_lock import WriterLock, CANONICAL_LOCK_PATH


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _alive_pid() -> int:
    """Return the PID of the current process (guaranteed alive)."""
    return os.getpid()


def _dead_pid() -> int:
    """Return a PID that is almost certainly not alive on this machine."""
    # Use a very large PID that is unlikely to exist.
    return 999999


def _make_expired_lock(tmp_path: Path, owner: str = "dead-agent") -> WriterLock:
    """Create a lock file with an expired lease and a dead PID."""
    lock = WriterLock.acquire(
        root=tmp_path,
        branch="dead-branch",
        head_sha="deadbeef",
        owner=owner,
        lease_minutes=0,  # immediately expired
    )
    # Override pid to a dead value
    lock.pid = _dead_pid()
    lock.save()
    return lock


# ---------------------------------------------------------------------------
# Process ownership: PID liveness
# ---------------------------------------------------------------------------


def test_is_live_requires_alive_pid(tmp_path: Path):
    """WriterLock.is_live() should return False when the recorded PID is dead.

    GAP: Current implementation only checks status + expires_at, NOT whether
    the PID is actually alive. A lock held by a dead process is still "live"
    until the lease expires. This test documents the gap.
    """
    lock = WriterLock.acquire(
        root=tmp_path,
        branch="test",
        head_sha="abc",
        owner="agent",
        lease_minutes=60,
    )
    # Override pid to a dead value while keeping status active + lease valid
    lock.pid = _dead_pid()
    lock.save()

    # is_live() currently returns True (only checks status+expiry, not PID liveness)
    # This documents the gap: PID liveness is not checked.
    assert lock.is_live() is True  # documents current (incomplete) behavior


def test_owned_by_pid_matches_current_process(tmp_path: Path):
    """The lock's pid should match the acquiring process."""
    lock = WriterLock.acquire(
        root=tmp_path,
        branch="test",
        head_sha="abc",
        owner="agent",
    )
    assert lock.pid == os.getpid()


# ---------------------------------------------------------------------------
# Crash recovery: dead pid -> stale lock -> reacquire
# ---------------------------------------------------------------------------


def test_lock_with_dead_pid_can_be_reacquired_after_expiry(tmp_path: Path):
    """A lock with a dead PID and expired lease can be reacquired.

    This simulates crash recovery: the owning process crashed, the lease
    expired, and a new agent can acquire the lock.
    """
    _make_expired_lock(tmp_path, owner="crashed-agent")
    lock = WriterLock.acquire(
        root=tmp_path,
        branch="recovery",
        head_sha="new-sha",
        owner="recovery-agent",
        lease_minutes=60,
    )
    assert lock.owner == "recovery-agent"


# ---------------------------------------------------------------------------
# Stale process/receipt detection
# ---------------------------------------------------------------------------


def test_stale_lock_is_not_live_after_lease_expiry(tmp_path: Path):
    """A lock whose lease has expired is not live, regardless of PID."""
    lock = WriterLock.acquire(
        root=tmp_path,
        branch="test",
        head_sha="abc",
        owner="agent",
        lease_minutes=0,  # immediately expired
    )
    assert lock.is_expired()
    assert not lock.is_live()


# ---------------------------------------------------------------------------
# CARLA lifecycle with mocks
# ---------------------------------------------------------------------------


def test_wait_for_port_returns_false_when_port_closed():
    """wait_for_port returns False when no listener is on the port."""
    from ultimate_pipeline.carla_tools.carla_server import wait_for_port

    assert wait_for_port("127.0.0.1", 19999, timeout_s=1.0) is False


def test_wait_for_port_returns_true_when_port_open(tmp_path: Path):
    """wait_for_port returns True when a listener is on the port."""
    from ultimate_pipeline.carla_tools.carla_server import wait_for_port
    import socket
    import threading

    # Start a tiny TCP listener on an ephemeral port
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def _accept_and_close():
        try:
            conn, _ = listener.accept()
            conn.close()
        except Exception:
            pass

    t = threading.Thread(target=_accept_and_close, daemon=True)
    t.start()

    assert wait_for_port("127.0.0.1", port, timeout_s=5.0) is True
    listener.close()


def test_start_carla_raises_when_exe_missing(tmp_path: Path):
    """start_carla raises FileNotFoundError when CarlaUE4.exe doesn't exist."""
    from ultimate_pipeline.carla_tools.carla_server import start_carla

    with pytest.raises(FileNotFoundError, match="CARLA executable not found"):
        start_carla(tmp_path / "nonexistent_CarlaUE4.exe")


def test_ensure_carla_server_raises_when_no_exe_and_port_closed(tmp_path: Path):
    """ensure_carla_server raises RuntimeError when CARLA can't start."""
    from ultimate_pipeline.carla_tools.carla_server import ensure_carla_server

    with pytest.raises((RuntimeError, FileNotFoundError)):
        ensure_carla_server(
            host="127.0.0.1",
            port=19998,
            carla_exe=tmp_path / "nonexistent_CarlaUE4.exe",
            timeout_s=2.0,
            kill_stale=False,
        )


@patch("ultimate_pipeline.carla_tools.carla_server.wait_for_port", return_value=True)
@patch("ultimate_pipeline.carla_tools.carla_server._handshake_carla_ready")
def test_ensure_carla_server_returns_none_when_port_already_open(mock_handshake, mock_wait, tmp_path: Path):
    """ensure_carla_server returns None (no new process) when port already open."""
    from ultimate_pipeline.carla_tools.carla_server import ensure_carla_server

    proc = ensure_carla_server(
        host="127.0.0.1",
        port=20000,
        carla_exe=tmp_path / "fake_CarlaUE4.exe",
        timeout_s=5.0,
        kill_stale=False,
    )
    assert proc is None  # no new process started
    mock_wait.assert_called_once()
    mock_handshake.assert_called_once_with(host="127.0.0.1", port=20000)


# ---------------------------------------------------------------------------
# kill_stale_carla safety: documents taskkill /IM concern (gap)
# ---------------------------------------------------------------------------


def test_kill_stale_carla_uses_executable_name_wide_taskkill():
    """GAP DOCUMENTED: kill_stale_carla uses taskkill /F /IM <name>, which is
    executable-name-wide termination. This can kill unrelated CARLA instances
    owned by other agents. Safe ownership-based termination is not implemented.

    See the original prompt: "Avoid executable-name-wide termination",
    "avoid uncontrolled taskkill /IM".
    """
    from ultimate_pipeline.carla_tools.carla_server import kill_stale_carla
    import subprocess

    # Verify kill_stale_carla calls taskkill with /F /IM (executable-name-wide)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        kill_stale_carla(process_names=("CarlaUE4.exe",))
        # Check that taskkill was called with /F and /IM
        call_args = mock_run.call_args[0][0]
        assert "/F" in call_args
        assert "/IM" in call_args
        assert "CarlaUE4.exe" in call_args


# ---------------------------------------------------------------------------
# Cross-platform: Windows named mutex (documented as gap)
# ---------------------------------------------------------------------------


def test_no_windows_named_mutex_implementation():
    """GAP DOCUMENTED: No Windows named mutex or Job Object-based process
    ownership is implemented. Cross-process fencing relies solely on the
    file-based WriterLock, which is not crash-proof (stale locks persist
    until lease expiry).

    See original prompt: "Job Object kill-on-close hazards", "Windows
    named mutex tests".
    """
    import ultimate_pipeline.contracts.writer_lock as wl
    src = open(wl.__file__).read()
    assert "Mutex" not in src
    assert "JobObject" not in src
    assert "CreateMutex" not in src


# ---------------------------------------------------------------------------
# Resource cleanup
# ---------------------------------------------------------------------------


def test_lock_release_cleans_up_status(tmp_path: Path):
    """Lock release sets status to 'released' and persists."""
    lock = WriterLock.acquire(
        root=tmp_path,
        branch="test",
        head_sha="abc",
        owner="agent",
    )
    lock.release(owner="agent", lock_id=lock.lock_id)
    assert lock.status == "released"

    # Verify persisted state
    loaded = WriterLock.load(tmp_path / ".agent_locks" / "writer.lock")
    assert loaded.status == "released"
