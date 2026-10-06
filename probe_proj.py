"""Test: does OSM2World use per-tile-centered tmerc instead of bare-tmerc?"""
import sys
sys.path.insert(0, "tools")
from placement_control_anchor_assay import load_tile_osm, load_obj_groups, obj_origin
from pathlib import Path
from pyproj import Transformer
import numpy as np
import math

for t in ["tile_6_6", "tile_6_7", "tile_10_8"]:
    td = Path("reports/production_readiness/20260924T100614Z_FULL_GRID_TILE_FBX_COOK/artifacts") / t
    obj = next(td.glob("*.obj"))
    osm = next(td.glob("*.osm"))
    olat, olon = obj_origin(obj)
    tw = load_tile_osm(osm)
    # per-tile-centered tmerc hypothesis
    loc = Transformer.from_crs(
        "EPSG:4326",
        f"+proj=tmerc +lat_0={olat} +lon_0={olon} +k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs",
        always_xy=True,
    )
    exp = []
    for w in tw:
        for p in w["lonlat"]:
            exp.append(loc.transform(*p))
    exp = np.array(exp)
    g = load_obj_groups(obj)
    V = g["verts"]
    # coverage: expected->mesh nearest
    d = [np.hypot(V[:, 0] - e[0], V[:, 1] - e[1]).min() for e in exp[::max(1, len(exp) // 300)]]
    print(t, "centered-tmerc coverage p50/p95: %.1f / %.1f" % (np.median(d), np.percentile(d, 95)))
