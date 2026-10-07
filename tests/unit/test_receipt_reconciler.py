"""Stale-RUNNING receipt reconciliation + supervisor-death handshake matrix.

Synthetic only. Covers Batch 17 sections 3 (5 reconciliation cases),
6/7 (case-08 deterministic handshake), 8 (case-10 identity semantics),
10 (lease-job coupling).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import uuid

import pytest

from ultimate_pipeline.governance.single_writer import (
    job_supervision,
    lease_store as leases,
    preflight,
    receipt_reconciler as reconciler,
)

TEST_MUTEX2 = f"CarlaGovOpsTest2_{uuid.uuid4().hex[:8]}"
ROOTS = {"engine_root": "E:/eng", "project_root": "P:/proj",
         "content_root": "P:/proj/Content"}


@pytest.fixture()
def lease_env(tmp_path):
    leases.set_dir_override(str(tmp_path / "leases"))
    yield tmp_path / "leases"
    leases.set_dir_override(None)


def _pid_dead(pid: int) -> bool:
    try:
        import ctypes

        SYNCHRONIZE = 0x00100000
        h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not h:
            return True
        try:
            return ctypes.windll.kernel32.WaitForSingleObject(h, 0) == 0
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    except Exception:
        return True


def _receipt(state="RUNNING", pid=424242):
    return {"state": state, "child_pid": pid, "label": "ImportAssets_003"}


def test_running_live_process_stays_running() -> None:
    import ctypes

    me = int(ctypes.windll.kernel32.GetCurrentProcessId())
    assert reconciler.reconcile_supervision_receipt(
        _receipt("RUNNING", me))["verdict"] == "RUNNING"


def test_running_dead_success_witness() -> None:
    out = reconciler.reconcile_supervision_receipt(
        _receipt("RUNNING", 2 ** 30),
        {"pid": 2 ** 30, "creation_time": "x", "exit_code_dec": 0})
    assert out["verdict"] == "SUCCESS"


def test_running_dead_nonzero_witness() -> None:
    out = reconciler.reconcile_supervision_receipt(
        _receipt("RUNNING", 2 ** 30),
        {"pid": 2 ** 30, "creation_time": "x",
         "exit_code_dec": 0xC0000005})
    assert out["verdict"] == "ACCESS_VIOLATION"


def test_running_dead_no_witness() -> None:
    out = reconciler.reconcile_supervision_receipt(
        _receipt("RUNNING", 2 ** 30), None)
    assert out["verdict"] == "UNKNOWN_TERMINATION_RECONCILIATION_REQUIRED"


def test_witness_pid_reuse_mismatch() -> None:
    out = reconciler.reconcile_supervision_receipt(
        _receipt("RUNNING", 2 ** 30),
        {"pid": 999999, "creation_time": "x", "exit_code_dec": 0})
    assert out["verdict"] == "UNKNOWN_TERMINATION_RECONCILIATION_REQUIRED"


def test_witness_creation_mismatch() -> None:
    r = _receipt("RUNNING", 2 ** 30)
    r["process_creation_time"] = "2026-01-01T00:00:00Z"
    out = reconciler.reconcile_supervision_receipt(
        r, {"pid": 2 ** 30, "creation_time": "2026-02-02T00:00:00Z",
            "exit_code_dec": 0})
    assert out["verdict"] == "UNKNOWN_TERMINATION_RECONCILIATION_REQUIRED"


# Case 08 analog: the SUPERVISOR OWNS the job handle. External kill of the
# supervisor closes its handle -> KILL_ON_CLOSE takes the owned tree.
# Handshake carries worker identity; nothing is discovered by racy scans.
SUPERVISOR_PROG = (
    "import os, subprocess, sys, time; "
    "sys.path.insert(0, r'{root}'); "
    "from ultimate_pipeline.governance.single_writer import job_supervision as J; "
    "marker = sys.argv[1]; "
    "job = J.create_job(); "
    "w = J.spawn_in_job(job, [sys.executable, '-c', "
    "'import time; time.sleep(120)']); "
    "r = J.resolve_executor_pid(job, w.pid, timeout_s=20); "
    "open(marker, 'w').write(str(w.pid) + ' ' + str(r.get('executor_pid'))); "
    "time.sleep(600)"
)


def _repo_root() -> str:
    from pathlib import Path as _P

    return str(_P(__file__).resolve().parents[2])


def test_case08_supervisor_death_handshake(tmp_path) -> None:
    if os.name != "nt":
        pytest.skip("Windows-only")
    marker = tmp_path / "handshake.txt"
    unrelated = subprocess.Popen([sys.executable, "-c",
                                  "import time; time.sleep(120)"])
    try:
        sup = subprocess.Popen(
            [sys.executable, "-c",
             SUPERVISOR_PROG.format(root=_repo_root()), str(marker)])
        try:
            # Handshake: launcher pid + handshake-verified executor pid.
            launcher = worker = None
            for _ in range(60):
                time.sleep(0.5)
                if marker.exists():
                    launcher, worker = (
                        int(x) for x in marker.read_text().split())
                    break
            assert launcher is not None, "handshake never arrived"
            assert worker, "executor never resolved"
            assert not _pid_dead(worker), "worker already dead pre-kill"
            # Externally terminate ONLY the supervisor (handle owner).
            # KILL_ON_CLOSE must take the whole owned tree.
            sup.terminate()
            assert sup.wait(timeout=60) is not None
            for _ in range(60):
                time.sleep(0.5)
                if _pid_dead(worker):
                    break
            assert _pid_dead(worker), "worker survived supervisor death"
        finally:
            try:
                sup.kill()
            except Exception:
                pass
        assert unrelated.poll() is None
    finally:
        unrelated.kill()


# Case 10 analog: job accounting vs PID identity.
def test_case10_identity_not_membership(tmp_path) -> None:
    if os.name != "nt":
        pytest.skip("Windows-only")
    job = job_supervision.create_job()
    try:
        child = job_supervision.spawn_in_job(
            job, [sys.executable, "-c", "import time; time.sleep(0.5)"])
        pid = child.pid
        child.wait(timeout=30)
        # wait() does NOT release the handle (Popen has no close(); the
        # dead PID stays observable while held). Close explicitly: same
        # lesson as the multiprocessing-handle finding, now pinned.
        import ctypes as _ct

        _ct.windll.kernel32.CloseHandle(child._handle)
        before = leases.process_creation_time(pid)
        assert before is None
        # A future process reusing this PID would carry a DIFFERENT
        # creation time; identity equivalence must be refused.
        assert not leases.owner_alive(pid, "2026-10-06T01:19:40.524957Z")
    finally:
        job.close()


# Lease-job coupling: no release while descendants live.
def test_lease_job_coupling(lease_env) -> None:
    if os.name != "nt":
        pytest.skip("Windows-only")
    res = preflight.acquire_operation("IMPORT", ROOTS, "PkgJ", "semJ")
    assert res.allowed, res
    try:
        job = job_supervision.create_job()
        try:
            child = job_supervision.spawn_in_job(
                job, [sys.executable, "-c",
                      "import time; time.sleep(120)"])
            time.sleep(2.0)
            assert child.pid in job.member_pids()
            early = job_supervision.release_lease_after_drain(
                res.lease, res.mutex, job,
                preflight.release_operation, "TEST_DONE", timeout_s=3)
            assert early["released"] is False  # child alive: no release
            assert leases.read_current() is not None  # lease still held
            job.terminate_owned(9)
            late = job_supervision.release_lease_after_drain(
                res.lease, res.mutex, job,
                preflight.release_operation, "TEST_DONE", timeout_s=30)
            assert late["released"] is True
            assert leases.read_current() is None
            res.mutex.release()
        finally:
            job.close()
    except Exception:
        try:
            preflight.release_operation(res.lease, res.mutex, "TEST_ABORT")
        except Exception:
            pass
        raise
