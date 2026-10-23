import json, os, sys, time, traceback
sys.path.insert(0, 'C:\\Users\\admin\\PycharmProjects\\gpt4\\pythonProject3\\carla_-main\\scripts')
AUTH = 'C:\\Users\\admin\\PycharmProjects\\gpt4\\pythonProject3\\carla_-main\\reports\\t6_runs\\t6_04_52d1b012\\authority.json'
STAGE = 'C:\\Users\\admin\\PycharmProjects\\gpt4\\pythonProject3\\carla_-main\\reports\\t6_runs\\t6_04_52d1b012\\stage.json'
INFO = {}

def publish(stage, **kw):
    rec = {"stage": stage, "ts": time.time(), "owner_pid": os.getpid(),
           "owner_creation_time": INFO.get("ct"),
           "run_id": INFO.get("run_id"), "lease_path": INFO.get("lease_path"),
           "child_pid": INFO.get("child_pid"), "error": None, **kw}
    tmp = STAGE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(rec, fh); fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp, STAGE)

def write_auth(stage, **extra):
    payload = {"schema_version": 1, "stage": stage,
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
               "timestamp": time.time(), "error": None, **extra}
    tmp = AUTH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh); fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp, AUTH)

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
