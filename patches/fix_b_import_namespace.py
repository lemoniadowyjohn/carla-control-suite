#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FIX-B' building namespace patch authority (Lane B, Python-side).

Root cause (BUILDING_REFERENCE_FIX_STATIC_AUDIT, WRONG_SUBPATH_IN_SERIALIZED_REFERENCE,
confirmed): Util/BuildTools/Import.py declares the tile-FBX import destination as
/Game/<package>/Maps/<name>, while CARLA's own large-map/Terrain generation
(MoveAssets relink step) places the meshes at the authoritative
/Game/<package>/Static/Terrain/<name>. The serialized umap references therefore
retain the Maps subpath and all 5,711 building references fail to resolve at
engine import.

Audited fix: change the PRODUCER so the serialized reference matches the
authoritative StaticMesh package location. NEVER move the 5,711 assets.

This file pins the external Import.py identity and applies/dry-runs the
exact patch. The external engine tree is a host dependency: applying the
patch requires a quiescent UE4Editor (no cook/import process active) and is
governed by the batch rule that existed when the fix was first deferred.

Usage:
    py -3 patches/fix_b_import_namespace.py --engine-root G:/CARLA/carla_source_probe
        [--dry-run]   # default: apply; --dry-run prints diff and exits
        [--check]     # only assert the pinned pre-state matches, no edit
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

PRE_IMPORT_PY_SHA256 = "af0f05f1fe0948c00c10f494fb70ee57e18f4c0c84b2814744b1657935e80e79"
PRE_IMPORT_PY_BYTES = 47515
# measured 2026-10-21 against G:/CARLA/carla_source_probe (mtime 2026-10-05T15:14:45Z)

OLD_LINE = '            maps_dest = "/" + "/".join(["Game", package_name, "Maps", umap["name"]])\n'
NEW_LINE = '            maps_dest = "/" + "/".join(["Game", package_name, "Static", "Terrain", umap["name"]])\n'
CONTEXT_BEFORE = '        for umap in maps:\n'
CONTEXT_AFTER_PROBE = '            if "source" in umap:'


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_patch(src_lines: list) -> list:
    """Return the patched line list, raising when the pin does not match."""
    target = src_lines.index(OLD_LINE) if OLD_LINE in src_lines else -1
    if target == -1:
        if NEW_LINE in src_lines:
            raise RuntimeError("FIX-B' already applied: patched maps_dest line present")
        raise RuntimeError("pinned maps_dest line not found; Import.py identity differs from the audited pre-state")
    if src_lines[target - 1] != CONTEXT_BEFORE:
        raise RuntimeError(f"context-before mismatch at line {target}")
    window = "".join(src_lines[target + 1 : target + 8])
    if CONTEXT_AFTER_PROBE not in window:
        raise RuntimeError(f"context-after probe not found within 8 lines after line {target}")
    out = list(src_lines)
    out[target] = NEW_LINE
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine-root", default=r"G:\CARLA\carla_source_probe")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--check", action="store_true")
    args = ap.parse_args()

    import_py = os.path.join(args.engine_root, "Util", "BuildTools", "Import.py")
    if not os.path.isfile(import_py):
        print(f"[FIX-B'] engine Import.py not found: {import_py}")
        return 2

    actual_sha = _sha256(import_py)
    actual_bytes = os.path.getsize(import_py)
    pin_matches = actual_sha == PRE_IMPORT_PY_SHA256 and actual_bytes == PRE_IMPORT_PY_BYTES
    manifest = {
        "schema": "FIX_B_IMPORT_NAMESPACE/v1",
        "original_sha256": PRE_IMPORT_PY_SHA256,
        "original_bytes": PRE_IMPORT_PY_BYTES,
        "observed_sha256": actual_sha,
        "observed_bytes": actual_bytes,
        "pin_matches": pin_matches,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "change": OLD_LINE.rstrip() + "  ->  " + NEW_LINE.rstrip(),
    }

    with open(import_py, "r", encoding="utf-8") as fh:
        lines = fh.readlines()

    try:
        patched = build_patch(lines)
    except RuntimeError as exc:
        print(f"[FIX-B'] {exc}")
        json.dump(manifest, sys.stdout, indent=2)
        print()
        return 1

    if args.check:
        manifest["pin_matches"] = pin_matches
        json.dump(manifest, sys.stdout, indent=2)
        print()
        print("[FIX-B'] pre-state verified; --check does not edit.")
        return 0

    if args.dry_run:
        print("--- " + import_py)
        print(f"@@ -{lines.index(OLD_LINE) - 1 + 1},3 +{lines.index(OLD_LINE) - 1 + 1},3 @@")
        for ln in patched[lines.index(OLD_LINE) - 1 : lines.index(OLD_LINE) + 3]:
            print(ln.rstrip())
        json.dump(manifest, sys.stdout, indent=2)
        print()
        print("[FIX-B'] dry-run only.")
        return 0

    if not pin_matches:
        print("[FIX-B'] REFUSED: Import.py sha does not match the audited pre-state pin.")
        print("         Anchorage-hash mismatch means the producer identity moved;")
        print("         re-run the FIX-A/FIX-B trace before editing.")
        json.dump(manifest, sys.stdout, indent=2)
        print()
        return 1

    with open(import_py, "w", encoding="utf-8", newline="") as fh:
        fh.writelines(patched)
    manifest["applied"] = True
    manifest["post_sha256"] = _sha256(import_py)
    print(json.dumps(manifest, indent=2))
    print("[FIX-B'] applied. Next: 1-tile clean-import decisive experiment +")
    print("         AssetRegistry probe (tools/ue_asset_registry_probe.py).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
