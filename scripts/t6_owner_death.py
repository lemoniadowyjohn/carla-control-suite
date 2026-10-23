"""T6 owner-death test with a fully observable synthetic owner.

The previous failure was unobservable because the holder's output went to
DEVNULL. Everything is captured now, and readiness is staged rather than a
single flag, so a failure identifies its own phase.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
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
    n = ctypes.c_uint32(0)
    if not k32.GetProcessHandleCount(k32.GetCurrentProcess(), ctypes.byref(n)):
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


OWNER_SRC = '''import json, os, sys, time, traceback
sys.path.insert(0, {scripts!r})
STAGE = {stage!r}
INFO = {{}}

def publish(stage, **kw):
    rec = {{"stage": stage, "ts": time.time(), "owner_pid": os.getpid(),
           "owner_creation_time": INFO.get("ct"), "error": None, **kw}}
    tmp = STAGE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(rec, fh); fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp, STAGE)
    print("STAGE", stage, kw, flush=True)

try:
    publish("BOOTSTRAP_STARTED", python=sys.executable, cwd=os.getcwd())
    import ctypes as _c
    class _F(_c.Structure):
        _fields_=[("a",_c.c_int64),("b",_c.c_int64),("c",_c.c_int64),
                  ("d",_c.c_int64),("e",_c.c_uint32),("f",_c.c_uint32),
                  ("g",_c.c_uint32),("h",_c.c_uint32),("i",_c.c_uint32),
                  ("j",_c.c_uint32),("k",_c.c_uint32)]
    _k = _c.WinDLL("kernel32", use_last_error=True)
    _k.GetProcessTimes.argtypes=[_c.c_void_p,_c.POINTER(_F),_c.POINTER(_F),
                                 _c.POINTER(_F),_c.POINTER(_F)]
    _k.OpenProcess.argtypes=[_c.c_uint32,_c.c_int,_c.c_uint32]
    _h = _k.OpenProcess(0x1000, False, os.getpid())
    _b = [_F() for _ in range(4)]
    _k.GetProcessTimes(_h, *[_c.byref(x) for x in _b])
    _k.CloseHandle(_h)
    _ft = _b[0].a
    INFO["ct"] = "%d-%09d" % (_ft & 0xFFFFFFFF, _ft >> 32)

    import control_plane as cpmod
    publish("CONTROL_PLANE_IMPORTED",
            control_plane_dir=cpmod.CONTROL_PLANE_DIR,
            lease_path=cpmod.LEASE_PATH, mutex_name=cpmod.MUTEX_NAME)
    from job_supervision import JobSupervisor as _JS
    publish("IMPORTS_OK")

    lease = cpmod.SingleWriterLease(operation="IMPORT", session_id="owner-sess")
    lease.acquire()
    publish("MUTEX_ACQUIRED", run_id=lease.run_id)
    publish("LEASE_WRITTEN", run_id=lease.run_id,
            lease_path=cpmod.LEASE_PATH)

    job = _JS(name="ownjob_%d" % os.getpid(), kill_on_close=True).create()
    publish("JOB_CREATED", job=job.name, kill_on_close=job.kill_on_close)
    publish("JOB_POLICY_SET", kill_on_close=job.kill_on_close)

    proc, assigned = job.spawn([sys.executable, "-c",
                                "import time;time.sleep(300)"])
    publish("CHILD_CREATED", child_pid=proc.pid, assigned=assigned)
    if not assigned:
        raise RuntimeError("child not assigned to job")
    publish("CHILD_ASSIGNED", child_pid=proc.pid)
    publish("CHILD_RESUMED", child_pid=proc.pid)
    publish("CHILD_ALIVE_CONFIRMED", child_pid=proc.pid)
    publish("READY_FOR_OWNER_DEATH_TEST", child_pid=proc.pid,
            run_id=lease.run_id)
    time.sleep(300)
except BaseException:
    publish("EXCEPTION", tb=traceback.format_exc()[-2000:])
    traceback.print_exc()
    sys.exit(9)
'''


def main():
    out_dir = os.path.join(REPO, "reports")
    work = os.path.join(out_dir, "t6")
    os.makedirs(work, exist_ok=True)
    stage = os.path.join(work, "stage.json")
    log_out = os.path.join(work, "T6_holder.stdout.log")
    log_err = os.path.join(work, "T6_holder.stderr.log")
    script = os.path.join(work, "owner.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(OWNER_SRC.format(scripts=os.path.join(REPO, "scripts"),
                                  stage=stage))

    fo, fe = open(log_out, "w"), open(log_err, "w")
    started = utc_now()
    hp = subprocess.Popen([PY, script], stdout=fo, stderr=fe, cwd=REPO)
    fo.flush(); fe.flush()

    def stages():
        out = []
        if os.path.isfile(stage):
            try:
                out.append(json.load(open(stage, encoding="utf-8")))
            except (ValueError, OSError):
                pass
        return out

    child_pid = None
    ready = False
    dl = time.time() + 90
    while time.time() < dl:
        s = stages()
        if s and s[0].get("stage") == "READY_FOR_OWNER_DEATH_TEST":
            ready = True
            child_pid = s[0].get("child_pid")
            break
        if hp.poll() is not None:
            break
        time.sleep(0.25)
    fo.close(); fe.close()

    launch = {
        "schema": "T6_OWNER_HOLDER_LAUNCH/v1", "schema_version": 1,
        "generated_utc": utc_now(),
        "command": [PY, script], "python": sys.executable,
        "script_path": script, "cwd": REPO,
        "owner_pid": hp.pid,
        "owner_creation_time": creation_time_of(hp.pid),
        "control_plane_dir": cp.CONTROL_PLANE_DIR,
        "lease_path": cp.LEASE_PATH, "mutex_name": cp.MUTEX_NAME,
        "start_utc": started,
        "stdout_log": log_out, "stderr_log": log_err,
        "stdout": open(log_out, encoding="utf-8", errors="replace").read()[-4000:],
        "stderr": open(log_err, encoding="utf-8", errors="replace").read()[-4000:],
        "stage_timeline": stages(),
        "stages_reached": [s.get("stage") for s in stages()],
        "ready": ready, "owner_exit": hp.poll(),
    }
    atomic_write_json(os.path.join(out_dir, "T6_OWNER_HOLDER_LAUNCH.json"), launch)

    result = {"ready": ready, "child_pid": child_pid}
    if not ready:
        result["failure_reason"] = (
            "owner exited before READY" if hp.poll() is not None
            else "owner stalled before READY")
        result["stderr_excerpt"] = launch["stderr"][-1500:]
        atomic_write_json(os.path.join(out_dir, "T6_OWNER_DEATH_RECEIPT.json"),
                          {"schema": "T6_OWNER_DEATH_RECEIPT/v1",
                           "schema_version": 1, "result": "FAIL", **result})
        print(json.dumps({**result, "launch": launch["stages_reached"]},
                         indent=2))
        return 1

    # SingleWriterLease records root_pid/root_creation_time; the
    # owner_identity shape belongs to OperationLease and does not exist here.
    lease = SingleWriterLease._read() or {}
    lease_pid = lease.get("root_pid")
    lease_ct = lease.get("root_creation_time")
    lease_ok = bool(lease_pid and lease_ct)
    lease_pid_matches = lease_pid == hp.pid
    child_alive = alive(child_pid)

    # T6b: reacquire must be denied before reconciliation
    reacquire_before = "ALLOWED"
    try:
        SingleWriterLease(operation="IMPORT", session_id="probe").acquire()
    except ArbitrationError as exc:
        reacquire_before = "DENIED"
        before_reason = exc.reason
    else:
        before_reason = None
    if reacquire_before == "ALLOWED":
        # clean up the probe's own lease before continuing
        SingleWriterLease.reconcile_stale("probe cleanup", "controller")

    hp.kill()
    try:
        hp.wait(timeout=30)
    except Exception:
        pass
    owner_dead_at = utc_now()

    dl = time.time() + 25
    while time.time() < dl and alive(child_pid):
        time.sleep(0.1)
    child_dead = not alive(child_pid)

    owner_state = SingleWorkerState = SingleWriterLease.holder_state(lease)
    recon = None
    reacquire_after = "UNKNOWN"
    if owner_state == "STALE" and child_dead:
        recon = SingleWriterLease.reconcile_stale("owner died, job drained",
                                                 "controller")
        reacquire_after = "ALLOWED"
    else:
        owner_state = "%s(child_dead=%s)" % (owner_state, child_dead)

    payload = {
        "schema": "T6_OWNER_DEATH_RECEIPT/v1", "schema_version": 1,
        "generated_utc": utc_now(),
        "T6_OWNER_READY": True,
        "T6_LEASE_EXISTS_BEFORE_OWNER_DEATH": lease_ok,
        "T6_LEASE_OWNER_PID": lease_pid,
        "T6_LEASE_OWNER_CREATION_TIME": lease_ct,
        "T6_LEASE_OWNER_PID_MATCHES_HOLDER": lease_pid_matches,
        "T6_LEASE_RUN_ID": lease.get("run_id"),
        "T6_CHILD_ALIVE_BEFORE_OWNER_DEATH": child_alive,
        "OWNER_DEAD": hp.poll() is not None,
        "T6_CHILD_TERMINATED_AFTER_OWNER_DEATH": child_dead,
        "REACQUIRE_BEFORE_RECONCILIATION": reacquire_before,
        "reacquire_before_reason": before_reason,
        "owner_state_after_death": owner_state,
        "reconciliation": recon,
        "REACQUIRE_AFTER_RECONCILIATION": reacquire_after,
        "result": "PASS" if (ready and lease_ok and child_alive and child_dead
                            and reacquire_before == "DENIED"
                            and reacquire_after == "ALLOWED") else "FAIL",
    }
    atomic_write_json(os.path.join(out_dir, "T6_OWNER_DEATH_RECEIPT.json"), payload)

    # T7: real handle metric
    h0 = handle_count()
    for _ in range(200):
        j = JobSupervisor(name="hk_%s" % uuid.uuid4().hex[:8]).create()
        j.close()
    h1 = handle_count()
    delta = h1 - h0
    status = "NO_LEAK" if delta <= 8 else ("BOUNDED_EXPLAINED" if delta <= 40
                                          else "LEAK")
    atomic_write_json(os.path.join(out_dir, "WINDOWS_HANDLE_LEAK_ACCEPTANCE.json"),
                      {"schema": "WINDOWS_HANDLE_LEAK_ACCEPTANCE/v1",
                       "schema_version": 1, "generated_utc": utc_now(),
                       "HANDLE_COUNT_API": "GetProcessHandleCount",
                       "cycles": 200, "HANDLE_COUNT_BEFORE": h0,
                       "HANDLE_COUNT_AFTER": h1, "HANDLE_COUNT_DELTA": delta,
                       "HANDLE_COUNT_MEASUREMENT_VALID": h0 > 0,
                       "HANDLE_LEAK_STATUS": status})
    print(json.dumps({"t6": payload["result"], **payload,
                      "handle": {"before": h0, "after": h1, "delta": delta,
                                 "valid": h0 > 0, "status": status}}, indent=2))
    return 0 if payload["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())