"""Consolidated final report for the CARLA final remediation batch.

Emits the Phase 22 status block plus per-domain JSON artifacts. Read-only with
respect to every protected path; the only live queries are OS/drive facts.
"""

from __future__ import annotations

import json
import os
import subprocess
import time

REPO = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"
REPORTS = os.path.join(REPO, "reports")
XODR = r"G:\CARLA\carla_source_probe\Import\Ingolstadt\ingolstadt_perception_map_of_record_20260916_232831.xodr"


def ps(script, timeout=300):
    p = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                       capture_output=True, text=True, errors="replace",
                       timeout=timeout)
    return p.stdout.strip()


def jload(name):
    p = os.path.join(REPORTS, name)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def drives():
    rows = []
    for letter in ("C", "E", "F", "G", "H"):
        out = ps(r"""
$l=Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='%s:'"
if($l){
  $p=Get-Partition -DriveLetter %s
  $d=Get-Disk -Number $p.DiskNumber
  [pscustomobject]@{
    drive='%s'; disk=$p.DiskNumber; bus=[string]$d.BusType
    friendly=[string]$d.FriendlyName
    total_gb=[math]::Round($l.Size/1GB,2); free_gb=[math]::Round($l.FreeSpace/1GB,2)
    fixed=([string]$d.BusType -ne 'USB'); boot=$d.IsBoot; system=$d.IsSystem
    health=[string]$d.HealthStatus}|ConvertTo-Json -Compress}
""" % (letter, letter, letter))
        if not out:
            continue
        try:
            rows.append(json.loads(out))
        except ValueError:
            pass
    return rows


def memory():
    out = ps(r"$o=Get-CimInstance Win32_OperatingSystem; $cs=Get-CimInstance Win32_ComputerSystem; $pf=Get-CimInstance Win32_PageFileUsage; [pscustomobject]@{phys_total_gb=[math]::Round($o.TotalVisibleMemorySize/1MB,2); phys_free_gb=[math]::Round($o.FreePhysicalMemory/1MB,2); commit_limit_gb=[math]::Round($o.TotalVirtualMemorySize/1MB,2); commit_used_gb=[math]::Round(($o.TotalVirtualMemorySize-$o.FreeVirtualMemory)/1MB,2); commit_headroom_gb=[math]::Round($o.FreeVirtualMemory/1MB,2); automatic_pagefile=$cs.AutomaticManagedPagefile; pagefiles=@($pf|ForEach-Object{[pscustomobject]@{name=$_.Name;allocated_mb=$_.AllocatedBaseSize;current_mb=$_.CurrentUsage;peak_mb=$_.PeakUsage}})}|ConvertTo-Json -Depth 4 -Compress")
    try:
        return json.loads(out) if out else {}
    except ValueError:
        return {}


def git_worktrees_under_temp():
    p = subprocess.run(["git", "-C", REPO, "worktree", "list", "--porcelain"],
                       capture_output=True, text=True, errors="replace", timeout=300)
    scratch = os.path.normcase(os.path.normpath(
        os.path.join(os.environ["LOCALAPPDATA"], "Temp", "opencode"))).rstrip("\\")
    n = 0
    for line in p.stdout.splitlines():
        if line.startswith("worktree "):
            path = os.path.normcase(os.path.normpath(line[9:].strip()))
            if path.startswith(scratch + "\\"):
                n += 1
    return n


def dir_size_gb(path):
    p = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "$s=(Get-ChildItem -LiteralPath '%s' -Recurse -Force -File "
                        "-ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum; "
                        "if($s){[math]::Round($s/1GB,3)}else{0}" % path],
                       capture_output=True, text=True, errors="replace", timeout=1800)
    try:
        return float(p.stdout.strip())
    except ValueError:
        return None


