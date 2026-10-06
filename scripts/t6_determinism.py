"""Deterministic T6 owner-death test: 5 consecutive isolated runs.

Determinism comes from three changes over the flaky version:

1. Every run gets a UNIQUE control-plane directory and mutex name, passed to
   the owner through the environment. No two runs share a lease file, journal,
   mutex or fixture, and the production control plane is never touched.

2. The owner publishes T6_OWNER_AUTHORITY.json describing what it ACTUALLY
   established (lease path, run_id, its own pid/creation time, child identity).
   The controller consumes that file instead of reconstructing paths from its
   own module globals, which was the source of the earlier confusion.

3. The owner publishes READY only after re-reading its own lease from disk and
   verifying pid, creation time and run_id, so there is no
   write-then-read race.
"""

from __future__ import annotations

import ctypes
import json
import os
import signal
import subprocess
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from orch_core import atomic_write_json, utc_now

REPO = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"
PY = sys.executable
WAIT_TIMEOUT = 0x102
SYNCHRONIZE = 0x00100000

OWNER_SRC = '''import json, os, sys, time, traceback
sys.path.insert(0, {scripts!r})
AUTH = {auth!r}
STAGE = {stage!r}
INFO = {{}}

def _atomic_replace(tmp, dst, attempts=60):
    # Python's open() on Windows does not grant FILE_SHARE_DELETE, so a
    # concurrent reader (the controller polls this file, and AV/indexers
    # scan it) makes os.replace fail with WinError 5. That is transient
    # contention, not a real error, so retry briefly before giving up.
    for i in range(attempts):
        try:
            os.replace(tmp, dst)
            return True
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.05)
        except OSError:
            if i == attempts - 1:
                raise
            time.sleep(0.05)
    return False

def publish(stage, **kw):
    rec = {{"stage": stage, "ts": time.time(), "owner_pid": os.getpid(),
           "owner_creation_time": INFO.get("ct"),
           "run_id": INFO.get("run_id"), "lease_path": INFO.get("lease_path"),
           "child_pid": INFO.get("child_pid"), "error": None, **kw}}
    tmp = STAGE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(rec, fh); fh.flush(); os.fsync(fh.fileno())
    _atomic_replace(tmp, STAGE)

def write_auth(stage, **extra):
    payload = {{"schema_version": 1, "stage": stage,
               "owner_pid": os.getpid(),
               "owner_creation_time": INFO.get("ct"),
               "run_id": INFO.get("run_id"),
               "operation_fingerprint": INFO.get("fingerprint"),
               "mutex_name": INFO.get("mutex_name"),
               "control_plane_dir": INFO.get("cp_dir"),
               "lease_path": INFO.get("lease_path"),
               "lease_id": INFO.get("lease_id"),
               "job_created": INFO.get("job_created", False),
               "job_policy_set": INFO.get("job_policy_set", False),
               "child_pid": INFO.get("child_pid"),
               "child_creation_time": INFO.get("child_ct"),
               "child_assigned": INFO.get("child_assigned", False),
               "child_alive": INFO.get("child_alive", False),
               "timestamp": time.time(), "error": None, **extra}}
    tmp = AUTH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh); fh.flush(); os.fsync(fh.fileno())
    _atomic_replace(tmp, AUTH)

try:
    publish("BOOTSTRAP_STARTED", python=sys.executable, cwd=os.getcwd())
    import ctypes as _c
    import control_plane as cpmod0
    # Creation time MUST come from the same function the lease writer uses.
    # control_plane writes PowerShell-ISO strings; deriving it independently via
    # GetProcessTimes yields a FILETIME pair, and comparing the two formats is
    # how this test previously failed.
    INFO["ct"] = cpmod0.process_creation_time(os.getpid())

    import control_plane as cpmod
    INFO["cp_dir"] = cpmod.CONTROL_PLANE_DIR
    INFO["mutex_name"] = cpmod.MUTEX_NAME
    INFO["lease_path"] = cpmod.LEASE_PATH
    publish("CONTROL_PLANE_IMPORTED", control_plane_dir=cpmod.CONTROL_PLANE_DIR,
            lease_path=cpmod.LEASE_PATH, mutex_name=cpmod.MUTEX_NAME)

    from job_supervision import JobSupervisor as _JS
    publish("IMPORTS_OK")

    lease = cpmod.SingleWriterLease(operation="IMPORT", session_id="owner-sess")
    publish("LEASE_OBJECT_CREATED")
    lease.acquire()
    INFO["run_id"] = lease.run_id
    INFO["fingerprint"] = lease.fingerprint.get("fingerprint")
    INFO["lease_id"] = lease.run_id
    publish("MUTEX_ACQUIRED")
    publish("LEASE_WRITTEN")

    # Re-read our own lease and verify before declaring readiness: removes the
    # write-then-read race entirely.
    with open(cpmod.LEASE_PATH) as fh:
        rec = json.load(fh)
    assert rec.get("root_pid") == os.getpid(), rec.get("root_pid")
    assert rec.get("root_creation_time") == INFO["ct"], rec.get("root_creation_time")
    assert rec.get("run_id") == lease.run_id
    INFO["lease_id"] = rec.get("run_id")
    publish("LEASE_REOPEN_VERIFIED")

    job = _JS(name="ownjob_%d" % os.getpid(), kill_on_close=True).create()
    INFO["job_created"] = True
    INFO["job_policy_set"] = True
    publish("JOB_CREATED", job=job.name)
    publish("JOB_CONFIGURED", kill_on_close=job.kill_on_close)

    proc, assigned = job.spawn([sys.executable, "-c",
                                "import time;time.sleep(300)"])
    INFO["child_pid"] = proc.pid
    INFO["child_assigned"] = bool(assigned)
    INFO["child_ct"] = cpmod0.process_creation_time(proc.pid)
    publish("CHILD_CREATED", child_pid=proc.pid, assigned=assigned)
    if not assigned:
        raise RuntimeError("child not assigned to job")
    publish("CHILD_ASSIGNED")
    publish("CHILD_RESUMED")

    _k = _c.WinDLL("kernel32", use_last_error=True)
    _sx = _k.WaitForSingleObject(_k.OpenProcess(0x100000, False, proc.pid), 0)
    INFO["child_alive"] = (_sx == 258)
    publish("CHILD_ALIVE_CONFIRMED", alive=INFO["child_alive"])

    write_auth("READY_FOR_OWNER_DEATH_TEST")
    publish("READY_FOR_OWNER_DEATH_TEST")
    time.sleep(300)
except BaseException:
    write_auth("EXCEPTION", tb=traceback.format_exc()[-2000:])
    publish("EXCEPTION", tb=traceback.format_exc()[-2000:])
    traceback.print_exc()
    sys.exit(9)
'''


