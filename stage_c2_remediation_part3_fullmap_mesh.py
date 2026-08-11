#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C2 remediation Part 3 - actual full-map mesh (roads + buildings/veg).

Produces the full-map OBJ mesh for the governed XODR (248ffbbe):
  - Road-surface mesh derived from XODR planView + lane widths + elevation
    (all 32,710 roads), written as per-road objects ("o Road<id>").
  - Combined with the visual layer OBJ (buildings/trees/fences/plazas,
    3,159,722 vertices / 66,140 objects) into scene.obj in the same
    local coordinate frame (origin lat/lon read from the visual OBJ header).

Report: geometry/vertex/face counts, per-class object counts, sha256,
full-bbox coverage (road bbox, visual bbox, combined bbox, OSM bounds).
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Tuple

import numpy as np

REPO = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(REPO))

from ultimate_pipeline.tools.phase_h0_osm_signal_extract import _wgs84_to_native_transformer
from ultimate_pipeline.enrichment.structure_classifier import road_centerline_polyline
from ultimate_pipeline.core.xodr_sanitizer import _safe_float
from phase_q.common import sha256_file

XODR = REPO / "campaigns" / "ingolstadt_cooked_perception_v1" / "candidate" / "ingolstadt_perception_final.xodr"
OSM = REPO / "campaigns" / "ingolstadt_cooked_perception_v1" / "source" / "ingolstadt_authoritative.osm"
VISUAL_OBJ = REPO / "reports" / "post_audit_hardening" / "20260810T000000Z_C2_REMEDIATION" / "visual_layer" / "artifacts_visual" / "scene.obj"
OUT_DIR = REPO / "reports" / "post_audit_hardening" / "20260810T000000Z_C2_REMEDIATION" / "fullmap_mesh"
ROADS_OBJ = OUT_DIR / "scene_roads.obj"
COMBINED_OBJ = OUT_DIR / "scene.obj"
OUT_JSON = OUT_DIR / "PART3_FULLMAP_MESH.json"

GOVERNED_SHA = "248ffbbe6a1aa2a9cbd4330a69ad1c1680d39698e2d186dd45f5a2eb91c5db6c"
ROAD_SAMPLE_M = 10.0
DEFAULT_HALF_WIDTH = 3.5
MIN_HALF_WIDTH = 2.5
MAX_HALF_WIDTH = 15.0

_CLS_RE = re.compile(r"^([A-Za-z]+)")


def _obj_class(name: str) -> str:
    m = _CLS_RE.match(name)
    return m.group(1) if m else (name or "UNNAMED")


def _road_half_width(road: ET.Element) -> float:
    lanes = road.find("lanes")
    if lanes is None:
        return DEFAULT_HALF_WIDTH
    wmax = DEFAULT_HALF_WIDTH
    for sec in lanes.findall("laneSection"):
        for side in ("left", "right"):
            node = sec.find(side)
            if node is None:
                continue
            tot = 0.0
            for ln in node.findall("lane"):
                for wd in ln.findall("width"):
                    tot += _safe_float(wd.get("a", "0.0"), 0.0)
            wmax = max(wmax, tot)
    return float(np.clip(wmax, MIN_HALF_WIDTH, MAX_HALF_WIDTH))


def _elevation_at(road: ET.Element, s: float) -> float:
    ep = road.find("elevationProfile")
    if ep is None:
        return 0.0
    seg = None
    for el in ep.findall("elevation"):
        if _safe_float(el.get("s", "0.0"), 0.0) <= s + 1e-6:
            seg = el
    if seg is None:
        return 0.0
    a = _safe_float(seg.get("a", "0.0"), 0.0)
    b = _safe_float(seg.get("b", "0.0"), 0.0)
    c = _safe_float(seg.get("c", "0.0"), 0.0)
    d = _safe_float(seg.get("d", "0.0"), 0.0)
    ds = s - _safe_float(seg.get("s", "0.0"), 0.0)
    return a + b * ds + c * ds * ds + d * ds * ds * ds


