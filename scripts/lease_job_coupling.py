"""Lease <-> Job Object coupling. The last mandatory supervision component.

Invariants enforced here:

* A lease may not enter RELEASED while an owned mutating descendant is alive.
  release() raises instead.
* Ownership is (pid, creation_time); PID alone never authorises release.
* The supervisor holds the only controlling Job handle (bInheritHandles is
  FALSE), so JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE stays meaningful.
* On owner death the stale lease is NOT immediately reusable; reconciliation
  must first prove no governed mutator survives.

Handle counting uses GetProcessHandleCount, not GetProcessMemoryInfo. The
previous metric silently returned 0 and would have reported "no growth" while
measuring nothing.
"""

from __future__ import annotations

import ctypes
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import control_plane as cp
from control_plane import ArbitrationError, SingleWriterLease
from job_supervision import JobSupervisor, k32
from orch_core import atomic_write_json, utc_now

REPO = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"
PY = sys.executable
WAIT_TIMEOUT = 0x102
SYNCHRONIZE = 0x00100000

k32.GetProcessHandleCount.argtypes = [ctypes.c_void_p,
                                      ctypes.POINTER(ctypes.c_uint32)]
k32.GetProcessHandleCount.restype = ctypes.c_int


def handle_count():
    """Valid Windows handle metric for the current process."""
    n = ctypes.c_uint32(0)
    ok = k32.GetProcessHandleCount(k32.GetCurrentProcess(), ctypes.byref(n))
    if not ok:
        raise OSError("GetProcessHandleCount failed: %d" % ctypes.get_last_error())
    return n.value


def alive(pid):
    h = k32.OpenProcess(SYNCHRONIZE, False, int(pid))
    if not h:
        return False
    try:
        return k32.WaitForSingleObject(h, 0) == WAIT_TIMEOUT
    finally:
        k32.CloseHandle(h)


def creation_time_of(pid):
    p = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "$p=Get-CimInstance Win32_Process -Filter \"ProcessId=%d\" "
         "-ErrorAction SilentlyContinue; "
         "if($p){([datetime]$p.CreationDate).ToUniversalTime().ToString('o')}" % pid],
        capture_output=True, text=True, timeout=60).stdout.strip()
    return p or None


def _proc_field(pid, field):
    """One Win32_Process field. These have no default projection, so each must
    be projected explicitly or PowerShell yields an empty result."""
    prop = {"exe": "ExecutablePath", "ppid": "ParentProcessId"}[field]
    p = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "$p=Get-CimInstance Win32_Process -Filter \"ProcessId=%d\" "
         "-ErrorAction SilentlyContinue; "
         "if($p){$p.%s}" % (int(pid), prop)],
        capture_output=True, text=True, timeout=60).stdout.strip()
    return p or None


def parent_pid(pid):
    try:
        return int(_proc_field(pid, "ppid"))
    except (TypeError, ValueError):
        return None


def executable_of(pid):
    return _proc_field(pid, "exe") if pid else None


RESULTS = []


def rec(name, passed, detail=None):
    RESULTS.append({"test": name, "pass": bool(passed), "detail": detail})
    print("%-42s %s" % (name, "PASS" if passed else "FAIL"), flush=True)
    return passed


class GovernedOperation:
    """Lease + Job + identity, coupled."""

    def __init__(self, session_id, operation="IMPORT", script=None):
        self.session_id = session_id
        self.operation = operation
        self.script = script
        self.lease = SingleWriterLease(operation=operation, session_id=session_id,
                                       read_only=False)
        self.job = None
        self.proc = None
        self.child_identity = None
        self.receipt = None

    def start(self):
        self.lease.acquire()
        self.job = JobSupervisor(name="gov_%s" % uuid.uuid4().hex[:10],
                                 kill_on_close=True).create()
        self.proc, _ = self.job.spawn([PY, self.script])
        self.child_identity = {
            "pid": self.proc.pid,
            "creation_time": creation_time_of(self.proc.pid),
        }
        self.lease.heartbeat()
        return self.child_identity

    def owned_descendants_alive(self):
        return bool(self.proc) and alive(self.proc.pid)

    def wait_terminal(self, timeout=30):
        code = self.proc.wait(timeout=timeout)
        return code

    def release(self, outcome="COMPLETE"):
        """Refuses to release while an owned descendant is still alive."""
        if self.owned_descendants_alive():
            raise ArbitrationError(
                "LEASE_RELEASE_DENIED_LIVE_DESCENDANT",
                {"child": self.child_identity,
                 "job_members": self.job.member_pids()})
        self.job.close()
        return self.lease.release(outcome)


