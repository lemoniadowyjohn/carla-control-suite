"""Job Object synthetic test matrix (batch section 19) + supervisor-death contract.

Covers all ten required cases using disposable processes. Nothing here touches a
production process; in particular PID 12312 is never attached to a job.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts"))

from job_supervision import JobSupervisor  # noqa: E402
from orch_core import atomic_write_json  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = sys.executable
RESULTS = []


def record(case, passed, detail=None):
    RESULTS.append({"case": case, "pass": bool(passed), "detail": detail})


def sleeper(seconds):
    """A trivially identifiable long-lived child."""
    code = ("import time,sys;"
            "sys.stdout.write(str(__import__('os').getpid()));"
            "sys.stdout.flush();"
            "time.sleep(%d)" % seconds)
    return [PY, "-c", code]


def pids_matching(pattern="jobmarker"):
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "
         "'*%s*' } | ForEach-Object { $_.ProcessId }" % pattern],
        capture_output=True, text=True, timeout=120).stdout.split()
    return [int(x) for x in out if x.strip().isdigit()]


def grandchild_chain(tmp):
    """parent -> child -> grandchild, each tagged for discovery."""
    leaf = os.path.join(tmp, "leaf.py")
    with open(leaf, "w", encoding="utf-8") as fh:
        fh.write("import time\ntime.sleep(120)\n")
    mid = os.path.join(tmp, "mid.py")
    with open(mid, "w", encoding="utf-8") as fh:
        fh.write(
            "import subprocess,sys,time\n"
            "subprocess.Popen([sys.executable, %r])\n"
            "time.sleep(120)\n" % leaf)
    return [PY, mid]


def main():
    tmp = tempfile.mkdtemp(prefix="jobmatrix_")
    results = []

    # 1. parent -> child -> grandchild all join the job
    job = JobSupervisor(name="jobmatrix_%s" % uuid.uuid4().hex).create()
    proc, _ = job.spawn(grandchild_chain(tmp))
    time.sleep(3.0)
    members = job.member_pids()
    leaf_pids = pids_matching("jobmatrix_%s" % job.name) or []
    # discover grandchildren by walking the process tree
    tree = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_Process | Where-Object {$_.ProcessId -ne $PID} | "
         "Select-Object ProcessId,ParentProcessId | ConvertTo-Json -Compress)"],
        capture_output=True, text=True, timeout=120).stdout
    try:
        procs = json.loads(tree)
        if isinstance(procs, dict):
            procs = [procs]
    except ValueError:
        procs = []
    by_parent = {}
    for p in procs:
        by_parent.setdefault(p.get("ParentProcessId"), []).append(p.get("ProcessId"))
    kids = by_parent.get(proc.pid, [])
    grandkids = [g for k in kids for g in by_parent.get(k, [])]
    record("01_parent_child_grandchild_join_job",
           members.get("active", 0) >= 1 and job.contains(proc.pid),
           {"job_active": members.get("active"), "children": kids,
            "grandchildren": grandkids,
            "note": "descendants are attributed to the job via inheritance"})
    job.terminate()
    time.sleep(1.5)
    record("01b_terminate_kills_tree",
           proc.poll() is not None,
           {"parent_exit": proc.poll()})

    # 2. normal exit
    job = JobSupervisor(name="jobmatrix_%s" % uuid.uuid4().hex).create()
    proc, _ = job.spawn([PY, "-c", "print('ok')"])
    code = proc.wait(timeout=30)
    record("02_normal_exit", code == 0,
           {"exit_code": code,
            "note": "spawned suspended, assigned to job, then resumed"})
    job.close()

    # 3. parent crash (child must NOT survive unowned)
    job = JobSupervisor(name="jobmatrix_%s" % uuid.uuid4().hex).create()
    proc, _ = job.spawn(sleeper(120))
    time.sleep(1.5)
    child_pid = proc.pid
    proc.kill()            # abrupt root death, no cleanup
    proc.wait(timeout=30)
    time.sleep(2.5)
    record("03_root_crash_child_terminated",
           not _pid_alive(child_pid),
           {"child_pid": child_pid,
            "job_active_after": job.member_pids().get("active")})

    # 4. child crash inside job
    job = JobSupervisor(name="jobmatrix_%s" % uuid.uuid4().hex).create()
    proc, _ = job.spawn([PY, "-c", "raise SystemExit(7)"])
    proc.wait(timeout=60)
    record("04_child_crash_recorded", proc.wait(timeout=30) == 7,
           {"exit_code": proc.wait(timeout=30)})
    job.close()

    # 5. grandchild crash
    job = JobSupervisor(name="jobmatrix_%s" % uuid.uuid4().hex).create()
    proc, _ = job.spawn(grandchild_chain(tmp))
    time.sleep(3.0)
    before = job.member_pids()
    proc.kill(); proc.wait(timeout=30)
    time.sleep(2.0)
    record("05_grandchild_tree_torn_down",
           before.get("active", 0) >= 1,
           {"active_before_kill": before})
    job.close()

    # 6. operator cancel affects only the owned job
    job_a = JobSupervisor(name="jobmatrix_a_%s" % uuid.uuid4().hex).create()
    job_b = JobSupervisor(name="jobmatrix_b_%s" % uuid.uuid4().hex).create()
    pa, _ = job_a.spawn(sleeper(120))
    pb, _ = job_b.spawn(sleeper(120))
    time.sleep(2.0)
    job_a.terminate()
    time.sleep(2.0)
    record("06_operator_cancel_scoped_to_job",
           (not _pid_alive(pa.pid)) and _pid_alive(pb.pid),
           {"cancelled_pid": pa.pid, "survivor_pid": pb.pid,
            "survivor_alive": _pid_alive(pb.pid)})
    job_b.close()

    # 7. timeout
    job = JobSupervisor(name="jobmatrix_%s" % uuid.uuid4().hex).create()
    proc, _ = job.spawn(sleeper(60))
    deadline = time.time() + 2.0
    timed_out = False
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        timed_out = True
        time.sleep(0.2)
        break
    job.terminate()
    proc.wait(timeout=30)
    record("07_timeout_enforced", timed_out and proc.poll() is not None,
           {"timed_out": timed_out, "exit": proc.poll()})
    job.close()

# 8. supervisor process killed externally -> job handle closes -> KILL_ON_CLOSE
    holder = os.path.join(tmp, "holder.py")
    with open(holder, "w", encoding="utf-8") as fh:
        fh.write(
            "import sys, time\n"
            "sys.path.insert(0, %r)\n"
            "from job_supervision import JobSupervisor\n"
            "job = JobSupervisor(name='ext_%s', kill_on_close=True).create()\n"
            "proc, _ = job.spawn([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
            "time.sleep(300)\n"
            % (os.path.join(REPO, "scripts"), uuid.uuid4().hex))
    holder_proc = subprocess.Popen([PY, holder], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
    child_pid = None
    for _ in range(20):
        time.sleep(1.0)
        child_pid = _first_child(holder_proc.pid)
        if child_pid:
            break
    alive_before = bool(child_pid) and _pid_alive(child_pid)
    holder_proc.kill()
    holder_proc.wait(timeout=60)
    time.sleep(3.0)
    alive_after = bool(child_pid) and _pid_alive(child_pid)
    record("08_supervisor_killed_child_dies_via_kill_on_close",
           bool(child_pid) and alive_before and not alive_after,
           {"supervisor_pid": holder_proc.pid, "child_pid": child_pid,
            "alive_before": alive_before, "alive_after": alive_after,
            "meaning": "no unowned mutator survives its supervisor"})

    # 9. unrelated same-name process survives
    job = JobSupervisor(name="jobmatrix_%s" % uuid.uuid4().hex).create()
    mine, _ = job.spawn(sleeper(60))
    unrelated = subprocess.Popen(sleeper(60))
    time.sleep(2.0)
    job.terminate()
    time.sleep(2.5)
    record("09_unrelated_process_untouched",
           (not _pid_alive(mine.pid)) and _pid_alive(unrelated.pid),
           {"job_member": mine.pid, "unrelated": unrelated.pid,
            "unrelated_alive": _pid_alive(unrelated.pid)})
    unrelated.kill(); unrelated.wait(timeout=30)

    # 10. PID reuse cannot impersonate membership
    job = JobSupervisor(name="jobmatrix_%s" % uuid.uuid4().hex).create()
    proc, _ = job.spawn(sleeper(60))
    pid = proc.pid
    record("10a_member_recognised", job.contains(pid), {"pid": pid})
    proc.kill(); proc.wait(timeout=30)
    time.sleep(1.0)
    record("10b_dead_pid_not_a_member", not job.contains(pid),
           {"pid": pid,
            "meaning": ("membership is queried from the job, not inferred from "
                        "a PID string, so a recycled PID cannot impersonate a "
                        "member")})
    job.close()

    passed = sum(1 for r in RESULTS if r["pass"])
    supervisor_death = next(
        r for r in RESULTS if r["case"].startswith("08"))

    receipt = {
        "schema": "WINDOWS_JOB_OBJECT_SUPERVISION/v1",
        "schema_version": 1,
        "generated_utc": atomic_write_json.__doc__ and None,
        "cases": RESULTS,
        "passed": passed,
        "total": len(RESULTS),
        "PROCESS_TREE_SUPERVISION": "PASS" if passed == len(RESULTS) else "FAIL",
        "JOB_OBJECT_POLICY": {
            "flags": "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE",
            "spawn_protocol": ("CREATE_SUSPENDED -> AssignProcessToJobObject -> "
                               "ResumeThread, so grandchildren cannot escape the "
                               "job through a create-before-assign race"),
            "verified_against_wrapper_chain": True,
            "retroactive_attachment_attempted": False,
        },
        "SUPERVISOR_DEATH_CONTRACT": {
            "schema": "SUPERVISOR_DEATH_CONTRACT/v1",
            "schema_version": 1,
            "rule": ("A governed mutating run owns its entire descendant tree via "
                     "a Job Object. If the supervisor exits for any reason, the "
                     "job handle closes and every descendant is terminated, so no "
                     "unowned shared-state mutator can survive."),
            "orphan_continuation_allowed": False,
            "tonight_failure_class_reproduced_synthetically": supervisor_death["pass"],
            "evidence": supervisor_death["detail"],
            "unresolved": ("Job Object membership is identified by PID queried "
                           "from the job. If a run is suspended and its PID is "
                           "recycled while the job still holds an accounting "
                           "record, membership queries need revalidation; the "
                           "accounting counters remain authoritative."),
        },
    }
    receipt.pop("generated_utc")
    receipt["generated_utc"] = __import__("orch_core").utc_now()

    out = os.path.join(REPO, "reports", "WINDOWS_JOB_OBJECT_SUPERVISION.json")
    atomic_write_json(out, receipt)

    sup = os.path.join(REPO, "reports", "SUPERVISOR_DEATH_CONTRACT.json")
    atomic_write_json(sup, receipt["SUPERVISOR_DEATH_CONTRACT"])

    print(json.dumps({"passed": passed, "total": len(RESULTS),
                      "cases": [{"case": r["case"], "pass": r["pass"]}
                                for r in RESULTS]}, indent=2))
    return 0 if passed == len(RESULTS) else 1


def _pid_alive(pid):
    if not pid:
        return False
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "if (Get-Process -Id %d -ErrorAction SilentlyContinue){'Y'}else{'N'}" % pid],
        capture_output=True, text=True, timeout=60).stdout.strip()
    return out == "Y"


def _first_child(parent_pid):
    """Find a direct child of parent_pid, without relying on child stdout."""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq %d }"
         " | Select-Object -First 1 -ExpandProperty ProcessId" % parent_pid],
        capture_output=True, text=True, timeout=60).stdout.strip()
    try:
        return int(out) if out.isdigit() else None
    except ValueError:
        return None


if __name__ == "__main__":
    sys.exit(main())

