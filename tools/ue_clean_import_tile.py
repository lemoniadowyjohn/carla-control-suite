#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-tile clean-import decisive experiment driver (Lane B / audited action #5).

Runs the smallest tile (Tile_10_8, 5 assets) through a clean CARLA import
against a patched Import.py (FIX-B' building namespace), capturing the UE
log receipt and asserting the marker conditions a bare import cannot fake:

  PRECONDITIONS (refuse without them):
    * engine root exists and contains UnrealEditor-Cmd.exe
    * Import.py at <engine>/Util/BuildTools/Identified sha equality with the
      FIX-B' post-patch sha recorded by patches/fix_b_import_namespace.py
    * no UE4Editor / UnrealEditor process is running (batch rule)
    * engine Import/Ingolstadt does not pre-contain the target tile's FBX
      (clean-import semantics: the tile must not already exist in Content)

  EVIDENCE WRITTEN: EVIDENCE/UE4_IMPORT_RECEIPT_<tile>.json containing
    * scanned_tile_name, engine identity (UnrealEditor-Cmd sha256),
    * Import.py sha256, content_root asset counts pre/post
    * UE log path + exit code + "Building Assets For Windows" marker count

Runtime success REQUIRES the actual commandlet receipt; port/process
existence alone is not evidence. When the engine cannot be reached the
tool exits 3 (host dependency escalation) and writes no PASS evidence.

Usage:
    py -3 tools/ue_clean_import_tile.py --engine-root G:/CARLA/carla_source_probe
        [--tile Tile_10_8] [--dry-run]
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

ESCALATE_EXIT = 3
POST_FIX_IMPORT_PY_SHA256 = None  # filled by fix_b_import_namespace.py apply step
RECEIPT_DIR = os.path.join("EVIDENCE")


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _fail_escalate(reason: str, receipt: dict) -> int:
    receipt["escalation"] = {"reason": reason, "exit_code": ESCALATE_EXIT,
                             "at_utc": datetime.now(timezone.utc).isoformat()}
    os.makedirs(RECEIPT_DIR, exist_ok=True)
    with open(os.path.join(RECEIPT_DIR, "UE4_IMPORT_ESCALATION.json"), "w") as fh:
        json.dump(receipt, fh, indent=2)
    print(f"[ue_clean_import_tile] ESCALATE: {reason}")
    return ESCALATE_EXIT


def _ue_processes_running() -> list:
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq UnrealEditor.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, timeout=60)
    rows = [ln for ln in (out.stdout or "").splitlines() if ln.strip()]
    out2 = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq UE4Editor.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, timeout=60)
    rows2 = [ln for ln in (out2.stdout or "").splitlines() if ln.strip()]
    return rows + rows2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine-root", default=r"G:\CARLA\carla_source_probe")
    ap.add_argument("--tile", default="Tile_10_8")
    ap.add_argument("--package", default="Ingolstadt")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    receipt = {
        "schema": "UE4_IMPORT_RECEIPT/v1",
        "tool": "ue_clean_import_tile.py",
        "tile": args.tile,
        "package": args.package,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "unreal_editor_cmd_sha256": None,
        "import_py_sha256": None,
        "content_asset_count_pre": None,
        "content_asset_count_post": None,
        "ue_log_path": None,
        "exit_code": None,
        "building_assets_marker_count": 0,
        "verdict": None,
    }

    engine = args.engine_root
    editor_cmd = os.path.join(engine, "Engine", "Binaries", "Win64", "UnrealEditor-Cmd.exe")
    if not os.path.isfile(editor_cmd):
        return _fail_escalate(f"UnrealEditor-Cmd.exe missing under {engine}", receipt)
    receipt["unreal_editor_cmd_sha256"] = _sha256(editor_cmd)

    import_py = os.path.join(engine, "Util", "BuildTools", "Import.py")
    if not os.path.isfile(import_py):
        return _fail_escalate(f"Import.py missing under {engine}", receipt)
    receipt["import_py_sha256"] = _sha256(import_py)

    fixb_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "EVIDENCE", "FIX_B_APPLY_MANIFEST.json")
    if os.path.isfile(fixb_path):
        with open(fixb_path) as fh:
            fix_manifest = json.load(fh)
        if fix_manifest.get("post_sha256") != receipt["import_py_sha256"]:
            return _fail_escalate(
                "Import.py sha does not match the FIX-B' post-patch pin", receipt)
    else:
        return _fail_escalate(
            "FIX_B_APPLY_MANIFEST.json missing: run patches/fix_b_import_namespace.py "
            "with a quiescent engine first", receipt)

    running = _ue_processes_running()
    if running:
        return _fail_escalate(
            f"UE4Editor/UnrealEditor processes active ({len(running)} rows); batch rule forbids import",
            receipt)

    content_dir = os.path.join(engine, "Unreal", "CarlaUE4", "Content", args.package)
    static_dir = os.path.join(content_dir, "Static", "Terrain", args.package)
    tile_uassets_pre = []
    if os.path.isdir(static_dir):
        tile_uassets_pre = glob.glob(os.path.join(static_dir, f"{args.tile}_*.uasset"))
    if tile_uassets_pre:
        return _fail_escalate(
            f"clean-import precondition violated: {len(tile_uassets_pre)} {args.tile} "
            "uassets already present in Static/Terrain content", receipt)
    receipt["content_asset_count_pre"] = len(glob.glob(os.path.join(static_dir, "*.uasset"))) \
        if os.path.isdir(static_dir) else 0

    fbx_dir = os.path.join(engine, "Import", args.package)
    tile_fbx = os.path.join(fbx_dir, f"{args.package}_{args.tile}.fbx")
    if not os.path.isfile(tile_fbx):
        return _fail_escalate(f"tile FBX missing: {tile_fbx}", receipt)

    if args.dry_run:
        print("[ue_clean_import_tile] dry-run: preconditions verified, no engine run.")
        print(json.dumps(receipt, indent=2))
        return 0

    cmd = [
        sys.executable,
        os.path.join(engine, "Util", "BuildTools", "Import.py"),
        "--package", f"{args.package}NoSig",
    ]
    receipt["command"] = cmd
    try:
        proc = subprocess.run(cmd, cwd=engine, capture_output=True, text=True, timeout=7200)
        receipt["exit_code"] = proc.returncode
    except subprocess.TimeoutExpired:
        return _fail_escalate("Import.py run exceeded 7200 s timeout", receipt)
    except OSError as exc:
        return _fail_escalate(f"engine invocation failed: {exc}", receipt)

    log_dir = os.path.join(engine, "Unreal", "CarlaUE4", "Saved", "Logs")
    logs = sorted(glob.glob(os.path.join(log_dir, "CarlaUE4.log*")), key=os.path.getmtime)
    if logs:
        receipt["ue_log_path"] = logs[-1]
        with open(logs[-1], "r", encoding="utf-8", errors="replace") as fh:
            log_text = fh.read()
        receipt["building_assets_marker_count"] = log_text.count("Building Assets For Windows")
        tile_asset_ready = log_text.count(f"{args.tile}_Building")
    else:
        tile_asset_ready = 0

    static_after = glob.glob(os.path.join(static_dir, f"{args.tile}_*.uasset")) \
        if os.path.isdir(static_dir) else []
    receipt["content_asset_count_post"] = len(static_after)
    receipt["tile_uassets"] = [os.path.basename(p) for p in static_after]
    receipt["tile_asset_ready_markers"] = tile_asset_ready

    ok = (
        receipt["exit_code"] == 0
        and len(static_after) > 0
        and tile_asset_ready > 0
    )
    receipt["verdict"] = "PASS" if ok else "FAIL"
    os.makedirs(RECEIPT_DIR, exist_ok=True)
    out_path = os.path.join(RECEIPT_DIR, f"UE4_IMPORT_RECEIPT_{args.tile}.json")
    with open(out_path, "w") as fh:
        json.dump(receipt, fh, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"[ue_clean_import_tile] receipt -> {out_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
