"""Read-only three-sample stall observer for the owned UE4 cook.

Samples are taken 10 minutes apart. Nothing is terminated here: this script only
records evidence so that the hard-stall contract in Phase 4 can be evaluated
from measurements rather than from absence of activity.

Per sample it records:
  log file size / last write time / tail marker
  cooked package count and packages remaining
  UE4Editor CPU seconds, I/O read+write bytes (deltas)
  working set and private bytes
  ShaderCompileWorker count
  system commit limit / used
  pagefile allocated / current / peak usage
"""

from __future__ import annotations

import ctypes
import glob
import json
import os
import re
import subprocess
import sys
import time

COOK_PID = 5344
PROJ = r"G:\CARLA\carla_source_probe\Unreal\CarlaUE4"
LOG_GLOBS = [
    os.path.join(PROJ, "Saved", "Logs", "*.log"),
    os.path.join(PROJ, "Saved", "Logs", "**", "*.log"),
]
OUT_DIR = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports"
SAMPLE_INTERVAL_SEC = 600
SAMPLES = 3


def process_io(pid):
    """Read cumulative IO counters for a pid (Windows)."""
    try:
        with open(r"\\.\pipe\none", "rb"):
            pass
    except Exception:
        pass
    # Use GetProcessIoCounters via ctypes.
    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong)]
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    counters = IO_COUNTERS()
    try:
        ok = ctypes.windll.kernel32.GetProcessIoCounters(h, ctypes.byref(counters))
        if not ok:
            return None
        return {"read_bytes": counters.ReadTransferCount,
                "write_bytes": counters.WriteTransferCount,
                "read_ops": counters.ReadOperationCount,
                "write_ops": counters.WriteOperationCount}
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def proc_snapshot(pid):
    out = {"pid": pid, "exists": False}
    try:
        import psutil  # type: ignore
        p = psutil.Process(pid)
        out.update({
            "exists": True,
            "cpu_seconds": round(p.cpu_times().user + p.cpu_times().system, 3),
            "working_set_bytes": p.memory_info().rss,
            "private_bytes": getattr(p.memory_info(), "private", 0) or 0,
            "num_threads": p.num_threads(),
            "status": p.status(),
            "create_time": p.create_time(),
        })
        io = process_io(pid)
        if io:
            out.update(io)
        return out
    except ImportError:
        pass
    except Exception as exc:
        out["error"] = repr(exc)
        return out

    # Fallback without psutil.
    p = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "$p=Get-Process -Id %d -ErrorAction SilentlyContinue;"
         "if($p){[pscustomobject]@{cpu=$p.CPU;ws=$p.WorkingSet64;priv=$p.PrivateMemorySize64;"
         "threads=$p.Threads.Count;start=$p.StartTime.ToUniversalTime().ToString('o')}"
         "|ConvertTo-Json -Compress}" % pid],
        capture_output=True, text=True, errors="replace", timeout=120)
    if p.stdout.strip():
        d = json.loads(p.stdout)
        out.update({
            "exists": True,
            "cpu_seconds": float(d.get("cpu") or 0),
            "working_set_bytes": int(d.get("ws") or 0),
            "private_bytes": int(d.get("priv") or 0),
            "num_threads": d.get("threads"),
            "create_time": d.get("start"),
        })
    return out


def count_scw():
    n = 0
    procs = []
    try:
        import psutil  # type: ignore
        for p in psutil.process_iter(["name", "pid"]):
            if (p.info["name"] or "").lower() == "shadercompileworker.exe":
                n += 1
                procs.append(p.info["pid"])
    except Exception:
        pass
    return {"count": n, "pids": procs}


def log_state():
    candidates = []
    for pattern in LOG_GLOBS:
        candidates.extend(glob.glob(pattern, recursive=True))
    candidates = [c for c in candidates if os.path.isfile(c)]
    if not candidates:
        return {"path": None}
    path = max(candidates, key=os.path.getmtime)
    st = os.stat(path)
    tail = ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            fh.seek(max(0, st.st_size - 65536))
            tail = fh.read()
    except OSError:
        pass
    cooked = len(re.findall(r"Cook\s+.*?(?:complete|succeeded)", tail, re.I))
    return {
        "path": path,
        "size_bytes": st.st_size,
        "mtime_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime)),
        "mtime_epoch": st.st_mtime,
        "tail_marker": tail.strip().splitlines()[-1][:300] if tail.strip() else "",
        "total_cook_lines_in_tail": len(re.findall(r"\bCook\b", tail)),
    }


def system_state():
    os_ = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "$o=Get-CimInstance Win32_OperatingSystem;"
         "$pf=Get-CimInstance Win32_PageFileUsage|Select-Object Name,AllocatedBaseSize,CurrentUsage,PeakUsage;"
         "[pscustomobject]@{TotalVisibleKB=$o.TotalVisibleMemorySize;FreePhysKB=$o.FreePhysicalMemory;"
         "TotalVirtKB=$o.TotalVirtualMemorySize;FreeVirtKB=$o.FreeVirtualMemory;"
         "PageFiles=@($pf)}|ConvertTo-Json -Depth 4 -Compress"],
        capture_output=True, text=True, errors="replace", timeout=180)
    d = json.loads(os_.stdout) if os_.stdout.strip() else {}
    total_kb = d.get("TotalVirtKB") or 0
    free_kb = d.get("FreeVirtKB") or 0
    pfs = d.get("PageFiles") or []
    return {
        "commit_limit_bytes": total_kb * 1024,
        "commit_used_bytes": (total_kb - free_kb) * 1024,
        "commit_limit_gb": round(total_kb / 1024 / 1024, 2),
        "commit_used_gb": round((total_kb - free_kb) / 1024 / 1024, 2),
        "commit_headroom_gb": round(free_kb / 1024 / 1024, 2),
        "phys_total_gb": round((d.get("TotalVisibleKB") or 0) / 1024 / 1024, 2),
        "phys_free_gb": round((d.get("FreePhysKB") or 0) / 1024 / 1024, 2),
        "pagefiles": pfs,
    }


def take_sample(index):
    s = {
        "index": index,
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "epoch": time.time(),
        "editor": proc_snapshot(COOK_PID),
        "shader_compile_workers": count_scw(),
        "log": log_state(),
        "system": system_state(),
    }
    dest = os.path.join(OUT_DIR, "COOK_STALL_SAMPLE_%d.json" % index)
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(s, fh, indent=2)
    return s


def main():
    samples = []
    for i in range(1, SAMPLES + 1):
        s = take_sample(i)
        samples.append(s)
        print("sample %d  log=%s bytes  cpu=%.1fs  ws=%dMB  scw=%d  commit=%s/%sGB" % (
            i, s["log"].get("size_bytes"), s["editor"].get("cpu_seconds") or 0.0,
            (s["editor"].get("working_set_bytes") or 0) // (1024 * 1024),
            s["shader_compile_workers"]["count"],
            s["system"]["commit_used_gb"], s["system"]["commit_limit_gb"]), flush=True)
        if i < SAMPLES:
            time.sleep(SAMPLE_INTERVAL_SEC)
    print("DONE")


if __name__ == "__main__":
    main()
