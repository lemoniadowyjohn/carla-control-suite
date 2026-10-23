"""Observe the in-flight import without interfering with it.

Deliberately read-only: no signals, no writes to Content, no DLL replacement.
Classification is based on measured deltas over an interval, never on process
existence alone, because a live process can be advancing or wedged.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from orch_core import atomic_write_json, utc_now  # noqa: E402

REPO = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"
OUT = os.path.join(REPO, "reports")
CARLA = r"G:\CARLA\carla_source_probe"
CONTENT = os.path.join(CARLA, "Unreal", "CarlaUE4", "Content", "Ingolstadt")
MAPS = os.path.join(CONTENT, "Maps", "Ingolstadt")

TARGET_PID = 12312
PARENT_PID = 10224
INTERVAL_SEC = 45


def ps(script, timeout=300):
    p = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                       capture_output=True, text=True, errors="replace",
                       timeout=timeout)
    out = p.stdout.strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return out


def proc_io(pid):
    """Cumulative IO counters; the delta is what proves forward progress."""
    script = r"""
$p = Get-Process -Id %d -ErrorAction SilentlyContinue
if ($p) {
  $io = Get-CimInstance Win32_Process -Filter ("ProcessId=" + %d)
  [pscustomobject]@{
    pid=%d; alive=$true; cpu_s=[math]::Round($p.CPU,2)
    ws_mb=[math]::Round($p.WorkingSet64/1MB,1)
    private_mb=[math]::Round($p.PrivateMemorySize64/1MB,1)
    handles=$p.HandleCount; threads=$p.Threads.Count
    start=$p.StartTime.ToUniversalTime().ToString('o')
    responding=$p.Responding
  } | ConvertTo-Json -Compress
} else { '{"alive":false}' }
""" % (pid, pid, pid)
    return ps(script)


def content_fingerprint():
    """Cheap structural census of the Content tree, plus tile umap count."""
    census = {"umaps": 0, "tile_umaps": 0, "uassets": 0, "bytes": 0,
              "newest_umap": None, "map_files": {}}
    if not os.path.isdir(MAPS):
        return census
    newest = (0.0, None)
    for root, _dirs, files in os.walk(MAPS):
        for f in files:
            full = os.path.join(root, f)
            try:
                st = os.stat(full)
            except OSError:
                continue
            census["bytes"] += st.st_size
            if f.endswith(".umap"):
                census["umaps"] += 1
                if "_Tile_" in f:
                    census["tile_umaps"] += 1
                rel = os.path.relpath(full, MAPS).replace("\\", "/")
                census["map_files"][rel] = {"bytes": st.st_size,
                                            "mtime_utc": time.strftime(
                                                "%Y-%m-%dT%H:%M:%SZ",
                                                time.gmtime(st.st_mtime))}
                if st.st_mtime > newest[0]:
                    newest = (st.st_mtime, rel)
    if newest[1]:
        census["newest_umap"] = {"path": newest[1], "mtime_utc": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(newest[0]))}
    for root, _dirs, files in os.walk(os.path.join(CONTENT, "Static")):
        census["uassets"] += sum(1 for f in files if f.endswith(".uasset"))
    return census


def newest_logs(limit=4):
    script = r"""
$roots = @('G:\CARLA\carla_source_probe\Unreal\CarlaUE4\Saved\Logs',
           'G:\CARLA\carla_source_probe\Util\BuildTools\_import_supervision',
           'G:\CARLA\build_logs')
$rows = @()
foreach ($r in $roots) {
  if (-not (Test-Path $r)) { continue }
  Get-ChildItem $r -Recurse -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 6 | ForEach-Object {
      $rows += [pscustomobject]@{
        path=$_.FullName; bytes=$_.Length
        mtime_utc=$_.LastWriteTimeUtc.ToString('o') } } }
$rows | Sort-Object mtime_utc -Descending | Select-Object -First %d |
  ConvertTo-Json -Compress
