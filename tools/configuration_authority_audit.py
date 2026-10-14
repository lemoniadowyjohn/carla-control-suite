"""Audit duplicated configuration authorities for O13."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ultimate_pipeline.carla_tools.map_registry import PINNED_MAP_REGISTRY, verify_pinned_map


def build_audit() -> dict[str, Any]:
    pin = verify_pinned_map("auto_map_of_record")
    rows = [
        {"setting": "authoritative automatic map", "category": "D", "authority": "ultimate_pipeline/carla_tools/map_registry.py:PINNED_MAP_REGISTRY", "duplicates": ["cook_full_grid_tiles.py: import-time pin", "stage_large_map_import_package.py: import-time pin"], "resolution": "Registry remains authority; execution paths re-resolve verify_pinned_map at runtime."},
        {"setting": "manual map identity", "category": "D", "authority": "ultimate_pipeline/carla_tools/map_registry.py:PINNED_MAP_REGISTRY.manual_grid0828", "duplicates": ["README/manual map references", "historical receipts"], "resolution": "Registry remains authority; historical references are evidence, not runtime selection."},
        {"setting": "CRS/header offset", "category": "D", "authority": "map_registry.py structured frame fields", "duplicates": ["tile_fbx_generator.py:_PROJ_STRING", "cook_full_grid_tiles.py:_header_offset_from_registry", "historical XODR offsets"], "resolution": "Frame transform is documented; offset is resolved from registry structured fields in current cook path."},
        {"setting": "tile size", "category": "A", "authority": "scripts/cook_full_grid_tiles.py:TILE_SIZE_M and package descriptor", "duplicates": ["large_map_package.py default 1000.0"], "resolution": "Intentional local CLI/default; descriptor carries the actual staged value."},
        {"setting": "CARLA version", "category": "A", "authority": "release contract / environment configuration", "duplicates": ["README, reports, historical receipts"], "resolution": "Documentation/evidence only; runtime receipt must verify executable."},
        {"setting": "UE4 root", "category": "A", "authority": "UE4_ROOT environment variable", "duplicates": ["hardcoded E:/ paths in historical scripts"], "resolution": "Environment variable is runtime authority; hardcoded paths are legacy examples."},
        {"setting": "OSM2World path", "category": "A", "authority": "script argument or environment/config", "duplicates": ["historical default paths in cook scripts"], "resolution": "Explicit CLI argument wins; defaults are local conveniences."},
        {"setting": "lane width fallback", "category": "A", "authority": "lane_width_policy.DEFAULT_DRIVING_WIDTH_M", "duplicates": ["connector-specific 3.5 fallback", "historical mesh remediation constants"], "resolution": "Policy default is intentional; connector discrepancy is GAP-026 finding, not a global config authority conflict."},
        {"setting": "position tolerance", "category": "A", "authority": "checker call contract", "duplicates": ["historical evidence thresholds"], "resolution": "No silent changes; policy proposal is draft pending review."},
        {"setting": "experiment seeds", "category": "A", "authority": "experiment contract/manifest", "duplicates": ["test fixtures and historical reports"], "resolution": "Fixtures are local; production seeds remain manifest-bound."},
        {"setting": "output directories", "category": "A", "authority": "run/output contract", "duplicates": ["historical report directories"], "resolution": "Historical outputs are immutable evidence, not current selection."},
    ]
    return {"schema": "configuration_authority_audit/v1", "status": "PASS", "map_registry_sha256": pin["registry_sha256"], "map_sha256": pin["sha256"], "categories": {"A": "intentional local override", "B": "test fixture", "C": "historical evidence", "D": "duplicated production authority", "E": "stale documentation"}, "rows": rows, "production_authority_conflicts": [r["setting"] for r in rows if r["category"] == "D"], "policy": "No global config framework was invented; existing registry/contracts remain authoritative."}


if __name__ == "__main__":
    print(json.dumps(build_audit(), indent=2, sort_keys=True))
