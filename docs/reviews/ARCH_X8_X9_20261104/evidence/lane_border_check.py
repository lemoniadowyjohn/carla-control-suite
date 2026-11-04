"""Is each junction connector's ORIGINAL start point the inner-border point of its laneLink
'from' lane on the incoming road (i.e. lane-continuous by construction)?  Pre-snap, read-only.

For incoming road end pose (x, y, h) with contact 'end' and right-hand lanes, the inner border of
lane k (k<0) lies at lateral offset t = -(sum of widths of lanes -1..k+1), plus laneOffset(s_end).
Point = (x - t*sin h, y + t*cos h)  [t positive = left].  Left lanes mirror with +.
Usage: python lane_border_check.py <worktree_for_kernel> <xodr> <candidate_worktree_for_snap_ids>
"""
import math
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, sys.argv[1])
from ultimate_pipeline.geometry.opendrive_geometry_kernel import pose_at_s, endpoint  # noqa: E402

root = ET.parse(sys.argv[2]).getroot()
roads = {r.get("id"): r for r in root.findall("road")}


def lane_offset_at_end(road):
    los = road.findall("lanes/laneOffset")
    if not los:
        return 0.0
    lo = sorted(los, key=lambda e: float(e.get("s")))[-1]
    ds = float(road.get("length")) - float(lo.get("s"))
    a, b, c, d = (float(lo.get(k)) for k in "abcd")
    return a + b * ds + c * ds ** 2 + d * ds ** 3


def widths_at_end(road):
    sec = road.findall("lanes/laneSection")[-1]
    s_sec = float(sec.get("s"))
    ds = float(road.get("length")) - s_sec
    out = {}
    for ln in sec.findall("left/lane") + sec.findall("right/lane"):
        ws = ln.findall("width")
        if not ws:
            continue
        w = sorted(ws, key=lambda e: float(e.get("sOffset")))[-1]
        dd = ds - float(w.get("sOffset"))
        a, b, c, d = (float(w.get(k)) for k in "abcd")
        out[int(ln.get("id"))] = a + b * dd + c * dd ** 2 + d * dd ** 3
    return out


tot = at_border = at_ref = neither = 0
far = []
seen = set()
for j in root.findall("junction"):
    for c in j.findall("connection"):
        cid, inc_id = c.get("connectingRoad"), c.get("incomingRoad")
        if cid in seen or cid not in roads or inc_id not in roads:
            continue
        if (c.get("contactPoint") or "start").lower() != "start":
            continue
        seen.add(cid)
        conn_g = roads[cid].findall("planView/geometry")
        st = pose_at_s(conn_g[0], 0.0)
        inc = roads[inc_id]
        ig = inc.findall("planView/geometry")
        # touch end of incoming = the end nearest the connector start
        a, b = pose_at_s(ig[0], 0.0), endpoint(ig[-1])
        use_end = math.hypot(b.x - st.x, b.y - st.y) <= math.hypot(a.x - st.x, a.y - st.y)
        if not use_end:
            continue  # only the incoming-end case (all 4,025 refits are this case)
        x, y, h = b.x, b.y, b.heading
        ws = widths_at_end(inc)
        lo = lane_offset_at_end(inc)
        best = None
        for ll in c.findall("laneLink"):
            fr = int(ll.get("from"))
            if fr < 0:
                t = lo - sum(ws.get(k, 0.0) for k in range(-1, fr, -1))
            else:
                t = lo + sum(ws.get(k, 0.0) for k in range(1, fr))
            px, py = x - t * math.sin(h), y + t * math.cos(h)
            dist = math.hypot(px - st.x, py - st.y)
            best = dist if best is None else min(best, dist)
        tot += 1
        dref = math.hypot(x - st.x, y - st.y)
        if best is not None and best <= 0.01:
            at_border += 1
        elif dref <= 0.01:
            at_ref += 1
        else:
            neither += 1
            if len(far) < 5:
                far.append((cid, round(dref, 3), round(best, 3) if best is not None else None))
print({"connectors_incoming_end_contact_start": tot,
       "start_on_from_lane_inner_border": at_border,
       "start_on_incoming_reference_point": at_ref,
       "neither": neither, "neither_examples(id, d_ref, d_border)": far})
