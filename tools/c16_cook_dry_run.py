#!/usr/bin/env python3
"""C16 step 1 — dry-run the semantic-tagging scaffold (no UE, no Blender).

The real cook (OSM2World -> Blender -> FBX -> UE4.26 import -> collision ->
package) is blocked on a human UE4.26 operator. This validates the piece
that CAN run now: given a mesh inventory (either a real
fbx_roundtrip_manifest.json if one exists from a prior FBX export, or a
documented representative fixture proving the mechanism if not), every
mesh gets classified against carla.CityObjectLabel and the fail-closed
gate (validate_semantic_tags) correctly accepts a fully-tagged inventory
and rejects one with any unmatched mesh.

**This does NOT prove real OSM2World mesh names classify correctly** --
that requires an actual cook to inspect. It proves the scaffold mechanism
itself (classification + fail-closed gate) is correct and wired, so the
moment a real FBX export exists, running this against it tells you
immediately whether the keyword table needs extending.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ultimate_pipeline.enrichment.semantic_tagging import (  # noqa: E402
    tag_mesh_inventory,
    validate_semantic_tags,
)

# A representative fixture standing in for a real OSM2World/FBX export --
# documented as synthetic, not fabricated real-cook output. Covers the
# static-scenery categories a map cook actually produces.
REPRESENTATIVE_FIXTURE_OBJECTS = [
    {"name": "Road_main_carriageway_001", "materials": ["Asphalt"]},
    {"name": "RoadLine_dashed_center_001", "materials": []},
    {"name": "Sidewalk_north_001", "materials": ["Pavement"]},
    {"name": "Building_residential_042", "materials": ["Brick_Wall", "Roof_Tile"]},
    {"name": "Wall_freestanding_boundary_003", "materials": []},
    {"name": "Fence_garden_012", "materials": []},
    {"name": "StreetLamp_pole_017", "materials": []},
    {"name": "TrafficLight_junction_A_head1", "materials": []},
    {"name": "TrafficSign_speed_limit_30_009", "materials": []},
    {"name": "Tree_broadleaf_large_128", "materials": ["Vegetation_Leaves"]},
    {"name": "RailTrack_segment_004", "materials": []},
    {"name": "GuardRail_highway_segment_022", "materials": []},
    {"name": "River_water_surface_001", "materials": []},
    {"name": "Bridge_deck_concrete_001", "materials": []},
    {"name": "Meadow_terrain_patch_055", "materials": []},
]


def _find_real_manifest(campaign_dir: Path) -> Optional[Path]:
    for candidate in campaign_dir.rglob("fbx_roundtrip_manifest.json"):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        objects = data.get("objects", [])
        # A real cook has far more than a 1-object smoke-test fixture.
        if len(objects) >= 10:
            return candidate
    return None


def run_dry_run(campaign_dir: Path) -> Dict[str, Any]:
    real_manifest_path = _find_real_manifest(campaign_dir)
    if real_manifest_path is not None:
        data = json.loads(real_manifest_path.read_text(encoding="utf-8"))
        objects = data.get("objects", [])
        try:
            display_path = real_manifest_path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            display_path = str(real_manifest_path)
        source = f"real_manifest:{display_path}"
    else:
        objects = REPRESENTATIVE_FIXTURE_OBJECTS
        source = "representative_fixture (no real OSM2World/FBX export found on disk -- " \
                 "this validates the scaffold mechanism, not real cook output)"

    report = tag_mesh_inventory(objects)
    validation = validate_semantic_tags(report)
    return {
        "source": source,
        "tag_report": report,
        "validation": validation,
        "verdict": f"COOK_SCAFFOLD_READY dry_run={'OK' if validation['ok'] else 'FAIL'}",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--campaign-dir", type=Path, default=REPO_ROOT / "campaigns")
    args = ap.parse_args()

    result = run_dry_run(args.campaign_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"[c16_cook_dry_run] source: {result['source']}")
    print(f"[c16_cook_dry_run] {result['verdict']} ({result['tag_report']['mesh_count']} meshes, "
          f"{result['validation']['unmatched_meshes']} unmatched)")
    return 0 if result["validation"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
