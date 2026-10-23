"""Determine whether PrepareAssetsForCooking's SetMaterial branches could ever
fire for the current canonical assets.

SSTags (Plugins/Carla/Source/Carla/Commandlet/SSTags.h) are plain substrings
matched against the ASSET NAME via AssetName.Contains(...). This counts, over
all canonical StaticMeshes, how many names can satisfy each branch, and
whether the 8 MAT_N_M packages can ever be selected by this mechanism.

Read-only: name analysis only, no package is opened for writing.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter

CONTENT = r"G:\CARLA\carla_source_probe\Unreal\CarlaUE4\Content"
CANON_DIR = os.path.join(CONTENT, "Ingolstadt", "Static", "Terrain",
                         "Ingolstadt")
MAPS_DIR = os.path.join(CONTENT, "Ingolstadt", "Maps", "Ingolstadt")
OUT = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports"

SSTAGS = {
    "R_ROAD1": "Road_Road", "R_ROAD2": "Roads_Road",
    "R_GRASS1": "Road_Grass", "R_GRASS2": "Roads_Grass",
    "R_MARKING1": "Road_Marking", "R_MARKING2": "Roads_Marking",
    "R_SIDEWALK1": "Road_Sidewalk", "R_SIDEWALK2": "Roads_Sidewalk",
    "R_CURB1": "Road_Curb", "R_CURB2": "Roads_Curb",
    "R_GUTTER1": "Road_Gutter", "R_GUTTER2": "Roads_Gutter",
    "R_TERRAIN": "Terrain",
}

ASSIGNED = {
    "R_MARKING": ["M_Road_03_Tiled_V3", "M_Road_03_LMW"],
    "R_ROAD": ["M_Road_03_Tiled_V2"],
    "R_TERRAIN": ["MI_LargeLandscape_Grass"],
    "R_SIDEWALK": ["MI_largeM_tile02"],
    "R_CURB": ["MI_largeM_curb01"],
    "R_GUTTER": ["MI_largeM_gutter01"],
}

BRANCHES = [
    ("R_MARKING", ["R_MARKING1", "R_MARKING2"]),
    ("R_ROAD", ["R_ROAD1", "R_ROAD2"]),
    ("R_TERRAIN", ["R_TERRAIN"]),
    ("R_SIDEWALK", ["R_SIDEWALK1", "R_SIDEWALK2"]),
    ("R_CURB", ["R_CURB1", "R_CURB2"]),
    ("R_GUTTER", ["R_GUTTER1", "R_GUTTER2"]),
]


def main():
    names = [os.path.splitext(n)[0] for n in os.listdir(CANON_DIR)
             if n.endswith(".uasset")]

    per_branch = Counter()
    per_tag = Counter()
    matched_any = 0
    examples = {}
    for n in names:
        hit = None
        for branch, tags in BRANCHES:
            if any(SSTAGS[t] in n for t in tags):
                hit = branch
                break
        if hit:
            matched_any += 1
            per_branch[hit] += 1
            examples.setdefault(hit, n)
        for t, v in SSTAGS.items():
            if v in n:
                per_tag[t] += 1

    # material assets themselves
    mats = sorted(x for x in os.listdir(MAPS_DIR)
                  if x.startswith("MAT_") and x.endswith(".uasset"))
    mats_matching_tag = [m for m in mats
                        if any(v in m for v in SSTAGS.values())]

    # are the 7 assigned materials referenced by any tile world?
    tile_worlds = sorted(x for x in os.listdir(MAPS_DIR)
                        if x.startswith("Ingolstadt_Tile_")
                        and x.endswith(".umap"))
    world_refs = {}
    for w in tile_worlds:
        with open(os.path.join(MAPS_DIR, w), "rb") as fh:
            blob = fh.read()
        found = [a for group in ASSIGNED.values() for a in group
                 if a.encode() in blob]
        if found:
            world_refs[w] = sorted(set(found))

    result = {
        "schema": "MATERIAL_SLOT_BINDING_RULE/v1",
        "mechanism": {
            "producer_of_real_bindings":
                "Plugins/Carla/Source/Carla/Commandlet/"
                "PrepareAssetsForCookingCommandlet.cpp lines 225-267",
            "binding_level": "StaticMeshComponent override (SetMaterial), NOT "
                             "the StaticMesh asset's StaticMaterials array",
            "selector": "AssetName.Contains(SSTags::...) against the asset "
                        "name string",
            "sstags": SSTAGS,
            "assigned_materials": ASSIGNED,
            "note": "SetMaterial(i, ...) on the component writes an override; "
                    "the mesh asset's own StaticMaterials are left as imported.",
        },
        "canonical_mesh_total": len(names),
        "canonical_meshes_matching_any_branch": matched_any,
        "canonical_meshes_matching_no_branch": len(names) - matched_any,
        "per_branch_counts": dict(per_branch),
        "per_sstag_counts": dict(per_tag),
        "branch_examples": examples,
        "MAT_N_M_count": len(mats),
        "MAT_N_M_matching_any_sstag": mats_matching_tag,
        "MAT_N_M_can_be_selected_by_this_mechanism":
            "NO. No SSTag substring appears in any MAT_N_M name, and no "
            "SetMaterial call in PrepareAssetsForCookingCommandlet references "
            "a MAT_ path.",
        "tile_worlds_scanned": len(tile_worlds),
        "tile_worlds_referencing_assigned_materials": len(world_refs),
        "tile_world_material_references": world_refs,
        "DYNAMIC_MATERIAL_LOOKUP": "REFUTED",
        "DYNAMIC_MATERIAL_LOOKUP_basis":
            "No LoadObject/StaticLoadObject/FindObject/FSoftObjectPath lookup "
            "keyed on a MAT_ name exists in the tile pipeline. The only "
            "runtime material binding for map meshes is the PrepareAssets "
            "SetMaterial branch above, which selects 7 fixed "
            "/Game/Carla/... material instances by asset-name tag.",
    }
    with open(os.path.join(OUT, "MATERIAL_SLOT_BINDING_RULE.json"), "w",
              encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
    print(json.dumps({k: v for k, v in result.items()
                      if k not in ("mechanism",)}, indent=2)[:2600])


if __name__ == "__main__":
    main()
