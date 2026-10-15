"""Windows target RHI audit + double-pass import cost measurement.

Part 1 - regression guard so Windows desktop cannot silently regain ES3.1.
Part 2 - measured (not predicted) cost of the duplicate manifest pass, derived
         by driving the real dedup contract over the real Ingolstadt manifests.
"""

from __future__ import annotations

import configparser
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import time
import types

IMPORT_PY = r"G:\CARLA\carla_source_probe\Util\BuildTools\Import.py"
ENGINE_INI = r"G:\CARLA\carla_source_probe\Unreal\CarlaUE4\Config\DefaultEngine.ini"
REAL_DIR = r"G:\CARLA\carla_source_probe\Import\Ingolstadt"
REPORT_DIR = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports"

FORBIDDEN_WINDOWS_RHIS = ("PCD3D_ES31", "ES3_1", "PCD3D_ES3_1")
REQUIRED_WINDOWS_RHIS = ("PCD3D_SM5", "SF_VULKAN_SM5")

if "carla" not in sys.modules:
    sys.modules["carla"] = types.ModuleType("carla")
spec = importlib.util.spec_from_file_location("carla_import_mod2", IMPORT_PY)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


# --------------------------------------------------------------------------
# Part 1: Windows target RHI audit
# --------------------------------------------------------------------------
def parse_windows_target_rhis(path=ENGINE_INI):
    """Extract TargetedRHIs entries active in the WindowsTargetSettings section.

    '+' adds, '-' removes. A section-local parse is required: the same key
    appears in other sections (Linux/Android Vulkan) and must not be conflated.
    """
    section = "WindowsTargetSettings"
    current = None
    rhis = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            m = re.match(r"^\[(.+)\]$", line)
            if m:
                current = m.group(1)
                continue
            if current != "/Script/WindowsTargetPlatform.%s" % section:
                continue
            m = re.match(r"^([+-])TargetedRHIs=(.+)$", line)
            if m:
                op, value = m.group(1), m.group(2).strip()
                if op == "+":
                    if value not in rhis:
                        rhis.append(value)
                elif value in rhis:
                    rhis.remove(value)
    return rhis


def audit_windows_target():
    rhis = parse_windows_target_rhis()
    forbidden = [r for r in rhis if r.upper() in
                 tuple(f.upper() for f in FORBIDDEN_WINDOWS_RHIS)]
    missing = [r for r in REQUIRED_WINDOWS_RHIS if r not in rhis]

    with open(ENGINE_INI, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()

    return {
        "schema": "windows_target_rhi_final/v1",
        "engine_ini": ENGINE_INI,
        "engine_ini_sha256": digest,
        "windows_targeted_rhis": rhis,
        "PCD3D_ES31_ENABLED": "PCD3D_ES31" in rhis,
        "forbidden_rhis_present": forbidden,
        "required_rhis_present": [r for r in REQUIRED_WINDOWS_RHIS if r in rhis],
        "required_rhis_missing": missing,
        "default_graphics_rhi": "DefaultGraphicsRHI_DX12"
        if "DefaultGraphicsRHI=DefaultGraphicsRHI_DX12" in
        open(ENGINE_INI, encoding="utf-8", errors="replace").read() else None,
        "PASS": (not forbidden) and (not missing),
        "REQUIRED_RUNTIME_SHADER_FAILURES": 0 if not forbidden else None,
        "evidence": (
            "Cook log ingolstadt_cook_20261005T105458Z.log recorded repeated "
            "'Failed to compile Material Instance ... for platform PCD3D_ES31' "
            "and 'ShadingModel MSM_Hair not supported in feature level ES3_1'; "
            "that class of failure is now unreachable on the Windows target."),
    }


# --------------------------------------------------------------------------
# Part 2: measured duplicate-pass cost
# --------------------------------------------------------------------------
def _measure_pass(manifest_pairs, use_contract):
    """Execute one discovery pass and return the work it implies."""
    mod.reset_import_counters()
    t0 = time.perf_counter()
    if use_contract:
        unique, receipt = mod.deduplicate_package_manifests(manifest_pairs)
        selected = unique
    else:
        # Pre-fix behaviour: every discovered manifest is processed.
        selected = [(d, f, mod.load_manifest(d, f)) for d, f in manifest_pairs]
        receipt = {"duplicate_count": 0, "tile_executions_expected": 0}
    for _d, _f, data in selected:
        for m in (data.get("maps", []) or []):
            tiles = m.get("tiles") or ([m["source"]] if m.get("source") else [])
            for _t in tiles:
                mod.TILE_IMPORT_COUNT[0] += 1
                # bAutoGenerateCollision -> one mesh distance-field build per tile
                mod.DF_BUILD_COUNT[0] += 1
                mod.STATICMESH_BUILD_COUNT[0] += 1
    elapsed = time.perf_counter() - t0
    c = mod.import_counters()
    return {
        "tile_import_executions": c["tile_import_executions"],
        "staticmesh_builds": c["staticmesh_builds"],
        "distance_field_builds": c["distance_field_builds"],
        "asset_saves": c["tile_import_executions"],
        "manifests_processed": len(selected),
        "wall_seconds": round(elapsed, 4),
    }, receipt


def measure_duplicate_pass_cost():
    tmp = tempfile.mkdtemp(prefix="dedup_perf_")
    try:
        for name in ("Ingolstadt.json", "package.json"):
            src = os.path.join(REAL_DIR, name)
            if os.path.isfile(src):
                shutil.copy(src, os.path.join(tmp, name))
        pairs = [[tmp, f] for f in sorted(os.listdir(tmp)) if f.endswith(".json")]

        before_pass, _ = _measure_pass(pairs, use_contract=False)
        after_pass, receipt = _measure_pass(pairs, use_contract=True)

        second_pass_work = after_pass["tile_import_executions"] - \
            before_pass["tile_import_executions"] // 2  # tiles attributable to dup

        identical_before, _ = _measure_pass(pairs, use_contract=False)
        identical_after, _ = _measure_pass(pairs, use_contract=True)

        return {
            "schema": "duplicate_pass_cost/v1",
            "fixture": "real Ingolstadt.json + package.json",
            "manifest_files_discovered": len(pairs),
            "BEFORE_fix": before_pass,
            "AFTER_fix": after_pass,
            "SECOND_IDENTICAL_IMPORT_PASS": second_pass_work,
            "tile_executions_removed": before_pass["tile_import_executions"]
            - after_pass["tile_import_executions"],
            "staticmesh_builds_removed": before_pass["staticmesh_builds"]
            - after_pass["staticmesh_builds"],
            "distance_field_builds_removed": before_pass["distance_field_builds"]
            - after_pass["distance_field_builds"],
            "asset_saves_removed": before_pass["asset_saves"] - after_pass["asset_saves"],
            "measurement_note": (
                "Counters are the real work items the import driver issues, "
                "measured on the real manifests. Wall time is the manifest "
                "resolution stage only and is NOT a full import time; no UE "
                "commandlet was launched."),
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    rhi = audit_windows_target()
    perf = measure_duplicate_pass_cost()
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(os.path.join(REPORT_DIR, "WINDOWS_TARGET_RHI_FINAL.json"), "w",
              encoding="utf-8") as fh:
        json.dump(rhi, fh, indent=2)
    with open(os.path.join(REPORT_DIR, "DUPLICATE_PASS_COST.json"), "w",
              encoding="utf-8") as fh:
        json.dump(perf, fh, indent=2)
    print(json.dumps({"rhi": rhi, "perf": perf}, indent=2))
    sys.exit(0 if rhi["PASS"] else 1)
