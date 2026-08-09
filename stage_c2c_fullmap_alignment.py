import sys
sys.path.insert(0, r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main")
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree

from ultimate_pipeline.tools.phase_h0_osm_signal_extract import _wgs84_to_native_transformer
from ultimate_pipeline.enrichment.structure_classifier import road_centerline_polyline

REPO = Path(r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main")
C2 = REPO / "reports" / "post_audit_hardening" / "20260809T000000Z_C2_3DPACKAGE"
OBJ = C2 / "artifacts_fullmap" / "scene.obj"
OSM = REPO / "campaigns" / "ingolstadt_cooked_perception_v1" / "source" / "ingolstadt_authoritative.osm"
XODR = REPO / "reports" / "post_audit_hardening" / "20260809T000000Z_C1_GENERATION" / "candidate_crosswalk_enriched.xodr"

# ---- OBJ header origin + vertices ----
origin = None
verts = []
with open(OBJ, encoding="utf-8", errors="replace") as f:
    for line in f:
        if line.startswith("# Coordinate origin") and "lat" in line:
            lat = float(line.split("lat")[1].split(",")[0].strip())
            lon = float(line.split("lon")[1].split(",")[0].strip())
            origin = (lat, lon)
        elif line.startswith("v "):
            parts = line.split()
            verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
print("OBJ origin wgs84:", origin, "vertices:", len(verts))

transformer, crs_record = _wgs84_to_native_transformer(str(XODR), str(OSM))
print("crs verdict:", crs_record.get("verdict"))
ox, oy = transformer.transform(origin[1], origin[0])
print("origin in native frame:", (ox, oy))

# map: xodr_x = origin_x + obj_x ; xodr_y = origin_y - obj_z ; xodr_z = obj_y
mapped = [(ox + v[0], oy - v[2], v[1]) for v in verts]

# ---- XODR road centerline index ----
root = ET.parse(XODR).getroot()
road_pts, road_own = [], []
road_polys = {}
for r in root.findall("road"):
    poly = road_centerline_polyline(r, 20.0)
    if len(poly) < 2:
        continue
    road_polys[r.get("id")] = poly
    road_pts.extend(poly)
    road_own.extend([r.get("id")] * len(poly))
tree = cKDTree(np.asarray(road_pts, dtype=np.float64))
print("xodr roads sampled:", len(road_polys), "pts:", len(road_pts))

# ---- per-vertex nearest road distance ----
def seg_dist(px, py, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    denom = dx * dx + dy * dy
    if denom < 1e-12:
        return math.hypot(px - a[0], py - a[1])
    t = max(0.0, min(1.0, ((px - a[0]) * dx + (py - a[1]) * dy) / denom))
    return math.hypot(px - (a[0] + t * dx), py - (a[1] + t * dy))

dists = []
vertex_roads = []
for (x, y, z) in mapped:
    d, i = tree.query([x, y], k=8)
    darr = np.atleast_1d(d)
    iarr = np.atleast_1d(i)
    best_d = math.inf
    best_road = None
    for dd, ii in zip(darr, iarr):
        rid = road_own[int(ii)]
        poly = road_polys[rid]
        dref = min(seg_dist(x, y, a, b) for a, b in zip(poly, poly[1:]))
        if dref < best_d:
            best_d = dref
            best_road = rid
    dists.append(best_d)
    vertex_roads.append(best_road)

darr_np = np.asarray(dists)
if len(darr_np) > 0:
    stats = {
        "count": int(len(darr_np)),
        "min_m": round(float(darr_np.min()), 3),
        "mean_m": round(float(darr_np.mean()), 3),
        "median_m": round(float(np.median(darr_np)), 3),
        "p95_m": round(float(np.percentile(darr_np, 95)), 3),
        "p99_m": round(float(np.percentile(darr_np, 99)), 3),
        "max_m": round(float(darr_np.max()), 3),
    }
    worst_idx = np.argsort(darr_np)[-10:][::-1]
    outliers = [{"vertex_idx": int(i), "road_id": vertex_roads[int(i)], "dist_m": round(float(darr_np[int(i)]), 2)} for i in worst_idx]
else:
    stats = {}
    outliers = []

out = {
    "producer": "stage_c2c_fullmap_alignment.py",
    "obj_path": str(OBJ),
    "obj_origin_wgs84": origin,
    "obj_origin_native_frame": [round(ox, 3), round(oy, 3)],
    "crs_verdict": crs_record.get("verdict"),
    "mapping": {"xodr_x = origin_x + obj_x": True, "xodr_y = origin_y - obj_z": True, "xodr_z = obj_y": True},
    "fullmap_objs_vertices": len(verts),
    "xodr_roads_sampled": len(road_polys),
    "nearest_road_residual_m": stats,
    "outlier_vertices": outliers,
    "note": "Full-map OSM2World OBJ (64 objects) restricted to extract content (0 buildings/0 vegetation ways in authoritative extract); residual over full-map geometry.",
}
(C2 / "C2C_FULLMAP_ALIGNMENT_RESIDUALS.json").write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
print(json.dumps(out, indent=2, sort_keys=True))