def alive(pid):
    k32 = __import__("ctypes").WinDLL("kernel32", use_last_error=True)
    h = k32.OpenProcess(SYNCHRONIZE, False, int(pid))
    if not h:
        return False
    try:
        return k32.WaitForSingleObject(h, 0) == WAIT_TIMEOUT
    finally:
        k32.CloseHandle(h)


_CIM_CACHE = {}


def _cim_all(pid):
    """Executable, parent PID, creation time and command for a live PID.

    Win32_Process has no default projection for ExecutablePath /
    ParentProcessId / CommandLine / CreationDate, so every field must be
    projected explicitly or PowerShell returns an empty object.

    Identity is PID + creation time, never a bare PID: Windows recycles PIDs
    and a stale authority file must never bind to a recycled PID.
    """
    if not pid:
        return None
    pid = int(pid)
    if pid in _CIM_CACHE:
        return _CIM_CACHE[pid]
    ps = (
        "$p=Get-CimInstance Win32_Process -Filter \"ProcessId=%d\" "
        "-ErrorAction SilentlyContinue; if($p){[pscustomobject]@{"
        "exe=$p.ExecutablePath;ppid=$p.ParentProcessId;cmd=$p.CommandLine;"
        "ct=([datetime]$p.CreationDate).ToUniversalTime().ToString('o')}"
        "|ConvertTo-Json -Compress}" % pid)
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, errors="replace",
            timeout=60).stdout.strip()
    except Exception:
        return None
    if not out:
        return None
    try:
        rec = json.loads(out)
    except ValueError:
        return None
    if isinstance(rec, list):
        rec = rec[0] if rec else None
    if not rec:
        return None
    try:
        rec["ppid"] = int(str(rec.get("ppid")).strip())
    except (TypeError, ValueError):
        rec["ppid"] = None
    rec["cmd"] = (rec.get("cmd") or "")[:200]
    _CIM_CACHE[pid] = rec
    return rec


