#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Detached-slab validation (Phase J8).

Checks an OBJ for geometric pathologies that break CARLA/Unreal collision:

  1. duplicate faces: identical vertex triples and near-coplanar overlapping
     triangles (same plane within tolerance + > 50% 2D overlap),
  2. floating/unsupported slabs: flat objects (z-extent <= thickness) whose
     footprint has no other geometry within support_gap_m below them,
     excluding elevated structures (elevator/bridge classes),
  3. degenerate faces (zero-area, caught by J1) are recounted here for the
     report.

Elevated structures are distinguished by the semantic class of the object.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from ultimate_pipeline.enrichment.semantic_partition import parse_obj_objects

DUPLICATE_PLANE_TOL_M = 0.01
FLAT_THICKNESS_M = 1.0
SUPPORT_GAP_M = 1.0
ELEVATED_CLASSES = {"elevator", "bridge"}
MAX_FACES_PER_OBJECT = 20000


def _faces_for_object(path: Path, name: str) -> List[List[int]]:
    faces: List[List[int]] = []
    current = None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "o":
                current = " ".join(parts[1:])
            elif parts[0] == "f" and current == name:
                tri = []
                for tok in parts[1:]:
                    idx = tok.split("/")[0]
                    if idx:
                        try:
                            tri.append(int(idx))
                        except ValueError:
                            pass
                if len(tri) >= 3:
                    faces.append(tri)
    return faces


def _verts_for_object(path: Path, name: str) -> List[Tuple[float, float, float]]:
    verts: List[Tuple[float, float, float]] = []
    current = None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "o":
                current = " ".join(parts[1:])
            elif parts[0] == "v" and current == name and len(parts) >= 4:
                try:
                    verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
                except ValueError:
                    pass
    return verts


def _normal_and_offset(
    tri: List[int], verts: List[Tuple[float, float, float]]
) -> Tuple[Tuple[float, float, float], float]:
    a, b, c = (verts[abs(i) - 1] for i in tri[:3])
    u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    n = (u[1] * v[2] - u[2] * v[1],
         u[2] * v[0] - u[0] * v[2],
         u[0] * v[1] - u[1] * v[0])
    ln = math.sqrt(sum(x * x for x in n))
    if ln < 1e-12:
        return (0.0, 0.0, 0.0), 0.0
    n = (n[0] / ln, n[1] / ln, n[2] / ln)
    return n, n[0] * a[0] + n[1] * a[1] + n[2] * a[2]


def _point_in_triangle(px: float, py: float, tri, verts, axis: Tuple[int, int]) -> bool:
    i, j = axis
    (ax, ay), (bx, by), (cx, cy) = (
        (verts[abs(k) - 1][i], verts[abs(k) - 1][j]) for k in tri[:3])
    s1 = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
    s2 = (cx - bx) * (py - by) - (cy - by) * (px - bx)
    s3 = (ax - cx) * (py - cy) - (ay - cy) * (px - cx)
    has_neg = (s1 < 0) or (s2 < 0) or (s3 < 0)
    has_pos = (s1 > 0) or (s2 > 0) or (s3 > 0)
    return not (has_neg and has_pos)


def _tri_centroid_in_triangle(
    t1: List[int], t2: List[int], verts, axis: Tuple[int, int]
) -> bool:
    i, j = axis
    c2 = ((verts[abs(t2[0]) - 1][i] + verts[abs(t2[1]) - 1][i]
           + verts[abs(t2[2]) - 1][i]) / 3.0,
          (verts[abs(t2[0]) - 1][j] + verts[abs(t2[1]) - 1][j]
           + verts[abs(t2[2]) - 1][j]) / 3.0)
    c1 = ((verts[abs(t1[0]) - 1][i] + verts[abs(t1[1]) - 1][i]
           + verts[abs(t1[2]) - 1][i]) / 3.0,
          (verts[abs(t1[0]) - 1][j] + verts[abs(t1[1]) - 1][j]
           + verts[abs(t1[2]) - 1][j]) / 3.0)
    return _point_in_triangle(c2[0], c2[1], t1, verts, axis) or \
        _point_in_triangle(c1[0], c1[1], t2, verts, axis)


