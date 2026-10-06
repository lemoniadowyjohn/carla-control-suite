import sys
sys.path.insert(0, "tools")
from placement_control_anchor_assay import load_tile_osm, ORACLE_FWD, obj_origin
from pathlib import Path
import math

for t in ["tile_6_6", "tile_6_7", "tile_10_8", "tile_9_7"]:
    td = Path("reports/production_readiness/20260924T100614Z_FULL_GRID_TILE_FBX_COOK/artifacts") / t
    obj = next(td.glob("*.obj"))
    osm = next(td.glob("*.osm"))
    olat, olon = obj_origin(obj)
    tw = load_tile_osm(osm)
    los = []
    las = []
    for w in tw:
        for p in w["lonlat"]:
            los.append(p[0])
            las.append(p[1])
    ax, ay = ORACLE_FWD.transform((min(los) + max(los)) / 2, (min(las) + max(las)) / 2)
    corners = [(min(los), min(las)), (max(los), min(las)), (min(los), max(las)), (max(los), max(las))]
    proj = [ORACLE_FWD.transform(x, y) for (x, y) in corners]
    bx = sum(p[0] for p in proj) / 4
    by = sum(p[1] for p in proj) / 4
    print(t, "A-vs-B m:", round(math.hypot(ax - bx, ay - by), 2))
