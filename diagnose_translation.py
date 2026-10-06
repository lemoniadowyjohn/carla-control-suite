"""Diagnose: is mesh-leg error a per-tile pure translation (auto-centering)?"""
import json, re
import numpy as np
from pathlib import Path
from collections import defaultdict
import sys
sys.path.insert(0, "tools")
from placement_control_anchor_assay import load_obj_groups, obj_origin, ORACLE_FWD
import xml.etree.ElementTree as ET

rep = json.load(open("TRUE_WORLD_PLACEMENT_ACCEPTANCE_V2.json"))
anchors = [a for a in rep["anchors"] if "anchor_id" in a]
root = Path("reports/production_readiness/20260924T100614Z_FULL_GRID_TILE_FBX_COOK/artifacts")

# rebuild actual nearest-vertex coords per anchor (same matching as assay)
by_tile = defaultdict(list)
for a in anchors:
    by_tile[a["tile"]].append(a)

for t in sorted(by_tile)[:20]:
    td = root / t
    obj = next(td.glob("*.obj"))
    groups = load_obj_groups(obj)
    gnames = sorted(groups.keys())
    # rebuild tile ways deterministically: need mapping anchor->group; reuse assay order is complex,
    # instead directly measure: for each anchor, nearest vertex in WHOLE tile mesh
    allv = np.vstack([v for v in groups.values() if len(v)]) if groups else np.zeros((0, 2))
    olat, olon = obj_origin(obj)
    ox, oy = ORACLE_FWD.transform(olon, olat)
    trans = []
    for a in by_tile[t]:
        ex, ey = a["expected_native"]
        d = np.hypot(allv[:, 0] - (ex - ox), allv[:, 1] - (ey - oy))
        j = int(np.argmin(d))
        trans.append((ex - ox - allv[j, 0], ey - oy - allv[j, 1]))
    trans = np.array(trans)
    med = np.median(trans, axis=0)
    std = trans.std(axis=0)
    res = np.hypot(trans[:, 0] - med[0], trans[:, 1] - med[1])
    print(f"{t}: n={len(trans)} T=({med[0]:.1f},{med[1]:.1f}) std=({std[0]:.2f},{std[1]:.2f}) p95detrend={np.percentile(res,95):.2f} maxdetrend={res.max():.2f}")
