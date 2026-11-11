"""Count U-turn junction connectors (exit road is the reverse twin of the incoming road) per stage."""
import math, sys, xml.etree.ElementTree as ET
sys.path.insert(0, "E:/wt/fix-gap070-connector-snap-exit-20261103")
from ultimate_pipeline.geometry.opendrive_geometry_kernel import pose_at_s, endpoint
R = "C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main/reports/rq1_trial_runs/run_01/20261007_214826_524342/"
def ends(road):
    g = road.findall("planView/geometry")
    a, b = pose_at_s(g[0], 0.0), endpoint(g[-1])
    return {"start": (a.x, a.y, a.heading), "end": (b.x, b.y, b.heading)}
for name in sys.argv[1:]:
    root = ET.parse(R + name).getroot()
    roads = {r.get("id"): r for r in root.findall("road")}
    cache = {}
    def E(rid):
        if rid not in cache: cache[rid] = ends(roads[rid])
        return cache[rid]
    n_conn = uturn = uturn_same_ref = 0
    lengths = []
    seen = set()
    for j in root.findall("junction"):
        for c in j.findall("connection"):
            cid, inc = c.get("connectingRoad"), c.get("incomingRoad")
            if cid in seen or cid not in roads or inc not in roads: continue
            seen.add(cid); n_conn += 1
            lk = roads[cid].find("link")
            ex = None
            for it in (list(lk) if lk is not None else []):
                if it.get("elementType") == "road" and it.get("elementId") not in (inc, None) and it.get("elementId") in roads:
                    ex = (it.get("elementId"), (it.get("contactPoint") or "start").lower())
            if ex is None: continue
            cp_in = (c.get("contactPoint") or "start").lower()
            # incoming touch end: the end of incoming nearest the connector start
            cs = E(cid)["start"]; ie = E(inc)
            touch = min(("start", "end"), key=lambda k: math.hypot(ie[k][0]-cs[0], ie[k][1]-cs[1]))
            ip = ie[touch]; ih = ip[2] if touch == "end" else ip[2] + math.pi
            ep = E(ex[0])[ex[1]]; eh = ep[2] if ex[1] == "start" else ep[2] + math.pi
            turn = abs(math.degrees((eh - ih + math.pi) % (2*math.pi) - math.pi))
            if turn > 150:
                uturn += 1
                lengths.append(float(roads[cid].get("length")))
                if math.hypot(ip[0]-ep[0], ip[1]-ep[1]) < 0.01: uturn_same_ref += 1
    lengths.sort()
    print(name.split("_2026")[0], "connectors", n_conn, "uturn(>150deg)", uturn,
          "uturn with coincident incoming/exit reference points", uturn_same_ref,
          "len p50", lengths[len(lengths)//2] if lengths else None, flush=True)
    del root, roads, cache
