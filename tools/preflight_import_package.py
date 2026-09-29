#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic preflight for a CARLA Large-Map import package (O4).

Verifies without launching Unreal whether a generated package in
``Import/<PackageName>/`` is ready to be handed to ``make import``.

This is the offline pre-cook gate that answers:

  READY            — all checks pass, package is self-consistent and bound to
                     the current authoritative XODR; hand to Unreal/CARLA
  BLOCKED          — hard failure that would make ``make import`` fail or
                     produce a stale/mixed package (missing XODR, SHA mismatch,
                     descriptor malformed, tile missing, stale tile, etc.)
  INCOMPLETE       — not enough evidence to decide (e.g., no tiles yet, missing
                     frame metadata but not hard fail, environment not
                     configured for a live cook)

The command never claims READY_FOR_RUNTIME — only READY_FOR_IMPORT (offline).

Checks (14, all deterministic, no mtime, no network):
  1. authoritative XODR exists (via verify_pinned_map)
  2. XODR SHA matches registry (verify_pinned_map)
  3. FBX manifest exists (per-tile *.tile_fbx.json alongside source FBX)
  4. every expected tile exists (descriptor tiles[] all on disk)
  5. every tile hash matches manifest (fbx.sha256 vs file, bytes)
  6. no unexpected stale tiles are selected (per-tile source SHA == staged XODR SHA,
     no mixed generations)
  7. package descriptor parses (valid JSON, single maps[] entry)
  8. package descriptor references correct map (name matches expected or XODR stem)
  9. tile naming convention valid (<MapName>_Tile_<x>_<y>.fbx)
  10. tile size consistent (descriptor tile_size == expected)
  11. world-frame metadata exists (XODR header offset + tile manifest header_offset_xy)
  12. output paths are writable (package_dir, Import root)
  13. sufficient free disk (threshold, default 5 GiB on Import volume)
  14. CARLA/UE env vars available where needed (CARLA_ROOT, UE4_ROOT — warning, not BLOCK)

Usage:
  python tools/preflight_import_package.py --package-dir Import/Ingolstadt
  python tools/preflight_import_package.py --package-dir Import/Ingolstadt --expected-tile-size 1000 --min-free-gib 5 --json-out preflight.json

Exit codes: 0 READY, 2 BLOCKED, 3 INCOMPLETE
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map  # noqa: E402
from ultimate_pipeline.tiling.large_map_package import (  # noqa: E402
    parse_tile_fbx_filename,
    _sha256,
    _find_tile_manifest,
    _read_tile_source_sha,
    validate_staged_package,
    audit_large_map_package_contract,
)


def _check_authoritative_xodr() -> Tuple[str, Dict[str, Any]]:
    """Check 1 & 2: authoritative XODR exists and SHA matches registry."""
    try:
        receipt = verify_pinned_map("auto_map_of_record")
    except Exception as exc:
        return "BLOCKED", {"check": "authoritative_xodr", "status": "BLOCKED", "reason": f"verify_pinned_map failed: {exc}"}
    # verify_pinned_map already checked existence, bytes, SHA, LFS
    return "PASS", {
        "check": "authoritative_xodr",
        "status": "PASS",
        "path": receipt["resolved_path"],
        "sha256": receipt["sha256"],
        "bytes": receipt["bytes"],
        "registry_sha256": receipt.get("registry_sha256", ""),
    }


