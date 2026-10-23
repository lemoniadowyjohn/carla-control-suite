"""Cross-session process inventory with ancestry and mutation classification.

Read-only. Terminates nothing. Identity is (pid, creation_time) throughout,
because PID reuse across sessions is exactly the failure mode that lets one
session's process be mistaken for another's.
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

WATCHED = {
    "python.exe": "ORCHESTRATOR",
    "opencode.exe": "AGENT_SESSION",
    "hermes.exe": "AGENT_SESSION",
    "ue4editor.exe": "UE_PROCESS",
    "ue4editor-cmd.exe": "UE_PROCESS",
    "shadercompileworker.exe": "SHADER_WORKER",
    "carlaue4.exe": "UE_PROCESS",
    "cmd.exe": "WRAPPER",
    "powershell.exe": "WRAPPER",
    "recaststaticmeshgenerator.exe": "NAV_BUILD",
    "blender.exe": "ASSET_PIPELINE",
    "msbuild.exe": "NATIVE_BUILD",
    "link.exe": "NATIVE_BUILD",
    "cl.exe": "NATIVE_BUILD",
    "unrealbuildtool.exe": "UE_BUILD",
}

# A process class mutates shared state when it can write Content, DDC,
# Binaries, Intermediate, cook output or import settings.
MUTATING_CLASSES = {
    "UE_PROCESS", "SHADER_WORKER", "NAV_BUILD", "ASSET_PIPELINE",
    "NATIVE_BUILD", "UE_BUILD",
}

CARLA_MARKERS = ("carla", "ingolstadt", "unrealengine", "ue4", "opencode")


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


def classify_operation(cmd, cls):
    low = (cmd or "").lower()
    if "ue4editor-cmd" in low or cls == "UE_PROCESS":
        for run, op in [("-run=importassets", "IMPORT"),
                        ("-run=cook", "COOK"),
                        ("-run=prepareassetsforcooking", "PREPARE_ASSETS"),
                        ("-run=moveassets", "MOVE_ASSETS"),
                        ("-run=loadassetmaterials", "LOAD_MATERIALS"),
                        ("-run=resavepackages", "RESAVE")]:
            if run in low:
                return op
        if "-carla-server" in low or " -game" in low:
            return "RUNTIME"
        if "-run=" in low:
            return "UE_COMMANDLET_OTHER"
        return "UE_EDITOR"
    if "import.py" in low:
        return "IMPORT"
    if "buildlibcarla" in low or "msbuild" in low or "libcarla" in low:
        return "BUILD"
    if "build.bat" in low:
        return "BUILD"
    if "shadercompileworker" in low:
        return "SHADER"
    if cls == "AGENT_SESSION":
        return "AGENT"
    if cls == "ORCHESTRATOR":
        return "ORCHESTRATOR"
    return "UNKNOWN"


def main():
    os.makedirs(OUT, exist_ok=True)
    names = ",".join("'%s'" % n for n in WATCHED)
    script = r"""
$rows = @()
foreach ($n in (%s)) {
  foreach ($p in (Get-CimInstance Win32_Process -Filter ("Name='" + $n + "'") -ErrorAction SilentlyContinue)) {
    $gp = Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue
    $parent = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $p.ParentProcessId) -ErrorAction SilentlyContinue
    $io = $null
    try { $io = (Get-CimInstance Win32_Process -Filter ("ProcessId=" + $p.ProcessId)).CommandLine } catch {}
    $rows += [pscustomobject]@{
      pid = $p.ProcessId
      ppid = $p.ParentProcessId
      name = $p.Name
      creation_utc = if ($p.CreationDate) { ([datetime]$p.CreationDate).ToUniversalTime().ToString('o') } else { $null }
      parent_name = if ($parent) { $parent.Name } else { $null }
      parent_creation_utc = if ($parent -and $parent.CreationDate) { ([datetime]$parent.CreationDate).ToUniversalTime().ToString('o') } else { $null }
      command_line = $p.CommandLine
      cpu_s = if ($gp) { [math]::Round($gp.CPU,2) } else { $null }
      ws_mb = if ($gp) { [math]::Round($gp.WorkingSet64/1MB,1) } else { $null }
      private_mb = if ($gp) { [math]::Round($gp.PrivateMemorySize64/1MB,1) } else { $null }
      handles = if ($gp) { $gp.HandleCount } else { $null }
      threads = if ($gp) { $gp.Threads.Count } else { $null }
      responding = if ($gp) { $gp.Responding } else { $null }
      owner = try { (Get-CimInstance Win32_Process -Filter ("ProcessId=" + $p.ProcessId) | Invoke-CimMethod -MethodName GetOwner).User } catch { $null }
    } } }
