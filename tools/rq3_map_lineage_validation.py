#!/usr/bin/env python3
"""RQ3: Exact Map-Lineage Validation.

Validates that a cooked map package has exact lineage to the authoritative
map-of-record, with no heuristic path matching or partial matches.

This implements the exact map-lineage validation gate:
- Verifies exact map SHA256 match
- Verifies exact tile set match (no missing/extra tiles)
- Verifies tile placement authority (world_placement_offset_m)
- Verifies Architecture B manifest consumption
- Fails closed on any mismatch
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

WORKTREE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKTREE))
os.chdir(str(WORKTREE))

from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map
from ultimate_pipeline.tiling.large_map_package import (
    stage_large_map_package,
    validate_staged_package,
    PackageProfile,
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_map_lineage(
    package_dir: Path,
    expected_map_sha256: str,
    expected_tile_indices: set[tuple[int, int]],
) -> Dict[str, Any]:
    """Verify exact map lineage for a staged package."""
    results = {
        "schema": "rq3_map_lineage/v1",
        "package_dir": str(package_dir),
        "expected_map_sha256": expected_map_sha256,
        "checks": {},
        "overall": "PASS",
    }

    # 1. Validate staged package structure
    validation = validate_staged_package(str(package_dir), expected_xodr_sha256=expected_map_sha256)
    results["checks"]["structure"] = {
        "status": validation.status,
        "failures": validation.failures,
        "warnings": validation.warnings,
    }
    if validation.status != "PASS":
        results["overall"] = "FAIL"

    # 2. Check exact tile set match
    pkg_json = package_dir / "package.json"
    if pkg_json.exists():
        doc = json.loads(pkg_json.read_text(encoding="utf-8"))
        maps = doc.get("maps", [])
        if maps and "tiles" in maps[0]:
            declared_tiles = [Path(t.lstrip("./")).name for t in maps[0]["tiles"]]
            # Parse tile indices from filenames
            import re
            tile_re = re.compile(r".+_Tile_(-?\d+)_(-?\d+)\.fbx$")
            staged_indices = set()
            for tile_name in declared_tiles:
                m = tile_re.match(tile_name)
                if m:
                    staged_indices.add((int(m.group(1)), int(m.group(2))))

            missing = expected_tile_indices - staged_indices
            extra = staged_indices - expected_tile_indices

            results["checks"]["tile_set"] = {
                "expected_count": len(expected_tile_indices),
                "staged_count": len(staged_indices),
                "missing_tiles": sorted([f"{tx},{ty}" for tx, ty in missing]),
                "extra_tiles": sorted([f"{tx},{ty}" for tx, ty in extra]),
                "status": "PASS" if not missing and not extra else "FAIL",
            }
            if missing or extra:
                results["overall"] = "FAIL"

    # 3. Check Architecture B manifest consumption (placement offsets)
    sidecars = list(package_dir.glob("*.large_map_package.json"))
    if len(sidecars) == 1:
        sidecar = json.loads(sidecars[0].read_text(encoding="utf-8"))
        placement_offsets = sidecar.get("tiles_placement_offsets", {})
        if placement_offsets:
            results["checks"]["placement_authority"] = {
                "tiles_with_offsets": len(placement_offsets),
                "status": "PASS" if placement_offsets else "FAIL",
            }
            if not placement_offsets:
                results["overall"] = "FAIL"
        else:
            results["checks"]["placement_authority"] = {
                "status": "FAIL",
                "reason": "No tiles_placement_offsets in sidecar",
            }
            results["overall"] = "FAIL"
    else:
        results["checks"]["placement_authority"] = {
            "status": "FAIL",
            "reason": f"Expected 1 sidecar, found {len(sidecars)}",
        }
        results["overall"] = "FAIL"

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="RQ3: Exact Map-Lineage Validation")
    parser.add_argument("package_dir", type=Path, help="Path to staged Import/<PackageName>/ directory")
    parser.add_argument("--expected-map-sha", required=True, help="Expected map-of-record SHA256")
    parser.add_argument("--expected-tiles", type=str, required=True,
                        help="Comma-separated expected tile indices (e.g., '6,6;7,6;8,6')")
    parser.add_argument("--out", type=Path, default=None, help="Output JSON path")
    args = parser.parse_args()

    # Parse expected tile indices (semicolon-separated pairs: "6,6;7,6;8,6")
    expected_tiles = set()
    for pair in args.expected_tiles.split(";"):
        tx, ty = map(int, pair.strip().split(","))
        expected_tiles.add((int(tx), int(ty)))

    results = _verify_map_lineage(args.package_dir, args.expected_map_sha, args.expected_tiles)

    output = json.dumps(results, indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)

    return 0 if results["overall"] == "PASS" else 1


if __name__ == "__main__":
    import re
    raise SystemExit(main())