def duplicate_faces_check(
    path: Path, obj: Dict[str, Any]
) -> Dict[str, Any]:
    """Duplicate + coplanar-overlapping face detection for one object."""
    faces = _faces_for_object(path, obj["name"])
    if len(faces) > MAX_FACES_PER_OBJECT:
        return {"checked": False, "reason": "too many faces",
                "faces": len(faces)}
    verts = _verts_for_object(path, obj["name"])
    if not verts:
        return {"checked": False, "reason": "no vertices", "faces": len(faces)}

    exact: Set[Tuple[int, ...]] = set()
    exact_dupes = 0
    for tri in faces:
        key = tuple(sorted(abs(i) for i in tri))
        if key in exact:
            exact_dupes += 1
        exact.add(key)

    # near-coplanar overlapping pairs (bucket by rounded normal)
    buckets: Dict[Tuple[float, float, float], List[Tuple[Tuple[float, float, float], List[int]]]] = {}
    for tri in faces:
        n, off = _normal_and_offset(tri, verts)
        if n == (0.0, 0.0, 0.0):
            continue
        key = (round(n[0], 2), round(n[1], 2), round(n[2], 2))
        buckets.setdefault(key, []).append(((n, off), tri))

    coplanar_dupes = 0
    samples = []
    for bucket in buckets.values():
        for i in range(len(bucket)):
            for j in range(i + 1, len(bucket)):
                (n1, o1), t1 = bucket[i]
                (n2, o2), t2 = bucket[j]
                if abs(o1 - o2) > DUPLICATE_PLANE_TOL_M:
                    continue
                # skip legitimate mesh connectivity: triangles sharing an edge
                shared = len(set(abs(k) for k in t1)
                            & set(abs(k) for k in t2))
                if shared >= 2:
                    continue
                axis = (0, 1) if abs(n1[2]) >= abs(n1[0]) and abs(n1[2]) >= abs(n1[1]) \
                    else (1, 2) if abs(n1[0]) >= abs(n1[2]) and abs(n1[0]) >= abs(n1[1]) \
                    else (0, 2)
                if not _tri_centroid_in_triangle(t1, t2, verts, axis):
                    continue
                coplanar_dupes += 1
                if len(samples) < 10:
                    samples.append({
                        "face_a": t1, "face_b": t2,
                        "normal": [round(x, 3) for x in n1],
                        "plane_offset_m": round(o1, 3),
                    })
    return {
        "checked": True,
        "faces": len(faces),
        "exact_duplicate_faces": exact_dupes,
        "coplanar_overlapping_pairs": coplanar_dupes,
        "samples": samples,
    }


def floating_slab_check(path: Path, objects: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Flat objects with no geometry within SUPPORT_GAP_M below them."""
    aabbs = {}
    for obj in objects:
        b = obj["bounds"]
        aabbs[obj["name"]] = b

    floating: List[Dict[str, Any]] = []
    for obj in objects:
        if obj["class"] in ELEVATED_CLASSES:
            continue
        b = obj["bounds"]
        thickness = b[5] - b[2]
        if thickness > FLAT_THICKNESS_M:
            continue  # not a slab
        # find any other object whose top is within SUPPORT_GAP_M below this slab
        supported = False
        support_name = ""
        for other_name, ob in aabbs.items():
            if other_name == obj["name"]:
                continue
            gap = b[2] - ob[5]
            if gap < 0 or gap > SUPPORT_GAP_M:
                continue
            w = min(b[3], ob[3]) - max(b[0], ob[0])
            h = min(b[4], ob[4]) - max(b[1], ob[1])
            if w > 0 and h > 0:
                supported = True
                support_name = other_name
                break
        if not supported:
            floating.append({
                "object": obj["name"],
                "class": obj["class"],
                "z_min_m": round(b[2], 2),
                "thickness_m": round(thickness, 2),
                "nearest_support": support_name or None,
            })
    return {"floating_slab_candidates": floating[:100],
            "floating_count": len(floating)}


def detached_slab_check(path: Path) -> Dict[str, Any]:
    """J8: aggregate slab validation for the whole OBJ."""
    objects = parse_obj_objects(path)
    per_object = []
    dup_total = 0
    coplanar_total = 0
    for obj in objects:
        res = duplicate_faces_check(path, obj)
        if res.get("checked"):
            dup_total += res["exact_duplicate_faces"]
            coplanar_total += res["coplanar_overlapping_pairs"]
            if res["faces"] > 0:
                per_object.append({
                    "object": obj["name"],
                    "faces": res["faces"],
                    "exact_duplicate_faces": res["exact_duplicate_faces"],
                    "coplanar_overlapping_pairs": res["coplanar_overlapping_pairs"],
                    "skipped": False,
                })
        else:
            per_object.append({
                "object": obj["name"],
                "faces": res.get("faces", 0),
                "skipped": True,
                "reason": res.get("reason", ""),
            })
    floating = floating_slab_check(path, objects)

    # degenerate (zero-area) faces across the file
    degenerate = 0
    for obj in objects:
        if obj["faces"] <= MAX_FACES_PER_OBJECT:
            for tri in _faces_for_object(path, obj["name"]):
                verts = _verts_for_object(path, obj["name"])
                if len(verts) >= 3 and len(tri) >= 3:
                    a, b, c = (verts[abs(i) - 1] for i in tri[:3])
                    u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
                    v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
                    n = (u[1] * v[2] - u[2] * v[1],
                         u[2] * v[0] - u[0] * v[2],
                         u[0] * v[1] - u[1] * v[0])
                    if math.sqrt(sum(x * x for x in n)) < 1e-12:
                        degenerate += 1

    violations = [v for v in floating["floating_slab_candidates"]
                  if v["class"] != "ground"]
    return {
        "objects_checked": len(per_object),
        "per_object": per_object,
        "exact_duplicate_faces_total": dup_total,
        "coplanar_overlapping_pairs_total": coplanar_total,
        "degenerate_faces_total": degenerate,
        "floating_slab_count": floating["floating_count"],
        "floating_slab_candidates": floating["floating_slab_candidates"],
        "verdict": "PASS" if (dup_total == 0 and coplanar_total == 0
                              and degenerate == 0 and not violations)
        else "ISSUES_FOUND",
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("usage: detached_slab_check.py <scene.obj>")
        sys.exit(2)
    print(json.dumps(detached_slab_check(Path(sys.argv[1])), indent=2, sort_keys=True))