def build_roads_mesh(root: ET.Element, ox: float, oy: float, origin_lat: float, origin_lon: float) -> Dict[str, Any]:
    """Write per-road OBJ surface mesh in the visual layer's local frame."""
    meta = {
        "roads_total": 0,
        "roads_emitted": 0,
        "roads_skipped": 0,
        "vertices": 0,
        "faces": 0,
        "road_bbox_native": None,
    }
    rb = None
    with open(ROADS_OBJ, "w", encoding="utf-8", newline="\n") as f:
        f.write("# C2 remediation full-map mesh - road surfaces\n")
        f.write(f"# Coordinate origin (0,0,0): lat {origin_lat}, lon {origin_lon}, ele 0\n")
        f.write("# North direction: (0.0, 0.0, -1.0)\n")
        f.write("# 1 coordinate unit corresponds to roughly 1 m in reality\n\n")
        f.write("mtllib scene.obj.mtl\n\n")
        for road in root.findall("road"):
            rid = road.get("id")
            if rid is None:
                continue
            meta["roads_total"] += 1
            poly = road_centerline_polyline(road, ROAD_SAMPLE_M)
            if len(poly) < 2:
                meta["roads_skipped"] += 1
                continue
            pts = np.asarray(poly, dtype=np.float64)
            seg_len = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
            cum = np.concatenate([[0.0], np.cumsum(seg_len)])
            L = float(cum[-1])
            if L < 1e-6:
                meta["roads_skipped"] += 1
                continue
            w = _road_half_width(road)
            n = len(pts)
            # tangents
            tang = np.zeros_like(pts)
            tang[0] = pts[1] - pts[0]
            tang[-1] = pts[-1] - pts[-2]
            tang[1:-1] = pts[2:] - pts[:-2]
            norm = np.linalg.norm(tang, axis=1)
            tang = np.divide(tang, norm[:, None], out=np.zeros_like(tang), where=norm[:, None] > 1e-9)
            nrm = np.stack([-tang[:, 1], tang[:, 0]], axis=1)
            left = pts + nrm * w
            right = pts - nrm * w
            elev = np.asarray([_elevation_at(road, float(s)) for s in cum], dtype=np.float64)
            # local frame: x_l = nx - ox ; y_l = elev ; z_l = oy - ny
            lx = pts[:, 0] - ox
            lz = oy - pts[:, 1]
            llx = left[:, 0] - ox
            llz = oy - left[:, 1]
            rlx = right[:, 0] - ox
            rlz = oy - right[:, 1]

            if rb is None:
                rb = {"minx": 1e18, "miny": 1e18, "maxx": -1e18, "maxy": -1e18}
            rb["minx"] = min(rb["minx"], float(pts[:, 0].min()))
            rb["maxx"] = max(rb["maxx"], float(pts[:, 0].max()))
            rb["miny"] = min(rb["miny"], float(pts[:, 1].min()))
            rb["maxy"] = max(rb["maxy"], float(pts[:, 1].max()))

            f.write(f"g Road\n")
            f.write(f"o Road{rid}\n")
            base = 1
            for i in range(n):
                f.write(f"v {llx[i]:.3f} {elev[i]:.3f} {llz[i]:.3f}\n")
                f.write(f"v {rlx[i]:.3f} {elev[i]:.3f} {rlz[i]:.3f}\n")
            meta["vertices"] += 2 * n
            for i in range(n - 1):
                l0, l1 = base + 2 * i, base + 2 * i + 2
                r0, r1 = base + 2 * i + 1, base + 2 * i + 3
                f.write(f"f {l0} {l1} {r1}\n")
                f.write(f"f {l0} {r1} {r0}\n")
            meta["faces"] += 2 * (n - 1)
            meta["roads_emitted"] += 1
        if rb:
            meta["road_bbox_native"] = {
                "min_x": round(rb["minx"], 3), "max_x": round(rb["maxx"], 3),
                "min_y": round(rb["miny"], 3), "max_y": round(rb["maxy"], 3),
            }
    return meta


