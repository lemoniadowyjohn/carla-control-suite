"""Enumerate every process that could be mutating CARLA/UE state.

Read-only. Nothing is stopped. The point is to establish who owns the machine
before any machine-touching operation, because PID alone is not an identity:
Windows reuses PIDs, so ownership is recorded as
(ProcessId, CreationDate, resolved image + command line).

Process creation time is read from the OS rather than from Process.StartTime so
that a PID recycled between discovery and inspection is detectable.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import time

REPO = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"
OUT = os.path.join(REPO, "reports")

# Images that can mutate CARLA/UE pipeline state, plus the orchestrators that
# normally launch them.
WATCHED = {
    "UE4EDITOR.EXE": ("UE_RUNTIME_OR_COOK", "Mutates Saved/, DDC, AssetRegistry"),
    "UE4EDITOR-CMD.EXE": ("UE_COMMANDLET", "Mutates Content/, Saved/, cook_out"),
    "SHADERCOMPILEWORKER.EXE": ("SHADER_COMPILER", "Writes DDC shader entries"),
    "PYTHON.EXE": ("ORCHESTRATOR", "Runs Import.py / build wrappers"),
    "CMD.EXE": ("WRAPPER", "Launches build.bat and command chains"),
    "BLENDER.EXE": ("ASSET_PIPELINE", "Geometry export/validation"),
    "RECACSTATICMESHGENERATOR.EXE": ("NAVIGATION_BUILD", "Writes nav binaries"),
    "UNREALBUILDTOOL.EXE": ("UE_BUILD", "Mutates Intermediate/ and Binaries/"),
    "MSBUILD.EXE": ("LIBCARLA_BUILD", "Mutates LibCarla build output"),
    "LINK.EXE": ("LIBCARLA_BUILD", "Mutates LibCarla build output"),
    "CL.EXE": ("LIBCARLA_BUILD", "Mutates LibCarla build output"),
    "GIT.EXE": ("VCS", "Reads/writes worktree + object database"),
}

MUTATING_OPERATIONS = {
    "UE_COMMANDLET", "UE_RUNTIME_OR_COOK", "ASSET_PIPELINE",
    "NAVIGATION_BUILD", "UE_BUILD", "LIBCARLA_BUILD", "ORCHESTRATOR",
}


def ps_json(script, timeout=300):
    p = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                       capture_output=True, text=True, errors="replace",
                       timeout=timeout)
    if not p.stdout.strip():
        return []
    try:
        data = json.loads(p.stdout)
    except ValueError:
        return []
    return data if isinstance(data, list) else [data]


def enumerate_processes():
    script = r"""
$names = @('UE4Editor.exe','UE4Editor-Cmd.exe','ShaderCompileWorker.exe',
           'python.exe','cmd.exe','blender.exe','RecastStaticMeshGenerator.exe',
           'UnrealBuildTool.exe','MSBuild.exe','link.exe','cl.exe','git.exe')
