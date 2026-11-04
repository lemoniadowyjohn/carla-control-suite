"""Start displacement applied by the X7 snap (entry_error_before_m = |old start - snapped start|).
Usage: python x7_displacement.py <candidate_worktree> <05_planview.xodr>"""
import sys, xml.etree.ElementTree as ET
sys.path.insert(0, sys.argv[1])
from ultimate_pipeline.tools import junction_connector_snap as snap
root = ET.parse(sys.argv[2]).getroot()
L = {r.get("id"): float(r.get("length")) for r in root.findall("road")}
rep = snap.snap_junction_connectors(root)
rows = [(r["connector_id"], r["entry_error_before_m"], L[r["connector_id"]]) for r in rep["connector_pose_reports"]]
d = sorted(x[1] for x in rows)
print("refits", len(rows), "move p50 %.3f p99 %.3f max %.3f" % (d[len(d)//2], d[int(.99*(len(d)-1))], d[-1]))
print("move > connector length:", sum(m > l for _, m, l in rows), "; move > 5 m:", sum(m > 5 for _, m, _ in rows))
for cid in ("68739", "67905", "68731", "51810"):
    print(cid, [("move_m %.3f" % m, "length_m %.3f" % l) for c, m, l in rows if c == cid])
# Lane-width hypothesis: is each move equal to a sum of the incoming road's lane widths at its contact end?
import collections
roads = {r.get("id"): r for r in root.findall("road")}
conn_in = {}
for j in root.findall("junction"):
    for c in j.findall("connection"):
        conn_in.setdefault(c.get("connectingRoad"), c.get("incomingRoad"))
def lane_widths_at_end(road):
    secs = road.findall("lanes/laneSection")
    sec = secs[-1] if secs else None
    ws = []
    if sec is None: return ws
    for side in ("left", "right"):
        for ln in sec.findall(side + "/lane"):
            w = ln.find("width")
            if w is not None: ws.append((side, int(ln.get("id")), float(w.get("a"))))
    return ws
match = 0; tot = 0; examples = []
for cid, m, l in rows:
    inc = roads.get(conn_in.get(cid))
    ws = lane_widths_at_end(inc) if inc is not None else []
    cands = set()
    for side in ("left", "right"):
        acc = 0.0
        for _, _, w in sorted([x for x in ws if x[0] == side], key=lambda x: abs(x[1])):
            acc += w; cands.add(round(acc, 3))
    tot += 1
    if any(abs(m - c) <= 0.01 for c in cands):
        match += 1
    elif len(examples) < 5:
        examples.append((cid, round(m, 3), sorted(cands)))
print("moves equal to a cumulative lane width of the incoming road (+-1 cm):", match, "of", tot)
print("non-matching examples:", examples)
print("most common moves:", collections.Counter(round(m, 2) for _, m, _ in rows).most_common(8))
# Lane-level check: does the original connector reference line sit on the inner border of the
# laneLink 'from' lane of the incoming road?  inner border offset of lane k = sum widths of lanes 1..|k|-1 on that side.
links = {}
for j in root.findall("junction"):
    for c in j.findall("connection"):
        if c.get("connectingRoad") not in links:
            links[c.get("connectingRoad")] = [(int(ll.get("from")), int(ll.get("to"))) for ll in c.findall("laneLink")]
ok = bad = nolink = 0; bad_ex = []
for cid, m, l in rows:
    inc = roads.get(conn_in.get(cid)); ll = links.get(cid) or []
    if inc is None or not ll: nolink += 1; continue
    ws = lane_widths_at_end(inc)
    hit = False
    for fr, to in ll:
        side = "left" if fr > 0 else "right"
        inner = sum(w for s, i, w in ws if s == side and 0 < abs(i) < abs(fr))
        if abs(inner - m) <= 0.01: hit = True
    if hit: ok += 1
    else:
        bad += 1
        if len(bad_ex) < 4: bad_ex.append((cid, round(m, 3), ll, [(s, i, w) for s, i, w in ws]))
print("move == inner-border offset of a laneLink 'from' lane:", ok, "; not:", bad, "; no laneLink:", nolink)
print("examples not matching:", bad_ex)