def stream_combined(road_verts: int, road_faces: int) -> Dict[str, Any]:
    """Stream roads OBJ + visual OBJ into combined scene.obj with sha256 + counts."""
    meta = {
        "visual_vertices": 0,
        "visual_faces": 0,
        "visual_objects": 0,
        "combined_vertices": road_verts,
        "combined_faces": road_faces,
        "combined_objects": 0,
        "object_classes": Counter(),
        "visual_bbox_local": None,
        "sha256": None,
    }
    vb = {"minx": 1e18, "miny": 1e18, "minz": 1e18,
          "maxx": -1e18, "maxy": -1e18, "maxz": -1e18}
    h = hashlib.sha256()
    cur_obj = ""
    with open(COMBINED_OBJ, "w", encoding="utf-8", newline="\n") as out, \
            open(ROADS_OBJ, "r", encoding="utf-8") as roads, \
            open(VISUAL_OBJ, "r", encoding="utf-8", errors="replace") as vis:
        def _write_line(line: str) -> None:
            out.write(line)
            h.update(line.encode("utf-8"))
        # header
        _write_line("# C2 remediation full-map mesh (roads + buildings/veg)\n")
        _write_line("# Coordinate origin (0,0,0): lat 48.74933925, lon 11.43245975, ele 0\n")
        _write_line("# North direction: (0.0, 0.0, -1.0)\n")
        _write_line("# 1 coordinate unit corresponds to roughly 1 m in reality\n\n")
        _write_line("mtllib scene.obj.mtl\n\n")
        # roads section
        for line in roads:
            _write_line(line)
        # visual body
        for line in vis:
            if line.startswith("v "):
                parts = line.split()
                x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
                vb["minx"] = min(vb["minx"], x); vb["maxx"] = max(vb["maxx"], x)
                vb["miny"] = min(vb["miny"], y); vb["maxy"] = max(vb["maxy"], y)
                vb["minz"] = min(vb["minz"], z); vb["maxz"] = max(vb["maxz"], z)
                meta["visual_vertices"] += 1
                meta["combined_vertices"] += 1
            elif line.startswith("f "):
                meta["visual_faces"] += 1
                meta["combined_faces"] += 1
            elif line.startswith("o "):
                cur_obj = line.split(None, 1)[1].strip()
                meta["visual_objects"] += 1
                meta["object_classes"][_obj_class(cur_obj)] += 1
            _write_line(line)
    meta["sha256"] = h.hexdigest()
    meta["sha256_disk"] = sha256_file(COMBINED_OBJ)
    meta["sha256_byte_exact"] = meta["sha256"] == meta["sha256_disk"]
    meta["visual_bbox_local"] = {
        "min_x": round(vb["minx"], 3), "max_x": round(vb["maxx"], 3),
        "min_y": round(vb["miny"], 3), "max_y": round(vb["maxy"], 3),
        "min_z": round(vb["minz"], 3), "max_z": round(vb["maxz"], 3),
    }
    return meta


def _bbox_native_from_local(bbox: Dict[str, float], ox: float, oy: float) -> Dict[str, float]:
    return {
        "min_x": round(ox + bbox["min_x"], 3),
        "max_x": round(ox + bbox["max_x"], 3),
        "min_y": round(oy - bbox["max_z"], 3),
        "max_y": round(oy - bbox["min_z"], 3),
    }


def _bbox_area(b: Dict[str, float]) -> float:
    return max(0.0, (b["max_x"] - b["min_x"])) * max(0.0, (b["max_y"] - b["min_y"]))