""" % limit
    out = ps(script)
    return out if isinstance(out, list) else ([] if out is None else [out])


def main():
    os.makedirs(OUT, exist_ok=True)

    parent = proc_io(PARENT_PID)
    samples = []
    for i in range(2):
        samples.append({
            "at_utc": utc_now(),
            "target": proc_io(TARGET_PID),
            "content": content_fingerprint(),
            "logs": newest_logs(3),
        })
        if i == 0:
            time.sleep(INTERVAL_SEC)

    a, b = samples
    ta = (a["target"] or {}).get("alive")
    tb = (b["target"] or {}).get("alive")

    cpu_delta = None
    ws_delta = None
    if ta and tb:
        cpu_delta = round((b["target"].get("cpu_s") or 0) - (a["target"].get("cpu_s") or 0), 2)
        ws_delta = round((b["target"].get("ws_mb") or 0) - (a["target"].get("ws_mb") or 0), 1)

    ca, cb = a["content"], b["content"]
    log_grew = False
    for la, lb in zip(a["logs"], b["logs"]):
        if la.get("path") == lb.get("path"):
            if (lb.get("bytes") or 0) > (la.get("bytes") or 0):
                log_grew = True
            break

    progress_signals = {
        "cpu_delta_seconds": cpu_delta,
        "cpu_advancing": bool(cpu_delta and cpu_delta > 0.5),
        "content_bytes_delta": (cb["bytes"] or 0) - (ca["bytes"] or 0),
        "umap_count_delta": cb["umaps"] - ca["umaps"],
        "tile_umap_count_delta": cb["tile_umaps"] - ca["tile_umaps"],
        "uasset_count_delta": cb["uassets"] - ca["uassets"],
        "log_grew": log_grew,
        "interval_sec": INTERVAL_SEC,
    }

    # Classification is derived only from these deltas.
    if not tb:
        status = "IMPORT_FINISHED"
        reason = "PID 12312 is no longer present at the second sample"
    elif progress_signals["cpu_advancing"] or progress_signals["umap_count_delta"] > 0 \
            or progress_signals["uasset_count_delta"] > 0 or log_grew:
        status = "IMPORT_ACTIVE_PROGRESSING"
        reason = ("CPU and/or content and/or log deltas are non-zero over the "
                  "sampling interval")
    else:
        status = "IMPORT_ACTIVE_IDLE"
        reason = ("process is alive but CPU, content and log deltas were all zero "
                  "over the sampling interval; forward progress is NOT proven")

    holds = ps(r"""
$rows = @()
foreach ($dll in @('UE4Editor-Carla.dll')) {
  $hits = @()
  foreach ($p in (Get-Process -ErrorAction SilentlyContinue)) {
    try {
      foreach ($m in $p.Modules) {
        if ($m.ModuleName -eq $dll) { $hits += $p.Id; break } } } catch {} }
  $rows += [pscustomobject]@{ dll=$dll; holder_pids=$hits } }
$rows | ConvertTo-Json -Compress
""")

    report = {
        "schema": "ACTIVE_IMPORT_STATUS/v1",
        "schema_version": 1,
        "generated_utc": utc_now(),
        "policy": "READ_ONLY__NO_INTERFERENCE",
        "target": {
            "pid": TARGET_PID,
            "ppid": PARENT_PID,
            "command_line": ps(
                r"(Get-CimInstance Win32_Process -Filter 'ProcessId=%d').CommandLine"
                % TARGET_PID),
            "alive_first_sample": ta,
            "alive_second_sample": tb,
        },
        "parent_python": parent,
        "samples": samples,
        "progress_signals": progress_signals,
        "status": status,
        "status_reason": reason,
        "dll_holder_check": holds,
        "content_census_now": cb,
    }
    atomic_write_json(os.path.join(OUT, "ACTIVE_IMPORT_STATUS.json"), report)

    print(json.dumps({
        "status": status,
        "reason": reason,
        "progress_signals": progress_signals,
        "alive_first": ta, "alive_second": tb,
        "content": {"umaps": cb["umaps"], "tile_umaps": cb["tile_umaps"],
                    "uassets": cb["uassets"], "bytes": cb["bytes"]},
        "dll_holder_check": holds,
    }, indent=2))


if __name__ == "__main__":
    main()