$rows = @()
foreach ($n in $names) {
  $procs = Get-CimInstance Win32_Process -Filter ("Name='" + $n + "'") -ErrorAction SilentlyContinue
  foreach ($p in $procs) {
    $gp = Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue
    $cwd = $null
    try { $cwd = (Get-CimInstance Win32_Process -Filter ("ProcessId=" + $p.ProcessId)).ExecutablePath } catch {}
    $rows += [pscustomobject]@{
      pid = $p.ProcessId
      ppid = $p.ParentProcessId
      name = $p.Name
      creation_date = if ($p.CreationDate) { ([datetime]$p.CreationDate).ToUniversalTime().ToString('o') } else { $null }
      cpu_seconds = if ($gp) { [math]::Round($gp.CPU, 2) } else { $null }
      working_set_mb = if ($gp) { [math]::Round($gp.WorkingSet64/1MB, 1) } else { $null }
      private_mb = if ($gp) { [math]::Round($gp.PrivateMemorySize64/1MB, 1) } else { $null }
      threads = if ($gp) { $gp.Threads.Count } else { $null }
      handles = if ($gp) { $gp.HandleCount } else { $null }
      executable = $cwd
      command_line = $p.CommandLine
      responding = if ($gp) { $gp.Responding } else { $null }
    }
  }
}
$rows | ConvertTo-Json -Compress
"""
    return ps_json(script)


def classify(rec):
    key = rec["name"].upper()
    op, effect = WATCHED.get(key, ("UNKNOWN", "unknown effect"))
    cmd = (rec.get("command_line") or "")
    # Narrow the generic operation label using the actual command line.
    if key == "UE4EDITOR-CMD.EXE" or key == "UE4EDITOR.EXE":
        if "-run=" in cmd:
            for run in ("cook", "ImportAssets", "PrepareAssetsForCooking",
                        "MoveAssets", "LoadAssetMaterials", "ResavePackages",
                        "Cook"):
                if run.lower() in cmd.lower():
                    op = "UE_COMMANDLET:" + run
                    break
            else:
                op = "UE_RUNTIME"
        elif "-carla-server" in cmd or " -game" in cmd:
            op = "UE_CARLA_SERVER"
        else:
            op = "UE_EDITOR_OR_COOK"
    elif key == "PYTHON.EXE":
        if "Import.py" in cmd:
            op = "ORCHESTRATOR:Import.py"
        elif "build" in cmd.lower() and "libcarla" in cmd.lower():
            op = "ORCHESTRATOR:LibCarlaBuild"
        elif "Import.py" not in cmd:
            op = "ORCHESTRATOR:generic"
    elif key == "SHADERCOMPILEWORKER.EXE":
        op = "SHADER_COMPILER"
    return op, effect


def ancestry(pid, by_pid):
    chain = []
    seen = set()
    cur = pid
    while cur and cur not in seen:
        seen.add(cur)
        rec = by_pid.get(cur)
        if rec is None:
            # Parent may not be a watched image; record it opaquely.
            chain.append({"pid": cur, "name": None, "watched": False})
            break
        chain.append({"pid": cur, "name": rec["name"], "watched": True})
        cur = rec["ppid"]
    return chain


def main():
    os.makedirs(OUT, exist_ok=True)
    procs = enumerate_processes()
    by_pid = {p["pid"]: p for p in procs if "pid" in p}

    records = []
    for p in procs:
        if "pid" not in p:
            continue
        op, effect = classify(p)
        records.append({
            "identity": {
                "pid": p["pid"],
                "creation_date_utc": p.get("creation_date"),
                "identity_key": "%s|%s" % (p["pid"], p.get("creation_date")),
            },
            "ppid": p.get("ppid"),
            "name": p.get("name"),
            "executable": p.get("executable"),
            "command_line": p.get("command_line"),
            "cpu_seconds": p.get("cpu_seconds"),
            "working_set_mb": p.get("working_set_mb"),
            "private_mb": p.get("private_mb"),
            "threads": p.get("threads"),
            "handles": p.get("handles"),
            "responding": p.get("responding"),
            "operation_type": op,
            "mutates_pipeline_state": op in MUTATING_OPERATIONS
            or op.startswith("UE_COMMANDLET"),
            "effect": effect,
            "ancestry": ancestry(p["pid"], by_pid),
            "run_receipt": None,
            "owner": None,
            "created_by_this_batch": False,
        })

    # Process-name-free ownership summary, so two runs of this script can be
    # diffed without PID reuse producing false "new process" signals.
    prints = {}
    for rec in records:
        key = (rec["name"] or "?").upper()
        prints.setdefault(key, []).append(rec["identity"]["identity_key"])

    mutating = [r for r in records if r["mutates_pipeline_state"]]

    report = {
        "schema": "active_operation_ownership/v1",
        "schema_version": 1,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "policy": "READ_ONLY__NO_PROCESS_STOPPED",
        "identity_note": (
            "PID alone is not an identity on Windows because PIDs are reused. "
            "Every record carries identity_key = pid|process_creation_time."),
        "watched_process_count": len(records),
        "mutating_process_count": len(mutating),
        "process_name_index": {k: sorted(v) for k, v in sorted(prints.items())},
        "mutating_operations": [
            {
                "operation_type": r["operation_type"],
                "identity_key": r["identity"]["identity_key"],
                "command_line": r["command_line"],
                "started_utc": r["identity"]["creation_date_utc"],
                "cpu_seconds": r["cpu_seconds"],
                "working_set_mb": r["working_set_mb"],
                "effect": r["effect"],
            }
            for r in mutating
        ],
        "processes": records,
    }
    with open(os.path.join(OUT, "ACTIVE_OPERATION_OWNERSHIP.json"), "w",
              encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    with open(os.path.join(OUT, "ACTIVE_OPERATION_OWNERSHIP.csv"), "w",
              newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["identity_key", "ppid", "name", "operation_type",
                    "mutates", "cpu_s", "ws_mb", "handles", "started_utc",
                    "command_line"])
        for r in records:
            w.writerow([r["identity"]["identity_key"], r["ppid"], r["name"],
                        r["operation_type"], r["mutates_pipeline_state"],
                        r["cpu_seconds"], r["working_set_mb"], r["handles"],
                        r["identity"]["creation_date_utc"],
                        (r["command_line"] or "")[:300]])

    print(json.dumps({
        "watched_process_count": len(records),
        "mutating_process_count": len(mutating),
        "mutating_operations": report["mutating_operations"],
    }, indent=2))


if __name__ == "__main__":
    main()
