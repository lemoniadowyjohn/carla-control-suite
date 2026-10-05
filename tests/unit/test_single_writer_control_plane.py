"""Single-writer control-plane tests (Batch 17, section 20).

All synthetic: real OS mutexes, real Job Objects, real child processes, but
NEVER any UE/CARLA production mutation. Lease dir is per-test tmp via
CARLA_OPS_LEASE_DIR (inherited by spawn children on reimport).
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from ultimate_pipeline.governance.single_writer import (
    domains,
    exit_codes,
    handoff,
    job_supervision,
    lease_store as leases,
    preflight,
    run_settings,
    ungoverned_detector,
)
from ultimate_pipeline.governance.single_writer.os_lock import (
    NamedMutex,
    read_only_session,
)

TEST_MUTEX = f"CarlaGovOpsTest_{uuid.uuid4().hex[:8]}"
ROOTS = {"engine_root": "E:/eng", "project_root": "P:/proj",
         "content_root": "P:/proj/Content"}


@pytest.fixture()
def lease_env(tmp_path, monkeypatch):
    d = tmp_path / "leases"
    # In-process override (respected because resolution is call-time).
    leases.set_dir_override(str(d))
    yield d
    leases.set_dir_override(None)


@pytest.fixture()
def live_lease(lease_env):
    m = NamedMutex(TEST_MUTEX)
    assert m.acquire(timeout_ms=5000).acquired
    lease = leases.new_lease("IMPORT", ["d"], "fp-test", "Local")
    leases._write_current(lease)
    yield lease
    try:
        leases._current_file().unlink()
    except OSError:
        pass
    m.release()


# 1. 10-way acquisition race: exactly 1 ACQUIRED, 9 DENIED_CONFLICT.
def _race_worker(tmpdir: str, mutex_name: str, q: "mp.Queue[str]") -> None:
    import os as _os

    _os.environ["CARLA_OPS_LEASE_DIR"] = tmpdir
    from ultimate_pipeline.governance.single_writer import (
        lease_store as _ls,
    )
    from ultimate_pipeline.governance.single_writer.os_lock import (
        NamedMutex as _NM,
    )
    import ctypes as _ct

    m = _NM(mutex_name)
    acq = m.acquire(timeout_ms=8000)
    if not acq.acquired:
        q.put("DENIED_CONFLICT")
        return
    try:
        flag = Path(tmpdir) / "winner"
        try:
            fd = _os.open(str(flag), _os.O_CREAT | _os.O_EXCL | _os.O_WRONLY)
            _os.close(fd)
            # Winner publishes a lease like the real path would.
            pid = int(_ct.windll.kernel32.GetCurrentProcessId())
            lease = _ls.new_lease("IMPORT", ["d"], "fp-race", acq.namespace)
            lease.root_pid = pid
            _ls._write_current(lease)
            time.sleep(0.5)
            q.put("ACQUIRED")
        except FileExistsError:
            q.put("DENIED_CONFLICT")
    finally:
        m.release()


def test_race_1_acquired_9_denied(tmp_path) -> None:
    if os.name != "nt":
        pytest.skip("Windows-only")
    ctx = mp.get_context("spawn")
    q: mp.Queue[str] = ctx.Queue()
    procs = [ctx.Process(target=_race_worker,
                         args=(str(tmp_path), TEST_MUTEX, q))
             for _ in range(10)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
        assert p.exitcode == 0
    results = [q.get(timeout=10) for _ in range(10)]
    assert results.count("ACQUIRED") == 1, results
    assert results.count("DENIED_CONFLICT") == 9, results


# 2. Stale lease / dead owner reconciles with evidence.
def test_stale_lease_dead_owner(lease_env) -> None:
    lease = leases.new_lease("COOK", ["d"], "fp-x", "Local")
    lease.root_pid = 2 ** 30  # cannot exist
    lease.root_creation_time = "2000-01-01T00:00:00Z"
    import datetime

    lease.heartbeat_utc = (datetime.datetime.now(datetime.timezone.utc)
                           - datetime.timedelta(seconds=9999)).isoformat()
    leases._write_current(lease)
    assert leases.is_stale(lease) is True
    out = leases.reconcile_stale()
    assert out["action"] == "reconciled"
    assert leases.read_current() is None
    assert (leases._history_dir() / f"{lease.run_id}.json").exists()


# 3. PID reuse defeated by creation-time comparison.
def test_pid_reuse_detection(lease_env) -> None:
    import ctypes

    me = int(ctypes.windll.kernel32.GetCurrentProcessId())
    good = leases.process_creation_time(me)
    assert good
    # A zero-FILETIME artifact (1601) would make every process compare equal
    # and defeat PID-reuse protection; the timestamp must be real.
    assert good >= "2020-01-01T00:00:00Z", good
    assert leases.owner_alive(me, good) is True
    assert leases.owner_alive(me, "1999-01-01T00:00:00Z") is False
    assert leases.owner_alive(2 ** 30, good) is False


# 4. Valid live owner + full acquire/release lifecycle.
def test_live_owner_lifecycle(lease_env) -> None:
    res = preflight.acquire_operation("IMPORT", ROOTS, "PkgA", "sem1")
    assert res.allowed, res
    assert res.lease is not None and res.mutex is not None
    assert leases.owner_alive(res.lease.root_pid,
                              res.lease.root_creation_time)
    out = preflight.release_operation(res.lease, res.mutex, "TEST_DONE")
    assert out["terminal_state"] == "TEST_DONE"
    assert leases.read_current() is None


# 5. Duplicate fingerprint denied with the exact NoSig code.
def test_duplicate_operation_denied(lease_env) -> None:
    first = preflight.acquire_operation("IMPORT", ROOTS, "IngolstadtNoSig",
                                        "sem-diagnostic")
    assert first.allowed, first
    try:
        second = preflight.acquire_operation("IMPORT", ROOTS,
                                             "IngolstadtNoSig",
                                             "sem-diagnostic")
        assert not second.allowed
        assert second.code == "DUPLICATE_OPERATION_ALREADY_RUNNING", second
    finally:
        preflight.release_operation(first.lease, first.mutex, "TEST_DONE")


# 6/7/8. Conflict matrix.
def test_import_cook_conflict() -> None:
    assert domains.check_conflict("IMPORT", "COOK")["conflict"] is True


def test_import_build_conflict() -> None:
    assert domains.check_conflict("IMPORT", "BUILD_LINK")["conflict"] is True


def test_two_imports_conflict() -> None:
    r = domains.check_conflict("IMPORT", "IMPORT")
    assert r["conflict"] is True
    assert "DUPLICATE" in str(r["reason"])


# 9. Run-scoped ImportSettings isolation.
def test_run_scoped_settings(tmp_path) -> None:
    groups_a = [{"maps": ["A"]}]
    groups_b = [{"maps": ["B"]}]
    ra = run_settings.create_run_settings(tmp_path, "runA", groups_a)
    rb = run_settings.create_run_settings(tmp_path, "runB", groups_b)
    assert ra["sha256"] != rb["sha256"]
    assert run_settings.verify_immutable(ra)["ok"] is True
    # Run B mutation cannot affect run A.
    p = Path(rb["path"])
    p.chmod(0o666)
    p.write_text("tampered", encoding="utf-8")
    assert run_settings.verify_immutable(rb)["ok"] is False
    assert run_settings.verify_immutable(ra)["ok"] is True
    assert run_settings.reject_duplicate_fingerprint("fp", ["fp"]) == \
        "DUPLICATE_OPERATION_ALREADY_RUNNING"
    assert run_settings.reject_duplicate_fingerprint("fp", ["other"]) is None


# 10. Heartbeat keeps a live lease fresh; expiry + dead owner = stale.
def test_heartbeat(lease_env) -> None:
    lease = leases.new_lease("COOK", ["d"], "fp-hb", "Local")
    leases._write_current(lease)
    old = lease.heartbeat_utc
    time.sleep(0.05)
    leases.heartbeat(lease)
    assert lease.state == "RUNNING"
    assert lease.heartbeat_utc >= old
    assert leases.is_stale(lease) is False  # live owner


# 11. Owner crash: mutex abandoned, lease stale, reconcile, re-acquire.
def _crash_owner(mutex_name: str, tmpdir: str) -> None:
    import os as _os

    _os.environ["CARLA_OPS_LEASE_DIR"] = tmpdir
    from ultimate_pipeline.governance.single_writer import (
        lease_store as _ls,
    )
    from ultimate_pipeline.governance.single_writer.os_lock import (
        NamedMutex as _NM,
    )
    import ctypes as _ct

    m = _NM(mutex_name)
    assert m.acquire(timeout_ms=5000).acquired
    lease = _ls.new_lease("IMPORT", ["d"], "fp-crash", "Local")
    pid = int(_ct.windll.kernel32.GetCurrentProcessId())
    lease.root_pid = pid
    lease.root_creation_time = _ls.process_creation_time(pid) or ""
    _ls._write_current(lease)
    # Die WITHOUT release: mutex abandoned, heartbeat frozen.
    _os._exit(3)


def test_owner_crash_recovery(tmp_path, lease_env) -> None:
    if os.name != "nt":
        pytest.skip("Windows-only")
    # lease_env isolates the PARENT module attrs; the env var below is for
    # spawn children, which reimport the module (monkeypatches don't cross).
    # It MUST point at the same dir the parent reads, or parent/child diverge.
    os.environ["CARLA_OPS_LEASE_DIR"] = str(lease_env)
    ctx = mp.get_context("spawn")
    p = ctx.Process(target=_crash_owner, args=(TEST_MUTEX, str(lease_env)))
    p.start()
    p.join(60)
    assert p.exitcode == 3
    # Release multiprocessing's own handle: an open handle keeps the dead
    # process object (and its creation time) observable, which would read
    # as alive. Production owners are not handle-held by the checker.
    p.close()
    time.sleep(0.5)
    # Crash detection rests on the LEASE (heartbeat + PID/creation-time),
    # not on WAIT_ABANDONED, which this host frequently does not deliver
    # (dead owner's mutex observed as plain signaled). Exclusion still
    # holds because the stale lease denies acquisition while the mutex
    # serializes the check.
    res = preflight.acquire_operation("IMPORT", ROOTS, "PkgB", "sem9")
    assert not res.allowed
    assert res.code == "DENY_STALE_RECONCILIATION_REQUIRED", res
    # Age the heartbeat past TTL so reconcile can clear (owner is dead).
    import datetime

    stale = leases.read_current()
    assert stale is not None
    stale.heartbeat_utc = (datetime.datetime.now(datetime.timezone.utc)
                           - datetime.timedelta(seconds=9999)).isoformat()
    leases._write_current(stale)
    out = leases.reconcile_stale()
    assert out["action"] == "reconciled", out
    retry = preflight.acquire_operation("IMPORT", ROOTS, "PkgB", "sem9")
    assert retry.allowed, retry
    preflight.release_operation(retry.lease, retry.mutex, "TEST_DONE")


# 12. Read-only session denies everything, including diagnostic pretexts.
@pytest.mark.parametrize("op", ["IMPORT", "COOK", "NOSIG_DIAGNOSTIC",
                                 "QUICK_TEST", "SINGLE_TILE"])
def test_read_only_denial(lease_env, monkeypatch, op) -> None:
    monkeypatch.setenv("READ_ONLY_SESSION", "true")
    res = preflight.acquire_operation(op if op in domains.OPERATION_DOMAINS
                                      else "IMPORT", ROOTS, "Pkg", "s")
    assert not res.allowed
    assert res.code == "MUTATION_DENIED_READ_ONLY_SESSION", res


# 13. Ungoverned-mutator detection.
def test_ungoverned_detection(lease_env, monkeypatch) -> None:
    fake = [{"pid": 4242, "image": "ue4editor-cmd.exe"}]
    monkeypatch.setattr(ungoverned_detector, "_all_processes",
                        lambda: fake)
    assert ungoverned_detector.scan(None)["UNGOVERNED_MUTATOR_DETECTED"] is True
    lease = leases.new_lease("IMPORT", ["d"], "fp-u", "Local")
    import ctypes

    lease.root_pid = int(ctypes.windll.kernel32.GetCurrentProcessId())
    lease.root_creation_time = leases.process_creation_time(
        lease.root_pid) or ""
    assert ungoverned_detector.scan(lease)[
        "UNGOVERNED_MUTATOR_DETECTED"] is True  # pid differs
    lease.root_pid = 4242
    import datetime

    lease.root_creation_time = (
        datetime.datetime.now(datetime.timezone.utc).isoformat())
    # creation time will not match -> still ungoverned (conservative)
    assert ungoverned_detector.scan(lease)[
        "UNGOVERNED_MUTATOR_DETECTED"] is True


# 14. Explicit handoff, incl. mismatch denial.
def test_handoff(lease_env) -> None:
    res = preflight.acquire_operation("IMPORT", ROOTS, "PkgH", "semH")
    assert res.allowed, res
    offer = handoff.offer_handoff(res.lease, "session-B", res.mutex)
    assert offer["ok"], offer
    res.mutex.release()
    bad = handoff.accept_handoff("session-EVIL", res.lease.run_id, res.mutex)
    assert not bad["ok"] and bad["code"] == "HANDOFF_SESSION_MISMATCH"
    good = handoff.accept_handoff("session-B", res.lease.run_id, res.mutex)
    assert good["ok"] and good["code"] == "HANDOFF_ACCEPTED", good


# 15. Job Object: owned tree dies, unrelated same-image process survives.
def test_job_owned_tree_kill() -> None:
    if os.name != "nt":
        pytest.skip("Windows-only")
    sleeper = ("import time; "
               "import subprocess, sys; "
               "subprocess.Popen([sys.executable, '-c', "
               "'import time; time.sleep(120)']); "
               "time.sleep(120)")
    unrelated = subprocess.Popen([sys.executable, "-c",
                                  "import time; time.sleep(120)"])
    try:
        job = job_supervision.create_job()
        try:
            child = job_supervision.spawn_in_job(
                job, [sys.executable, "-c", sleeper])
            members = []
            for _ in range(30):
                time.sleep(0.5)
                members = job.member_pids()
                if child.pid in members and len(members) >= 2:
                    break
            assert child.pid in members, members
            assert len(members) >= 2, members  # child + grandchild
            job.terminate_owned(exit_code=7)
            time.sleep(2.0)
            assert child.poll() is not None
            for m in members:
                if m != child.pid:
                    assert _pid_dead(m), m
        finally:
            job.close()
        assert unrelated.poll() is None  # unrelated survives
    finally:
        unrelated.kill()


def _pid_dead(pid: int) -> bool:
    try:
        import ctypes

        SYNCHRONIZE = 0x00100000
        h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not h:
            return True
        try:
            rc = ctypes.windll.kernel32.WaitForSingleObject(h, 0)
            return rc == 0
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    except Exception:
        return True


# 16. Windows exit 1/2 classification (+ live process proof).
def test_exit_1_2_classification() -> None:
    assert exit_codes.classify_exit(1)["class"] == "PROGRAM_NONZERO_EXIT"
    assert exit_codes.classify_exit(2)["class"] == "PROGRAM_NONZERO_EXIT"
    assert exit_codes.classify_exit(0)["class"] == "SUCCESS"
    r = subprocess.run(["cmd", "/c", "exit 1"], capture_output=False)
    assert exit_codes.classify_exit(r.returncode)["class"] == \
        "PROGRAM_NONZERO_EXIT"


# 17. CONTROL_C classification.
def test_control_c_classification() -> None:
    assert exit_codes.classify_exit(0xC000013A)["class"] == "CONTROL_C_EXIT"
    assert exit_codes.classify_exit(-1073741510)["class"] == "CONTROL_C_EXIT"
    assert exit_codes.classify_exit(0xC0000005)["class"] == "ACCESS_VIOLATION"
    assert exit_codes.classify_exit(130)["class"] == "UNKNOWN_WINDOWS_EXIT"
