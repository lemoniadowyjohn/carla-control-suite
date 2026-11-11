import json, math, sys, xml.etree.ElementTree as ET
sys.path.insert(0, "E:/wt/fix-gap070-connector-snap-exit-20261103")
from ultimate_pipeline.tools import junction_connector_snap as snap
from ultimate_pipeline.geometry.opendrive_geometry_kernel import pose_at_s, endpoint
SRC = "C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main/reports/rq1_trial_runs/run_01/20261007_214826_524342/05_planview_20261007_214826_524342.xodr"
A = json.load(open("C:/Users/admin/AppData/Local/Temp/claude/C--Users-admin-PycharmProjects-gpt4-pythonProject3-carla--main/0b5b4ef8-7df2-41a5-90d5-d3ad2b0f9bcc/scratchpad/x7_geom_audit.json"))
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
