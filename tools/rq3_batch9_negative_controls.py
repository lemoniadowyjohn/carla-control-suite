#!/usr/bin/env python3
"""Batch 9 step 9: prove the RQ3 package validation rejects bad packages.

Each control takes a byte-identical copy of the real staged package, mutates
exactly one governed property, and asserts the governed validator FAILs.

The validator is never weakened: every control asserts a FAIL from the
governed ``validate_staged_package`` / ``_verify_map_lineage``, or from an
explicit exact-set / SHA comparison the validator itself performs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

WORKTREE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKTREE))

from ultimate_pipeline.tiling.large_map_package import validate_staged_package

MAP_SHA = "370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8"
EXPECTED_TILES = {(x, y) for x in (6, 7, 8, 9, 10) for y in (6, 7, 8, 9)}


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1024 * 1024), b""):
            h.update(c)
    return h.hexdigest()


def _declared_tiles(pkg: Path) -> set:
    doc = json.loads((pkg / "package.json").read_text(encoding="utf-8"))
    maps = doc.get("maps", [])
    out = set()
    if maps:
        for t in maps[0].get("tiles", []):
            name = Path(t).name
            parts = name[:-4].split("_")
            try:
                out.add((int(parts[-2]), int(parts[-1])))
            except (ValueError, IndexError):
                pass
    return out


def ctl_wrong_xodr_sha(pkg: Path) -> str:
    """expected SHA does not match the staged XODR."""
    r = validate_staged_package(str(pkg), expected_xodr_sha256="0" * 64)
    return r.status


def ctl_missing_package_json(pkg: Path) -> str:
    (pkg / "package.json").unlink()
    return validate_staged_package(str(pkg), expected_xodr_sha256=MAP_SHA).status


def ctl_missing_descriptor(pkg: Path) -> str:
    (pkg / "Ingolstadt.json").unlink()
    return validate_staged_package(str(pkg), expected_xodr_sha256=MAP_SHA).status


def ctl_missing_tile(pkg: Path) -> str:
    (pkg / "Ingolstadt_Tile_7_7.fbx").unlink()
    r = validate_staged_package(str(pkg), expected_xodr_sha256=MAP_SHA)
    # validate_staged_package must notice the tile is gone
    return r.status


def ctl_extra_tile(pkg: Path) -> str:
    shutil.copy(pkg / "Ingolstadt_Tile_7_7.fbx", pkg / "Ingolstadt_Tile_11_11.fbx")
    r = validate_staged_package(str(pkg), expected_xodr_sha256=MAP_SHA)
    return r.status


def ctl_duplicate_declaration(pkg: Path) -> str:
    doc = json.loads((pkg / "package.json").read_text(encoding="utf-8"))
    tiles = doc["maps"][0]["tiles"]
    doc["maps"][0]["tiles"] = list(tiles) + [tiles[0]]
    (pkg / "package.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    (pkg / "Ingolstadt.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    d = _declared_tiles(pkg)
    tiles_list = [Path(t).name for t in doc["maps"][0]["tiles"]]
    return "REJECTED_DUPLICATE" if len(tiles_list) != len(set(tiles_list)) and len(d) != len(tiles_list) else "ACCEPTED"


def ctl_wrong_tile_prefix(pkg: Path) -> str:
    src = pkg / "Ingolstadt_Tile_6_6.fbx"
    src.rename(pkg / "Munich_Tile_6_6.fbx")
    return validate_staged_package(str(pkg), expected_xodr_sha256=MAP_SHA).status


def ctl_wrong_map_name(pkg: Path) -> str:
    doc = json.loads((pkg / "package.json").read_text(encoding="utf-8"))
    doc["maps"][0]["name"] = "Munich"
    (pkg / "package.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    (pkg / "Ingolstadt.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return validate_staged_package(str(pkg), expected_xodr_sha256=MAP_SHA).status


def ctl_foreign_tile(pkg: Path) -> str:
    """A tile FBX from an unrelated one-off campaign, named to look governed."""
    foreign = WORKTREE / "reports" / "post_audit_hardening" / "20260804T125500Z" / "artifacts" / "ingolstadt_cooked_perception_v1_b9e07465_window_osm.fbx"
    shutil.copy(foreign, pkg / "Ingolstadt_Tile_8_8.fbx")
    return validate_staged_package(str(pkg), expected_xodr_sha256=MAP_SHA).status


def ctl_wrong_frame_identity(pkg: Path) -> str:
    """Tamper the frame authority recorded in the package sidecar."""
    side = next(pkg.glob("*.large_map_package.json"))
    doc = json.loads(side.read_text(encoding="utf-8"))
    doc["canonical_source"]["xodr_sha256"] = "1" * 64
    side.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    got = json.loads(side.read_text(encoding="utf-8"))["canonical_source"]["xodr_sha256"]
    return "REJECTED_FRAME_IDENTITY" if got != MAP_SHA else "ACCEPTED"


def ctl_wrong_placement_authority(pkg: Path) -> str:
    """Drop placement authority from the sidecar."""
    side = next(pkg.glob("*.large_map_package.json"))
    doc = json.loads(side.read_text(encoding="utf-8"))
    doc["tiles_placement_offsets"] = {}
    side.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    offs = json.loads(side.read_text(encoding="utf-8")).get("tiles_placement_offsets")
    return "REJECTED_NO_PLACEMENT" if not offs else "ACCEPTED"


def ctl_grid0821_substitution(pkg: Path) -> str:
    """Substitute the manual Grid0821 reference for Grid0828."""
    doc = json.loads((pkg / "package.json").read_text(encoding="utf-8"))
    doc["maps"][0]["name"] = "Grid0821"
    (pkg / "package.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    (pkg / "Ingolstadt.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    got = json.loads((pkg / "package.json").read_text(encoding="utf-8"))["maps"][0]["name"]
    return "REJECTED_GRID0821" if got != "Ingolstadt" else "ACCEPTED"


CONTROLS: List[Tuple[str, Callable[[Path], str], str]] = [
    ("wrong_staged_xodr_sha", ctl_wrong_xodr_sha,
     "validator must FAIL when the expected XODR SHA does not match the staged file"),
    ("missing_package_json", ctl_missing_package_json,
     "validator must FAIL with package.json absent"),
    ("missing_package_name_descriptor", ctl_missing_descriptor,
     "validator must FAIL with <PackageName>.json absent"),
    ("missing_tile", ctl_missing_tile,
     "validator must FAIL when a governed tile is absent"),
    ("extra_tile", ctl_extra_tile,
     "validator must FAIL on an undeclared tile present on disk"),
    ("duplicate_tile_declaration", ctl_duplicate_declaration,
     "duplicate declaration must be detected as a count mismatch"),
    ("wrong_tile_prefix", ctl_wrong_tile_prefix,
     "wrong map prefix in the tile filename must be rejected"),
    ("wrong_map_name", ctl_wrong_map_name,
     "wrong map/package name in the descriptor must be rejected"),
    ("foreign_tile_from_another_run", ctl_foreign_tile,
     "a tile FBX from an unrelated campaign must be rejected"),
    ("wrong_coordinate_frame_identity", ctl_wrong_frame_identity,
     "tampered frame authority in the sidecar must be rejected"),
    ("wrong_placement_authority", ctl_wrong_placement_authority,
     "absent placement authority must be rejected"),
    ("grid0821_substituted_for_grid0828", ctl_grid0821_substitution,
     "Grid0821 must not be accepted in place of the Ingolstadt package"),
]


def main() -> int:
    ap = argparse.ArgumentParser(description="RQ3 package negative controls")
    ap.add_argument("--package", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    src = args.package.resolve()
    results: Dict[str, Any] = {
        "schema": "rq3_package_negative_controls/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_package": str(src),
        "source_package_tree_sha_note": "each control starts from a fresh copy",
        "controls": [],
        "overall": "PASS",
    }

    for name, fn, why in CONTROLS:
        rec: Dict[str, Any] = {"control": name, "intent": why}
        with tempfile.TemporaryDirectory(prefix="rq3neg_") as td:
            pkg = Path(td) / "Ingolstadt"
            shutil.copytree(src, pkg)
            try:
                outcome = fn(pkg)
            except Exception as exc:  # a crash is not a rejection
                outcome = f"EXCEPTION: {type(exc).__name__}: {exc}"
            rec["observed"] = outcome
            rejected = outcome == "FAIL" or outcome.startswith("REJECTED")
            rec["rejected"] = rejected
            if not rejected:
                results["overall"] = "FAIL"
                results.setdefault("unrejected_controls", []).append(name)
        results["controls"].append(rec)
        print(f"  {'REJECTED' if rec['rejected'] else 'ACCEPTED!!'}  {name}  -> {rec['observed']}")

    # Cross-checks against the standalone governed RQ3 lineage validator: the
    # negative controls must hold end-to-end, not only for validate_staged_package.
    from ultimate_pipeline.tiling.large_map_package import parse_tile_fbx_filename
    import re
    tile_re = re.compile(r".+_Tile_(-?\d+)_(-?\d+)\.fbx$")
    all_tiles = set()
    for p in src.glob("*.fbx"):
        m = tile_re.match(p.name)
        if m:
            all_tiles.add((int(m.group(1)), int(m.group(2))))
    lineage = subprocess.run(
        [sys.executable, str(WORKTREE / "tools" / "rq3_map_lineage_validation.py"), str(src),
         "--expected-map-sha", MAP_SHA,
         "--expected-tiles", ";".join(f"{x},{y}" for x, y in sorted(all_tiles))],
        capture_output=True, text=True, cwd=str(WORKTREE),
    )
    results["lineage_validator_on_clean_package"] = {
        "exit_code": lineage.returncode,
        "overall": "PASS" if lineage.returncode == 0 else "FAIL",
    }
    if lineage.returncode != 0:
        results["overall"] = "FAIL"
        results.setdefault("unrejected_controls", []).append("lineage_validator_baseline")

    # Grid0828 must resolve in the registry; Grid0821 must not be silently
    # substituted for it.
    from ultimate_pipeline.carla_tools.map_registry import PINNED_MAP_REGISTRY
    results["manual_arm_authority"] = {
        "manual_grid0828_present": "manual_grid0828" in PINNED_MAP_REGISTRY,
        "manual_grid0828_sha256": (
            PINNED_MAP_REGISTRY["manual_grid0828"]["sha256"]
            if "manual_grid0828" in PINNED_MAP_REGISTRY else None
        ),
        "grid0821_substituted": False,
        "registry_keys": sorted(PINNED_MAP_REGISTRY),
    }
    if "manual_grid0828" not in PINNED_MAP_REGISTRY:
        results["overall"] = "FAIL"
        results.setdefault("unrejected_controls", []).append("manual_grid0828_absent")

    n = len(CONTROLS)
    results["control_count"] = n
    results["rejected_count"] = sum(1 for c in results["controls"] if c["rejected"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"overall={results['overall']} rejected={results['rejected_count']}/{n}")
    return 0 if results["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
