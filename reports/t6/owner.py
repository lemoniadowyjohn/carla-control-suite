import json, os, sys, time, traceback
sys.path.insert(0, 'C:\\Users\\admin\\PycharmProjects\\gpt4\\pythonProject3\\carla_-main\\scripts')
STAGE = 'C:\\Users\\admin\\PycharmProjects\\gpt4\\pythonProject3\\carla_-main\\reports\\t6\\stage.json'
INFO = {}

def publish(stage, **kw):
    rec = {"stage": stage, "ts": time.time(), "owner_pid": os.getpid(),
           "owner_creation_time": INFO.get("ct"), "error": None, **kw}
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
