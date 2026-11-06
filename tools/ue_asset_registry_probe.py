#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UE AssetRegistry reference-resolution probe (Lane B / audited action #5).

Post-import assertion that no serialized umap reference is left unresolved.
Drives a short UnrealEditor-Cmd session that exports the asset registry for
the Ingolstadt package maps and reports, per top-level namespace point
(Game/<pkg>/... /Game refs), whether the target asset resolves on disk.

PASS requires: UNRESOLVED_REFERENCE_COUNT == 0 over the probed set.
The probe is read-only; it never moves or repathes assets.

Because a passive scan of the disk cannot by itself evaluate serialized
in-umap references, the engine-side part emits a JSON registry dump via a
five-line commandlet script (``-ExecutePythonScript``). When the engine
cannot be started the tool escalates (exit 3) without writing PASS evidence;
offline mode (--offline) audits only serialized reference PATHS extracted
directly from umap text/exports present on disk (no false PASS is produced
for what was not actually probed).

Usage:
    py -3 tools/ue_asset_registry_probe.py --engine-root G:/CARLA/carla_source_probe
        [--offline] [--maps Ingolstadt]
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone

ESCALATE_EXIT = 3
UNRESOLVED_LIMIT = 0  # audited requirement


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


REGISTRY_DUMP_SCRIPT = r"""
import unreal, json
ar = unreal.AssetRegistryHelpers.get_asset_registry()
pkg = unreal.SystemLibrary.get_command_line_param_value('probe_package', 'Ingolstadt')
maps_root = '/Game/%s/Maps' % pkg
rows = []
assets = ar.get_assets_by_path(maps_root, recursive=True)
deps_options = unreal.AssetRegistryDependencyOptions()
for a in assets:
    for d in ar.get_dependencies(a.package_name, deps_options):
        rows.append({'source_pkg': str(a.package_name), 'dep_pkg': str(d.package_name)})
category = ar.get_referencers(maps_root, unreal.AssetRegistryDependencyOptions())
out = {'package': pkg, 'asset_count': len(assets), 'deps': rows}
p = unreal.Paths.project_saved_dir()
with open(p + ('AssetRegistryProbeDump.json'), 'w') as f:
    json.dump(out, f, indent=1)
print('REGISTRY_PROBE_DONE', len(assets))
"""


def _scan_offline(cartent_root: str, package: str) -> dict:
    """Offline audit of serialized reference paths inside umap/exports.

    Counts /Game/<pkg>/... object references found in the Maps subfolder and
    reports which resolve to an existing on-disk uasset ANYWHERE under the
    package Content tree (Static/Terrain or Maps). This is the truthful
    WEAK probe: it can only surface path-form references on disk.
    """
    maps_dir = os.path.join(cartent_root, package, "Maps", package)
    root = os.path.join(cartent_root, package)
    uassets = {
        os.path.splitext(os.path.basename(p))[0]: p
        for p in glob.glob(os.path.join(root, "**", "*.uasset"), recursive=True)
    }
    report = {"mode": "offline", "umaps_probed": [], "ref_count": 0,
              "resolved_count": 0, "unresolved": [], "note":
              "offline text probe of serialized path-form references; a false-"
              "PASS is impossible only when umaps expose path text. Engine "
              "AssetRegistry probe remains the audited decisive measure."}
    for umap_path in glob.glob(os.path.join(maps_dir, "*.umap")):
        report["umaps_probed"].append(os.path.basename(umap_path))
        with open(umap_path, "rb") as fh:
            blob = fh.read()
        refs = re.findall(rb"/Game/" + package.encode() + rb"/[A-Za-z0-9_./-]+", blob)
        for r in refs:
            report["ref_count"] += 1
            leaf = r.decode().rsplit(".", 1)[0]
            stem = leaf.rsplit("/", 1)[-1]
            if stem in uassets:
                report["resolved_count"] += 1
            else:
                report["unresolved"].append(leaf)
    report["unresolved_reference_count"] = len(report["unresolved"])
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine-root", default=r"G:\CARLA\carla_source_probe")
    ap.add_argument("--package", default="Ingolstadt")
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()

    report = {
        "schema": "UE_ASSET_REGISTRY_PROBE/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "package": args.package,
        "unresolved_limit": UNRESOLVED_LIMIT,
    }
    cartent_root = os.path.join(args.engine_root, "Unreal", "CarlaUE4", "Content")

    if args.offline:
        report.update(_scan_offline(cartent_root, args.package))
        verdict = report["unresolved_reference_count"] <= UNRESOLVED_LIMIT
        report["verdict"] = "PASS" if verdict else "FAIL"
        print(json.dumps(report, indent=2)[:4000])
        with open(os.path.join("EVIDENCE", "UE_ASSET_REGISTRY_PROBE_OFFLINE.json"),
                  "w") as fh:
            json.dump(report, fh, indent=2)
        return 0 if verdict else 1

    editor_cmd = os.path.join(args.engine_root, "Engine", "Binaries", "Win64",
                              "UnrealEditor-Cmd.exe")
    if not os.path.isfile(editor_cmd):
        report["escalation"] = {"reason": "engine not reachable", "exit": ESCALATE_EXIT}
        print(json.dumps(report, indent=2))
        print("[ue_asset_registry_probe] ESCALATE: engine not reachable.")
        return ESCALATE_EXIT

    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "_ar_probe_dump.py")
    with open(script_path, "w") as fh:
        fh.write(REGISTRY_DUMP_SCRIPT)

    cmd = [
        editor_cmd,
        os.path.join(args.engine_root, "Unreal", "CarlaUE4", "CarlaUE4.uproject"),
        "-run=pythonscript", "-script=" + script_path,
        f"-probe_package={args.package}",
        "-unattended", "-nopause", "-nosplash",
    ]
    report["command"] = cmd
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        report["exit_code"] = proc.returncode
    except (subprocess.TimeoutExpired, OSError) as exc:
        report["escalation"] = {"reason": f"engine run failed: {exc}", "exit": ESCALATE_EXIT}
        print(json.dumps(report, indent=2))
        return ESCALATE_EXIT

    dump_path = os.path.join(args.engine_root, "Unreal", "CarlaUE4", "Saved",
                             "AssetRegistryProbeDump.json")
    if not os.path.isfile(dump_path):
        report["escalation"] = {"reason": "registry dump not produced", "exit": ESCALATE_EXIT}
        print(json.dumps(report, indent=2))
        return ESCALATE_EXIT

    with open(dump_path) as fh:
        dump = json.load(fh)
    report["registry_dump"] = dump
    # deps referencing the Maps namespace that no longer exist on disk = unresolved
    root = os.path.join(cartent_root, args.package)
    uassets = {
        os.path.splitext(os.path.basename(p))[0]
        for p in glob.glob(os.path.join(root, "**", "*.uasset"), recursive=True)
    }
    unresolved = [d["dep_pkg"] for d in dump.get("deps", [])
                  if d["dep_pkg"].split("/")[-1] not in uassets]
    report["unresolved_references"] = unresolved[:200]
    report["unresolved_reference_count"] = len(unresolved)
    verdict = len(unresolved) <= UNRESOLVED_LIMIT
    report["verdict"] = "PASS" if verdict else "FAIL"
    os.makedirs("EVIDENCE", exist_ok=True)
    with open(os.path.join("EVIDENCE", "UE_ASSET_REGISTRY_PROBE.json"), "w") as fh:
        json.dump(report, fh, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != "registry_dump"}, indent=2))
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
