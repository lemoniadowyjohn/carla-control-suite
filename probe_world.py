"""Direct mesh->world placement test: mesh_rel + obj_origin_native - rebase vs MoR."""
import sys
sys.path.insert(0, "tools")
from placement_control_anchor_assay import (
    load_obj_groups, load_tile_osm, ORACLE_FWD, obj_origin, load_mor_buildings,
    REBASE,
)
from pathlib import Path
import numpy as np
import math

mor = load_mor_buildings(
    Path("campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr"))
art = Path("reports/production_readiness/20260924T100614Z_FULL_GRID_TILE_FBX_COOK/artifacts")
for t in ["tile_6_6", "tile_9_6", "tile_10_8", "tile_9_7"]:
    td = art / t
    pre = "Ingolstadt_Tile_" + t.split("_", 1)[1]
    obj = next(td.glob("*.obj"))
    olat, olon = obj_origin(obj)
    ox, oy = ORACLE_FWD.transform(olon, olat)
    g = load_obj_groups(obj)
    V, G = g["verts"], g["groups"]
    # world position of each mesh vertex via origin+rebase chain
    res = []
    # match groups to MoR by way: need way->group assignment; use assay pairs is complex,
    # instead: for each mesh vertex, nearest MoR corner OF ANY BUILDING IN TILE is meaningless;
    # use buildings present in both: tile OSM ways matched to full OSM ids via assay JSON is overkill.
    # Simpler: whole-tile translation between mesh-centroid-set and MoR-corner-set is distribution-y.
    # Instead directly test one known building: way 35744635 in tile_6_8.
    print(t, "mesh verts:", len(V), "groups:", len(G))
