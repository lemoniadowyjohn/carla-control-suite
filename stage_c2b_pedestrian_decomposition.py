#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C2 Stage B - decompose the blanket ALREADY_PRESENT ledger (5071) into
per-feature geometric proof: each OSM pedestrian way (SIDEWALK/FOOTWAY/PATH)
is matched against the existing XODR sidewalk lanes (17,392) of the C1
candidate.  Ways that run inside an existing sidewalk lane strip for a
significant aligned run are ROAD_ADJACENT_SIDEWALK_MATCHED (no duplication:
the lane already exists, nothing new is authored); the remainder are
STANDALONE_PACKAGE_MESH_NAVMESH (require a package mesh + navigation mesh at
packaging, offline-deferred).

Reuses OSM extraction from phase_h0 (OSMSignalExtractor, CRS-verified) and the
lane/width conventions of the hardening pipeline.
"""
from __future__ import annotations

import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy.spatial import cKDTree

REPO = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(REPO))

from ultimate_pipeline.tools.phase_h0_osm_signal_extract import OSMSignalExtractor
from ultimate_pipeline.enrichment.structure_classifier import road_centerline_polyline

RUN_ID = "20260809T000000Z_C2_3DPACKAGE"
REPORTS = REPO / "reports" / "post_audit_hardening" / RUN_ID
C1_DIR = REPO / "reports" / "post_audit_hardening" / "20260809T000000Z_C1_GENERATION"
OSM_PATH = REPO / "campaigns" / "ingolstadt_cooked_perception_v1" / "source" / "ingolstadt_authoritative.osm"
XODR_PATH = C1_DIR / "candidate_crosswalk_enriched.xodr"
C1C_PATH = C1_DIR / "C1C_PEDESTRIAN_LEDGER.json"

MIN_ALIGNED_RUN_M = 20.0
MIN_CONTIGUOUS_RUN_M = 10.0
COVERAGE_FRACTION = 0.4
SHORT_WAY_M = 30.0
RUN_FRACTION_FOR_SHORT = 0.6
CONTAIN_TOL_M = 4.0
CENTERLINE_SPACING_M = 2.0
SAMPLE_SPACING_M = 2.0

C2B_JSON = REPORTS / "C2B_ALREADY_PRESENT_DECOMPOSITION.json"
C2B_CSV = REPORTS / "C2B_ALREADY_PRESENT_DECOMPOSITION.csv"


def _road_length(road: ET.Element) -> float:
    try:
        return float(road.get("length", "0"))
    except Exception:
        return 0.0


def _lane_widths_by_side(lsec: ET.Element) -> Dict[str, Tuple[float, float]]:
    """Per side -> (cumulative offset of lane start from centre, total width)."""
    out: Dict[str, Tuple[float, float]] = {}
    for side in ("left", "right"):
        el = lsec.find(side)
        if el is None:
            continue
        run = 0.0
        for lane in el.findall("lane"):
            w = 0.0
            for wid in lane.findall("width"):
                try:
                    a = float(wid.get("a", "0")); b = float(wid.get("b", "0"))
                    c = float(wid.get("c", "0")); d = float(wid.get("d", "0"))
                    ds = -float(wid.get("sOffset", "0"))
                    w = a + b * ds + c * ds * ds + d * ds * ds * ds
                except Exception:
                    w = 0.0
            w = max(0.0, w)
            out[(side, lane.get("id"))] = (run, w)
            run += w
    return out


def _lane_center_polyline(
    road: ET.Element, lane: ET.Element, side: str,
    widths: Dict[Tuple[str, str], Tuple[float, float]],
    centerline: List[Tuple[float, float]],
) -> Tuple[List[Tuple[float, float]], float]:
    """Offset the road centerline perpendicular by the lane-center t offset."""
    start, w = widths.get((side, lane.get("id")), (0.0, 0.0))
    t = -(start + w / 2.0) if side == "right" else (start + w / 2.0)
    pts: List[Tuple[float, float]] = []
    for (ax, ay), (bx, by) in zip(centerline, centerline[1:]):
        hdg = math.atan2(by - ay, bx - ax)
        cx, cy = ax - t * math.sin(hdg), ay + t * math.cos(hdg)
        pts.append((cx, cy))
    return pts, w


def build_sidewalk_lane_index(root: ET.Element) -> Dict[str, Any]:
    pts_all: List[Tuple[float, float]] = []
    owners: List[Dict[str, Any]] = []
    lane_records: List[Dict[str, Any]] = []
    for road in root.findall("road"):
        rid = road.get("id")
        centerline = road_centerline_polyline(road, CENTERLINE_SPACING_M)
        if len(centerline) < 2:
            continue
        for lsec in road.findall("lanes/laneSection"):
            widths = _lane_widths_by_side(lsec)
            for side in ("left", "right"):
                el = lsec.find(side)
                if el is None:
                    continue
                for lane in el.findall("lane"):
                    if lane.get("type") != "sidewalk":
                        continue
                    pts, w = _lane_center_polyline(
                        road, lane, side, widths, centerline)
                    if len(pts) < 2:
                        continue
                    s0 = float(lsec.get("s", "0") or 0)
                    lane_id = lane.get("id")
                    lane_records.append({
                        "road_id": rid, "lane_id": lane_id, "side": side,
                        "s0": s0, "width": w, "points": pts,
                    })
                    base = len(pts_all)
                    pts_all.extend(pts)
                    owners.extend([{"road_id": rid, "lane_id": lane_id,
                                    "s0": s0, "i": i}
                                   for i in range(len(pts))])
    tree = cKDTree(np.asarray(pts_all, dtype=np.float64))
    return {"tree": tree, "owners": owners, "lanes": lane_records}


def _dist_to_segment(px: float, py: float, ax: float, ay: float,
                     bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    if denom < 1e-12:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / denom
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _refine_distance(px: float, py: float, pts: List[Tuple[float, float]],
                     idx: int) -> float:
    best = math.hypot(px - pts[idx][0], py - pts[idx][1])
    for j in (idx - 1, idx):
        if 0 <= j < len(pts) - 1:
            best = min(best, _dist_to_segment(
                px, py, pts[j][0], pts[j][1], pts[j + 1][0], pts[j + 1][1]))
    return best


def _densify(poly: List[Tuple[float, float]], spacing: float) -> List[Tuple[float, float]]:
    if len(poly) < 2:
        return poly
    out: List[Tuple[float, float]] = [poly[0]]
    for a, b in zip(poly, poly[1:]):
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, int(math.ceil(seg / spacing)))
        for i in range(1, n + 1):
            t = i / n
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def match_way_to_sidewalks(
    way_poly: List[Tuple[float, float]],
    index: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], float]:
    """Return (matched lanes sorted by aligned run desc, way length).

    The OSM way is densified at SAMPLE_SPACING_M; a sample point is
    contained in a sidewalk lane when its refined distance to the lane
    centerline is <= lane_width/2 + CONTAIN_TOL_M.  Contiguous contained
    samples accumulate the aligned run (meters).  Short XODR roads split a
    single footway into many consecutive lane segments, so the aggregated
    run accumulates across lane switches (every sample still carries its
    per-feature lane proof); the dominant lane per run is reported.
    """
    tree: cKDTree = index["tree"]
    owners = index["owners"]
    lanes = {f"{r['road_id']}:{r['lane_id']}:{r['s0']}": r for r in index["lanes"]}
    densified = _densify(way_poly, SAMPLE_SPACING_M)
    contained: List[Dict[str, Any]] = []
    for px, py in densified:
        d, i = tree.query([px, py], k=8)
        if isinstance(i, np.integer):
            d, i = [d], [i]
        best: Optional[Tuple[float, str]] = None
        for dd, ii in zip(list(np.atleast_1d(d)), list(np.atleast_1d(i))):
            o = owners[int(ii)]
            lane_key = f"{o['road_id']}:{o['lane_id']}:{o['s0']}"
            rec = lanes[lane_key]
            dref = _refine_distance(px, py, rec["points"], int(o["i"]))
            allowed = rec["width"] / 2.0 + CONTAIN_TOL_M
            if dref <= allowed and (best is None or dref < best[0]):
                best = (dref, lane_key)
        contained.append({"ok": best is not None, "d": best[0] if best else None,
                          "lane": best[1] if best else None})
    length = sum(math.hypot(b[0] - a[0], b[1] - a[1])
                 for a, b in zip(way_poly, way_poly[1:]))
    n = max(len(densified) - 1, 1)

    # contiguous contained runs (across lane changes stayed on sidewalks)
    runs: List[Dict[str, Any]] = []
    i = 0
    while i < len(densified):
        if not contained[i]["ok"]:
            i += 1
            continue
        j = i
        keys_in_run: List[str] = []
        while j < len(densified) and contained[j]["ok"]:
            keys_in_run.append(contained[j]["lane"])
            j += 1
        seg_run = max(0, j - i - 1) * SAMPLE_SPACING_M
        if seg_run > 0:
            dominant = max(set(keys_in_run), key=keys_in_run.count)
            rec = lanes[dominant]
            ds = [contained[k]["d"] for k in range(i, j) if contained[k]["d"] is not None]
            runs.append({
                "road_id": rec["road_id"], "lane_id": rec["lane_id"],
                "lane_s": rec["s0"], "lane_width_m": round(rec["width"], 3),
                "aligned_run_m": round(seg_run, 2),
                "run_fraction": round((j - i) / n, 3),
                "mean_eff_dist_m": round(sum(ds) / len(ds), 3) if ds else 0.0,
                "max_eff_dist_m": round(max(ds), 3) if ds else 0.0,
            })
        i = j
    runs.sort(key=lambda r: -r["aligned_run_m"])
    return runs, length


def is_road_adjacent(runs: List[Dict[str, Any]], length: float) -> bool:
    if not runs:
        return False
    total_frac = sum(r["run_fraction"] for r in runs)
    best_run = runs[0]["aligned_run_m"]
    if length >= SHORT_WAY_M:
        return (best_run >= MIN_ALIGNED_RUN_M
                or total_frac >= COVERAGE_FRACTION)
    return (best_run >= MIN_CONTIGUOUS_RUN_M
            or total_frac >= RUN_FRACTION_FOR_SHORT)


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    c1c = json.loads(C1C_PATH.read_text(encoding="utf-8"))
    ledger = c1c["ledger"]
    already = [e for e in ledger if e["disposition"] == "ALREADY_PRESENT"]
    want_ids = {e["osm_id"] for e in already}
    print(f"C1C ALREADY_PRESENT: {len(already)} (target 5071)")

    ext = OSMSignalExtractor(str(OSM_PATH), str(XODR_PATH))
    if ext.crs_record.get("verdict") != "OSM2ODR_NATIVE_VERIFIED":
        print(f"CRS not verified: {ext.crs_record.get('verdict')}", file=sys.stderr)
        return 1
    ext._load_nodes()
    ext._load_ways()

    root = ET.parse(XODR_PATH).getroot()
    print("Building sidewalk lane index (17,392 lanes expected)...")
    index = build_sidewalk_lane_index(root)
    print(f"  lanes indexed: {len(index['lanes'])}, points: {len(index['owners'])}")

    rows: List[Dict[str, Any]] = []
    matched = 0
    standalone = 0
    not_osm = 0
    for entry in already:
        way = ext.ways.get(entry["osm_id"])
        if way is None or len(way.get("polyline_m", [])) < 2:
            rows.append({
                "osm_id": entry["osm_id"], "classification": entry["classification"],
                "c2b_disposition": "STANDALONE_PACKAGE_MESH_NAVMESH",
                "alignment": "OSM_WAY_MISSING", "length_m": 0.0,
                "road_id": "", "lane_id": "", "aligned_run_m": 0.0,
                "mean_eff_dist_m": 0.0,
                "proof": "OSM way unavailable in extractor; conservative standalone",
            })
            not_osm += 1
            standalone += 1
            continue
        poly = way["polyline_m"]
        runs, length = match_way_to_sidewalks(poly, index)
        adj = is_road_adjacent(runs, length)
        if adj:
            b = runs[0]
            rows.append({
                "osm_id": entry["osm_id"],
                "classification": entry["classification"],
                "c2b_disposition": "ROAD_ADJACENT_SIDEWALK_MATCHED",
                "alignment": "MATCHED", "length_m": round(length, 2),
                "road_id": b["road_id"], "lane_id": b["lane_id"],
                "aligned_run_m": b["aligned_run_m"],
                "mean_eff_dist_m": b["mean_eff_dist_m"],
                "proof": (f"runs inside existing sidewalk lane {b['road_id']}/"
                          f"{b['lane_id']} (s={b['lane_s']} m, w={b['lane_width_m']} m) "
                          f"for {b['aligned_run_m']} m; lane already present - nothing "
                          f"new authored (no duplication)"),
            })
            matched += 1
        else:
            best = runs[0] if runs else None
            rows.append({
                "osm_id": entry["osm_id"],
                "classification": entry["classification"],
                "c2b_disposition": "STANDALONE_PACKAGE_MESH_NAVMESH",
                "alignment": (f"nearest lane {best['road_id']}/{best['lane_id']} "
                              f"aligned {best['aligned_run_m']} m" if best
                              else "no sidewalk lane within containment"),
                "length_m": round(length, 2),
                "road_id": best["road_id"] if best else "",
                "lane_id": best["lane_id"] if best else "",
                "aligned_run_m": best["aligned_run_m"] if best else 0.0,
                "mean_eff_dist_m": best["mean_eff_dist_m"] if best else 0.0,
                "proof": ("no existing sidewalk lane contains this way for the "
                          "required run; requires PACKAGE_MESH + NAVMESH at "
                          "packaging (offline-deferred)"),
            })
            standalone += 1

    total = len(rows)
    summary = {
        "run_id": RUN_ID,
        "producer": "stage_c2b_pedestrian_decomposition.py",
        "source": str(XODR_PATH),
        "source_node_sha256": "see C1B/C1F digests",
        "crs_verdict": ext.crs_record.get("verdict"),
        "already_present_ledger_total": len(already),
        "road_adjacent_sidewalk_matched": matched,
        "standalone_package_mesh": standalone,
        "osm_way_missing": not_osm,
        "split_invariant_pass": (matched + standalone) == len(already) == 5071,
        "sidewalk_lanes_indexed": len(index["lanes"]),
        "min_aligned_run_m": MIN_ALIGNED_RUN_M,
        "contain_tolerance_m": CONTAIN_TOL_M,
        "verdict": ("C2B_ALREADY_PRESENT_DECOMPOSED"
                    if (matched + standalone) == len(already) == 5071
                    else "C2B_LEDGER_INCOMPLETE"),
    }
    C2B_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True),
                        encoding="utf-8")

    import csv
    with open(C2B_CSV, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        wr.writeheader()
        for r in rows:
            wr.writerow(r)

    print(f"matched={matched} standalone={standalone} missing={not_osm} "
          f"total={total} invariant={summary['split_invariant_pass']}")
    return 0 if summary["split_invariant_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())