"""Lane-centre continuity at junction connector ENTRY and EXIT (ARCH-003 task 1/6).

For every junction connection laneLink (from = incoming lane, to = connector lane):
  entry : centre of incoming lane `from` at the incoming road's junction end
          vs centre of connector lane `to` at the connector's start (connection contactPoint=start)
  exit  : centre of connector lane `to` at the connector's end
          vs centre of the exit-road lane named by that connector lane's <link><successor id>
          at the exit road's contact end (connector road-level successor contactPoint).
Lane centre offset t(s) = laneOffset(s) + sign(k) * (sum_{1..|k|-1} w_i(s) + w_k(s)/2)
(OpenDRIVE: positive t to the left of the reference line, left lanes have positive ids).
Travel heading of lane k = reference heading + (pi if k > 0 else 0) (right-hand traffic).

Arms: OFF (input as is), SNAP (apply snap_junction_connectors from the given worktree in memory).
Usage: python lane_centre_continuity.py <worktree> <xodr> <arm: off|snap> <out.json>
"""
import json
import math
import sys
import xml.etree.ElementTree as ET

WT, SRC, ARM, OUT = sys.argv[1:5]
sys.path.insert(0, WT)
from ultimate_pipeline.geometry.opendrive_geometry_kernel import pose_at_s  # noqa: E402

root = ET.parse(SRC).getroot()
snap_report = None
if ARM == "snap":
    from ultimate_pipeline.tools import junction_connector_snap as snap  # noqa: E402
    snap_report = {k: v for k, v in snap.snap_junction_connectors(root).items() if not isinstance(v, list)}
roads = {r.get("id"): r for r in root.findall("road")}


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def poly(e, ds):
    a, b, c, d = (float(e.get(k, 0.0)) for k in "abcd")
    return a + b * ds + c * ds * ds + d * ds ** 3


def ref_pose(road, s):
    geoms = road.findall("planView/geometry")
    g = geoms[0]
    for cand in geoms:
        if float(cand.get("s")) <= s + 1e-9:
            g = cand
    ls = min(max(s - float(g.get("s")), 0.0), float(g.get("length")))
    p = pose_at_s(g, ls)
    return float(p.x), float(p.y), float(p.heading)


def lane_offset(road, s):
    los = [e for e in road.findall("lanes/laneOffset") if float(e.get("s")) <= s + 1e-9]
    if not los:
        return 0.0
    lo = max(los, key=lambda e: float(e.get("s")))
    return poly(lo, s - float(lo.get("s")))


def section_at(road, s):
    secs = road.findall("lanes/laneSection")
    best = secs[0]
    for sec in secs:
        if float(sec.get("s")) <= s + 1e-9:
            best = sec
    return best


def width(lane, ds):
    ws = [w for w in lane.findall("width") if float(w.get("sOffset")) <= ds + 1e-9]
    if not ws:
        ws = lane.findall("width")[:1]
    if not ws:
        return 0.0
    w = max(ws, key=lambda e: float(e.get("sOffset")))
    return poly(w, ds - float(w.get("sOffset")))


def lane_centre(road, s, k):
    sec = section_at(road, s)
    ds = s - float(sec.get("s"))
    side = "left" if k > 0 else "right"
    lanes = {int(l.get("id")): l for l in sec.findall(side + "/lane")}
    if k not in lanes:
        return None
    sign = 1.0 if k > 0 else -1.0
    inner = sum(width(lanes[i], ds) for i in (range(1, k) if k > 0 else range(-1, k, -1)) if i in lanes)
    t = lane_offset(road, s) + sign * (inner + width(lanes[k], ds) / 2.0)
    x, y, h = ref_pose(road, s)
    return x - t * math.sin(h), y + t * math.cos(h), wrap(h + (math.pi if k > 0 else 0.0))


def junction_end_s(road, jid):
    lk = road.find("link")
    L = float(road.get("length"))
    if lk is not None:
        for slot, s in (("successor", L), ("predecessor", 0.0)):
            e = lk.find(slot)
            if e is not None and e.get("elementType") == "junction" and e.get("elementId") == jid:
                return s
    return None


