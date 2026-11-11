import os as _os
# Paths come from the environment (see REPRODUCE.md); no machine-specific paths.
CANDIDATE_WT = _os.environ["CANDIDATE_WT"]
RUN_DIR = _os.environ["RUN_DIR"].rstrip("/\\") + "/"
OUT_DIR = _os.environ.get("OUT_DIR", ".").rstrip("/\\") + "/"

import json, math, sys, xml.etree.ElementTree as ET
sys.path.insert(0, CANDIDATE_WT)
from ultimate_pipeline.tools import junction_connector_snap as snap
from ultimate_pipeline.geometry.opendrive_geometry_kernel import pose_at_s, endpoint
SRC = RUN_DIR + "05_planview_20261007_214826_524342.xodr"
A = json.load(open(OUT_DIR + "x7_geom_audit.json"))
root = ET.parse(SRC).getroot()
roads = {r.get("id"): r for r in root.findall("road")}
conns = {}
for j in root.findall("junction"):
    for c in j.findall("connection"):
        conns.setdefault(c.get("connectingRoad"), []).append((j.get("id"), c.get("incomingRoad"), c.get("contactPoint")))
rep = snap.snap_junction_connectors(root.__copy__()) if False else None
# pick connectors: 3 from the snap report order (median chord) - rerun snap on a fresh parse to get ids
root2 = ET.parse(SRC).getroot()
r2 = snap.snap_junction_connectors(root2)
ids = [r["connector_id"] for r in r2["connector_pose_reports"]]
import statistics
sel = [ids[0], ids[len(ids)//2], ids[-1]]
def P(p): return f"({p.x:.3f},{p.y:.3f},h={math.degrees(getattr(p, "hdg", getattr(p, "heading", 0.0))):.1f})"
for cid in sel:
    rd = roads[cid]
    geoms = rd.findall("planView/geometry")
    s0 = pose_at_s(geoms[0], 0.0); e0 = endpoint(geoms[-1])
    print("connector", cid, "len", rd.get("length"), "junction", rd.get("junction"), "ngeom", len(geoms), [g[0].tag for g in geoms])
    print("  orig start", P(s0), "orig end", P(e0))
    lk = rd.find("link")
    print("  link:", [(x.tag, x.get("elementType"), x.get("elementId"), x.get("contactPoint")) for x in (lk if lk is not None else [])])
    print("  connections:", conns.get(cid))
    for jid, inc, cp in conns.get(cid, []):
        ir = roads[inc]; ig = ir.findall("planView/geometry")
        print("   incoming", inc, "junction", ir.get("junction"), "start", P(pose_at_s(ig[0],0.0)), "end", P(endpoint(ig[-1])))
    for x in (lk if lk is not None else []):
        if x.get("elementType") == "road":
            er = roads[x.get("elementId")]; eg = er.findall("planView/geometry")
            print("   linked", x.get("elementId"), "junction", er.get("junction"), "start", P(pose_at_s(eg[0],0.0)), "end", P(endpoint(eg[-1])))
    g = roads[cid] and root2.find(f"./road[@id='{cid}']/planView/geometry")
    print("  AFTER geom", dict(g.attrib), dict(g[0].attrib))
