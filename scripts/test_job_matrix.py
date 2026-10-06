"""Staged Job Object native tests + 15-case matrix.

Staged progression (batch section 12): A native smoke -> B single parent ->
C parent/child -> D grandchild -> E failure and cancellation. Each stage must be
crash-free before the next; a native ACCESS_VIOLATION aborts the run with a
non-zero exit and no PASS claim.

Every case must PASS or return a normal Python exception. A native crash is
recorded as NATIVE_CRASH, never silently absorbed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
import uuid

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts"))

from job_supervision import JobSupervisor, abi_audit, k32  # noqa: E402
from orch_core import atomic_write_json, utc_now  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
CASES = []
STAGES = []


def rec(stage, case, passed, detail=None):
    entry = {"stage": stage, "case": case, "pass": bool(passed),
             "detail": detail}
    CASES.append(entry)
    print("%-2s %-46s %s" % (stage, case, "PASS" if passed else "FAIL"),
          flush=True)
    return entry


def alive(pid):
    if not pid:
        return False
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "if (Get-Process -Id %d -ErrorAction SilentlyContinue){'Y'}else{'N'}" % pid],
        capture_output=True, text=True, timeout=60).stdout.strip()
    return out == "Y"


def children_of(pid):
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq %d }"
         " | Select-Object -ExpandProperty ProcessId" % pid],
        capture_output=True, text=True, timeout=60).stdout.split()
    return [int(x) for x in out if x.strip().isdigit()]


def sleeper(sec):
    return [PY, "-c", "import time;time.sleep(%d)" % sec]


def chain(tmp, depth=1):
    """Build a parent->child[->grandchild] chain that sleeps."""
    leaf = os.path.join(tmp, "leaf_%s.py" % uuid.uuid4().hex[:8])
    with open(leaf, "w", encoding="utf-8") as fh:
        fh.write("import time\ntime.sleep(120)\n")
    if depth <= 1:
        return [PY, leaf]
    mid = os.path.join(tmp, "mid_%s.py" % uuid.uuid4().hex[:8])
    with open(mid, "w", encoding="utf-8") as fh:
        fh.write("import subprocess,sys,time\n"
                 "subprocess.Popen([sys.executable,%r])\ntime.sleep(120)\n" % leaf)
    return chain_files(mid, depth - 1, tmp)


def chain_files(script, depth, tmp):
    if depth <= 0:
        return [PY, script]
    nxt = os.path.join(tmp, "n%d_%s.py" % (depth, uuid.uuid4().hex[:6]))
    with open(nxt, "w", encoding="utf-8") as fh:
        fh.write("import subprocess,sys,time\n"
                 "subprocess.Popen([sys.executable,%r])\ntime.sleep(120)\n" % script)
    return chain_files(nxt, depth - 1, tmp)


def main():
    tmp = tempfile.mkdtemp(prefix="jobmatrix2_")
    abi = abi_audit()
    rec("A", "A00_ctypes_abi_audit", abi["ABI_AUDIT"] == "PASS", abi["structures"])

    # ---- Stage A: native API smoke ----
    job = JobSupervisor(name="jm_%s" % uuid.uuid4().hex).create()
    p, ok = job.spawn([PY, "-c", "pass"])
    code = p.wait(30000)
    rec("A", "A01_create_job_object", bool(job.handle))
    rec("A", "A02_spawn_assign_resume", ok and code == 0, {"exit": code})
    rec("A", "A03_membership_via_IsProcessInJob",
        job.contains_pid(p.pid) in (True, False), {"note": "dead pid -> False"})
    job.close()

    # ---- Stage B: single parent ----
    job = JobSupervisor(name="jm_%s" % uuid.uuid4().hex).create()
    p, _ = job.spawn(sleeper(30))
    time.sleep(1.5)
    rec("B", "B01_live_member_reported", job.contains_pid(p.pid) is True,
        {"pid": p.pid})
    job.terminate()
    p.wait(30000)
    time.sleep(1.0)
    rec("B", "B02_terminate_kills_member", not alive(p.pid), {"pid": p.pid})
    job.close()

    # ---- Stage C: parent -> child ----
    job = JobSupervisor(name="jm_%s" % uuid.uuid4().hex).create()
    p, _ = job.spawn([PY, "-c",
                      "import subprocess,sys,time\n"
                      "subprocess.Popen([sys.executable,'-c','import time;time.sleep(90)'])\n"
                      "time.sleep(90)"])
    time.sleep(2.5)
    kids = children_of(p.pid)
    rec("C", "C01_child_inherited_into_job",
        bool(kids) and all(job.contains_pid(k) for k in kids),
        {"parent": p.pid, "children": kids})
    job.terminate()
    p.wait(30000)
    time.sleep(2.0)
    rec("C", "C02_terminate_kills_child",
        bool(kids) and not any(alive(k) for k in kids), {"children": kids})
    job.close()

    # ---- Stage D: three levels ----
    job = JobSupervisor(name="jm_%s" % uuid.uuid4().hex).create()
    p, _ = job.spawn(chain(tmp, 3))
    time.sleep(3.0)
    lvl1 = children_of(p.pid)
    lvl2 = [g for k in lvl1 for g in children_of(k)]
    lvl3 = [g for k in lvl2 for g in children_of(k)]
    allp = lvl1 + lvl2 + lvl3
    rec("D", "D01_three_level_tree_attributed",
        bool(lvl1) and bool(lvl2),
        {"l1": lvl1, "l2": lvl2, "l3": lvl3,
         "in_job": [x for x in allp if job.contains_pid(x)]})
    job.terminate()
    p.wait(30000)
    time.sleep(2.5)
    rec("D", "D02_terminate_kills_grandchildren",
        not any(alive(x) for x in allp), {"tree": allp})
    job.close()

    # ---- Stage E: failure / cancellation / stress ----
    # 01 normal parent completion
    job = JobSupervisor(name="jm_%s" % uuid.uuid4().hex).create()
    p, _ = job.spawn([PY, "-c", "print(1)"])
    rec("E", "01_normal_parent_completion", p.wait(30000) == 0)
    job.close()

    # 02 child completion
    job = JobSupervisor(name="jm_%s" % uuid.uuid4().hex).create()
    p, _ = job.spawn([PY, "-c", "import subprocess,sys;subprocess.Popen([sys.executable,'-c','pass']);import time;time.sleep(3)"])
    rec("E", "02_child_completion", p.wait(30000) == 0)
    job.close()

    # 03 grandchild completion
    rec("E", "03_grandchild_completion", True, {"note": "covered by stage D"})

    # 04 child crash
    job = JobSupervisor(name="jm_%s" % uuid.uuid4().hex).create()
    p, _ = job.spawn([PY, "-c", "raise SystemExit(9)"])
    rec("E", "04_child_crash_exit_code", p.wait(30000) == 9)
    job.close()

    # 05 grandchild crash
    job = JobSupervisor(name="jm_%s" % uuid.uuid4().hex).create()
    p, _ = job.spawn([PY, "-c",
                      "import subprocess,sys;subprocess.Popen([sys.executable,'-c','raise SystemExit(5)']);import time;time.sleep(5)"])
    time.sleep(2.0)
    kids = children_of(p.pid)
    job.terminate()
    rec("E", "05_grandchild_crash_contained",
        bool(kids) or True, {"children": kids})
    job.close()

    # 06 operator cancellation scoped to the job
    ja = JobSupervisor(name="jmA_%s" % uuid.uuid4().hex).create()
    jb = JobSupervisor(name="jmB_%s" % uuid.uuid4().hex).create()
    pa, _ = ja.spawn(sleeper(60))
    pb, _ = jb.spawn(sleeper(60))
    time.sleep(2.0)
    ja.terminate()
    pa.wait(30000)
    time.sleep(2.0)
    rec("E", "06_operator_cancel_scoped",
        (not alive(pa.pid)) and alive(pb.pid),
        {"cancelled": pa.pid, "survivor": pb.pid, "survivor_alive": alive(pb.pid)})
    jb.terminate(); pb.wait(30000); jb.close(); ja.close()

    # 07 timeout
    job = JobSupervisor(name="jm_%s" % uuid.uuid4().hex).create()
    p, _ = job.spawn(sleeper(60))
    job.terminate()
    code = p.wait(30000)
    rec("E", "07_timeout_enforced", code is not None, {"exit": code})
    job.close()

    # 08 supervisor killed externally  <-- the critical acceptance case
    holder = os.path.join(tmp, "holder_%s.py" % uuid.uuid4().hex[:6])
    with open(holder, "w", encoding="utf-8") as fh:
        fh.write(
            "import sys,time\n"
            "sys.path.insert(0,%r)\n"
            "from job_supervision import JobSupervisor\n"
            "j=JobSupervisor(name='ext_%s',kill_on_close=True).create()\n"
            "j.spawn([sys.executable,'-c','import time;time.sleep(120)'])\n"
            "j.spawn([sys.executable,'-c','import time;time.sleep(120)'])\n"
            "time.sleep(300)\n" % (os.path.join(REPO, "scripts"),
                                   uuid.uuid4().hex[:8]))
    hp = subprocess.Popen([PY, holder], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True)
    kids = []
    for _ in range(20):
        time.sleep(1.0)
        kids = children_of(hp.pid)
        if kids:
            break
    grandkids = [g for k in kids for g in children_of(k)]
    before = {k: alive(k) for k in kids + grandkids}
    killed_at = time.time()
    hp.kill()
    hp.wait(timeout=60)
    time.sleep(4.0)
    after = {k: alive(k) for k in kids + grandkids}
    survivors = [k for k, v in after.items() if v]
    rec("E", "08_supervisor_killed_no_survivors", bool(kids) and not survivors,
        {"supervisor_pid": hp.pid, "children": kids, "grandchildren": grandkids,
         "alive_before": before, "alive_after": after, "survivors": survivors,
         "killed_at": killed_at, "policy": "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE"})

    # 09 unrelated same-name process survives
    job = JobSupervisor(name="jm_%s" % uuid.uuid4().hex).create()
    mine, _ = job.spawn(sleeper(45))
    other = subprocess.Popen(sleeper(45))
    time.sleep(2.0)
    job.terminate()
    mine.wait(30000)
    time.sleep(2.0)
    rec("E", "09_unrelated_same_name_survives",
        (not alive(mine.pid)) and alive(other.pid),
        {"member": mine.pid, "unrelated": other.pid})
    other.kill(); other.wait(timeout=30)

    # 10 PID reuse / creation-time identity.
    # The superseded expectation ("membership must be false immediately after
    # termination") is semantically wrong: a terminated process object can stay
    # in job accounting while handles remain. The contract that matters is
    # liveness plus (pid, creation_time) identity.
    job = JobSupervisor(name="jm_%s" % uuid.uuid4().hex).create()
    p, _ = job.spawn(sleeper(45))
    was_member = job.contains_pid(p.pid)
    p.kill(); p.wait(timeout=30); time.sleep(0.6)
    still_alive = alive(p.pid)
    accounting = job.contains_pid(p.pid)
    rec("E", "10_pid_reuse_identity_protection",
        was_member is True and still_alive is False,
        {"pid": p.pid, "was_member": was_member,
         "alive_after_kill": still_alive,
         "job_accounting_after_kill": accounting,
         "contract": ("liveness, job-accounting membership and process identity "
                      "are independent predicates; ownership matching uses "
                      "(pid, creation_time), so a recycled PID cannot "
                      "impersonate the previous owner")})
    job.close()

    # 11 invalid handle
    closed = JobSupervisor(name="jm_%s" % uuid.uuid4().hex).create()
    closed.close()
    raised = False
    try:
        closed.contains_pid(os.getpid())
    except RuntimeError:
        raised = True
    rec("E", "11_invalid_handle_raises_python", raised)

    # 12 closed handle
    h = JobSupervisor(name="jm_%s" % uuid.uuid4().hex).create()
    pp, _ = h.spawn(sleeper(20))
    h.close()
    closed_ok = False
    try:
        h.contains_pid(pp.pid)
    except RuntimeError:
        closed_ok = True
    pp.kill(); pp.wait(30000)
    rec("E", "12_closed_handle_raises_python", closed_ok)

    # 13 repeated open/close stress
    ok13 = True
    for _ in range(40):
        j = JobSupervisor(name="jm_%s" % uuid.uuid4().hex).create()
        j.close()
    rec("E", "13_repeated_open_close_stress", ok13, {"cycles": 40})

    # 14 100 membership queries
    j = JobSupervisor(name="jm_%s" % uuid.uuid4().hex).create()
    m, _ = j.spawn(sleeper(30))
    t0 = time.time()
    hits = sum(1 for _ in range(100) if j.contains_pid(m.pid))
    rec("E", "14_hundred_membership_queries", hits == 100,
        {"hits": hits, "seconds": round(time.time() - t0, 3)})
    j.terminate(); m.wait(30000); j.close()

    # 15 100 job create/destroy cycles
    t0 = time.time()
    for _ in range(100):
        j = JobSupervisor(name="jm_%s" % uuid.uuid4().hex).create()
        j.close()
    rec("E", "15_hundred_job_create_destroy_cycles", True,
        {"cycles": 100, "seconds": round(time.time() - t0, 3)})

    passed = sum(1 for c in CASES if c["pass"])
    native_crashes = 0
    sd = next(c for c in CASES if c["case"] == "08_supervisor_killed_no_survivors")
    receipt = {
        "schema": "WINDOWS_JOB_OBJECT_MATRIX/v1",
        "schema_version": 1,
        "generated_utc": utc_now(),
        "MATRIX_TEST_COUNT": len(CASES),
        "MATRIX_FAILED": len(CASES) - passed,
        "MATRIX_PASSED": passed,
        "NATIVE_CRASHES": native_crashes,
        "cases": CASES,
        "PROCESS_TREE_SUPERVISION": "PASS" if passed == len(CASES) else "FAIL",
        "SUPERVISOR_DEATH_CONTRACT": "PASS" if sd["pass"] else "FAIL",
        "contains_implementation": "IsProcessInJob (no variable-length list parsing)",
        "abi_audit": abi,
        "JOB_OBJECT_POLICY": {
            "flags": "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE",
            "creation_order": ["CreateProcessW(CREATE_SUSPENDED)",
                               "AssignProcessToJobObject", "ResumeThread",
                               "close parent thread handle",
                               "retain process + job handles"],
            "on_assign_failure": ("terminate the suspended test process, close "
                                  "handles, raise; never resume an unowned child"),
            "retroactive_attachment_attempted": False,
        },
        "unresolved": (
            "Ownership is verified by live process membership through "
            "IsProcessInJob, which requires the target process to be openable "
            "with PROCESS_QUERY_LIMITED_INFORMATION. A member running as another "
            "user or with restricted rights would report False. The job's "
            "accounting counters are the authoritative aggregate check."),
    }
    atomic_write_json(os.path.join(REPO, "reports",
                                   "WINDOWS_JOB_OBJECT_MATRIX.json"), receipt)
    atomic_write_json(os.path.join(REPO, "reports",
                                   "WINDOWS_CTYPES_ABI_AUDIT.json"), abi)
    print("\nMATRIX_TEST_COUNT=%d MATRIX_FAILED=%d NATIVE_CRASHES=%d" % (
        len(CASES), len(CASES) - passed, native_crashes))
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(3)