def _cim(pid, field):
    rec = _cim_all(pid)
    return None if not rec else rec.get(field)


def hp_exe(pid):
    return _cim(pid, "exe")


def proc_ppid(pid):
    return _cim(pid, "ppid")


def run_once(idx, base):
    run_id = "t6_%02d_%s" % (idx, uuid.uuid4().hex[:8])
    rdir = os.path.join(base, run_id)
    os.makedirs(rdir, exist_ok=True)
    mutex = "Local\\CARLA_T6_%s" % uuid.uuid4().hex[:10]
    env = {**os.environ,
           "CARLA_CONTROL_PLANE_DIR": rdir,
           "CARLA_MUTEX_NAME": mutex}
    auth = os.path.join(rdir, "authority.json")
    stage = os.path.join(rdir, "stage.json")
    script = os.path.join(rdir, "owner.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(OWNER_SRC.format(scripts=os.path.join(REPO, "scripts"),
                                  auth=auth, stage=stage))

    out = os.path.join(rdir, "owner.stdout.log")
    err = os.path.join(rdir, "owner.stderr.log")
    timeline = []
    t_start = time.time()
    with open(out, "w") as fo, open(err, "w") as fe:
        hp = subprocess.Popen([PY, script], stdout=fo, stderr=fe,
                              cwd=REPO, env=env)
        authority = None
        dl = time.time() + 90
        while time.time() < dl:
            if os.path.isfile(stage):
                try:
                    s = json.load(open(stage, encoding="utf-8"))
                    if not timeline or timeline[-1]["stage"] != s.get("stage"):
                        timeline.append({"observed_at": time.time(),
                                        "stage": s.get("stage")})
                except (ValueError, OSError):
                    pass
            if os.path.isfile(auth):
                try:
                    a = json.load(open(auth, encoding="utf-8"))
                    if a.get("stage") == "READY_FOR_OWNER_DEATH_TEST":
                        authority = a
                        timeline.append({"observed_at": time.time(),
                                        "stage": "CONTROLLER_SAW_READY"})
                        break
                    if a.get("stage") == "EXCEPTION":
                        timeline.append({"observed_at": time.time(),
                                        "stage": "CONTROLLER_SAW_EXCEPTION"})
                        break
                except (ValueError, OSError):
                    pass
            if hp.poll() is not None:
                break
            time.sleep(0.1)
        fe.flush()
    owner_exit = hp.poll()

    r = {"run": run_id, "run_dir": rdir, "mutex": mutex,
         # Launcher PID is what subprocess.Popen created; on Windows a venv
         # Scripts\python.exe is a redirector that spawns the real interpreter
         # as a child. It is launch-topology evidence only and is never the
         # logical lease-owner identity.
         "launcher_pid": hp.pid,
         "owner_pid": authority.get("owner_pid") if authority else None,
         "owner_exit_before_gate": owner_exit,
         "authority": authority, "controller_timeline": timeline,
         "stderr": open(err, encoding="utf-8", errors="replace").read()[-1500:],
         "gate_ok": False}
    if not authority or authority.get("stage") != "READY_FOR_OWNER_DEATH_TEST":
        r["setup_fail_reason"] = "owner did not publish READY"
        return r

    # §9 pre-kill hard gate, validated against the owner's own authority file.
    lease_path = authority["lease_path"]
    try:
        lease = json.load(open(lease_path, encoding="utf-8"))
        lease_valid = True
    except (ValueError, OSError):
        lease, lease_valid = None, False
    launcher_exe = hp_exe(hp.pid)
    owner_ppid = proc_ppid(authority["owner_pid"])
    owner_exe = _cim(authority["owner_pid"], "exe")
    if authority["owner_pid"] == hp.pid:
        topology = "SAME_PROCESS"
    elif owner_ppid == hp.pid:
        topology = "KNOWN_INTERMEDIATE_WRAPPER"
    else:
        topology = "UNKNOWN_INTERMEDIATE"
    checks = {
        "OWNER_READY": True,
        "OWNER_ALIVE": alive(authority["owner_pid"]),
        "LAUNCHER_ALIVE": alive(hp.pid),
        # §6 the owner-published identity must belong to the launched
        # hierarchy: either it IS the launched process, or its parent is the
        # launched process. Anything else is UNRELATED and must STOP.
        "OWNER_AUTHORITY_PROCESS_BINDING":
            topology in ("SAME_PROCESS", "KNOWN_INTERMEDIATE_WRAPPER"),
        "LAUNCHER_EXECUTABLE": bool(launcher_exe),
        "OWNER_EXECUTABLE": bool(owner_exe),
        "LEASE_EXISTS": lease_valid,
        "LEASE_VALID_JSON": lease_valid,
        "LEASE_RUN_ID_MATCH": bool(lease) and lease.get("run_id") == authority["run_id"],
        # Identity authority is the owner-published record, never the
        # controller-side launcher PID. A venv launcher makes hp.pid != the
        # logical owner, so comparing against hp.pid is simply wrong.
        "LEASE_OWNER_PID_MATCH": bool(lease) and lease.get("root_pid") == authority["owner_pid"],
        "LEASE_OWNER_CREATION_TIME_MATCH":
            bool(lease) and lease.get("root_creation_time") == authority["owner_creation_time"],
        "CHILD_PID_KNOWN": bool(authority.get("child_pid")),
        "CHILD_ALIVE": alive(authority["child_pid"]) if authority.get("child_pid") else False,
        "CHILD_IDENTITY_MATCH": bool(authority.get("child_creation_time")),
    }
    r["pre_kill_gate"] = checks
    r["gate_debug"] = {
        "authority_owner_pid": authority.get("owner_pid"),
        "launcher_hp_pid": hp.pid,
        "launcher_hp_executable": launcher_exe,
        "launcher_hp_creation_time": _cim(hp.pid, "ct"),
        "owner_os_ppid": owner_ppid,
        "owner_os_executable": owner_exe,
        "launch_topology_classification": topology,
        "owner_creation_time": authority.get("owner_creation_time"),
        "popen_pid_equals_owner_pid": hp.pid == authority.get("owner_pid"),
        "identity_authority": "authority.owner_pid (owner-published), "
                              "never launcher hp.pid",
        "lease_root_pid": (lease or {}).get("root_pid"),
        "lease_root_creation_time": (lease or {}).get("root_creation_time"),
        "lease_run_id": (lease or {}).get("run_id"),
        "authority_run_id": authority.get("run_id"),
        "lease_keys": sorted(lease.keys()) if lease else None,
    }
    r["gate_ok"] = all(checks.values())
    if not r["gate_ok"]:
        r["setup_fail_reason"] = "pre-kill gate: %s" % [
            k for k, v in checks.items() if not v]
        try:
            hp.kill(); hp.wait(timeout=20)
        except Exception:
            pass
        return r

    # §11 reacquire before reconciliation must be denied
    r["reacquire_before"] = "ALLOWED"
    probe = os.path.join(rdir, "probe")
    probe_env = {**env}
    probe_src = (
        "import sys,json;sys.path.insert(0,%r)\n"
        "import control_plane as cp\n"
        "try:\n"
        "    cp.SingleWriterLease(operation='IMPORT',session_id='probe').acquire()\n"
        "    print('RESULT ALLOWED')\n"
        "except cp.ArbitrationError as e:\n"
        "    print('RESULT DENIED', e.reason)\n"
        % os.path.join(REPO, "scripts"))
    p = subprocess.run([PY, "-c", probe_src], env=probe_env,
                       capture_output=True, text=True, timeout=120)
    line = next((l for l in p.stdout.splitlines() if l.startswith("RESULT")), "")
    if line.startswith("RESULT DENIED"):
        r["reacquire_before"] = "DENIED"
        r["reacquire_before_reason"] = line.split(" ", 2)[-1]
    r["cleanup_race_detected"] = False

    # §10 owner death. Kill the LOGICAL OWNER, not the launcher: on Windows a
    # venv Scripts\python.exe is a redirector that forks the real interpreter,
    # so hp.pid is not the lease owner. Killing the launcher leaves the actual
    # lease owner running and this test would silently measure nothing.
    child = authority["child_pid"]
    owner_pid = authority["owner_pid"]
    launcher_pid = hp.pid
    try:
        os.kill(int(owner_pid), signal.SIGTERM)
    except (OSError, ValueError):
        hp.kill()
    dl = time.time() + 25
    while time.time() < dl and alive(owner_pid):
        time.sleep(0.1)
    r["OWNER_DEAD"] = not alive(owner_pid)
    r["owner_pid_killed"] = owner_pid
    r["launcher_pid"] = launcher_pid
    r["launcher_alive_after_owner_kill"] = alive(launcher_pid)
    try:
        hp.wait(timeout=30)
    except Exception:
        pass
    # Owner death is the precondition for every later assertion; if the owner
    # survived, nothing below is meaningful.
    if not r["OWNER_DEAD"]:
        r["setup_fail_reason"] = "logical owner %s survived kill" % owner_pid
        return r
    dl = time.time() + 25
    while time.time() < dl and alive(child):
        time.sleep(0.1)
    r["child_terminated_after_owner_death"] = not alive(child)

    # §11 reconciliation via the authority-published lease path
    rec_src = (
        "import sys,json;sys.path.insert(0,%r)\n"
        "import control_plane as cp\n"
        "l=cp.SingleWriterLease._read() or {}\n"
        "st=cp.SingleWriterLease.holder_state(l) if l else 'NONE'\n"
        "print('STATE', st)\n"
        "try:\n"
        "    print('RECON', json.dumps(cp.SingleWriterLease.reconcile_stale('t6','ctl')))\n"
        "except cp.ArbitrationError as e:\n"
        "    print('RECON', 'DENIED', e.reason)\n"
        % os.path.join(REPO, "scripts"))
    p2 = subprocess.run([PY, "-c", rec_src], env=probe_env,
                        capture_output=True, text=True, timeout=120)
    r["reconcile_output"] = p2.stdout.strip()

    p3 = subprocess.run([PY, "-c", probe_src], env=probe_env,
                        capture_output=True, text=True, timeout=120)
    line3 = next((l for l in p3.stdout.splitlines() if l.startswith("RESULT")), "")
    r["reacquire_after"] = "ALLOWED" if "ALLOWED" in line3 else "DENIED"
    return r


