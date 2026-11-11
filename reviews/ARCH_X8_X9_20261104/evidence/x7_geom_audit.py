"""Read-only numerical audit of the X7 Hermite refit (fix/gap070-connector-snap-exit-20261103 @2cee039f).

Runs the candidate snap in memory on the untracked 2026-10-07 stage-5 output and measures every
refit connector. Writes only a JSON summary to the scratchpad.
"""
import json
import math
import sys
import time
import xml.etree.ElementTree as ET

WT = "E:/wt/fix-gap070-connector-snap-exit-20261103"
sys.path.insert(0, WT)
from ultimate_pipeline.tools import junction_connector_snap as snap  # noqa: E402
from ultimate_pipeline.geometry.opendrive_geometry_kernel import pose_at_s  # noqa: E402
from shapely.geometry import LineString  # noqa: E402

SRC = ("C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main/reports/rq1_trial_runs/run_01/"
       "20261007_214826_524342/05_planview_20261007_214826_524342.xodr")
OUT = ("C:/Users/admin/AppData/Local/Temp/claude/C--Users-admin-PycharmProjects-gpt4-pythonProject3-carla--main/"
       "0b5b4ef8-7df2-41a5-90d5-d3ad2b0f9bcc/scratchpad/x7_geom_audit.json")


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def adiff_deg(a, b):
    return abs(math.degrees(wrap(a - b)))


def kernel_samples(plan_el, n_per_geom=60):
    pts = []
    for g in plan_el.findall("geometry"):
        L = float(g.get("length"))
        for i in range(n_per_geom + 1):
            p = pose_at_s(g, min(L, L * i / n_per_geom))
            pts.append((float(p.x), float(p.y), float(p.heading)))
    return pts


def curve_metrics(pts):
    arc = 0.0
    kmax = 0.0
    turn = 0.0
    for (x0, y0, h0), (x1, y1, h1) in zip(pts, pts[1:]):
        ds = math.hypot(x1 - x0, y1 - y0)
        dh = wrap(h1 - h0)
        arc += ds
        turn += abs(dh)
        if ds > 1e-9:
            kmax = max(kmax, abs(dh) / ds)
    return arc, kmax, turn