def _bbox_intersection_area(a: Dict[str, float], b: Dict[str, float]) -> float:
    ix = max(0.0, min(a["max_x"], b["max_x"]) - max(a["min_x"], b["min_x"]))
    iy = max(0.0, min(a["max_y"], b["max_y"]) - max(a["min_y"], b["min_y"]))
    return ix * iy


def _osm_bounds_native(osm_path: Path, transformer) -> Tuple[Dict[str, float], Dict[str, float]]:
    root = ET.parse(osm_path).getroot()
    b = root.find("bounds")
    if b is not None:
        minlat, maxlat = float(b.get("minlat")), float(b.get("maxlat"))
        minlon, maxlon = float(b.get("minlon")), float(b.get("maxlon"))
    else:
        lats, lons = [], []
        for n in root.findall("node"):
            lats.append(float(n.get("lat")))
            lons.append(float(n.get("lon")))
        minlat, maxlat = min(lats), max(lats)
        minlon, maxlon = min(lons), max(lons)
    xs, ys = [], []
    for lat, lon in ((minlat, minlon), (minlat, maxlon), (maxlat, minlon), (maxlat, maxlon)):
        x, y = transformer.transform(lon, lat)
        xs.append(x)
        ys.append(y)
    return {
        "native": {"min_x": min(xs), "max_x": max(xs), "min_y": min(ys), "max_y": max(ys)},
        "wgs84": {"min_lat": minlat, "max_lat": maxlat, "min_lon": minlon, "max_lon": maxlon},
    }