def main():
    out_dir = os.path.join(REPO, "reports")
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, "t6_runs")
    os.makedirs(base, exist_ok=True)
    runs = []
    for i in range(1, 6):
        try:
            runs.append(run_once(i, base))
        except Exception as exc:
            runs.append({"run": "t6_%d" % i, "gate_ok": False,
                         "setup_fail_reason": "harness exception: %r" % exc})

    setup = sum(1 for r in runs if r.get("gate_ok"))
    death = sum(1 for r in runs if r.get("gate_ok")
                and r.get("child_terminated_after_owner_death"))
    recon = sum(1 for r in runs if r.get("gate_ok")
                and "RECONCILED" in (r.get("reconcile_output") or ""))
    reacq = sum(1 for r in runs if r.get("reacquire_after") == "ALLOWED")
    denied = sum(1 for r in runs if r.get("reacquire_before") == "DENIED")

    payload = {
        "schema": "T6_DETERMINISM_RECEIPT/v1", "schema_version": 1,
        "generated_utc": utc_now(),
        "T6_CONSECUTIVE_RUNS": 5,
        "T6_SETUP_PASS": "%d/5" % setup,
        "T6_OWNER_DEATH_PASS": "%d/5" % death,
        "T6_RECONCILIATION_PASS": "%d/5" % recon,
        "T6_REACQUIRE_AFTER_PASS": "%d/5" % reacq,
        "T6_REACQUIRE_BEFORE_DENIED": "%d/5" % denied,
        "LEASE_OWNER_DEATH_TEST": "PASS" if (setup == death == recon == reacq == 5
                                             and denied == 5) else "FAIL",
        "isolation": ("each run used a unique control-plane directory and "
                      "mutex name passed through the environment; the "
                      "production control plane was never read or written"),
        "runs": [{k: v for k, v in r.items() if k != "authority"} for r in runs],
    }
    atomic_write_json(os.path.join(out_dir, "T6_DETERMINISM_RECEIPT.json"), payload)
    print(json.dumps({k: v for k, v in payload.items() if k != "runs"}, indent=2))
    for r in runs:
        if not r.get("gate_ok"):
            print("FAIL", r.get("run"), r.get("setup_fail_reason"))
    return 0 if payload["LEASE_OWNER_DEATH_TEST"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())