UV = {}
rows = {"entry_gap": [], "entry_kink": [], "exit_gap": [], "exit_kink": []}
counts = {"lanelinks": 0, "entry_unresolved": 0, "exit_unresolved": 0, "connector_left_lane_to": 0}
for j in root.findall("junction"):
    jid = j.get("id")
    for c in j.findall("connection"):
        inc, con = roads.get(c.get("incomingRoad")), roads.get(c.get("connectingRoad"))
        if inc is None or con is None or (c.get("contactPoint") or "start") != "start":
            continue
        s_inc = junction_end_s(inc, jid)
        Lc = float(con.get("length"))
        lk = con.find("link")
        succ = lk.find("successor") if lk is not None else None
        ex = roads.get(succ.get("elementId")) if succ is not None and succ.get("elementType") == "road" else None
        ex_cp = (succ.get("contactPoint") or "").lower() if succ is not None else ""
        for ll in c.findall("laneLink"):
            counts["lanelinks"] += 1
            fr, to = int(ll.get("from")), int(ll.get("to"))
            if to > 0:
                counts["connector_left_lane_to"] += 1
            a = lane_centre(inc, s_inc, fr) if s_inc is not None else None
            b = lane_centre(con, 0.0, to)
            if a is None or b is None:
                counts["entry_unresolved"] += 1
            else:
                rows["entry_gap"].append(math.hypot(a[0] - b[0], a[1] - b[1]))
                rows["entry_kink"].append(abs(math.degrees(wrap(a[2] - b[2]))))
            # exit
            sec_end = section_at(con, Lc)
            ln = {int(l.get("id")): l for l in sec_end.findall(("left" if to > 0 else "right") + "/lane")}.get(to)
            nxt = ln.find("link/successor") if ln is not None else None
            if ex is None or ex_cp not in ("start", "end") or nxt is None:
                counts["exit_unresolved"] += 1
                continue
            e_lane = int(nxt.get("id"))
            p = lane_centre(con, Lc, to)
            q = lane_centre(ex, 0.0 if ex_cp == "start" else float(ex.get("length")), e_lane)
            if p is None or q is None:
                counts["exit_unresolved"] += 1
                continue
            rows["exit_gap"].append(math.hypot(p[0] - q[0], p[1] - q[1]))
            if a is not None and b is not None:
                ut = abs(math.degrees(wrap(a[2] - q[2]))) > 150
                key = "uturn" if ut else "non_uturn"
                cls = counts.setdefault("by_class", {}).setdefault(key, {"lanelinks": 0, "entry_gap_gt_0_5": 0, "entry_gap_gt_1": 0, "entry_kink_gt_10": 0, "exit_gap_gt_0_5": 0, "exit_gap_gt_1": 0, "exit_kink_gt_10": 0, "exit_kink_gt_30": 0})
                eg = math.hypot(a[0] - b[0], a[1] - b[1]); ek = abs(math.degrees(wrap(a[2] - b[2])))
                xg = math.hypot(p[0] - q[0], p[1] - q[1]); xk = abs(math.degrees(wrap(p[2] - q[2])))
                cls["lanelinks"] += 1
                if ut: UV.setdefault("eg",[]).append(eg); UV.setdefault("ek",[]).append(ek); UV.setdefault("xg",[]).append(xg); UV.setdefault("xk",[]).append(xk)
                cls["entry_gap_gt_0_5"] += eg > .5; cls["entry_gap_gt_1"] += eg > 1; cls["entry_kink_gt_10"] += ek > 10
                cls["exit_gap_gt_0_5"] += xg > .5; cls["exit_gap_gt_1"] += xg > 1; cls["exit_kink_gt_10"] += xk > 10; cls["exit_kink_gt_30"] += xk > 30
            rows["exit_kink"].append(abs(math.degrees(wrap(p[2] - q[2]))))


def dist(v):
    v = sorted(v)
    n = len(v)
    q = lambda f: v[min(n - 1, int(f * (n - 1)))] if n else None
    return {"n": n, "p50": q(.5), "p99": q(.99), "max": v[-1] if n else None}


def pct(v, f):
    v = sorted(v); return v[min(len(v)-1, int(f*(len(v)-1)))] if v else None
summary_uturn = {k: {"p05": pct(v,.05), "p25": pct(v,.25), "p50": pct(v,.5), "p75": pct(v,.75), "p95": pct(v,.95)} for k, v in UV.items()}
summary = {"uturn_distributions": summary_uturn, "arm": ARM, "worktree": WT.rsplit("/", 1)[-1], "snap_report": snap_report, "counts": counts}
for k in ("entry_gap", "exit_gap"):
    v = rows[k]
    summary[k] = dict(dist(v), gt_0_10m=sum(x > .10 for x in v), gt_0_50m=sum(x > .5 for x in v), gt_1m=sum(x > 1 for x in v))
for k in ("entry_kink", "exit_kink"):
    v = rows[k]
    summary[k] = dict(dist(v), gt_10deg=sum(x > 10 for x in v), gt_30deg=sum(x > 30 for x in v), gt_150deg=sum(x > 150 for x in v))
json.dump(summary, open(OUT, "w"), indent=1)
print(json.dumps(summary, indent=1))
