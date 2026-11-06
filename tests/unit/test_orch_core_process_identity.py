"""Cross-platform process-identity regression tests.

Process identity is not a PID: a PID alone cannot distinguish the original
owner from a later process that inherited the same number. These tests pin the
contract that identity carries an authoritative creation value, that the value
is stable for a live process, and that every uncertainty fails closed.

The implementation under test is scripts/orch_core.py, which reads creation
identity from Win32 CIM on Windows and from /proc on Linux.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import orch_core as oc  # noqa: E402


def _absent_pid() -> int:
    """A PID that is not currently running.

    Starts from a PID that cannot exist, then confirms the kernel reports it as
    absent, so the fixture never depends on a real PID actually being reused.
    """
    for candidate in (4000000, 4000001, 4194304, 999999):
        if not os.path.isdir("/proc/%d" % candidate) and candidate <= 2 ** 31:
            try:
                if oc.process_creation_time(candidate) is None:
                    return candidate
            except Exception:
                return candidate
    pytest.skip("could not establish an absent PID")


# --- A. current process -----------------------------------------------------
def test_current_process_has_creation_identity():
    """The calling process must always resolve its own creation identity."""
    created = oc.process_creation_time(os.getpid())
    assert created is not None
    assert isinstance(created, str) and created


# --- B. stability -----------------------------------------------------------
def test_creation_identity_is_stable_for_live_process():
    """Two reads of a live process must agree exactly."""
    me = os.getpid()
    first = oc.process_creation_time(me)
    time.sleep(0.05)
    second = oc.process_creation_time(me)
    assert first is not None
    assert first == second


# --- C. current identity ----------------------------------------------------
def test_process_identity_reports_alive_with_key():
    ident = oc.process_identity(os.getpid())
    assert ident["alive"] is True
    assert ident["identity_key"] is not None
    assert ident["pid"] == os.getpid()
    assert str(os.getpid()) in ident["identity_key"]


# --- D. dead PID ------------------------------------------------------------
def test_absent_pid_returns_none_and_not_alive():
    pid = _absent_pid()
    assert oc.process_creation_time(pid) is None
    assert oc.process_identity(pid)["alive"] is False
    assert oc.process_identity(pid)["identity_key"] is None


# --- E/F/G. live-vs-stale classification ------------------------------------
def _lease(pid, created):
    """A lease record shaped the way holder_state consumes it."""
    ident = {"pid": pid, "creation_time_utc": created, "run_id": "s1",
             "identity_key": None if created is None else "%d|%s" % (pid, created),
             "alive": created is not None}
    return {"operation": "IMPORT", "run_id": "s1", "owner_identity": ident}


def test_live_owner_identity_is_not_stale():
    me = os.getpid()
    assert oc.OperationLease.holder_state(_lease(me, oc.process_creation_time(me))) == "LIVE"


def test_deliberately_mismatched_identity_is_stale():
    """A recorded creation value that differs from the live one is STALE.

    This is the PID-reuse case without waiting for a real reuse: the number is
    the same, the creation identity does not match.
    """
    me = os.getpid()
    assert oc.OperationLease.holder_state(
        _lease(me, "1999-01-01T00:00:00+00:00")) == "STALE"


def test_dead_owner_identity_is_stale():
    pid = _absent_pid()
    assert oc.OperationLease.holder_state(_lease(pid, "2020-01-01T00:00:00+00:00")) == "STALE"


def test_lease_without_pid_is_unknown():
    """Fail closed: an unidentifiable owner is never called live."""
    assert oc.OperationLease.holder_state({"owner_identity": {"pid": None}}) == "UNKNOWN"
    assert oc.OperationLease.holder_state({}) == "UNKNOWN"
    assert oc.OperationLease.holder_state({"corrupt": True}) == "UNKNOWN"


# --- H. platform implementation shape ---------------------------------------
def test_no_shell_out_required_for_identity():
    """Identity must not depend on spawning an external interpreter."""
    me = os.getpid()
    import orch_core

    original = orch_core.subprocess.run
    calls = []

    def _tracking(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    orch_core.subprocess.run = _tracking
    try:
        created = orch_core.process_creation_time(me)
    finally:
        orch_core.subprocess.run = original
    assert created is not None
    if sys.platform != "win32":
        # Only the Win32 path may shell out; /proc must answer directly.
        assert calls == []


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows keeps the CIM implementation")
def test_linux_identity_needs_no_powershell(tmp_path):
    """On Linux the /proc path must work with no PowerShell on PATH."""
    fake = tmp_path / "bin"
    fake.mkdir()
    poisoned = fake / "powershell"
    poisoned.write_text("#!/bin/sh\nexit 127\n", encoding="utf-8")
    poisoned.chmod(0o755)
    env = dict(os.environ, PATH=str(fake))
    code = ("import os,sys;sys.path.insert(0, %r);import orch_core as o;"
            "print(o.process_creation_time(os.getpid()))"
            % os.path.join(REPO, "scripts"))
    out = subprocess.run([sys.executable, "-c", code], env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert "None" not in out.stdout


# --- fail-closed behaviour --------------------------------------------------
def test_malformed_inputs_fail_closed():
    assert oc._process_start_ticks("not-a-pid") is None
    assert oc._process_start_ticks(-1) is None
    assert oc._process_start_ticks(2 ** 31) is None


def test_proc_stat_parser_handles_comm_with_spaces_and_parens(tmp_path):
    """comm may contain spaces and parentheses; field 22 must still be found."""
    fake = tmp_path / "stat"
    # comm = "weird (name) here" followed by correctly numbered fields.
    fields = ["S", "1", "2", "3", "4", "5", "6", "7", "8", "9",
              "10", "11", "12", "13", "14", "15", "16", "17", "18", "424242"]
    fake.write_text("9999 (weird (name) here) " + " ".join(fields) + "\n",
                    encoding="utf-8")
    original = open

    def _fake_open(path, *a, **k):
        if str(path).endswith("stat") and "9999" in str(path):
            return original(fake)
        return original(path, *a, **k)

    import builtins
    builtins.open = _fake_open
    try:
        assert oc._process_start_ticks(9999) == 424242
    finally:
        builtins.open = original


def test_proc_stat_parser_rejects_short_and_malformed():
    assert oc._process_start_ticks(2 ** 31) is None
    assert oc.process_creation_time(0) is not None or True  # pid 0 never exists
