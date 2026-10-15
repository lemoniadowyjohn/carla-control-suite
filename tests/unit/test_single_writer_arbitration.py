"""Single-writer arbitration test suite (batch section 27).

The race test is a genuine test: ten independent OS processes attempt to acquire
the named mutex simultaneously and the suite asserts that exactly one wins. It
is not a simulation inside one interpreter, because a same-process test could
not detect the two-writers race that the NoSig incident exhibited.

Tests cover the required list:
  1 simultaneous acquisition race        9  owner crash
  2 stale lease with dead PID           10 read-only session denied mutation
  3 PID reused with different creation  11 ungoverned mutator detection
  4 live owner                         12 explicit handoff
  5 duplicate operation fingerprint     13 two imports cannot start
  6 unrelated operation conflict        14 import + cook cannot start
  7 run-scoped ImportSettings           15 import + build/link cannot start
  8 lease heartbeat
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import control_plane as cp  # noqa: E402
from control_plane import (  # noqa: E402
    ArbitrationError, MutexHandle, SingleWriterLease,
    compare_configuration, configuration_snapshot, detect_ungoverned_mutators,
    mutation_preflight, operation_fingerprint, run_scoped_settings_path,
    run_scoped_staging,
)


@pytest.fixture(autouse=True)
def isolated_control_plane(tmp_path, monkeypatch):
    """Point the control plane at a temp dir and a uniquely named mutex.

    Isolation matters twice over: the production mutex is Global-namespace and
    machine wide, so a test must not contend with the real one; and every test
    shares a single pytest process, so the in-process lease registry and the
    lease file must be reset between tests or one test's held lease would deny
    the next test for the wrong reason.
    """
    d = tmp_path / "cp"
    d.mkdir()
    monkeypatch.setattr(cp, "CONTROL_PLANE_DIR", str(d))
    monkeypatch.setattr(cp, "LEASE_PATH", str(d / "mutation_lease.json"))
    monkeypatch.setattr(cp, "LOG_PATH", str(d / "acquisition_log.jsonl"))
    name = "Local\\CARLA_Test_%s" % uuid.uuid4().hex
    monkeypatch.setattr(cp, "MUTEX_NAME", name)

    def _reset():
        cp._PROCESS_HELD.clear()
        if os.path.exists(cp.LEASE_PATH):
            os.unlink(cp.LEASE_PATH)

    _reset()
    yield d
    _reset()


def mklease(op="IMPORT", session="s1", **kw):
    return SingleWriterLease(operation=op, session_id=session, **kw)


# ---------------------------------------------------------------------------
# 1. simultaneous acquisition race, across ten real processes
# ---------------------------------------------------------------------------
RACE_WORKER = r"""
import json, os, sys
sys.path.insert(0, %(scripts)r)
import control_plane as cp
lease = cp.SingleWriterLease(%(op)r, %(session)r,
                              engine_root=%(engine)r,
                              project_root=%(engine)r,
                              content_root=%(content)r)
try:
    rec = lease.acquire()
    print("RESULT " + json.dumps({"status": "ACQUIRED", "run_id": rec["run_id"],
                                  "verdict": rec["mutex_verdict"]}))
except cp.ArbitrationError as exc:
    print("RESULT " + json.dumps({"status": "DENIED", "reason": exc.reason}))
