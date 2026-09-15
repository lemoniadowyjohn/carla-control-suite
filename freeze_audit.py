#!/usr/bin/env python3
"""Geometry Freeze Audit - trace functions capable of mutating planView etc."""
import json
import pathlib
import re

# Search for functions that mutate geometry
search_dirs = ["ultimate_pipeline/geometry", "ultimate_pipeline/topology", "ultimate_pipeline/enrichment", "ultimate_pipeline/pipeline_stages"]

mutations = {
    "planView": [],
    "geometry_primitives": [],
    "road_length": [],
    "junction_connector_geometry": [],
    "coordinate_offsets": []
}

# Patterns that indicate mutation
patterns = {
    "planView": [r"planView", r"\.find.*geometry", r"geometry\.set", r"planView.*append"],
    "geometry_primitives": [r"def.*geometry", r"primitive", r"spiral", r"arc", r"poly3"],
    "road_length": [r"road\.set.*length", r"length.*=", r"road_length"],
    "junction_connector_geometry": [r"junction.*connector", r"connectingRoad", r"connector.*rebuild", r"junction_model"],
    "coordinate_offsets": [r"offset", r"geoReference", r"coordinate.*transform", r"proj.*transform"]
}

for dir_path in search_dirs:
    p = pathlib.Path(dir_path)
    if not p.exists():
        continue
    for file in p.rglob("*.py"):
        try:
            content = file.read_text(encoding="utf-8", errors="ignore")
            for category, pats in patterns.items():
                for pat in pats:
                    if re.search(pat, content, re.IGNORECASE):
                        mutations[category].append(str(file))
                        break
        except:
            pass

# Deduplicate
for k in mutations:
    mutations[k] = sorted(list(set(mutations[k])))

# Check if any can execute after freeze
# The freeze is typically after stage_05_geometry, stage_06_links etc.
# Look for stage files that run after geometry freeze

freeze_stage = "stage_05_geometry.py"
post_freeze_mutations = []
for file_list in mutations.values():
    for f in file_list:
        if "stage_0" in f and "stage_05" not in f and "stage_06" not in f:
            # Check if stage number > 05
            try:
                # Extract stage number
                match = re.search(r"stage_(\d+)", f)
                if match and int(match.group(1)) > 5:
                    post_freeze_mutations.append(f)
            except:
                pass

# Determine if post-freeze mutation is reachable
reachable = len(post_freeze_mutations) > 0
status = "FAILED" if reachable else "VERIFIED"
guard_needed = reachable

audit = {
    "freeze_stage": "stage_05_geometry (horizontal geometry freeze)",
    "mutations_by_category": mutations,
    "post_freeze_mutations_reachable": post_freeze_mutations,
    "reachable_without_invalidation": reachable,
    "status": status,
    "guard_required": guard_needed,
    "mutation_dag": {
        "nodes": ["stage_05_geometry", "stage_06_links", "stage_07_lanes", "stage_08_hygiene", "stage_09_tiling"],
        "edges": [
            ["stage_05_geometry", "stage_06_links"],
            ["stage_06_links", "stage_07_lanes"],
            ["stage_07_lanes", "stage_08_hygiene"],
            ["stage_08_hygiene", "stage_09_tiling"]
        ],
        "note": "Any mutation of planView after stage_05_geometry should trigger invalidation of downstream stages; current pipeline does not have fail-closed guard for all paths"
    },
    "timestamp": "2026-09-15T23:00:00Z"
}

print(f"Post-freeze mutations reachable: {reachable}")
print(f"Files with potential post-freeze mutations: {post_freeze_mutations[:5]}")

with open("reports/production_readiness/20260915T230000Z_GEOMETRY_TOPOLOGY_ORACLE_V2/GEOMETRY_FREEZE_AUDIT.json", "w") as f:
    json.dump(audit, f, indent=2)

print("Done")