def main():
    t0 = time.time()
    root = ET.parse(SRC).getroot()
    roads = {r.get("id"): r for r in root.findall("road")}
    before_plan = {}
    for j in root.findall("junction"):
        for c in j.findall("connection"):
            cid = c.get("connectingRoad")
            if cid in roads and cid not in before_plan:
                before_plan[cid] = ET.tostring(roads[cid].find("planView"))
    conn_of = {}
    for j in root.findall("junction"):
        for c in j.findall("connection"):
            conn_of.setdefault(c.get("connectingRoad"), c)

    rep = snap.snap_junction_connectors(root)
    print("snap done", round(time.time() - t0, 1), "s; snapped", rep["connectors_snapped"],
          "skipped_missing_exit_anchor", rep["skipped_missing_exit_anchor"],
          "skipped_refit_validation", rep["skipped_refit_validation"], flush=True)

    rows = []
    for r in rep["connector_pose_reports"]:
        cid = r["connector_id"]
        road = roads[cid]
        plan = road.find("planView")
        g = plan.find("geometry")
        L = float(g.get("length"))
        x0, y0, h0 = float(g.get("x")), float(g.get("y")), float(g.get("hdg"))
        pp = g.find("paramPoly3")
        c = {k: float(pp.get(k)) for k in ("bU", "cU", "dU", "bV", "cV", "dV")}
        # analytic samples in local frame
        N = 800
        loc = []
        for i in range(N + 1):
            p = i / N
            u = c["bU"] * p + c["cU"] * p * p + c["dU"] * p ** 3
            v = c["bV"] * p + c["cV"] * p * p + c["dV"] * p ** 3
            loc.append((u, v))
        du = [(c["bU"] + 2 * c["cU"] * (i / N) + 3 * c["dU"] * (i / N) ** 2,
               c["bV"] + 2 * c["cV"] * (i / N) + 3 * c["dV"] * (i / N) ** 2) for i in range(N + 1)]
        dd = [(2 * c["cU"] + 6 * c["dU"] * (i / N), 2 * c["cV"] + 6 * c["dV"] * (i / N)) for i in range(N + 1)]
        speeds = [math.hypot(a, b) for a, b in du]
        arc = sum((speeds[i] + speeds[i + 1]) / 2 for i in range(N)) / N
        kap = [abs(a * d - b * cc) / (s ** 3) if s > 1e-12 else float("inf")
               for (a, b), (cc, d), s in zip(du, dd, speeds)]
        kmax = max(kap)
        min_speed = min(speeds)
        u1, v1 = loc[-1]
        chord = math.hypot(u1, v1)
        # overshoot: projection on chord direction outside [0, chord]
        if chord > 1e-9:
            ex, ey = u1 / chord, v1 / chord
            proj = [u * ex + v * ey for u, v in loc]
            lat = [abs(-u * ey + v * ex) for u, v in loc]
            overshoot = max(0.0, -min(proj), max(proj) - chord)
            max_lat = max(lat)
        else:
            overshoot = max_lat = float("nan")
        simple = LineString(loc).is_simple
        # required tangents from topology
        conn = conn_of.get(cid)
        inc = roads.get(conn.get("incomingRoad")) if conn is not None else None
        inc_s = snap._road_endpoint_pose(inc, "start")
        inc_e = snap._road_endpoint_pose(inc, "end")
        used_inc_end = math.hypot(inc_e.x - x0, inc_e.y - y0) <= math.hypot(inc_s.x - x0, inc_s.y - y0)
        req_start = inc_e.hdg if used_inc_end else inc_s.hdg + math.pi
        start_err = adiff_deg(h0, req_start)
        exit_contact = None
        exit_road = None
        link = road.find("link")
        for slot in ("successor", "predecessor"):
            for it in (link.findall(slot) if link is not None else []):
                if it.get("elementType") == "road" and it.get("elementId") != conn.get("incomingRoad"):
                    exit_contact = (it.get("contactPoint") or "").lower()
                    exit_road = roads.get(it.get("elementId"))
        ex_pose = snap._road_endpoint_pose(exit_road, exit_contact)
        req_end = ex_pose.hdg if exit_contact == "start" else ex_pose.hdg + math.pi
        end_tan = h0 + math.atan2(du[-1][1], du[-1][0])
        end_err = adiff_deg(end_tan, req_end)
        # baseline: original connector geometry via kernel
        b_arc, b_kmax, b_turn = curve_metrics(kernel_samples(ET.fromstring(before_plan[cid])))
        rows.append(dict(id=cid, L=L, arc=arc, arc_ratio=arc / L, chord=chord, kmax=kmax, min_speed=min_speed,
                         overshoot=overshoot, max_lat=max_lat, simple=simple, start_err=start_err,
                         end_err=end_err, used_inc_end=used_inc_end, exit_contact=exit_contact,
                         b_arc=b_arc, b_kmax=b_kmax, chord_over_L=chord / L))
    print("measured", len(rows), round(time.time() - t0, 1), "s", flush=True)

    def pct(vals, q):
        v = sorted(vals)
        return v[min(len(v) - 1, int(q * (len(v) - 1)))] if v else None

    n = len(rows)
    for r in rows:
        r["uturn_zero_chord"] = r["chord_over_L"] < 1e-3
    import collections
    def cls_stats(sub):
        if not sub: return {"n": 0}
        return {"n": len(sub),
                "arc_ratio_p50": pct([r["arc_ratio"] for r in sub], .5),
                "arc_dev_gt_10pct": sum(abs(r["arc_ratio"]-1) > .1 for r in sub),
                "cusp": sum(r["min_speed"] < 1e-6*max(r["L"],1e-9) for r in sub),
                "not_simple": sum(not r["simple"] for r in sub),
                "radius_lt_2m_after": sum(r["kmax"] > .5 for r in sub),
                "radius_lt_2m_before": sum(r["b_kmax"] > .5 for r in sub),
                "kmax_after_p50": pct([r["kmax"] for r in sub], .5),
                "kmax_after_p99": pct([r["kmax"] for r in sub], .99),
                "kmax_before_p50": pct([r["b_kmax"] for r in sub], .5),
                "kmax_increase_gt_2x": sum(r["kmax"] > 2*r["b_kmax"]+1e-9 for r in sub),
                "overshoot_gt_0_5m": sum((r["overshoot"] or 0) > .5 for r in sub),
                "chord_over_L_p50": pct([r["chord_over_L"] for r in sub], .5),
                "L_p50": pct([r["L"] for r in sub], .5)}
    by_class = {"uturn_zero_chord": cls_stats([r for r in rows if r["uturn_zero_chord"]]),
                "other": cls_stats([r for r in rows if not r["uturn_zero_chord"]])}
    others = [r for r in rows if not r["uturn_zero_chord"]]
    summ = {
        "by_class": by_class,
        "other_worst_kmax": sorted(others, key=lambda r: -r["kmax"])[:6],
        "other_not_simple_examples": [r for r in others if not r["simple"]][:6],
        "input": SRC, "candidate_sha": "2cee039f235f2cff7c87fa1fce935154cdcf3cd8",
        "snap_report": {k: rep[k] for k in rep if not isinstance(rep[k], list)},
        "refits_measured": n,
        "start_contact_used": {"incoming_end": sum(r["used_inc_end"] for r in rows),
                               "incoming_start": sum(not r["used_inc_end"] for r in rows)},
        "exit_contact": {k: sum(r["exit_contact"] == k for r in rows) for k in ("start", "end")},
        "start_tangent_err_gt_90deg": sum(r["start_err"] > 90 for r in rows),
        "start_tangent_err_gt_10deg": sum(r["start_err"] > 10 for r in rows),
        "end_tangent_err_gt_90deg": sum(r["end_err"] > 90 for r in rows),
        "end_tangent_err_gt_10deg": sum(r["end_err"] > 10 for r in rows),
        "not_simple_self_intersecting": sum(not r["simple"] for r in rows),
        "arc_ratio": {"p01": pct([r["arc_ratio"] for r in rows], .01), "p50": pct([r["arc_ratio"] for r in rows], .5),
                      "p99": pct([r["arc_ratio"] for r in rows], .99), "max": max(r["arc_ratio"] for r in rows),
                      "abs_dev_gt_1pct": sum(abs(r["arc_ratio"] - 1) > .01 for r in rows),
                      "abs_dev_gt_10pct": sum(abs(r["arc_ratio"] - 1) > .10 for r in rows)},
        "chord_over_L": {"p01": pct([r["chord_over_L"] for r in rows], .01), "p50": pct([r["chord_over_L"] for r in rows], .5),
                         "p99": pct([r["chord_over_L"] for r in rows], .99), "max": max(r["chord_over_L"] for r in rows)},
        "kmax_after": {"p50": pct([r["kmax"] for r in rows], .5), "p99": pct([r["kmax"] for r in rows], .99),
                       "max": max(r["kmax"] for r in rows)},
        "kmax_before_kernel": {"p50": pct([r["b_kmax"] for r in rows], .5), "p99": pct([r["b_kmax"] for r in rows], .99),
                               "max": max(r["b_kmax"] for r in rows)},
        "min_radius_lt_5m_after": sum(r["kmax"] > 0.2 for r in rows),
        "min_radius_lt_5m_before": sum(r["b_kmax"] > 0.2 for r in rows),
        "min_radius_lt_2m_after": sum(r["kmax"] > 0.5 for r in rows),
        "min_radius_lt_2m_before": sum(r["b_kmax"] > 0.5 for r in rows),
        "kmax_increase_gt_2x": sum(r["kmax"] > 2 * r["b_kmax"] + 1e-9 for r in rows),
        "overshoot_gt_0_5m": sum((r["overshoot"] or 0) > .5 for r in rows),
        "zero_speed_cusp": sum(r["min_speed"] < 1e-6 * max(r["L"], 1e-9) for r in rows),
        "worst_by_kmax": sorted(rows, key=lambda r: -r["kmax"])[:8],
        "worst_by_arc_ratio": sorted(rows, key=lambda r: -abs(r["arc_ratio"] - 1))[:8],
        "examples_start_reversed": [r for r in rows if r["start_err"] > 90][:5],
        "examples_end_reversed": [r for r in rows if r["end_err"] > 90][:5],
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(summ, f, indent=1, default=str)
    print(json.dumps({k: v for k, v in summ.items() if not k.startswith(("worst", "examples"))}, indent=1, default=str))


if __name__ == "__main__":
    main()
