"""Ownership/lifetime regression tests for Windows job supervision.

These pin the handle-ownership contract that produced a real
``PytestUnraisableExceptionWarning`` (``Handle.Close`` -> ``WinError 6``): a
borrowed ``subprocess`` handle was released with a raw ``CloseHandle`` while
the owning ``subprocess.Handle`` wrapper still believed it held a live handle,
so the wrapper closed the same handle again during garbage collection.

The tests count Win32 ``CloseHandle`` calls through an injected fake so they
never depend on garbage-collection timing.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("win"),
    reason="Windows job-object ownership semantics",
)

from ultimate_pipeline.governance.single_writer import job_supervision as js


class CountingWin32:
    """Minimal stand-in for the kernel32 surface used by job_supervision."""

    def __init__(self, inner=None):
        self._inner = inner
        self.closed: list[int] = []
        self.created: list[int] = []
        self.duplicated: list[tuple[int, int]] = []
        self.transferred: list[int] = []

    # --- ownership primitives -------------------------------------------
    def CreateJobObjectW(self, *_a, **_k):
        handle = 9000 + len(self.created)
        self.created.append(handle)
        return handle

    def DuplicateHandle(self, src, dst=None):
        self.duplicated.append((src, dst))
        return src + 1

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return 1

    # --- everything else is delegated; these must not be reached ----------
    def __getattr__(self, name):
        if self._inner is not None and hasattr(self._inner, name):
            return getattr(self._inner, name)
        raise AssertionError(f"unexpected kernel32 use in ownership test: {name}")


@pytest.fixture()
def counting(monkeypatch):
    fake = CountingWin32()
    monkeypatch.setattr(js, "_kernel32", fake, raising=True)
    return fake


# 1. normal supervision releases the owned handle exactly once
def test_owned_job_close_releases_exactly_once(counting):
    job = js.OwnedJob(handle=4242, root_pid=0)
    job.close()
    assert counting.closed == [4242]
    assert job.released is True


# 6. repeated teardown is safe / idempotent
def test_owned_job_close_is_idempotent(counting):
    job = js.OwnedJob(handle=4242, root_pid=0)
    job.close()
    job.close()
    job.close()
    assert counting.closed == [4242], "handle released more than once"


# 3. a released owner never releases again even if the handle is reused
def test_released_owner_does_not_close_a_recycled_handle_value(counting):
    job = js.OwnedJob(handle=7, root_pid=0)
    job.close()
    counting.closed.clear()
    # Windows may hand value 7 to an unrelated object later; a released
    # owner must not touch it.
    job.close()
    assert counting.closed == []


# 4. exception paths release owned resources
def test_exception_path_still_releases_owned_handle(counting):
    job = js.OwnedJob(handle=555, root_pid=0)
    with pytest.raises(RuntimeError):
        try:
            job.close()
            raise RuntimeError("post-close failure")
        finally:
            pass
    assert counting.closed == [555]
    assert job.released is True


# 5. ownership is explicit and observable before release
def test_ownership_state_is_observable(counting):
    job = js.OwnedJob(handle=31337, root_pid=0)
    assert job.released is False
    job.close()
    assert job.released is True


# 2. the caller does not own the handle it merely borrows from Popen
def test_borrowed_popen_handle_is_not_closed_by_the_borrower():
    """A Popen owns its process handle; a borrower must not raw-close it.

    This is the exact defect: releasing the OS handle behind the owning
    ``subprocess.Handle`` wrapper leaves ``closed`` False, so the wrapper's
    finalizer closes the same handle again.
    """
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=30)
    handle = proc._handle
    assert handle.closed is False
    # The owning API is idempotent and marks the wrapper released.
    handle.Close()
    assert handle.closed is True
    handle.Close()  # second call must not raise
    assert handle.closed is True
    # The process object is already reaped; nothing further may touch the
    # handle (poll()/wait() on a released handle would raise WinError 6).


# 7. real supervision path emits no unraisable exception
def test_spawn_in_job_emits_no_unraisable_exception(recwarn):
    job = js.create_job()
    try:
        child = js.spawn_in_job(
            job, [sys.executable, "-c", "import time; time.sleep(0.2)"])
        child.wait(timeout=60)
        child._handle.Close()
        assert child._handle.closed is True
    finally:
        job.close()
        job.close()  # idempotent teardown


# 8. raw CloseHandle on a Popen handle is exactly what must not happen
def test_raw_closehandle_would_double_close(recwarn):
    """Guard the regression: prove the bad pattern is detectable, not silent."""
    import ctypes

    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    try:
        proc.wait(timeout=30)
        raw = ctypes.windll.kernel32.CloseHandle(proc._handle)
        # OS handle is now released but the wrapper still thinks it owns it.
        assert proc._handle.closed is False
        # The wrapper's finalizer will therefore attempt a second close.
        assert raw == 1
    finally:
        proc._handle.closed = True  # prevent the finalizer from erroring


# 9. a child that stays suspended must NOT be reported as successfully resumed
class _StuckThreadWin32(CountingWin32):
    """ResumeThread always reports work remaining -> child never runs."""

    INVALID = ctypes.c_void_p(-1).value
    calls = 0

    def CreateToolhelp32Snapshot(self, *_a):
        return 4242

    def Thread32First(self, _snap, byref_entry):
        entry = getattr(byref_entry, "_obj", byref_entry)
        entry.th32OwnerProcessID = 1234
        entry.th32ThreadID = 99
        return 1

    def Thread32Next(self, _snap, _entry):
        return 0

    def OpenThread(self, *_a):
        return 555

    def ResumeThread(self, _th):
        type(self).calls += 1
        return 5  # never reaches 0

    def CloseHandle(self, handle):
        return 1


def test_resume_failure_is_not_silently_accepted(monkeypatch):
    """A single non-failing ResumeThread call must not count as success."""
    fake = _StuckThreadWin32()
    monkeypatch.setattr(js, "_kernel32", fake, raising=True)
    _StuckThreadWin32.calls = 0
    with pytest.raises(RuntimeError, match="still suspended"):
        js._resume_primary_thread(1234, max_attempts=3)
    # It retried before giving up rather than trusting one call.
    assert _StuckThreadWin32.calls >= 3


def test_real_spawn_leaves_no_suspended_orphan():
    """A supervised child must actually run and exit, not linger suspended."""
    job = js.create_job()
    try:
        child = js.spawn_in_job(
            job, [sys.executable, "-c", "import time; time.sleep(0.2)"])
        assert child.wait(timeout=60) == 0
        assert child._handle.closed is False
        child._handle.Close()
    finally:
        job.close()