"""


def test_01_simultaneous_acquisition_race(tmp_path):
    """Ten independent processes; exactly one ACQUIRED, nine DENIED_CONFLICT."""
    scripts = tmp_path / "workers"
    scripts.mkdir()
    engines = str(tmp_path / "ue")
    contents = str(tmp_path / "content")
    os.makedirs(engines)
    os.makedirs(contents)

    procs = []
    for i in range(10):
        worker = scripts / ("w%d.py" % i)
        worker.write_text(RACE_WORKER % {
            "scripts": os.path.join(REPO, "scripts"),
            "op": "IMPORT", "session": "s%d" % i,
            "engine": engines, "content": contents})
        procs.append(subprocess.Popen(
            [sys.executable, str(worker)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env={**os.environ,
                 "CARLA_CONTROL_PLANE_DIR": cp.CONTROL_PLANE_DIR,
                 "CARLA_MUTEX_NAME": cp.MUTEX_NAME}))

    results = []
    for p in procs:
        out, err = p.communicate(timeout=180)
        line = next((l for l in out.splitlines() if l.startswith("RESULT ")), None)
        if line is None:
            pytest.fail("worker produced no result: %s / %s" % (out, err))
        results.append(json.loads(line[len("RESULT "):]))

    acquired = [r for r in results if r["status"] == "ACQUIRED"]
    denied = [r for r in results if r["status"] == "DENIED"]

    assert len(acquired) == 1, \
        "expected exactly 1 ACQUIRED, got %d (%s)" % (
            len(acquired), [r.get("reason") for r in results])
    assert len(denied) == 9, "expected 9 DENIED, got %d" % len(denied)

    receipt = {
        "schema": "SINGLE_WRITER_RACE_TEST/v1",
        "schema_version": 1,
        "mutex_name": cp.MUTEX_NAME,
        "contenders": 10,
        "acquired": len(acquired),
        "denied": len(denied),
        "winner_run_id": acquired[0]["run_id"],
        "winner_mutex_verdict": acquired[0]["verdict"],
        "never_two_owners": len(acquired) == 1,
        "results": results,
    }
    out_path = os.path.join(REPO, "reports", "SINGLE_WRITER_RACE_TEST.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(receipt, fh, indent=2)
    assert receipt["never_two_owners"] is True


# ---------------------------------------------------------------------------
# 2/3/4. lease state
# ---------------------------------------------------------------------------
def test_02_stale_lease_with_dead_pid():
    lease = mklease()
    rec = lease.acquire()
    rec["root_pid"] = 999999999
    rec["root_creation_time"] = "1999-01-01T00:00:00.0000000Z"
    with open(cp.LEASE_PATH, "w", encoding="utf-8") as fh:
        json.dump(rec, fh)
    assert SingleWriterLease.holder_state(rec) == "STALE"


def test_03_pid_reused_with_different_creation_time():
    """Same PID, different creation time => the recorded owner is gone."""
    lease = mklease()
    rec = lease.acquire()
    rec["root_pid"] = os.getpid()
    rec["root_creation_time"] = "2000-01-01T00:00:00.0000000Z"
    with open(cp.LEASE_PATH, "w", encoding="utf-8") as fh:
        json.dump(rec, fh)
    assert SingleWriterLease.holder_state(rec) == "STALE"


def test_04_live_owner_detected():
    lease = mklease()
    lease.acquire()
    holder = SingleWriterLease._read()
    assert SingleWriterLease.holder_state(holder) == "LIVE"


def test_live_owner_blocks_second_session():
    a = mklease(session="s1")
    a.acquire()
    b = mklease(session="s2")
    with pytest.raises(ArbitrationError) as exc:
        b.acquire()
    assert exc.value.reason in ("DUPLICATE_OPERATION_ALREADY_RUNNING",
                                "OPERATION_CLASS_CONFLICT")


# ---------------------------------------------------------------------------
# 5. duplicate operation fingerprint
# ---------------------------------------------------------------------------
def test_05_duplicate_operation_fingerprint(tmp_path):
    a = mklease(session="s1", engine_root=str(tmp_path / "ue"),
                content_root=str(tmp_path / "content"))
    a.acquire()
    b = mklease(session="s2", engine_root=str(tmp_path / "ue"),
                content_root=str(tmp_path / "content"))
    assert (a.fingerprint["fingerprint"] == b.fingerprint["fingerprint"])
    with pytest.raises(ArbitrationError) as exc:
        b.acquire()
    assert exc.value.reason == "DUPLICATE_OPERATION_ALREADY_RUNNING"


def test_different_operation_has_different_fingerprint(tmp_path):
    a = mklease(op="IMPORT", engine_root=str(tmp_path / "ue"))
    b = mklease(op="COOK", engine_root=str(tmp_path / "ue"))
    assert a.fingerprint["fingerprint"] != b.fingerprint["fingerprint"]


# ---------------------------------------------------------------------------
# 6/13/14/15. conflict matrix
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("first,second", [
    ("IMPORT", "IMPORT"),
    ("IMPORT", "COOK"),
    ("IMPORT", "BUILD"),
    ("COOK", "COOK"),
    ("BUILD", "BUILD"),
])
def test_06_exclusive_operation_pairs(first, second, tmp_path):
    a = mklease(op=first, session="s1", engine_root=str(tmp_path / "ue"))
    a.acquire()
    b = mklease(op=second, session="s2",
                engine_root=str(tmp_path / "ue") + ("x" if second == "BUILD" else ""))
    with pytest.raises(ArbitrationError):
        b.acquire()


def test_13_two_imports_cannot_start(tmp_path):
    a = mklease(op="IMPORT", session="a")
    a.acquire()
    b = mklease(op="IMPORT", session="b")
    with pytest.raises(ArbitrationError) as exc:
        b.acquire()
    assert exc.value.reason == "DUPLICATE_OPERATION_ALREADY_RUNNING"


def test_14_import_plus_cook_cannot_start(tmp_path):
    a = mklease(op="IMPORT", session="a")
    a.acquire()
    b = mklease(op="COOK", session="b")
    with pytest.raises(ArbitrationError) as exc:
        b.acquire()
    assert exc.value.reason in ("OPERATION_CLASS_CONFLICT",
                                "DUPLICATE_OPERATION_ALREADY_RUNNING",
                                "PROCESS_ALREADY_HOLDS_LEASE")


def test_15_import_plus_build_cannot_start(tmp_path):
    a = mklease(op="IMPORT", session="a")
    a.acquire()
    b = mklease(op="BUILD", session="b")
    with pytest.raises(ArbitrationError) as exc:
        b.acquire()
    assert exc.value.reason in ("OPERATION_CLASS_CONFLICT",
                                "DUPLICATE_OPERATION_ALREADY_RUNNING",
                                "PROCESS_ALREADY_HOLDS_LEASE")


# ---------------------------------------------------------------------------
# 7. run-scoped import settings
# ---------------------------------------------------------------------------
def test_07_run_scoped_import_settings(tmp_path):
    root = str(tmp_path / "staging")
    a = run_scoped_settings_path(root, "runA")
    b = run_scoped_settings_path(root, "runB")
    assert a != b
    assert "runA" in a and "runB" in b
    with open(a, "w") as fh:
        fh.write('{"tiles": ["a"]}')
    with open(b, "w") as fh:
        fh.write('{"tiles": ["b"]}')
    assert open(a).read() != open(b).read()
    # Mutating B must not change A.
    with open(b, "w") as fh:
        fh.write('{"tiles": ["MUTATED"]}')
    assert open(a).read() == '{"tiles": ["a"]}'


def test_run_scoped_staging_isolated(tmp_path):
    a = run_scoped_staging(str(tmp_path), "runA")
    b = run_scoped_staging(str(tmp_path), "runB")
    assert a != b and os.path.isdir(a) and os.path.isdir(b)


# ---------------------------------------------------------------------------
# 8. heartbeat
# ---------------------------------------------------------------------------
def test_08_lease_heartbeat():
    lease = mklease()
    lease.acquire()
    first = lease.heartbeat()["heartbeat_utc"]
    time.sleep(0.01)
    second = lease.heartbeat()["heartbeat_utc"]
    assert second >= first
    assert SingleWriterLease._read()["status"] == "RUNNING"


def test_heartbeat_after_release_is_refused():
    lease = mklease()
    lease.acquire()
    lease.release()
    with pytest.raises(ArbitrationError):
        lease.heartbeat()


# ---------------------------------------------------------------------------
# 9. owner crash
# ---------------------------------------------------------------------------
def test_09_owner_crash_releases_mutex():
    """An owner that dies holding the mutex must not deadlock the next waiter.

    Both halves matter. While the owner is alive the next waiter must be
    DENIED; once the owner dies the mutex must become acquirable again. A mutex
    that never released on death would wedge every future run on this machine.
    """
    env = {**os.environ, "CARLA_CONTROL_PLANE_DIR": cp.CONTROL_PLANE_DIR,
           "CARLA_MUTEX_NAME": cp.MUTEX_NAME}
    scripts = os.path.join(REPO, "scripts")

    acquire_snippet = (
        "import sys; sys.path.insert(0, {scripts!r}); "
        "import control_plane as cp; h = cp.MutexHandle(); "
        "print(h.try_acquire(cp.MUTEX_NAME)); "
        "import time; time.sleep(120)").format(scripts=scripts)

    probe_snippet = (
        "import sys; sys.path.insert(0, {scripts!r}); "
        "import control_plane as cp; h = cp.MutexHandle(); "
        "print(h.try_acquire(cp.MUTEX_NAME))").format(scripts=scripts)

    holder = subprocess.Popen([sys.executable, "-c", acquire_snippet], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True)
    try:
        time.sleep(4)
        probe = subprocess.run([sys.executable, "-c", probe_snippet], env=env,
                               capture_output=True, text=True, timeout=120)
        assert probe.stdout.strip() == "DENIED_CONFLICT", (
            "a live owner must deny the next waiter, got %r"
            % probe.stdout.strip())
    finally:
        holder.kill()
        holder.wait(timeout=60)

    time.sleep(2)
    after = subprocess.run([sys.executable, "-c", probe_snippet], env=env,
                           capture_output=True, text=True, timeout=120)
    assert after.stdout.strip().startswith("ACQUIRED"), (
        "after owner death the mutex must be acquirable, got %r"
        % after.stdout.strip())


# ---------------------------------------------------------------------------
# 10. read-only session
# ---------------------------------------------------------------------------
def test_10_read_only_session_denied_mutation():
    lease = mklease(read_only=True)
    with pytest.raises(ArbitrationError) as exc:
        lease.acquire()
    assert exc.value.reason == "READ_ONLY_SESSION_MODE_FORBIDS_MUTATION"


def test_read_only_preflight_denies_governed_command():
    res = mutation_preflight(
        "UE4Editor-Cmd.exe proj -run=ImportAssets", "ro-session", read_only=True)
    assert res["verdict"] == "DENY"
    assert res["reason"] == "READ_ONLY_SESSION_MODE"


def test_read_only_allows_audit_command():
    res = mutation_preflight("git status", "ro-session", read_only=True)
    assert res["verdict"] == "ALLOW"


# ---------------------------------------------------------------------------
# 11. ungoverned mutator detection
# ---------------------------------------------------------------------------
def test_11_ungoverned_mutator_detection():
    inventory = {"mutators": [
        {"pid": 111, "identity_key": "111|t", "name": "UE4Editor-Cmd.exe",
         "operation_class": "IMPORT", "command_line": "x"},
        {"pid": 222, "identity_key": "222|t", "name": "UE4Editor.exe",
         "operation_class": "COOK", "command_line": "y"},
    ]}
    res = detect_ungoverned_mutators(inventory, "s1")
    assert res["UNGOVERNED_MUTATOR_DETECTED"] is True
    assert len(res["ungoverned"]) == 2
    assert res["action"] == "ALERT_AND_BLOCK_NEW_MUTATIONS__DO_NOT_KILL"


def test_governed_mutator_is_not_flagged():
    lease = mklease(session="s1")
    lease.acquire()
    holder = SingleWriterLease._read()
    inventory = {"mutators": [
        {"pid": holder["root_pid"],
         "identity_key": "%d|%s" % (holder["root_pid"], holder["root_creation_time"]),
         "name": "UE4Editor-Cmd.exe", "operation_class": "IMPORT",
         "command_line": "x"}]}
    res = detect_ungoverned_mutators(inventory, "s1")
    assert res["UNGOVERNED_MUTATOR_DETECTED"] is False


# ---------------------------------------------------------------------------
# 12. explicit handoff
# ---------------------------------------------------------------------------
def test_12_explicit_handoff():
    a = mklease(session="s1")
    a.acquire()
    # A new session may NOT take over implicitly.
    b = mklease(session="s2")
    with pytest.raises(ArbitrationError):
        b.acquire()
    a.release("COMPLETE")
    c = mklease(session="s2")
    rec = c.acquire()
    assert rec["session_id"] == "s2"
    c.release()


def test_handoff_requires_reconciliation_when_owner_died():
    a = mklease(session="s1")
    rec = a.acquire()
    rec["root_pid"] = 999999999
    with open(cp.LEASE_PATH, "w", encoding="utf-8") as fh:
        json.dump(rec, fh)
    out = SingleWriterLease.reconcile_stale("owner died", "s2")
    assert out["action"] == "RECONCILED"
    assert out["prior_state"] == "STALE"
    assert os.path.isfile(cp.LEASE_PATH + ".reconciled.json")


# ---------------------------------------------------------------------------
# 15b. mutation preflight requires a lease
# ---------------------------------------------------------------------------
def test_preflight_denies_without_lease():
    res = mutation_preflight("UE4Editor-Cmd.exe p -run=cook", "s9")
    assert res["verdict"] == "DENY"


def test_preflight_allows_with_own_lease():
    lease = mklease(session="s1")
    lease.acquire()
    res = mutation_preflight("UE4Editor-Cmd.exe p -run=ImportAssets", "s1")
    assert res["verdict"] == "ALLOW"
    lease.release()


def test_preflight_denies_another_sessions_lease():
    a = mklease(session="s1")
    a.acquire()
    res = mutation_preflight("UE4Editor-Cmd.exe p -run=cook", "s2")
    assert res["verdict"] == "DENY"
    a.release()


# ---------------------------------------------------------------------------
# 19. configuration snapshot
# ---------------------------------------------------------------------------
def test_configuration_mutation_detected():
    before = {"files": {"Import.py": "aaa", "DefaultEngine.ini": "bbb"}}
    same = compare_configuration(before, configuration_snapshot.__wrapped__() if False else {
        "files": {"Import.py": "aaa", "DefaultEngine.ini": "bbb"}})
    assert same["CONFIGURATION_MUTATED_DURING_RUN"] is False
    assert same["run_authoritative"] is True

    changed = compare_configuration(before, {"files": {"Import.py": "ZZZ",
                                                       "DefaultEngine.ini": "bbb"}})
    assert changed["CONFIGURATION_MUTATED_DURING_RUN"] is True
    assert changed["run_authoritative"] is False


# ---------------------------------------------------------------------------
# release semantics
# ---------------------------------------------------------------------------
def test_release_removes_lease_and_frees_mutex():
    a = mklease(session="s1")
    a.acquire()
    assert os.path.isfile(cp.LEASE_PATH)
    a.release()
    assert not os.path.exists(cp.LEASE_PATH)
    b = mklease(session="s2")
    assert b.acquire()["session_id"] == "s2"
    b.release()
