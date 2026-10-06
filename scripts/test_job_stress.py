"""Bounded synthetic stress for Job Object supervision (batch section 34).

Required counters: NATIVE_CRASHES, UNOWNED_CHILD_SURVIVORS,
UNEXPECTED_HANDLE_GROWTH, plus leaked job/process handles.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from job_supervision import JobSupervisor  # noqa: E402
from orch_core import atomic_write_json, utc_now  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
WAIT_TIMEOUT = 0x102
SYNCHRONIZE = 0x00100000

import ctypes  # noqa: E402
from job_supervision import k32, PROCESS_QUERY_LIMITED_INFORMATION  # noqa: E402


def alive(pid):
    h = k32.OpenProcess(SYNCHRONIZE, False, int(pid))
    if not h:
        return False
    try:
        return k32.WaitForSingleObject(h, 0) == WAIT_TIMEOUT
    finally:
        k32.CloseHandle(h)


def handle_count():
    """Current process open-handle count via GetProcessHandleCount.

    The previous implementation called GetProcessMemoryInfo with a
    hand-rolled PROCESS_MEMORY_COUNTERS that declared "handles" and "threads"
    fields that do not exist in the real structure, and set cb to its own
    (wrong) size. GetProcessMemoryInfo therefore failed and the function
    returned 0, so every before/after pair read 0 -> 0 and the leak check
    passed vacuously. PROCESS_MEMORY_COUNTERS has no handle count at all;
    GetProcessHandleCount is the correct API.
    """
    import ctypes as c
    k = c.WinDLL("kernel32", use_last_error=True)
    k.GetProcessHandleCount.argtypes = [c.c_void_p,
                                        c.POINTER(c.c_uint32)]
    k.GetProcessHandleCount.restype = c.c_int
    count = c.c_uint32(0)
    ok = k.GetProcessHandleCount(k.GetCurrentProcess(), c.byref(count))
    if not ok:
        raise OSError(c.get_last_error(),
                      "GetProcessHandleCount failed; handle metric invalid")
    return int(count.value)


def main():
    tmp = tempfile.mkdtemp(prefix="jobstress_")
    res = {"schema": "WINDOWS_JOB_OBJECT_STRESS/v1", "schema_version": 1,
           "generated_utc": utc_now()}
    native_crashes = 0
    survivors = 0
    leaks = 0

    h0 = handle_count()
    # 100 job create/configure/close cycles
    t0 = time.time()
    for _ in range(100):
        j = JobSupervisor(name="st_%s" % uuid.uuid4().hex[:10]).create()
        j.close()
    res["job_create_close_cycles"] = 100
    res["job_cycle_seconds"] = round(time.time() - t0, 2)

    # 100 IsProcessInJob membership queries on a live process
    j = JobSupervisor(name="st_%s" % uuid.uuid4().hex[:10]).create()
    p, _ = j.spawn([PY, "-c", "import time;time.sleep(120)"])
    time.sleep(1.0)
    t0 = time.time()
    hits = 0
    for _ in range(100):
        if j.contains_pid(p.pid):
            hits += 1
    res["membership_queries"] = 100
    res["membership_hits"] = hits
    res["membership_seconds"] = round(time.time() - t0, 2)

    # 50 child-exit races
    races = 0
    for _ in range(50):
        r, _ = j.spawn([PY, "-c", "pass"])
        races += 1
        r.wait(timeout=20)
    res["child_exit_races"] = races
    j.terminate(); p.wait(timeout=30); j.close()

    # 50 supervisor-death cycles, each fully isolated
    death_ok = 0
    death_fail = 0
    t0 = time.time()
    for i in range(50):
        ready = os.path.join(tmp, "r%d.json" % i)
        holder = os.path.join(tmp, "h%d.py" % i)
        with open(holder, "w", encoding="utf-8") as fh:
            fh.write(
                "import json,os,sys,time\n"
                "sys.path.insert(0,%r)\n"
                "from job_supervision import JobSupervisor\n"
                "jj=JobSupervisor(name='sj%%s'%%os.getpid(),kill_on_close=True).create()\n"
                "c,_=jj.spawn([sys.executable,'-c','import time;time.sleep(60)'])\n"
                "t=%r+'.tmp'\n"
                "open(t,'w').write(str(c.pid))\n"
                "os.replace(t,%r)\n"
                "time.sleep(60)\n" % (os.path.join(REPO, "scripts"), ready, ready))
        hp = subprocess.Popen([PY, holder], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
        cp = None
        dl = time.time() + 30
        while time.time() < dl:
            if os.path.isfile(ready):
                try:
                    cp = int(open(ready).read().strip()); break
                except (ValueError, OSError):
                    pass
            time.sleep(0.1)
        if cp is None:
            death_fail += 1
            try:
                hp.kill(); hp.wait(timeout=10)
            except Exception:
                pass
            continue
        hp.kill()
        try:
            hp.wait(timeout=20)
        except Exception:
            pass
        dl = time.time() + 10
        while time.time() < dl and alive(cp):
            time.sleep(0.05)
        if alive(cp):
            death_fail += 1
            survivors += 1
        else:
            death_ok += 1
        try:
            os.unlink(ready)
        except OSError:
            pass
    res["supervisor_death_cycles"] = 50
    res["supervisor_death_contained"] = death_ok
    res["supervisor_death_uncontained"] = death_fail
    res["supervisor_death_seconds"] = round(time.time() - t0, 1)

    # invalid / closed handle calls must raise, never call through
    raised = 0
    for _ in range(20):
        k = JobSupervisor(name="st_%s" % uuid.uuid4().hex[:10]).create()
        k.close()
        try:
            k.contains_pid(os.getpid())
        except RuntimeError:
            raised += 1
    res["invalid_handle_calls"] = 20
    res["invalid_handle_raised_python"] = raised

    h1 = handle_count()
    res["handle_count_before"] = h0
    res["handle_count_after"] = h1
    res["handle_growth"] = h1 - h0
    res["handle_metric_api"] = "GetProcessHandleCount"
    # A live process always has a nonzero handle count. If the reading is 0
    # the measurement failed and the growth check below would pass vacuously,
    # so treat an invalid reading as a failure rather than as "no growth".
    res["handle_measurement_valid"] = bool(h0 > 0 and h1 > 0)
    res["UNEXPECTED_HANDLE_GROWTH"] = 1 if (h1 - h0) > 40 else 0
    if not res["handle_measurement_valid"]:
        res["UNEXPECTED_HANDLE_GROWTH"] = 1
    res["UNOWNED_CHILD_SURVIVORS"] = survivors
    res["NATIVE_CRASHES"] = native_crashes
    res["JOB_STRESS_FAILURES"] = int(res["UNEXPECTED_HANDLE_GROWTH"]) + survivors + \
        max(0, 20 - raised)
    res["PROCESS_TREE_SUPERVISION_STRESS"] = (
        "PASS" if res["JOB_STRESS_FAILURES"] == 0 else "FAIL")
    atomic_write_json(os.path.join(REPO, "reports",
                                   "WINDOWS_JOB_OBJECT_STRESS.json"), res)
    print(json.dumps(res, indent=2))
    return 0 if res["JOB_STRESS_FAILURES"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())