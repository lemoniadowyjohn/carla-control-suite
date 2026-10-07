#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 8: offline revalidation of the promoted large-map package.

Checks (all offline, no UE4, no CARLA):
  1. exactly the 20 governed tiles are present, no extras, no gaps
  2. the whole-map XODR SHA256 is byte-exact against the registry pin
  3. package.json parses and its declared fields agree with disk
  4. the package-name mirror descriptor is byte-identical to package.json
  5. every tile's SHA256 matches the sidecar manifest (no substitution)
  6. coordinate identity is exact (frame_id + rebase offsets)
  7. the candidate commit is recorded explicitly

Emits STAGED_PACKAGE_REVALIDATION.json.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

PKG = Path(r"E:\CARLA\CARLA_0.9.16\Import\Ingolstadt")
EXPECTED_XODR_SHA = "370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8"
EXPECTED_TILES = [(tx, ty) for tx in range(6, 11) for ty in range(6, 10)]
EXPECTED_FRAME = {
    "frame_id": "ingolstadt_local_rebased",
    "frame_kind": "rebased_local",
    "rebase_dx": 832671.676,
    "rebase_dy": 5458671.104,
}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    import subprocess

    from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map
    from ultimate_pipeline.tiling.large_map_package import (
        parse_tile_fbx_filename,
        validate_staged_package,
    )

    pinned = verify_pinned_map("auto_map_of_record")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(REPO), capture_output=True, text=True
    ).stdout.strip()

    rep: Dict[str, Any] = {
        "schema": "staged_package_revalidation/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "package_dir": str(PKG),
        "candidate_commit": commit,
        "registry_pin": {
            "registry_key": "auto_map_of_record",
            "sha256": pinned["sha256_actual"],
            "bytes": pinned["bytes_actual"],
            "resolved_path": pinned["resolved_path"],
        },
        "checks": {},
        "failures": [],
    }
    fail = rep["failures"]

    if not PKG.is_dir():
        fail.append(f"promoted package directory missing: {PKG}")
        rep["status"] = "FAIL"
        print(json.dumps(rep, indent=2))
        return 2

    # --- governed validator (the real offline gate) ----------------------
    v = validate_staged_package(str(PKG), expected_xodr_sha256=EXPECTED_XODR_SHA)
    rep["governed_validator"] = v.to_dict()
    if v.status != "PASS":
        fail.append(f"governed validate_staged_package status={v.status}")

    # --- 1. tile set ------------------------------------------------------
    desc = json.loads((PKG / "package.json").read_text(encoding="utf-8"))
    entry = desc["maps"][0]
    declared = [Path(str(t).lstrip("./")).name for t in entry["tiles"]]
    on_disk = sorted(
        p.name for p in PKG.glob("*_Tile_*.fbx") if parse_tile_fbx_filename(p.name)
    )
    declared_idx = sorted(
        (parse_tile_fbx_filename(n) or ("", -1, -1))[1:]
        for n in declared
    )
    expected_idx = sorted(EXPECTED_TILES)
    rep["checks"]["tile_set"] = {
        "expected_count": len(expected_idx),
        "declared_count": len(declared),
        "on_disk_count": len(on_disk),
        "missing": sorted(set(expected_idx) - set(declared_idx)),
        "extra": sorted(set(declared_idx) - set(expected_idx)),
        "undeclared_on_disk": sorted(set(on_disk) - set(declared)),
        "declared_missing_on_disk": sorted(set(declared) - set(on_disk)),
    }
    for k in ("missing", "extra", "undeclared_on_disk", "declared_missing_on_disk"):
        if rep["checks"]["tile_set"][k]:
            fail.append(f"tile_set {k}={rep['checks']['tile_set'][k]}")

    # --- 2. XODR byte-exactness ------------------------------------------
    xodrs = sorted(PKG.glob("*.xodr"))
    xodr_report: Dict[str, Any] = {"count": len(xodrs)}
    if len(xodrs) != 1:
        fail.append(f"expected exactly 1 xodr, found {len(xodrs)}")
    else:
        actual = sha256_file(xodrs[0])
        xodr_report.update(
            {
                "filename": xodrs[0].name,
                "sha256_actual": actual,
                "sha256_expected": EXPECTED_XODR_SHA,
                "byte_exact": actual == EXPECTED_XODR_SHA,
                "bytes": xodrs[0].stat().st_size,
            }
        )
        if actual != EXPECTED_XODR_SHA:
            fail.append(f"xodr sha256 {actual} != {EXPECTED_XODR_SHA}")
    rep["checks"]["xodr_identity"] = xodr_report

    # --- 3/4. descriptor validity + mirror --------------------------------
    pj = (PKG / "package.json").read_bytes()
    mirror = PKG / "Ingolstadt.json"
    rep["checks"]["descriptor"] = {
        "package_json_sha256": hashlib.sha256(pj).hexdigest(),
        "declared_map_name": entry.get("name"),
        "declared_tile_size": entry.get("tile_size"),
        "declared_xodr": entry.get("xodr"),
        "declared_xodr_sha256": entry.get("xodr_sha256"),
        "mirror_present": mirror.is_file(),
        "mirror_byte_identical": mirror.is_file() and mirror.read_bytes() == pj,
        "map_name_matches_dir": entry.get("name") == PKG.name,
    }
    if not rep["checks"]["descriptor"]["mirror_byte_identical"]:
        fail.append("package-name mirror descriptor missing or diverged")
    if not rep["checks"]["descriptor"]["map_name_matches_dir"]:
        fail.append("descriptor map name != package directory name")

    # --- 5. per-tile content hashes (no substitution) ---------------------
    # The promoted package binds per-file content hashes in PACKAGE_SHA256.json
    # (21 files: 20 tiles + the whole-map XODR). The large_map_package sidecar
    # is the descriptor/lineage record and does NOT carry tiles_fbx_sha256, so
    # tiles_fbx_sha256_verified=False from the governed validator is expected
    # here and is compensated by this explicit manifest check.
    sha_manifest = PKG / "PACKAGE_SHA256.json"
    bound: Dict[str, str] = {}
    if sha_manifest.is_file():
        md = json.loads(sha_manifest.read_text(encoding="utf-8"))
        bound = dict(md.get("files") or {})
    sidecars = list(PKG.glob("*.large_map_package.json"))
    tile_hash_report: Dict[str, Any] = {
        "manifest_file": sha_manifest.name if sha_manifest.is_file() else None,
        "manifest_artifact_type": (
            json.loads(sha_manifest.read_text(encoding="utf-8")).get("artifact_type")
            if sha_manifest.is_file()
            else None
        ),
        "manifest_status": (
            json.loads(sha_manifest.read_text(encoding="utf-8")).get("status")
            if sha_manifest.is_file()
            else None
        ),
        "files_bound": len(bound),
        "tiles_bound": sum(1 for k in bound if k.endswith(".fbx")),
        "mismatches": [],
        "unbound_present": [],
        "bound_but_absent": [],
    }
    for name in on_disk:
        if name not in bound:
            tile_hash_report["unbound_present"].append(name)
            continue
        actual = sha256_file(PKG / name)
        if actual.lower() != str(bound[name]).strip().lower():
            tile_hash_report["mismatches"].append(
                {"tile": name, "expected": bound[name], "actual": actual}
            )
    for name in bound:
        if name.endswith(".fbx") and not (PKG / name).is_file():
            tile_hash_report["bound_but_absent"].append(name)
    rep["checks"]["tile_content_hashes"] = tile_hash_report
    if tile_hash_report["mismatches"]:
        fail.append(f"{len(tile_hash_report['mismatches'])} tile content hash mismatches")
    if tile_hash_report["unbound_present"]:
        fail.append(
            f"{len(tile_hash_report['unbound_present'])} tiles not bound by the manifest"
        )
    if tile_hash_report["bound_but_absent"]:
        fail.append(
            f"{len(tile_hash_report['bound_but_absent'])} manifest-bound tiles absent"
        )
    if tile_hash_report["tiles_bound"] != len(expected_idx):
        fail.append(
            f"manifest binds {tile_hash_report['tiles_bound']} tiles, expected "
            f"{len(expected_idx)}"
        )

    # --- 6. coordinate identity -------------------------------------------
    # Coordinate/frame identity for the promoted package is recorded in the
    # release run's AUTO_COOK_RECEIPT.json (source_provenance.header_offset_xy
    # + map_of_record_sha256 + frame fields), cross-checked against the
    # registry pin. The package sidecar itself carries only the tile grid.
    frame_actual: Dict[str, Any] = {}
    auto_receipt = PKG / "AUTO_COOK_RECEIPT.json"
    if auto_receipt.is_file():
        ar = json.loads(auto_receipt.read_text(encoding="utf-8"))
        sp = ar.get("source_provenance") or {}
        mor = ar.get("map_of_record") or {}
        frame_actual = {
            "source": auto_receipt.name,
            "header_offset_xy": sp.get("header_offset_xy"),
            "tile_size_m": sp.get("tile_size_m"),
            "map_of_record_sha256": sp.get("map_of_record_sha256"),
            "frame_id": mor.get("frame_id"),
            "frame_kind": mor.get("frame_kind"),
            "rebase_dx": mor.get("rebase_dx"),
            "rebase_dy": mor.get("rebase_dy"),
            "run_id": ar.get("run_id"),
        }
    for s in sidecars:
        doc = json.loads(s.read_text(encoding="utf-8"))
        pl = doc.get("placement_authority") or {}
        frame_actual["placement_authority_basis"] = pl.get("basis")
        frame_actual["placement_independently_verified"] = pl.get(
            "independent_verification"
        )
        frame_actual["tile_size_m_sidecar"] = doc.get("tile_size_m")
        break
    expected_off = [EXPECTED_FRAME["rebase_dx"], EXPECTED_FRAME["rebase_dy"]]
    coord_exact = (
        frame_actual.get("header_offset_xy") == expected_off
        and frame_actual.get("map_of_record_sha256") == EXPECTED_XODR_SHA
        and frame_actual.get("frame_id") == EXPECTED_FRAME["frame_id"]
        and frame_actual.get("frame_kind") == EXPECTED_FRAME["frame_kind"]
    )
    rep["checks"]["coordinate_identity"] = {
        "expected": EXPECTED_FRAME,
        "observed": frame_actual,
        "exact": coord_exact,
    }
    if not coord_exact:
        fail.append("coordinate identity not exact")

    # --- verdict -----------------------------------------------------------
    rep["failures"] = fail
    rep["status"] = "PASS" if not fail else "FAIL"
    rep["no_substitution"] = (
        not tile_hash_report["mismatches"] and not tile_hash_report["unbound_present"]
    )
    rep["not_claimed"] = (
        "Offline validation only. No UE4 editor, no `make import`, no cook, no "
        "runtime load of the Ingolstadt auto map was performed or is implied. "
        "COOK_LOG.txt / AUTO_COOK_RECEIPT.json in this package are OFFLINE FBX "
        "GENERATION records and explicitly say no editor was invoked."
    )

    out = Path("STAGED_PACKAGE_REVALIDATION.json")
    out.write_text(json.dumps(rep, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in rep.items() if k != "not_claimed"}, indent=2, sort_keys=True))
    print(f"\nwritten: {out}")
    return 0 if rep["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())