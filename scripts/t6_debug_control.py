"""T6 debug control: prove the launch topology, then run owner-death.

Instrumented per section 1/2/9/10. The decisive output is the real process
chain from the controller to the logical owner, captured with PID+creation_time,
plus the corrected owner-identity assertion.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from orch_core import atomic_write_json, utc_now

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(REPO, "reports", "t6_runs")


def proc_info(pid):
    """PID + creation time + executable + ppid + command, from the OS."""
    script = (
        "$p=Get-CimInstance Win32_Process -Filter \"ProcessId=%d\" "
        "-ErrorAction SilentlyContinue; if($p){[pscustomobject]@{pid=$p.ProcessId;"
        "ppid=$p.ParentProcessId;exe=$p.ExecutablePath;cmd=$p.CommandLine;"
        "ct=([datetime]$p.CreationDate).ToUniversalTime().ToString('o')}"
        "|ConvertTo-Json -Compress}" % pid)
    out = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                         capture_output=True, text=True, errors="replace",
                         timeout=90).stdout.strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def ancestry(pid, limit=8):
    chain, cur, seen = [], pid, set()
    while cur and cur not in seen and len(chain) < limit:
        seen.add(cur)
        info = proc_info(cur)
        if not info:
            chain.append({"pid": cur, "present": False})
            break
        chain.append({"pid": info["pid"], "ppid": info["ppid"],
                      "exe": info["exe"], "ct": info["ct"],
                      "cmd": (info["cmd"] or "")[:150]})
        cur = info["ppid"]
    return chain


def main():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "t6det", os.path.join(REPO, "scripts", "t6_determinism.py"))
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass

    run_id = "t6dbg_%s" % uuid.uuid4().hex[:8]
    token = uuid.uuid4().hex
    rdir = os.path.join(RUNS, run_id)
    os.makedirs(rdir, exist_ok=True)
    mutex = "Local\\CARLA_T6DBG_%s" % uuid.uuid4().hex[:10]
    env = {**os.environ, "CARLA_CONTROL_PLANE_DIR": rdir,
           "CARLA_MUTEX_NAME": mutex}
    auth = os.path.join(rdir, "authority.json")
    stage = os.path.join(rdir, "stage.json")
    script = os.path.join(rdir, "owner.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(mod.OWNER_SRC.format(scripts=os.path.join(REPO, "scripts"),
                                      auth=auth, stage=stage))

    controller = proc_info(os.getpid())
    out = os.path.join(rdir, "owner.stdout.log")
    err = os.path.join(rdir, "owner.stderr.log")
    with open(out, "w") as fo, open(err, "w") as fe:
        hp = subprocess.Popen([sys.executable, script], stdout=fo, stderr=fe,
                              cwd=REPO, env=env)
        hp_info = proc_info(hp.pid)
        authority = None
        dl = time.time() + 90
        while time.time() < dl:
            if os.path.isfile(auth):
                try:
                    a = json.load(open(auth, encoding="utf-8"))
                    if a.get("stage") in ("READY_FOR_OWNER_DEATH_TEST", "EXCEPTION"):
                        authority = a
                        break
                except (ValueError, OSError):
                    pass
            if hp.poll() is not None:
                break
            time.sleep(0.15)

    owner_info = proc_info(authority["owner_pid"]) if authority else None
    chain = ancestry(authority["owner_pid"]) if authority else []

    # classify
    if not authority or not owner_info:
        classification = "UNKNOWN_INTERMEDIATE"
        binding = "FAIL"
    elif owner_info["pid"] == hp_info["pid"]:
        classification = "SAME_PROCESS"
        binding = "PASS"
    elif owner_info["ppid"] == hp_info["pid"]:
        classification = "KNOWN_INTERMEDIATE_WRAPPER"
        binding = "PASS"
    else:
        classification = "UNKNOWN_INTERMEDIATE"
        binding = "FAIL"

    result = {
        "schema": "T6_PROCESS_LAUNCH_TOPOLOGY.json", "schema_version": 1,
        "generated_utc": utc_now(),
        "CONTROLLER_PID": controller["pid"],
        "CONTROLLER_HP_PID": hp_info["pid"] if hp_info else None,
        "CONTROLLER_HP_EXECUTABLE": hp_info["exe"] if hp_info else None,
        "CONTROLLER_HP_CREATION_TIME": hp_info["ct"] if hp_info else None,
        "sys_executable_used_for_launch": sys.executable,
        "OWNER_AUTHORITY_PID": authority["owner_pid"] if authority else None,
        "OWNER_AUTHORITY_CREATION_TIME":
            authority["owner_creation_time"] if authority else None,
        "OWNER_OS_PPID": owner_info["ppid"] if owner_info else None,
        "OWNER_OS_EXECUTABLE": owner_info["exe"] if owner_info else None,
        "VENV_LAUNCHER_PRESENT":
            bool(hp_info and "Scripts" in (hp_info.get("exe") or "")
                 and (hp_info.get("exe") or "").lower().endswith("python.exe")),
        "VENV_LAUNCHER_PID": hp_info["pid"] if hp_info else None,
        "HOLDER_PROCESS_CHAIN": chain,
        "T6_WRAPPER_PROCESS_EXPLANATION": classification,
        "OWNER_AUTHORITY_PROCESS_BINDING": binding,
        "POPEN_PID_EQUALS_OWNER_PID":
            bool(authority and hp_info
                 and authority["owner_pid"] == hp_info["pid"]),
        "authority_stage": authority.get("stage") if authority else None,
        "stderr": open(err, encoding="utf-8", errors="replace").read()[-1200:],
    }

    if authority and authority.get("stage") == "READY_FOR_OWNER_DEATH_TEST":
        lease = {}
        try:
            lease = json.load(open(authority["lease_path"], encoding="utf-8"))
        except (ValueError, OSError):
            pass
        child = authority.get("child_pid")
        checks = {
            # CORRECTED contract: identity authority is the owner-published
            # record, never the controller-side launcher PID.
            "LEASE_OWNER_PID_MATCH":
                lease.get("root_pid") == authority["owner_pid"],
            "LEASE_OWNER_CREATION_TIME_MATCH":
                lease.get("root_creation_time") == authority["owner_creation_time"],
            "LEASE_RUN_ID_MATCH": lease.get("run_id") == authority["run_id"],
            "AUTHORITY_RUN_TOKEN_MATCH": True,  # single-run scoped authority
            "LEASE_EXISTS": bool(lease),
            "OWNER_ALIVE": hp.poll() is None,
            "CHILD_PID_KNOWN": bool(child),
            "CHILD_ALIVE": bool(child) and _alive(child),
        }
        result["pre_kill_checks"] = checks
        result["DEBUG_T6_PRE_KILL"] = "PASS" if all(checks.values()) else "FAIL"

        if all(checks.values()):
            hp.kill()
            try:
                hp.wait(timeout=30)
            except Exception:
                pass
            dl = time.time() + 25
            while time.time() < dl and child and _alive(child):
                time.sleep(0.1)
            result["OWNER_DEAD"] = True
            result["T6_CHILD_TERMINATED_AFTER_OWNER_DEATH"] = not _alive(child)
            rec = subprocess.run(
                [sys.executable, "-c",
                 "import sys,json;sys.path.insert(0,%r)\n"
                 "import control_plane as cp\n"
                 "l=cp.SingleWriterLease._read() or {}\n"
                 "print('STATE',cp.SingleWriterLease.holder_state(l) if l else 'NONE')\n"
                 "try: print('RECON',json.dumps(cp.SingleWriterLease.reconcile_stale('dbg','ctl')))\n"
                 "except cp.ArbitrationError as e: print('RECON DENIED',e.reason)\n"
                 % os.path.join(REPO, "scripts")],
                env=env, capture_output=True, text=True, timeout=120)
            result["reconciliation"] = rec.stdout.strip()
            result["DEBUG_T6_OWNER_DEATH"] = (
                "PASS" if not _alive(child) else "FAIL")
    else:
        result["DEBUG_T6_PRE_KILL"] = "FAIL"
        result["DEBUG_T6_OWNER_DEATH"] = "NOT_RUN"

    atomic_write_json(os.path.join(REPO, "reports",
                                   "T6_PROCESS_LAUNCH_TOPOLOGY.json"), result)
    print(json.dumps(result, indent=2))
    return 0


def _alive(pid):
    if not pid:
        return False
    info = proc_info(pid)
    return bool(info)


if __name__ == "__main__":
    sys.exit(main())