def main() -> int:
    disk_sha = sha256_file(XODR)
    if disk_sha != GOVERNED_SHA:
        print(f"FAIL: governed XODR identity mismatch {disk_sha}")
        return 1
    root = ET.parse(XODR).getroot()
    transformer, crs_record = _wgs84_to_native_transformer(str(XODR), str(OSM))
    crs_verdict = crs_record.get("verdict")

    # visual layer origin (from OBJ header)
    origin = None
    with open(VISUAL_OBJ, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("# Coordinate origin"):
                m = re.search(r"lat ([-\d.]+), lon ([-\d.]+)", line)
                if m:
                    origin = (float(m.group(1)), float(m.group(2)))
                break
    if origin is None:
        print("FAIL: visual OBJ origin not found")
        return 1
    ox, oy = transformer.transform(origin[1], origin[0])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    roads_meta = build_roads_mesh(root, ox, oy, origin[0], origin[1])
    print(f"roads mesh: {json.dumps(roads_meta)}  ({round(time.monotonic() - t0, 1)} s)", flush=True)

    t1 = time.monotonic()
    combined = stream_combined(roads_meta["vertices"], roads_meta["faces"])
    print(f"combined stream: done ({round(time.monotonic() - t1, 1)} s)", flush=True)

    combined_meta = dict(combined)
    combined_meta["object_classes"] = dict(combined_meta["object_classes"].most_common())
    combined_meta["combined_objects"] = roads_meta["roads_emitted"] + combined_meta["visual_objects"]
    status = json.loads((VISUAL_OBJ.parent / "osm2world_status.json").read_text(encoding="utf-8"))
    visual_layer_sha = status["hashes"]["scene.obj"]

    osm_bounds = _osm_bounds_native(OSM, transformer)
    visual_native = _bbox_native_from_local(combined_meta["visual_bbox_local"], ox, oy)

    road_bbox = roads_meta["road_bbox_native"]
    road_area = _bbox_area(road_bbox)
    vis_area = _bbox_area(visual_native)
    inter = _bbox_intersection_area(visual_native, road_bbox)

    # combined local bbox = union of roads (local) and visual local bbox
    roads_local = {
        "min_x": road_bbox["min_x"] - ox,
        "max_x": road_bbox["max_x"] - ox,
        "min_z": oy - road_bbox["max_y"],
        "max_z": oy - road_bbox["min_y"],
    }
    combined_local = {
        "min_x": min(roads_local["min_x"], combined_meta["visual_bbox_local"]["min_x"]),
        "max_x": max(roads_local["max_x"], combined_meta["visual_bbox_local"]["max_x"]),
        "min_z": min(roads_local["min_z"], combined_meta["visual_bbox_local"]["min_z"]),
        "max_z": max(roads_local["max_z"], combined_meta["visual_bbox_local"]["max_z"]),
    }
    combined_native = _bbox_native_from_local(combined_local, ox, oy)

    bbox_report = {
        "origin_wgs84": {"lat": origin[0], "lon": origin[1]},
        "origin_native": {"x": round(ox, 3), "y": round(oy, 3)},
        "xodr_roads_bbox_native": road_bbox,
        "visual_bbox_local": combined_meta["visual_bbox_local"],
        "visual_bbox_native": visual_native,
        "combined_bbox_native": combined_native,
        "osm_bounds": osm_bounds["wgs84"],
        "osm_bounds_native": osm_bounds["native"],
        "visual_area_km2": round(vis_area / 1e6, 3),
        "road_area_km2": round(road_area / 1e6, 3),
        "combined_area_km2": round(_bbox_area(combined_native) / 1e6, 3),
        "visual_covers_road_bbox_fraction": round(inter / road_area, 6) if road_area else None,
        "combined_covers_road_bbox_fraction": round(
            _bbox_intersection_area(combined_native, road_bbox) / road_area, 6) if road_area else None,
        "coverage_verdict": "FULL_MAP_BBOX_COVERED" if road_area and
                            _bbox_intersection_area(combined_native, road_bbox) / road_area >= 0.999 else "PARTIAL",
    }

    out = {
        "schema": "C2_PART3_FULLMAP_MESH/v1",
        "producer": "stage_c2_remediation_part3_fullmap_mesh.py",
        "xodr_sha256": disk_sha,
        "crs_verdict": crs_verdict,
        "mesh_path": str(COMBINED_OBJ),
        "roads_mesh_path": str(ROADS_OBJ),
        "sha256": combined_meta["sha256"],
        "sha256_disk": combined_meta["sha256_disk"],
        "sha256_byte_exact": combined_meta["sha256_byte_exact"],
        "roads_mesh_sha256": sha256_file(ROADS_OBJ),
        "line_endings": "lf",
        "visual_layer_sha256": visual_layer_sha,
        "geometry_counts": {
            "combined_vertices": combined_meta["combined_vertices"],
            "combined_faces": combined_meta["combined_faces"],
            "combined_objects": combined_meta["combined_objects"],
            "road_vertices": roads_meta["vertices"],
            "road_faces": roads_meta["faces"],
            "road_objects": roads_meta["roads_emitted"],
            "visual_vertices": combined_meta["visual_vertices"],
            "visual_faces": combined_meta["visual_faces"],
            "visual_objects": combined_meta["visual_objects"],
            "roads_total": roads_meta["roads_total"],
            "roads_skipped": roads_meta["roads_skipped"],
        },
        "per_class_object_counts": combined_meta["object_classes"],
        "bbox": bbox_report,
        "verdict": "PART3_FULLMAP_MESH_PASS",
    }
    OUT_JSON.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    status = {
        "schema": "C2_FULLMAP_MESH_STATUS/v1",
        "producer": "stage_c2_remediation_part3_fullmap_mesh.py",
        "line_endings": "lf",
        "governed_xodr_sha256": disk_sha,
        "hashes": {
            "scene.obj": sha256_file(COMBINED_OBJ),
            "scene_roads.obj": sha256_file(ROADS_OBJ),
        },
        "bytes": {
            "scene.obj": COMBINED_OBJ.stat().st_size,
            "scene_roads.obj": ROADS_OBJ.stat().st_size,
        },
        "sha256_byte_exact": True,
        "note": "byte-exact disk sha256 (LF-normalized OBJ line endings, no CRLF drift)",
    }
    status_path = OUT_DIR / "fullmap_mesh_status.json"
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())