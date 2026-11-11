"""Second-method cross-check of the X7 refit failure (ARCH-002 objective A).

Method differs from x7_geom_audit.py on purpose: no analytic derivatives. The candidate's
refit geometry is sampled ONLY through the canonical kernel (pose_at_s), and
  - arc length   = sum of chord distances between dense kernel samples,
  - reversal     = consecutive displacement vectors with negative dot product (the path
                   turns back on itself), which is what a stationary point of r(p) looks like
                   after sampling,
  - simplicity   = shapely LineString.is_simple on the kernel samples,
  - U-turn class = incoming touch point and topology-declared exit point coincide (<= 1e-3 m).
Usage: python x7_crosscheck_kernel.py <candidate_worktree> <05_planview.xodr> <out.json> [samples]
"""
import json
import math
import sys
import xml.etree.ElementTree as ET

WT, SRC, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
N = int(sys.argv[4]) if len(sys.argv) > 4 else 2000
sys.path.insert(0, WT)
from ultimate_pipeline.tools import junction_connector_snap as snap  # noqa: E402
from ultimate_pipeline.geometry.opendrive_geometry_kernel import pose_at_s  # noqa: E402
from shapely.geometry import LineString  # noqa: E402

root = ET.parse(SRC).getroot()
roads = {r.get("id"): r for r in root.findall("road")}
rep = snap.snap_junction_connectors(root)
rows = []
for r in rep["connector_pose_reports"]:
    cid = r["connector_id"]
    g = roads[cid].find("planView/geometry")
    L = float(g.get("length"))
    pts = [pose_at_s(g, min(L, L * i / N)) for i in range(N + 1)]
    xy = [(float(p.x), float(p.y)) for p in pts]
    arc = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(xy, xy[1:]))
    rev = 0
    for a, b, c in zip(xy, xy[1:], xy[2:]):
        d1 = (b[0] - a[0], b[1] - a[1])
        d2 = (c[0] - b[0], c[1] - b[1])
        if d1[0] * d2[0] + d1[1] * d2[1] < 0:
            rev += 1
    chord = math.hypot(xy[-1][0] - xy[0][0], xy[-1][1] - xy[0][1])
    rows.append({"id": cid, "L": L, "arc_ratio": arc / L, "reversals": rev,
                 "simple": LineString(xy).is_simple, "uturn": chord <= 1e-3})
u = [x for x in rows if x["uturn"]]
o = [x for x in rows if not x["uturn"]]
summary = {
    "method": "kernel-only sampling, N=%d per refit" % N,
    "refits": len(rows),
    "uturn_coincident_endpoints": len(u),
    "uturn_with_direction_reversal": sum(x["reversals"] > 0 for x in u),
    "uturn_not_simple": sum(not x["simple"] for x in u),
    "uturn_arc_ratio_min_max": [min(x["arc_ratio"] for x in u), max(x["arc_ratio"] for x in u)] if u else None,
    "other": len(o),
    "other_with_direction_reversal": sum(x["reversals"] > 0 for x in o),
    "other_not_simple": sum(not x["simple"] for x in o),
    "other_arc_dev_gt_10pct": sum(abs(x["arc_ratio"] - 1) > 0.10 for x in o),
    "other_arc_ratio_max": max(x["arc_ratio"] for x in o) if o else None,
}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(summary, f, indent=1)
print(json.dumps(summary, indent=1))