def main():
    os.makedirs(REPORTS, exist_ok=True)
    guard = jload("WORKTREE_CLEANUP_GUARD_FINAL.json") or {}
    reloc = jload("WORKTREE_RELOCATION.json") or {}
    dedup = jload("PACKAGE_MANIFEST_DEDUP_CONTRACT.json") or {}
    rhi = jload("WINDOWS_TARGET_RHI_FINAL.json") or {}
    perf = jload("DUPLICATE_PASS_COST.json") or {}

    dv = {d["drive"]: d for d in drives()}
    mem = memory()
    wt_temp = git_worktrees_under_temp()

    g = dv.get("G", {})
    f = dv.get("F", {})

    # ---- Phase 14: reclaim candidate inventory (read-only, no deletion) ----
    candidates = []
    for label, path, reconstructable, in_use, authority in [
        ("stale_ingolstadt_cook_output", r"G:\CARLA\cook_out\Ingolstadt", True, False,
         "SUPERSEDED_COOK_STAGING"),
        ("cook_temp_scratch", r"G:\CARLA\cook_temp", True, False,
         "SUPERSEDED_COOK_STAGING"),
        ("build_logs_archive", r"G:\CARLA\build_logs", True, False,
         "EVIDENCE_DO_NOT_DELETE"),
        ("g_download_dir", r"G:\download", True, False,
         "USER_DATA_UNVERIFIED_AUTHORIZATION"),
        ("g_new_folder", r"G:\New folder", True, False,
         "USER_DATA_UNVERIFIED_AUTHORIZATION"),
        ("g_tmp", r"G:\tmp", True, False, "USER_DATA_UNVERIFIED_AUTHORIZATION"),
    ]:
        if os.path.isdir(path):
            candidates.append({
                "path": path, "size_gb": dir_size_gb(path),
                "reconstructable": reconstructable, "currently_in_use": in_use,
                "authority_status": authority,
                "auto_delete_permitted": False,
            })

    reclaimable = [c for c in candidates
                   if c["authority_status"] == "SUPERSEDED_COOK_STAGING"]
    reclaimable_gb = round(sum(c["size_gb"] or 0 for c in reclaimable), 2)

    cook_gate_gb = 45.0
    g_free = g.get("free_gb")
    storage_gate = (g_free is not None and g_free >= cook_gate_gb)
    projected = round((g_free or 0) + reclaimable_gb, 2)

    report = {
        "schema": "carla_final_remediation_batch/v1",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),

        "worktrees_under_temp_before": 5,
        "worktrees_under_temp_after": wt_temp,
        "cleanup_guard": "PASS" if guard.get("ALL_REQUIRED_PASS") else "FAIL",
        "cleanup_guard_cases": "%s/%s" % (guard.get("passed"), guard.get("total")),
        "worktree_destination": reloc.get("destination_root"),
        "worktree_destination_is_temporary": reloc.get("destination_is_temporary"),
        "worktrees_relocated_ok": reloc.get("relocated_ok"),
        "git_worktree_move_cross_volume": reloc.get("git_worktree_move_cross_volume"),

        "stalled_cook_proven": False,
        "stalled_cook_termination": "NOT_APPLICABLE_COOK_PROCESS_ALREADY_EXITED",
        "cook_stall_root_cause": "SHADER_COMPILE",
        "cook_stall_evidence": {
            "last_completed_package": "2975/3558",
            "packages_remaining": 583,
            "last_shader_task": "LogShaderCompilers: Worker (2/4): shaders left to compile 15034",
            "virtual_memory_max_mib": 6822,
            "virtual_memory_final_mib": 6793,
            "open_file_handles_frozen_at": 3559,
            "ddc_warnings_0_to_0_02_mb_s": 8,
            "cook_process_exit_observed": True,
            "premise_correction": (
                "The cook process (PID 5344) had already exited before sampling; "
                "the currently running UE4Editor (PID 35812) is a CARLA runtime "
                "server (-game -carla-server), not a cook, and was not touched."),
            "commit_pressure": "NOT_PROVEN_REFUTED",
            "ddc_pathology": "PROVEN",
        },

        "duplicate_manifest_root_cause": (
            "get_packages_json_list() was name-agnostic and returned both "
            "Ingolstadt.json and package.json, which are byte-identical "
            "(SHA256 DA5EB6EA9598DFC5005C283181E99C0EC605D477DA1502401C434AA317F01024), "
            "so the same 20-tile package was imported twice into two different "
            "content folders (package name derived from file name)."),
        "duplicate_manifest_fix": "PASS" if dedup.get("ALL_REQUIRED_PASS") else "FAIL",
        "duplicate_manifest_dedup_cases": "%s/%s" % (dedup.get("passed"), dedup.get("total")),
        "import_tile_executions_before": dedup.get("IMPORT_TILE_EXECUTIONS_BEFORE"),
        "import_tile_executions_after": dedup.get("IMPORT_TILE_EXECUTIONS_AFTER"),
        "second_identical_import_pass": perf.get("SECOND_IDENTICAL_IMPORT_PASS"),
        "measured_removed": {
            "staticmesh_builds": perf.get("staticmesh_builds_removed"),
            "distance_field_builds": perf.get("distance_field_builds_removed"),
            "asset_saves": perf.get("asset_saves_removed"),
        },

        "pcd3d_es31_before": True,
        "pcd3d_es31_after": rhi.get("PCD3D_ES31_ENABLED"),
        "windows_targeted_rhis_after": rhi.get("windows_targeted_rhis"),
        "required_runtime_shader_failures": rhi.get("REQUIRED_RUNTIME_SHADER_FAILURES"),

        "ddc_old_path": r"G:\UnrealEngine_4.26_CARLA\Engine\DerivedDataCache",
        "ddc_new_path": r"F:\UnrealEngine_DDC",
        "ddc_target_fixed_or_removable": ("FIXED_LOCAL" if f.get("fixed")
                                          else "REMOVABLE_USB"),
        "ddc_target_bus_type": f.get("bus"),
        "ddc_target_free_gb": f.get("free_gb"),
        "ddc_read_before_mbps": "0.00-0.08",
        "ddc_read_after_mbps": "NOT_MEASURED",
        "ddc_qualified": "DEFERRED_NOT_APPLIED",

        "pagefile_old_target": "C:\\pagefile.sys (system-managed, 9216 MB)",
        "pagefile_new_target": "UNSET",
        "pagefile_target_type": "FIXED_LOCAL_CANDIDATE_F",
        "pagefile_reboot_required": "PENDING_REBOOT",
        "pagefile_policy": "EXPLICITLY_DEFERRED",
        "commit_limit_before_gb": mem.get("commit_limit_gb"),
        "commit_limit_after_gb": mem.get("commit_limit_gb"),

        "memory_policy": "DEFERRED_PENDING_CORRECTION",
        "memory_policy_finding": (
            "MemoryMaxUsedVirtual/MemoryMinFreeVirtual are CookOnTheFlyServer "
            "settings read from [CookSettings] in GEditorIni and compare "
            "MemStats.UsedVirtual / AvailableVirtual, i.e. system-wide commit "
            "charge, not process RSS. PopulateMemorySettings has zero call "
            "sites under Engine/Source/Editor/UnrealEd, so the setting may not "
            "even be reachable in this build; a value must not be applied "
            "before that is proven."),

        "g_free_before_gb": g_free,
        "g_free_after_gb": g_free,
        "storage_gate": "FAIL" if not storage_gate else "PASS",
        "storage_gate_required_gb": cook_gate_gb,
        "storage_gate_reclaimable_candidates_gb": reclaimable_gb,
        "storage_gate_projected_gb": projected,
        "storage_gate_candidates": candidates,
        "storage_gate_note": (
            "G: is a USB-attached disk (Disk 3, Intenso SCSI). No deletion was "
            "performed: only superseded cook staging is auto-permissible, and "
            "the remainder is user data or frozen evidence requiring explicit "
            "authorization."),

        "georef_cxx_review": "PASS_WITH_BLOCKING_DEFECT",
        "georef_build": "NOT_RUN",
        "georef_compiled_tests": "NOT_RUN",
        "georef_parser_finding": (
            "The uncommitted change correctly removes the silent 42/2 default, "
            "fails closed on incomplete geoReference and range-validates "
            "+lat_0/+lon_0. However the authoritative XODR "
            "(SHA256 370ABBBB...) declares <geoReference>+proj=tmerc</geoReference> "
            "with NO +lat_0 and NO +lon_0, so this change would make the "
            "authoritative Ingolstadt map FAIL to parse. Quarantined, not built, "
            "not committed."),
        "georef_parser_sha256": "8D641ACE2CAFD42D1F371549AE1E9966B86FA630262F254797F9359C5503C7C8",
        "georef_parser_head_blob": "cc5d2c947a4541dd7e206d8ed5469e120935ec7a",

        "map_authority": "370abbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8",
        "absolute_frame_origin": "UNRESOLVED",
        "absolute_frame_origin_evidence": (
            "Header carries <offset hdg=0.0 z=0.0 x=832671.676 y=5458671.104> "
            "and a bare <geoReference>+proj=tmerc</geoReference> with no "
            "lat_0/lon_0 and no source-projected absolute origin."),

        "primary_asset_status": (
            "STOCK_CARLA_BEHAVIOR_NON_BLOCKING_FOR_INGOLSTADT"),
        "reference_5711_status": "LIKELY_INTERRUPTED_IMPORT_ARTIFACT_NOT_YET_PROVEN",

        "bounded_cook": "NOT_RUN",
        "single_tile_import": "NOT_RUN",
    }

    blockers = []
    if report["storage_gate"] == "FAIL":
        blockers.append("STORAGE_GATE_BLOCKED")
    blockers.append("GEOREFERENCE_PARSER_QUARANTINED_MAP_UNPARSEABLE")
    blockers.append("MEMORY_POLICY_NOT_QUALIFIED")
    blockers.append("PAGEFILE_POLICY_DEFERRED")
    blockers.append("DDC_NOT_QUALIFIED")
    blockers.append("BOUNDED_COOK_NOT_RUN")

    gate = {
        "REGISTERED_WORKTREES_UNDER_TEMP": 0 if wt_temp == 0 else "BLOCKED",
        "CLEANUP_GUARD": report["cleanup_guard"],
        "DUPLICATE_PACKAGE_IMPORT": report["duplicate_manifest_fix"],
        "IMPORT_TILE_EXECUTIONS": report["import_tile_executions_after"],
        "ES31_REMOVED": report["pcd3d_es31_after"] is False,
        "DDC_QUALIFIED": False,
        "MEMORY_POLICY_QUALIFIED": False,
        "PAGEFILE_POLICY_QUALIFIED": False,
        "STORAGE_GATE": report["storage_gate"],
        "BOUNDED_COOK": "NOT_RUN",
        "SINGLE_TILE_IMPORT": "NOT_RUN",
        "GEOREFERENCE_PARSER": "FAIL_BLOCKING",
    }
    # Each gate is compared against its exact expected value. Using a generic
    # truthiness test would be wrong here: in Python `False == 0`, so a failed
    # boolean gate would silently satisfy a `== 0` check.
    gate["FULL_PRODUCTION_COOK_ALLOWED"] = bool(
        wt_temp == 0
        and report["cleanup_guard"] == "PASS"
        and report["duplicate_manifest_fix"] == "PASS"
        and report["import_tile_executions_after"] == 20
        and report["pcd3d_es31_after"] is False
        and report["ddc_qualified"] == "QUALIFIED"
        and report["memory_policy"] == "QUALIFIED"
        and report["pagefile_policy"] == "QUALIFIED"
        and report["storage_gate"] == "PASS"
        and report["bounded_cook"] == "PASS"
        and report["single_tile_import"] == "PASS"
        and report["georef_cxx_review"] == "PASS"
        and report["georef_build"] == "PASS"
        and report["georef_compiled_tests"] == "PASS"
    )
    report["authorization_gate"] = gate
    report["blockers"] = blockers
    report["FINAL_VERDICT"] = "PARTIAL_WITH_EXACT_BLOCKERS"

    out = os.path.join(REPORTS, "FINAL_REMEDIATION_BATCH_REPORT.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print(json.dumps(report, indent=2))
    print("\nWROTE %s" % out)


if __name__ == "__main__":
    main()
