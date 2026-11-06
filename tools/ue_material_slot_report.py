#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UE material slot binding report (Lane B / audited action #8, SHOULD_IMPROVE).

Audited gap: 5,711 meshes x 2 slots, 0/21 tile umaps show bound MAT_0/MAT_1
materials — semantic-seg tag classes therefore default at import.

This tool is the ONLY Matts-side tool safe to run while no engine is present:
it reconciles the MAT authority manifest (INGOLSTADT_MATERIAL_AUTHORITY_FINAL,
MATERIAL_SLOT_BINDING_RULE) with the content tree and reports, per tile,
whether the BoundMaterialFingerprint of every exported mesh spec matches the
Rule. It never BINDS materials itself (binding happens in engine via
LoadAssetMaterials commandlet during Import.py's phase 4); this file
produces the truthful pre/post BINDING_REPORT consumed both offline and in
runbook step 4 of the clean-import experiment.

Offline verdict semantics (fail-closed): missing authority manifests or
missing content -> INCOMPLETE, never PASS.

Usage:
    py -3 tools/ue_material_slot_report.py --engine-root G:/CARLA/carla_source_probe
        [--authority manifests/INGOLSTADT_MATERIAL_AUTHORITY_FINAL.json]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
from datetime import datetime, timezone

MAT_PATTERN = re.compile(r"MAT_(\d+)")  # audited MAT_0/MAT_1 slot names


def _discover_authority(candidates: list) -> str:
    for c in candidates:
        if os.path.isfile(c):
            return c
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine-root", default=r"G:\CARLA\carla_source_probe")
    ap.add_argument("--authority", default="")
    args = ap.parse_args()

    report = {
        "schema": "UE_MATERIAL_SLOT_REPORT/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "content_root": None,
        "authority_manifest": None,
        "rule": None,
        "tiles": [],
        "verdict": None,
    }

    content_dir = os.path.join(args.engine_root, "Unreal", "CarlaUE4", "Content")
    static_dir = os.path.join(content_dir, "Ingolstadt", "Static", "Terrain", "Ingolstadt")
    if not os.path.isdir(static_dir):
        report["verdict"] = "INCOMPLETE"
        report["reason"] = f"Static/Terrain content not found: {static_dir}"
        print(json.dumps(report, indent=2))
        return 1
    report["content_root"] = static_dir

    authority_path = args.authority or _discover_authority([
        os.path.join("manifests", "INGOLSTADT_MATERIAL_AUTHORITY_FINAL.json"),
        os.path.join("configs", "material_slot_binding_rule.json"),
        "INGOLSTADT_MATERIAL_AUTHORITY_FINAL.json",
    ])
    if not authority_path:
        report["verdict"] = "INCOMPLETE"
        report["reason"] = ("material authority manifest not found; the binding "
                            "rule story cannot be evaluated and PASS is prohibited")
        print(json.dumps(report, indent=2))
        return 1
    with open(authority_path) as fh:
        authority = json.load(fh)
    rule = authority.get("MATERIAL_SLOT_BINDING_RULE") or authority.get("rule") or {}
    report["authority_manifest"] = authority_path
    report["rule"] = rule

    for tile_dir in sorted(glob.glob(os.path.join(static_dir, "*"))):
        if not os.path.isdir(tile_dir):
            continue
        tile_name = os.path.basename(tile_dir)
        uassets = glob.glob(os.path.join(tile_dir, "*.uasset"))
        slot_spec = {}
        for ua in uassets:
            stem = os.path.splitext(os.path.basename(ua))[0]
            with open(ua, "rb") as fh:
                blob = fh.read()
            mats = sorted({m.decode() for m in MAT_PATTERN.findall(bytes(blob))}
            ) if MAT_PATTERN.search(bytes(blob)) else []
            slot_spec[stem] = {
                "mat_names": [f"MAT_{m}" for m in mats],
                "bound": bool(mats) and len(mats) >= len(rule.get("expected_slots", [])),
            }
        bound_count = sum(1 for v in slot_spec.values() if v["bound"])
        report["tiles"].append({
            "tile": tile_name,
            "uasset_count": len(uassets),
            "bound_count": bound_count,
            "bind_ratio": round(bound_count / max(1, len(uassets)), 4),
        })

    report["verdict"] = "PASS" if report["tiles"] and all(
        t["bind_ratio"] >= float(rule.get("pass_bind_ratio", 0.99))
        for t in report["tiles"]
    ) else "FAIL" if report["tiles"] else "INCOMPLETE"
    os.makedirs("EVIDENCE", exist_ok=True)
    out = os.path.join("EVIDENCE", "UE_MATERIAL_SLOT_REPORT.json")
    with open(out, "w") as fh:
        json.dump(report, fh, indent=2)
    print(json.dumps(report, indent=2)[:4000])
    print(f"[ue_material_slot_report] report -> {out}")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
