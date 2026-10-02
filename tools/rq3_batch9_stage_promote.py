#!/usr/bin/env python3
"""Batch 9 steps 5-7: stage, validate, and promote the RQ3 package.

Stages into ``Import/.staging/<run_id>/<PackageName>`` via the governed
``stage_large_map_package``, validates the TEMPORARY staged package with the
governed ``validate_staged_package``, then atomically promotes to
``Import/<PackageName>``.

XODR authority is checked before anything is staged. A manifest override is
never allowed to mask a failed authoritative XODR SHA: a mismatch aborts with
MAP_AUTHORITY_DRIFT.

Writes STAGED_PACKAGE_VALIDATION.json and PACKAGE_PROMOTION_RECEIPT.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

WORKTREE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKTREE))

from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map
from ultimate_pipeline.tiling.large_map_package import (
    stage_large_map_package,
    validate_staged_package,
)

EXPECTED_TILES = [(x, y) for x in (6, 7, 8, 9, 10) for y in (6, 7, 8, 9)]
RELEASE = WORKTREE / "reports" / "production_readiness" / "20260924T100614Z_FULL_GRID_TILE_FBX_COOK"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(WORKTREE)).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def main() -> int:
    ap = argparse.ArgumentParser(description="RQ3 stage / validate / promote")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--registry-key", default="auto_map_of_record")
    ap.add_argument("--map-name", default="Ingolstadt")
    ap.add_argument("--package-name", default="Ingolstadt")
    ap.add_argument("--import-root", type=Path, default=WORKTREE / "Import")
    ap.add_argument("--stage-only", action="store_true", help="skip promotion")
    ap.add_argument("--skip-promote", action="store_true")
    args = ap.parse_args()

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = "20260924T100614Z_rq3batch9"
    import_root: Path = args.import_root
    stage_root = import_root / ".staging" / run_id

    candidate_sha = subprocess.run(
        ["git", "-C", str(WORKTREE), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    report: Dict[str, Any] = {
        "schema": "rq3_package_staging/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_sha": candidate_sha,
        "run_id": run_id,
        "import_root": _rel(import_root),
        "staging_root": _rel(stage_root),
        "package_name": args.package_name,
    }

    # ---------- step 6: XODR authority, before any staging ----------
    pinned = verify_pinned_map(args.registry_key)
    xodr = Path(pinned["resolved_path"])
    actual = _sha256(xodr)
    report["xodr_authority"] = {
        "registry_key": args.registry_key,
        "xodr_path": _rel(xodr),
        "sha256_expected": pinned["sha256_expected"],
        "sha256_actual": actual,
        "bytes": xodr.stat().st_size,
        "registry_bytes": pinned.get("bytes"),
    }
    if actual != pinned["sha256_expected"]:
        report["overall"] = "MAP_AUTHORITY_DRIFT"
        report["abort_reason"] = (
            "authoritative XODR SHA256 does not match the pinned registry entry; "
            "no manifest override was applied and nothing was staged"
        )
        (out_dir / "STAGED_PACKAGE_VALIDATION.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print("MAP_AUTHORITY_DRIFT -- aborting before staging")
        return 2
    if xodr.stat().st_size != pinned.get("bytes"):
        report["overall"] = "MAP_AUTHORITY_DRIFT"
        report["abort_reason"] = "XODR byte length disagrees with the registry entry"
        print("MAP_AUTHORITY_DRIFT (bytes) -- aborting before staging")
        return 2
    print(f"XODR authority OK: {actual}")

    # ---------- step 5: stage into the temporary staging root ----------
    if stage_root.exists():
        shutil.rmtree(stage_root)
    stage_root.mkdir(parents=True, exist_ok=True)

    tile_paths = [
        str(RELEASE / "artifacts" / f"tile_{tx}_{ty}" / f"{args.map_name}_Tile_{tx}_{ty}.fbx")
        for tx, ty in EXPECTED_TILES
    ]
    missing = [p for p in tile_paths if not Path(p).is_file()]
    if missing:
        report["overall"] = "FAIL"
        report["abort_reason"] = f"{len(missing)} governed tile(s) missing from the release"
        report["missing_tiles"] = [_rel(Path(p)) for p in missing]
        print(f"FAIL: {len(missing)} governed tile(s) missing")
        return 2

    t0 = time.time()
    staged = stage_large_map_package(
        map_name=args.map_name,
        xodr_path=str(xodr),
        tile_fbx_paths=tile_paths,
        import_root=str(stage_root),
        package_name=args.package_name,
        tile_size_m=1000.0,
        use_carla_materials=True,
        expected_xodr_sha256=pinned["sha256_expected"],
    )
    stage_sec = round(time.time() - t0, 3)
    # StagedPackageResult.status is "ok" on success in the governed contract.
    stage_status = "PASS" if str(staged.status).lower() in ("ok", "pass") else staged.status
    report["staging"] = {
        "status": stage_status,
        "governed_status_literal": staged.status,
        "reason": staged.reason,
        "package_dir": _rel(Path(staged.package_dir)),
        "package_name": staged.package_name,
        "xodr_staged_path": _rel(Path(staged.xodr_staged_path)) if staged.xodr_staged_path else None,
        "xodr_sha256": staged.xodr_sha256,
        "tiles_staged": staged.tiles_staged,
        "tiles_skipped_missing": staged.tiles_skipped_missing,
        "package_json_path": _rel(Path(staged.package_json_path)) if staged.package_json_path else None,
        "manifest_path": _rel(Path(staged.manifest_path)) if staged.manifest_path else None,
        "duration_sec": stage_sec,
        "governed_interface": "ultimate_pipeline.tiling.large_map_package.stage_large_map_package",
    }
    if stage_status != "PASS":
        report["overall"] = "FAIL"
        print(f"STAGING FAILED: {staged.reason}")
        (out_dir / "STAGED_PACKAGE_VALIDATION.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return 2
    print(f"STAGING PASS: {len(staged.tiles_staged)} tiles -> {staged.package_dir}")

    package_dir = Path(staged.package_dir)

    # independent copies: staged members must not be the source files
    members = sorted(p for p in package_dir.rglob("*") if p.is_file())
    independence = []
    for m in members:
        try:
            same = m.samefile(RELEASE / m.name)
        except OSError:
            same = False
        independence.append({"member": m.name, "is_source_file": bool(same)})
    report["copy_independence"] = {
        "checked": len(independence),
        "any_alias_to_source": any(x["is_source_file"] for x in independence),
    }

    # exactly one whole-map XODR, no per-tile duplicate XODRs
    xodrs = sorted(p.name for p in package_dir.glob("*.xodr"))
    report["xodr_members"] = xodrs
    report["exactly_one_xodr"] = len(xodrs) == 1

    # ---------- step 7: validate the TEMPORARY staged package ----------
    val = validate_staged_package(str(package_dir), expected_xodr_sha256=pinned["sha256_expected"])
    validation: Dict[str, Any] = {
        "governed_interface": "ultimate_pipeline.tiling.large_map_package.validate_staged_package",
        "validated_dir": _rel(package_dir),
        "validated_dir_is_temporary_staging": True,
        "status": val.status,
        "failures": list(val.failures),
        "warnings": list(val.warnings),
        "xodr_sha256": val.xodr_sha256,
        "tile_count": val.tile_count,
        "exactly_one_xodr": report["exactly_one_xodr"],
        "xodr_members": xodrs,
        "copy_independence": report["copy_independence"],
        "member_sha256": {m.name: _sha256(m) for m in members},
        "member_bytes": {m.name: m.stat().st_size for m in members},
        "candidate_sha": candidate_sha,
    }

    # declared tiles == on-disk tiles, no dupes, no strays, name validity
    pkg_json_path = package_dir / "package.json"
    descriptor = json.loads(pkg_json_path.read_text(encoding="utf-8")) if pkg_json_path.is_file() else {}
    maps = descriptor.get("maps", [])
    declared = sorted(Path(t).name for t in (maps[0].get("tiles", []) if maps else []))
    ondisk = sorted(p.name for p in package_dir.glob("*.fbx"))
    validation["declared_tiles"] = declared
    validation["ondisk_tiles"] = ondisk
    validation["declared_equals_ondisk"] = declared == ondisk
    validation["duplicate_declarations"] = len(declared) != len(set(declared))
    validation["no_stray_fbx"] = set(ondisk) == set(declared)
    for key, ok in (
        ("declared_equals_ondisk", validation["declared_equals_ondisk"]),
        ("no_stray_fbx", validation["no_stray_fbx"]),
    ):
        if not ok:
            validation["failures"].append(key)
    if validation["duplicate_declarations"]:
        validation["failures"].append("duplicate_declarations")
    if not validation["exactly_one_xodr"]:
        validation["failures"].append("exactly_one_xodr")
    if val.status != "PASS":
        validation["overall"] = "FAIL"
    elif any(f for f in validation["failures"] if not isinstance(f, str) or f.startswith(("declared_", "no_stray", "duplicate_", "exactly_one"))):
        validation["overall"] = "FAIL"
    else:
        validation["overall"] = "PASS"

    (out_dir / "STAGED_PACKAGE_VALIDATION.json").write_text(
        json.dumps(validation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"STAGED PACKAGE VALIDATION: {validation['overall']} "
          f"({val.status}, tiles={val.tile_count})")
    if validation["overall"] != "PASS":
        report["overall"] = "FAIL"
        report["abort_reason"] = "staged package validation failed; promotion withheld"
        (out_dir / "STAGING_REPORT.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return 2

    if args.stage_only or args.skip_promote:
        report["overall"] = "PACKAGE_STAGING_PASS"
        report["promotion"] = "WITHHELD_BY_FLAG"
        (out_dir / "STAGING_REPORT.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print("promotion withheld by flag")
        return 0

    # ---------- step 10: atomic promotion ----------
    final_dir = import_root / args.package_name
    receipt: Dict[str, Any] = {
        "schema": "rq3_package_promotion/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_sha": candidate_sha,
        "run_id": run_id,
        "package_name": args.package_name,
        "from_dir": _rel(package_dir),
        "to_dir": _rel(final_dir),
        "strategy": "same-volume os.replace (atomic rename) with backup of any prior package",
        "xodr_sha256": val.xodr_sha256,
        "tile_count": val.tile_count,
    }

    import_root.mkdir(parents=True, exist_ok=True)
    backup_dir: Optional[Path] = None
    if final_dir.exists():
        backup_dir = import_root / f".superseded_{args.package_name}_{run_id}"
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        os.replace(final_dir, backup_dir)
        receipt["prior_package_backed_up_to"] = _rel(backup_dir)

    promoted_members = sorted(p for p in package_dir.rglob("*") if p.is_file())
    promoted_sha = {p.name: _sha256(p) for p in promoted_members}
    try:
        os.replace(package_dir, final_dir)
        receipt["atomic_rename"] = "OK"
    except OSError as exc:
        if backup_dir is not None and not final_dir.exists():
            os.replace(backup_dir, final_dir)
            receipt["prior_package_restored"] = True
        receipt["atomic_rename"] = f"FAILED: {exc}"
        receipt["status"] = "FAIL"
        (out_dir / "PACKAGE_PROMOTION_RECEIPT.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"PROMOTION FAILED: {exc}")
        return 2

    # the promotion target must independently verify after the move
    post = validate_staged_package(str(final_dir), expected_xodr_sha256=pinned["sha256_expected"])
    receipt["post_promotion_validation"] = {
        "status": post.status,
        "failures": list(post.failures),
        "warnings": list(post.warnings),
        "tile_count": post.tile_count,
        "xodr_sha256": post.xodr_sha256,
    }
    final_members = sorted(p for p in final_dir.rglob("*") if p.is_file())
    receipt["member_sha256"] = {p.name: _sha256(p) for p in final_members}
    receipt["member_bytes"] = {p.name: p.stat().st_size for p in final_members}
    receipt["sha256_preserved_across_promotion"] = receipt["member_sha256"] == promoted_sha
    receipt["status"] = (
        "PASS"
        if post.status == "PASS" and receipt["sha256_preserved_across_promotion"]
        else "FAIL"
    )
    receipt["package_dir"] = _rel(final_dir)

    # remove the now-empty staging tree
    try:
        stage_root.rmdir()
        (import_root / ".staging").rmdir()
    except OSError:
        pass

    (out_dir / "PACKAGE_PROMOTION_RECEIPT.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"PROMOTION {receipt['status']}: {receipt['to_dir']}")

    report["overall"] = (
        "PACKAGE_STAGING_PASS" if receipt["status"] == "PASS" else "PROMOTION_FAIL"
    )
    report["promotion"] = receipt["status"]
    (out_dir / "STAGING_REPORT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if receipt["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