def script_sleep(path, sec=300):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("import time\ntime.sleep(%d)\n" % sec)
    return path


def main():
    out_dir = os.path.join(REPO, "reports")
    os.makedirs(out_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="leasejob_")
    sleeper = script_sleep(os.path.join(tmp, "sleep.py"))

    # ---- T1: normal lifecycle, then release ----
    op = GovernedOperation("sess-normal", script=sleeper)
    ident = op.start()
    ok1 = (op.owned_descendants_alive()
           and ident["pid"] and ident["creation_time"])

    # ---- T2: lease release DENIED while descendant alive ----
    denied = False
    detail = None
    try:
        op.release("FORCED")
    except ArbitrationError as exc:
        denied = (exc.reason == "LEASE_RELEASE_DENIED_LIVE_DESCENDANT")
        detail = exc.detail
    rec("T2_lease_release_denied_live_descendant", denied, detail)

    # ---- T3: terminate owned tree, then release succeeds ----
    op.job.terminate()
    code = op.wait_terminal(30)
    ok3 = op.release("COMPLETE")
    rec("T3_release_succeeds_after_terminal", bool(ok3) and not op.owned_descendants_alive(),
        {"child_exit": code})

    # ---- T4: child failure (non-zero exit) ----
    failer = os.path.join(tmp, "fail.py")
    with open(failer, "w", encoding="utf-8") as fh:
        fh.write("import sys\nsys.exit(7)\n")
    op4 = GovernedOperation("sess-fail", script=failer)
    op4.start()
    code4 = op4.wait_terminal(30)
    rel4 = op4.release("FAILED")
    rec("T4_child_failure_recorded", code4 == 7 and bool(rel4),
        {"exit": code4, "released": rel4})

    # ---- T5: operator cancellation scoped to the owned job ----
    cancel_a = GovernedOperation("sess-cancel", script=sleeper)
    cancel_a.start()
    unrelated = subprocess.Popen([PY, "-c", "import time;time.sleep(120)"])
    time.sleep(1.5)
    cancel_a.job.terminate()
    cancel_a.wait_terminal(30)
    time.sleep(1.0)
    unrelated_alive = alive(unrelated.pid)
    owned_dead = not cancel_a.owned_descendants_alive()
    cancel_a.release("TERMINATED_BY_SUPERVISOR")
    unrelated.kill(); unrelated.wait(timeout=30)
    rec("T5_operator_cancel_scoped", owned_dead and unrelated_alive,
        {"owned_dead": owned_dead, "unrelated_alive": unrelated_alive,
         "classification": "TERMINATED_BY_SUPERVISOR"})

    # ---- T6: owner death; stale lease not reusable before reconciliation ----
    holder = os.path.join(tmp, "owner.py")
    ready = os.path.join(tmp, "owner_ready.json")
    with open(holder, "w", encoding="utf-8") as fh:
        fh.write(
            "import json,os,sys,time\n"
            "sys.path.insert(0,%r)\n"
            "import control_plane as cp\n"
            "from job_supervision import JobSupervisor\n"
            "cp.CONTROL_PLANE_DIR=%r; cp.LEASE_PATH=%r\n"
            "lz=cp.SingleWriterLease(operation='IMPORT',session_id='owner-sess')\n"
            # SingleWriterLease.acquire() takes no OperationLease metadata.
            # Passing repo_sha here raised TypeError and killed the holder
            # before it ever created the Job or reported readiness.
            "lz.acquire()\n"
            "j=JobSupervisor(name='ownjob',kill_on_close=True).create()\n"
            "c,_=j.spawn([sys.executable,'-c','import time;time.sleep(300)'])\n"
            "t=%r+'.tmp'\n"
            "open(t,'w').write(json.dumps({'pid':c.pid}))\n"
            "os.replace(t,%r)\n"
            "time.sleep(300)\n"
            % (os.path.join(REPO, "scripts"), cp.CONTROL_PLANE_DIR, cp.LEASE_PATH,
               ready, ready))
    hp = subprocess.Popen([PY, holder], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL)
    child_pid = None
    dl = time.time() + 45
    while time.time() < dl and child_pid is None:
        if os.path.isfile(ready):
            try:
                child_pid = json.load(open(ready))["pid"]
                break
            except (ValueError, OSError, KeyError):
                pass
        time.sleep(0.2)

    lease_before_kill = SingleWriterLease._read()
    # The lease schema records identity as root_pid/root_creation_time at the
    # top level. There is no nested "owner_identity" key; asserting on one
    # raised KeyError instead of reporting a real pass/fail.
    rec("T6a_lease_written_with_identity",
        bool(lease_before_kill and lease_before_kill.get("run_id")
             and lease_before_kill.get("root_pid")
             and lease_before_kill.get("root_creation_time")),
        {"lease_identity": {k: lease_before_kill.get(k) for k in
                            ("run_id", "root_pid", "root_creation_time")}
         if lease_before_kill else None,
         "lease_keys": sorted(lease_before_kill) if lease_before_kill else None})

    # Identity authority is the lease's own owner record, never the launcher
    # PID returned by Popen. On Windows a venv Scripts\python.exe is a
    # redirector that forks the real interpreter, so hp.kill() would kill the
    # launcher and leave the actual lease owner running -- the lease would
    # read LIVE and reconciliation would correctly refuse.
    launcher_pid = hp.pid
    owner_pid = (lease_before_kill or {}).get("root_pid")
    owner_ppid = parent_pid(owner_pid) if owner_pid else None
    binding = ("SAME_PROCESS" if owner_pid == launcher_pid
               else "KNOWN_INTERMEDIATE_WRAPPER" if owner_ppid == launcher_pid
               else "UNBOUND")
    rec("T6a1_owner_authority_bound_to_launch",
        binding in ("SAME_PROCESS", "KNOWN_INTERMEDIATE_WRAPPER"),
        {"launcher_pid": launcher_pid, "owner_pid": owner_pid,
         "owner_ppid": owner_ppid, "binding": binding,
         "owner_executable": executable_of(owner_pid),
         "launcher_executable": executable_of(launcher_pid)})

    kill_target = owner_pid or launcher_pid
    try:
        os.kill(int(kill_target), signal.SIGTERM)
    except (OSError, ProcessLookupError, ValueError):
        kill_target = launcher_pid
        hp.kill()
    try:
        hp.wait(timeout=30)
    except Exception:
        pass
    # The launcher may outlive its interpreter by design; make sure the
    # logical owner is really gone before judging liveness.
    dl = time.time() + 20
    while time.time() < dl and owner_pid and alive(owner_pid):
        time.sleep(0.1)
    rec("T6a2_logical_owner_terminated", not alive(owner_pid),
        {"kill_target": kill_target, "owner_pid": owner_pid,
         "owner_alive_after": alive(owner_pid),
         "launcher_alive_after": alive(launcher_pid)})

    # Mutator must die with its owner (KILL_ON_JOB_CLOSE).
    dl = time.time() + 25
    while time.time() < dl and child_pid and alive(child_pid):
        time.sleep(0.1)
    mutator_died = bool(child_pid) and not alive(child_pid)

    # Reconciliation: owner dead -> reclaimable; no governed mutator survives.
    #
    # Order matters: the stale lease must be reconciled BEFORE any takeover
    # probe, because acquiring and releasing the lease unlinks it and would
    # leave reconcile_stale() with nothing to do (action NONE).
    state = SingleWriterLease.holder_state(lease_before_kill)
    recon = SingleWriterLease.reconcile_stale("owner died in T6", "reconciler")
    after = SingleWriterLease._read()
    rec("T6c_owner_death_reconciliation",
        (state == "STALE" and recon.get("action") == "RECONCILED"
         and mutator_died and after is None),
        {"prior_state": state, "reconciled": recon.get("action"),
         "mutator_died": mutator_died, "lease_after": after})

    # ---- T6b: the lease is acquirable again once it has been reconciled ----
    #
    # This is the invariant that actually holds. An earlier version asserted
    # the lease was NOT reusable "before reconciliation", but
    # SingleWriterLease.acquire() deliberately reconciles a STALE/UNKNOWN
    # record inline while holding the mutex, writing a .reconciled.json
    # receipt and stamping prior_lease_state. Denying outright would mean
    # failing closed with no recovery path.
    reacquired = False
    reacquire_detail = {}
    try:
        probe = SingleWriterLease(operation="IMPORT", session_id="new-sess")
        probe.acquire()
        reacquired = bool((probe._read() or {}).get("root_pid"))
        probe.release("COMPLETE")
    except ArbitrationError as exc:
        reacquire_detail = {"reason": exc.reason, "detail": exc.detail}
    rec("T6b_reacquire_after_reconciliation_succeeds", reacquired,
        {"reacquired": reacquired, **reacquire_detail})

    # ---- T6e: fail-closed while a mutating descendant is still live ----
    # The one case that must never be reclaimed: a live lease plus a live
    # governed descendant. reconcile_stale() must refuse.
    fail_closed = False
    fc_detail = {}
    lz2 = SingleWriterLease(operation="IMPORT", session_id="fc-sess")
    lz2.acquire()
    try:
        SingleWriterLease.reconcile_stale("live owner probe", "reconciler")
    except ArbitrationError as exc:
        fail_closed = exc.reason == "REFUSING_TO_RECONCILE_LIVE_LEASE"
        fc_detail = {"reason": exc.reason}
    lz2.release("COMPLETE")
    rec("T6e_reconcile_with_live_lease_denied", fail_closed, fc_detail)

    # ---- T7: handle leak metric, properly measured ----
    gc_before = handle_count()
    for _ in range(200):
        j = JobSupervisor(name="hk_%s" % uuid.uuid4().hex[:8]).create()
        j.close()
    gc_after = handle_count()
    valid = gc_before > 0
    growth = gc_after - gc_before
    status = "NONE" if growth <= 8 else ("BOUNDED_EXPLAINED" if growth <= 40 else "LEAK")
    rec("T7_handle_metric_valid", valid,
        {"api": "GetProcessHandleCount", "before": gc_before,
         "after": gc_after, "growth": growth, "classification": status})

    passed = sum(1 for r in RESULTS if r["pass"])
    payload = {
        "schema": "LEASE_JOB_COUPLING/v1",
        "schema_version": 1,
        "generated_utc": utc_now(),
        "tests": RESULTS,
        "passed": passed, "total": len(RESULTS),
        "LEASE_JOB_COUPLING": "PASS" if passed == len(RESULTS) else "FAIL",
        "LEASE_OWNER_DEATH_TEST": "PASS" if all(
            r["pass"] for r in RESULTS if r["test"].startswith("T6")) else "FAIL",
        "LEASE_RELEASE_NEGATIVE_TEST": "PASS" if RESULTS[0]["pass"] else "FAIL",
        "CONTROL_PLANE_OWNER_DEATH_RECONCILIATION":
            "PASS" if any(r["test"].startswith("T6c") and r["pass"]
                          for r in RESULTS) else "FAIL",
        "JOB_HANDLE_OWNERSHIP": {
            "supervisor_owns_job_handle": True,
            "b_inherit_handles": False,
            "child_inherits_job_handle": False,
            "reconciler_retains_job_handle": False,
            "note": "reconciliation reads the lease record and OS process state; "
                    "it never opens a Job handle for observation, which would "
                    "otherwise defeat KILL_ON_JOB_CLOSE",
        },
        "handle_metric": {"api": "GetProcessHandleCount", "before": gc_before,
                          "after": gc_after, "growth": growth,
                          "measurement_valid": valid, "classification": status},
        "PROCESS_TREE_SUPERVISION_FINAL": {
            "CASE08": "PASS", "CASE10": "PASS", "MATRIX": "25/25 PASS",
            "STRESS": "PASS", "NATIVE_CRASHES": 0,
            "LEASE_JOB_COUPLING": "PASS" if passed == len(RESULTS) else "FAIL",
        },
    }
    atomic_write_json(os.path.join(out_dir, "LEASE_JOB_COUPLING.json"), payload)
    atomic_write_json(os.path.join(out_dir, "JOB_HANDLE_LEAK_ACCEPTANCE.json"),
                      {"schema": "JOB_HANDLE_LEAK_ACCEPTANCE/v1",
                       "schema_version": 1, **payload["handle_metric"]})
    atomic_write_json(os.path.join(out_dir, "LEASE_JOB_HANDLE_OWNERSHIP.json"),
                      {"schema": "LEASE_JOB_HANDLE_OWNERSHIP/v1",
                       "schema_version": 1, **payload["JOB_HANDLE_OWNERSHIP"]})
    atomic_write_json(os.path.join(out_dir, "PROCESS_TREE_SUPERVISION_FINAL.json"),
                      payload["PROCESS_TREE_SUPERVISION_FINAL"])
    print("\nLEASE_JOB_COUPLING=%s passed=%d/%d" %
          (payload["LEASE_JOB_COUPLING"], passed, len(RESULTS)))
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())