$rows | ConvertTo-Json -Compress
""" % names
    data = ps(script)
    rows = data if isinstance(data, list) else ([] if data is None else [data])

    by_pid = {r["pid"]: r for r in rows if r.get("pid")}
    records = []
    for r in rows:
        name = (r.get("name") or "?").lower()
        cls = WATCHED.get(name, "OTHER")
        cmd = r.get("command_line") or ""
        low = cmd.lower()
        carla_related = any(m in low or m in name for m in CARLA_MARKERS)
        op = classify_operation(cmd, cls)
        mutates = (cls in MUTATING_CLASSES) and carla_related

        # ancestry up to 4 levels
        chain = []
        cur = r.get("pid")
        seen = set()
        while cur and cur not in seen and len(chain) < 5:
            seen.add(cur)
            rec = by_pid.get(cur)
            if rec is None:
                chain.append({"pid": cur, "name": None, "in_inventory": False})
                break
            chain.append({"pid": cur, "name": rec["name"],
                          "creation_utc": rec["creation_utc"],
                          "in_inventory": True})
            cur = rec.get("ppid")

        records.append({
            "identity_key": "%s|%s" % (r.get("pid"), r.get("creation_utc")),
            "pid": r.get("pid"), "ppid": r.get("ppid"),
            "name": r.get("name"),
            "creation_utc": r.get("creation_utc"),
            "parent_name": r.get("parent_name"),
            "parent_creation_utc": r.get("parent_creation_utc"),
            "command_line": cmd,
            "process_class": cls,
            "operation_class": op,
            "carla_related": carla_related,
            "mutates_shared_state": mutates,
            "cpu_s": r.get("cpu_s"), "ws_mb": r.get("ws_mb"),
            "private_mb": r.get("private_mb"), "handles": r.get("handles"),
            "threads": r.get("threads"), "responding": r.get("responding"),
            "owner_user": r.get("owner"),
            "ancestry": chain,
        })

    mutators = [r for r in records if r["mutates_shared_state"]]

    report = {
        "schema": "CROSS_SESSION_PROCESS_INVENTORY/v1",
        "schema_version": 1,
        "generated_utc": utc_now(),
        "policy": "READ_ONLY__NOTHING_TERMINATED",
        "identity_rule": "pid + process creation time (PID alone is reusable)",
        "process_count": len(records),
        "carla_related_count": len([r for r in records if r["carla_related"]]),
        "mutator_count": len(mutators),
        "mutators": mutators,
        "processes": records,
    }
    atomic_write_json(os.path.join(OUT, "CROSS_SESSION_PROCESS_INVENTORY.json"),
                      report)

    print(json.dumps({
        "process_count": len(records),
        "carla_related": report["carla_related_count"],
        "ACTIVE_MUTATOR_COUNT": len(mutators),
        "mutators": [{"identity_key": m["identity_key"],
                      "pid": m["pid"], "name": m["name"],
                      "operation_class": m["operation_class"],
                      "cpu_s": m["cpu_s"], "ws_mb": m["ws_mb"],
                      "ppid": m["ppid"], "parent_name": m["parent_name"],
                      "owner_user": m["owner_user"]} for m in mutators],
    }, indent=2))


if __name__ == "__main__":
    main()