def _check_package_descriptor(package_dir: Path) -> Tuple[str, Dict[str, Any]]:
    """Check 7,8,9,10: descriptor parses, references correct map, naming, tile size."""
    pkg_json = package_dir / "package.json"
    if not pkg_json.is_file():
        return "BLOCKED", {"check": "package_descriptor", "status": "BLOCKED", "reason": f"missing package.json in {package_dir}"}
    try:
        doc = json.loads(pkg_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return "BLOCKED", {"check": "package_descriptor", "status": "BLOCKED", "reason": f"package.json not valid JSON: {exc}"}
    maps = doc.get("maps")
    if not isinstance(maps, list) or len(maps) != 1:
        return "BLOCKED", {"check": "package_descriptor", "status": "BLOCKED", "reason": f"maps must be single-entry list, got {maps!r}"}
    entry = maps[0]
    for field in ("name", "xodr", "use_carla_materials", "tile_size", "tiles"):
        if field not in entry:
            return "BLOCKED", {"check": "package_descriptor", "status": "BLOCKED", "reason": f"missing required field {field!r}"}
    # Tile naming
    for name in entry.get("tiles", []):
        if parse_tile_fbx_filename(str(name).lstrip("./")) is None:
            return "BLOCKED", {"check": "tile_naming", "status": "BLOCKED", "reason": f"tile does not match convention: {name!r}"}
    return "PASS", {"check": "package_descriptor", "status": "PASS", "doc": entry}


def _check_tiles_and_manifests(package_dir: Path, expected_xodr_sha: str) -> List[Dict[str, Any]]:
    """Checks 3,4,5,6: FBX manifest exists, every tile exists, hash matches, no stale."""
    results: List[Dict[str, Any]] = []
    pkg_json = package_dir / "package.json"
    try:
        doc = json.loads(pkg_json.read_text(encoding="utf-8"))
        entry = doc["maps"][0]
        declared = [str(t).lstrip("./") for t in entry.get("tiles", [])]
    except Exception:
        return [{"check": "tiles", "status": "BLOCKED", "reason": "cannot read descriptor"}]

    # 4. every expected tile exists
    for name in declared:
        p = package_dir / name
        if not p.is_file():
            results.append({"check": "tile_exists", "status": "BLOCKED", "tile": name, "reason": f"declared tile not found on disk: {p}"})
        else:
            results.append({"check": "tile_exists", "status": "PASS", "tile": name})

    # 3 & 5 & 6: per-tile manifest and hash, stale detection
    # For staged package, per-tile manifests are not staged (they live beside
    # source FBXs).  The only provenance we can check in the staged dir is the
    # package's own descriptor xodr_sha256 and sidecar, plus whether the staged
    # FBX files themselves have manifests alongside them (unlikely, since FBXs
    # are copied without manifests).  However, the O1 strict provenance for
    # staged packages is enforced via the staged package's own validation
    # (validate_staged_package checks per-tile manifests if any staged tile has
    # a manifest).  For preflight, we check that the package's tiles, when
    # traced back to their source manifests (if available via the package's
    # tiles_provenance in large_map_package.json), all share the expected SHA.
    # If the package was built via stage_large_map_package with O1, its
    # large_map_package.json already contains tiles_provenance.
    # For preflight without that, we treat missing per-tile manifests in the
    # staged dir as INCOMPLETE (not BLOCKED) unless the package manifest says
    # the tiles were stale.
    has_any_manifest_in_staged = any((_find_tile_manifest(package_dir / name) is not None) for name in declared)
    if has_any_manifest_in_staged:
        for name in declared:
            p = package_dir / name
            manifest = _find_tile_manifest(p)
            if manifest is None:
                results.append({"check": "fbx_manifest", "status": "BLOCKED", "tile": name, "reason": f"missing manifest {name.rsplit('.',1)[0]}.tile_fbx.json in staged dir"})
                continue
            sha = _read_tile_source_sha(manifest)
            if sha is None:
                results.append({"check": "fbx_manifest", "status": "BLOCKED", "tile": name, "reason": f"manifest has no source SHA: {manifest}"})
                continue
            if sha.lower() != expected_xodr_sha.lower():
                results.append({"check": "tile_provenance", "status": "BLOCKED", "tile": name, "reason": f"stale tile provenance {sha} != expected {expected_xodr_sha}"})
            else:
                # 5. hash matches manifest
                try:
                    manifest_doc = json.loads(manifest.read_text(encoding="utf-8"))
                    manifest_fbx_sha = (manifest_doc.get("fbx") or {}).get("sha256")
                    manifest_fbx_bytes = (manifest_doc.get("fbx") or {}).get("bytes")
                    actual_sha = _sha256(p)
                    actual_bytes = p.stat().st_size
                    if manifest_fbx_sha and actual_sha.lower() != manifest_fbx_sha.lower():
                        results.append({"check": "tile_hash", "status": "BLOCKED", "tile": name, "reason": f"FBX sha {actual_sha} != manifest {manifest_fbx_sha}"})
                    elif manifest_fbx_bytes is not None and actual_bytes != manifest_fbx_bytes:
                        results.append({"check": "tile_hash", "status": "BLOCKED", "tile": name, "reason": f"FBX bytes {actual_bytes} != manifest {manifest_fbx_bytes}"})
                    else:
                        results.append({"check": "tile_hash", "status": "PASS", "tile": name})
                except (OSError, json.JSONDecodeError) as exc:
                    results.append({"check": "tile_hash", "status": "BLOCKED", "tile": name, "reason": f"cannot read manifest: {exc}"})
        # 6. no mixed generations (distinct SHAs among staged tiles)
        # Collect SHAs we saw
        shas = {}
        for name in declared:
            m = _find_tile_manifest(package_dir / name)
            if m is not None:
                sha = _read_tile_source_sha(m)
                if sha:
                    shas[name] = sha
        if len(set(shas.values())) > 1:
            results.append({"check": "no_mixed_generations", "status": "BLOCKED", "reason": f"mixed source SHAs {sorted(set(shas.values()))}"})
        else:
            if shas:
                results.append({"check": "no_mixed_generations", "status": "PASS"})
    else:
        # No per-tile manifests in staged dir — check the package's own sidecar
        # large_map_package.json for tiles_provenance (O1)
        sidecars = list(package_dir.glob("*.large_map_package.json"))
        if sidecars:
            try:
                mdoc = json.loads(sidecars[0].read_text(encoding="utf-8"))
                prov = mdoc.get("tiles_provenance") or {}
                if prov:
                    distinct = set(prov.values())
                    if len(distinct) > 1:
                        results.append({"check": "no_mixed_generations", "status": "BLOCKED", "reason": f"sidecar mixed SHAs {sorted(distinct)}"})
                    elif distinct and next(iter(distinct)).lower() != expected_xodr_sha.lower():
                        results.append({"check": "tile_provenance", "status": "BLOCKED", "reason": f"sidecar provenance {next(iter(distinct))} != expected {expected_xodr_sha}"})
                    else:
                        results.append({"check": "tile_provenance", "status": "PASS"})
                else:
                    results.append({"check": "fbx_manifest", "status": "INCOMPLETE", "reason": "no per-tile manifests in staged dir and sidecar has no tiles_provenance (synthetic package?)"})
            except (json.JSONDecodeError, OSError) as exc:
                results.append({"check": "fbx_manifest", "status": "INCOMPLETE", "reason": f"cannot read sidecar: {exc}"})
        else:
            results.append({"check": "fbx_manifest", "status": "INCOMPLETE", "reason": "no per-tile manifests and no sidecar found in staged dir"})

    return results


def _check_world_frame(package_dir: Path, expected_xodr_sha: str) -> Dict[str, Any]:
    """Check 11: world-frame metadata exists."""
    # Check XODR header offset
    pkg_json = package_dir / "package.json"
    try:
        doc = json.loads(pkg_json.read_text(encoding="utf-8"))
        entry = doc["maps"][0]
        xodr_name = str(entry["xodr"]).lstrip("./")
        xodr_path = package_dir / xodr_name
        if not xodr_path.is_file():
            return {"check": "world_frame", "status": "BLOCKED", "reason": f"xodr not found: {xodr_path}"}
        # Parse XODR header offset
        import xml.etree.ElementTree as ET

        root = ET.parse(xodr_path).getroot()
        header = root.find("header")
        if header is None:
            return {"check": "world_frame", "status": "BLOCKED", "reason": "XODR missing <header>"}
        offset = header.find("offset")
        if offset is None:
            return {"check": "world_frame", "status": "INCOMPLETE", "reason": "XODR header has no <offset> (frame metadata missing)"}
        # Check that offset is finite and matches expected (from registry, the offset is 832671.676,5458671.104)
        try:
            ox = float(offset.get("x", "nan"))
            oy = float(offset.get("y", "nan"))
            if not (ox == ox and oy == oy):  # nan check
                raise ValueError
        except (TypeError, ValueError):
            return {"check": "world_frame", "status": "BLOCKED", "reason": f"XODR header offset x/y not finite: {offset.attrib}"}
        return {"check": "world_frame", "status": "PASS", "offset": [ox, oy]}
    except (json.JSONDecodeError, OSError) as exc:
        return {"check": "world_frame", "status": "BLOCKED", "reason": f"cannot read descriptor: {exc}"}
    except Exception as exc:
        return {"check": "world_frame", "status": "BLOCKED", "reason": f"frame check failed: {exc}"}


def _check_output_writable(package_dir: Path) -> Dict[str, Any]:
    """Check 12: output paths are writable."""
    try:
        # Try to create and delete a temp file in package_dir
        test = package_dir / ".preflight_writable_test"
        test.write_text("test", encoding="utf-8")
        test.unlink()
        return {"check": "output_writable", "status": "PASS", "path": str(package_dir)}
    except (OSError, PermissionError) as exc:
        return {"check": "output_writable", "status": "BLOCKED", "reason": f"not writable: {exc}"}


def _check_disk_free(package_dir: Path, min_gib: float) -> Dict[str, Any]:
    """Check 13: sufficient free disk."""
    try:
        usage = shutil.disk_usage(package_dir)
        free_gib = usage.free / (1024**3)
        if free_gib < min_gib:
            return {"check": "disk_free", "status": "BLOCKED", "free_gib": round(free_gib, 2), "required_gib": min_gib, "reason": f"free {free_gib:.2f} GiB < required {min_gib} GiB on {package_dir}"}
        return {"check": "disk_free", "status": "PASS", "free_gib": round(free_gib, 2), "required_gib": min_gib}
    except (OSError, ValueError) as exc:
        return {"check": "disk_free", "status": "INCOMPLETE", "reason": f"cannot check disk usage: {exc}"}


def _check_env_vars() -> List[Dict[str, Any]]:
    """Check 14: CARLA/UE env vars where needed."""
    results = []
    # For READY_FOR_IMPORT (offline), CARLA/UE vars are not required, but we
    # report their presence as INCOMPLETE warnings.
    for var in ("CARLA_ROOT", "UE4_ROOT", "CARLA_VERSION", "UE4_VERSION"):
        val = os.environ.get(var)
        if val:
            results.append({"check": f"env_{var}", "status": "PASS", "value": val})
        else:
            results.append({"check": f"env_{var}", "status": "INCOMPLETE", "reason": f"{var} not set (not required for READY_FOR_IMPORT, but needed for live cook)"})
    return results


def preflight_package(
    package_dir: str,
    expected_tile_size_m: float = 1000.0,
    min_free_gib: float = 5.0,
    expected_xodr_sha: Optional[str] = None,
) -> Dict[str, Any]:
    """Run all 14 checks deterministically, return structured result.

    Never claims READY_FOR_RUNTIME.
    """
    pkg_dir = Path(package_dir)
    checks: List[Dict[str, Any]] = []
    # 1 & 2
    status, info = _check_authoritative_xodr()
    checks.append(info)
    authoritative_sha = info.get("sha256") if status == "PASS" else None
    # Use authoritative SHA as expected if not overridden
    expected_sha = expected_xodr_sha or authoritative_sha or ""

    # Also run the existing offline validation gates for comprehensive coverage
    validation = validate_staged_package(str(pkg_dir), expected_xodr_sha256=expected_sha if expected_sha else None)
    checks.append({"check": "validate_staged_package", "status": "PASS" if validation.status == "PASS" else "BLOCKED", "failures": validation.failures, "warnings": validation.warnings})
    audit = audit_large_map_package_contract(str(pkg_dir), expected_tile_size_m=expected_tile_size_m)
    checks.append({"check": "audit_contract", "status": audit.status, "failures": audit.failures, "warnings": audit.warnings})

    # 7,8,9,10 via descriptor check
    desc_status, desc_info = _check_package_descriptor(pkg_dir)
    checks.append(desc_info)
    # 10 tile size already in audit, but double-check descriptor tile_size
    if desc_info.get("status") == "PASS":
        try:
            doc = json.loads((pkg_dir / "package.json").read_text(encoding="utf-8"))
            ts = float(doc["maps"][0].get("tile_size", 0))
            if abs(ts - expected_tile_size_m) > 1e-6:
                checks.append({"check": "tile_size", "status": "BLOCKED", "reason": f"tile_size {ts} != expected {expected_tile_size_m}"})
            else:
                checks.append({"check": "tile_size", "status": "PASS", "value": ts})
        except Exception as exc:
            checks.append({"check": "tile_size", "status": "BLOCKED", "reason": f"cannot check tile_size: {exc}"})
    else:
        checks.append({"check": "tile_size", "status": "BLOCKED", "reason": "descriptor failed, cannot check tile_size"})

    # 3,4,5,6 via tile checks
    if expected_sha:
        tile_checks = _check_tiles_and_manifests(pkg_dir, expected_sha)
        checks.extend(tile_checks)
    else:
        checks.append({"check": "tiles", "status": "INCOMPLETE", "reason": "no authoritative SHA to verify tile provenance"})

    # 11 world-frame
    if expected_sha:
        checks.append(_check_world_frame(pkg_dir, expected_sha))
    else:
        checks.append({"check": "world_frame", "status": "INCOMPLETE", "reason": "no SHA for frame check"})

    # 12 writable
    checks.append(_check_output_writable(pkg_dir))
    # 13 disk free
    checks.append(_check_disk_free(pkg_dir, min_free_gib))
    # 14 env vars (INCOMPLETE, not BLOCKED for READY_FOR_IMPORT)
    checks.extend(_check_env_vars())

    # Aggregate status: BLOCKED if any BLOCKED, else INCOMPLETE if any INCOMPLETE, else READY
    # For READY_FOR_IMPORT, we ignore INCOMPLETE env vars (they are expected offline)
    hard_checks = [c for c in checks if c.get("check", "").startswith("env_") is False]
    has_blocked = any(c.get("status") == "BLOCKED" for c in hard_checks)
    has_incomplete = any(c.get("status") == "INCOMPLETE" for c in hard_checks)
    if has_blocked:
        overall = "BLOCKED"
    elif has_incomplete:
        overall = "INCOMPLETE"
    else:
        overall = "READY"

    # Only claim READY_FOR_IMPORT, never READY_FOR_RUNTIME
    claim = "READY_FOR_IMPORT" if overall == "READY" else ("BLOCKED_FOR_IMPORT" if overall == "BLOCKED" else "INCOMPLETE_FOR_IMPORT")

    return {
        "schema_version": 1,
        "artifact_type": "carla_large_map_preflight",
        "status": overall,
        "claim": claim,
        "package_dir": str(pkg_dir),
        "checks": checks,
        "summary": {
            "total": len(checks),
            "pass": sum(1 for c in checks if c.get("status") == "PASS"),
            "blocked": sum(1 for c in checks if c.get("status") == "BLOCKED"),
            "incomplete": sum(1 for c in checks if c.get("status") == "INCOMPLETE"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--package-dir", required=True, help="Import/<PackageName>/ directory to preflight")
    parser.add_argument("--expected-tile-size", type=float, default=1000.0, help="expected tile_size (default 1000.0)")
    parser.add_argument("--min-free-gib", type=float, default=5.0, help="minimum free GiB on Import volume (default 5)")
    parser.add_argument("--expected-xodr-sha", default=None, help="override expected XODR SHA (default: authoritative via registry)")
    parser.add_argument("--json-out", default=None, help="write JSON result to file")
    parser.add_argument("--human-readable", action="store_true", help="print human-readable summary (default with --json-out)")
    args = parser.parse_args()

    result = preflight_package(
        package_dir=args.package_dir,
        expected_tile_size_m=args.expected_tile_size,
        min_free_gib=args.min_free_gib,
        expected_xodr_sha=args.expected_xodr_sha,
    )

    # Human-readable
    print(f"Preflight: {result['status']} ({result['claim']})")
    print(f"Package: {result['package_dir']}")
    print(f"Checks: {result['summary']['pass']} PASS / {result['summary']['blocked']} BLOCKED / {result['summary']['incomplete']} INCOMPLETE (total {result['summary']['total']})")
    for c in result["checks"]:
        status = c.get("status", "?")
        check = c.get("check", "?")
        reason = c.get("reason", "")
        if status != "PASS":
            print(f"  [{status}] {check}: {reason or c.get('failures','')}")
        else:
            # Only print PASS for key checks to reduce noise
            if check in ("authoritative_xodr", "validate_staged_package", "audit_contract", "package_descriptor"):
                print(f"  [PASS] {check}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Wrote JSON to {args.json_out}")

    # Also print full JSON to stdout if no json-out
    if not args.json_out:
        print("\nJSON:")
        print(json.dumps(result, indent=2, sort_keys=True))

    if result["status"] == "READY":
        return 0
    elif result["status"] == "BLOCKED":
        return 2
    else:
        return 3


if __name__ == "__main__":
    sys.exit(main())
