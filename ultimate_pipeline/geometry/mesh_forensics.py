"""Extended per-mesh metrics for distance-field causal analysis (§15/§17).

These are the properties a distance-field build is sensitive to, measured on the
actual OBJ geometry rather than inferred from file size:

  connected components, duplicate faces, non-manifold edges, boundary edges,
  triangle-area distribution (min/p1/p50/p95), tiny and sliver fractions,
  bbox dimensions, surface area, vertex/face counts.

Nothing here claims causation. It produces the independent variables so the
stall durations can be tested against them.
"""
from __future__ import annotations

import numpy as np

TINY_AREA_M2 = 1e-4          # 1 cm^2
SLIVER_AREA_M2 = 1e-3         # ~3 cm x 3 cm
ZERO_AREA_EPS = 1e-12


def _pct(values: np.ndarray, q: float) -> float:
    return float(np.percentile(values, q)) if values.size else 0.0


def extended_mesh_metrics(positions: np.ndarray, faces: np.ndarray) -> dict:
    pos = np.asarray(positions, np.float64)
    idx = np.asarray(faces, np.int64)
    if pos.size == 0 or idx.size == 0:
        return {"vertex_count": int(pos.shape[0]), "triangle_count": 0}

    vcount = int(pos.shape[0])
    fcount = int(idx.shape[0])

    tri = pos[idx]
    e1 = tri[:, 1] - tri[:, 0]
    e2 = tri[:, 2] - tri[:, 0]
    cross = np.cross(e1, e2)
    area = 0.5 * np.linalg.norm(cross, axis=1)

    lo = pos.min(axis=0)
    hi = pos.max(axis=0)
    dims = hi - lo

    # ---- duplicate faces (same unordered vertex triple) ----
    canon = np.sort(idx, axis=1)
    _uniq, counts = np.unique(canon, axis=0, return_counts=True)
    duplicate_face_count = int((counts - 1).sum())

    # ---- edges: manifold / boundary / non-manifold ----
    edges = np.vstack([idx[:, [0, 1]], idx[:, [1, 2]], idx[:, [2, 0]]])
    edges_sorted = np.sort(edges, axis=1)
    uniq_edges, edge_counts = np.unique(edges_sorted, axis=0, return_counts=True)
    boundary_edges = int((edge_counts == 1).sum())
    non_manifold_edges = int((edge_counts > 2).sum())
    manifold_edges = int((edge_counts == 2).sum())

    # ---- connected components over the edge graph ----
    # union-find, iterative; avoids recursion limits on large meshes
    parent = list(range(vcount))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for a, b in uniq_edges:
        union(int(a), int(b))
    used = np.unique(idx)
    roots = {find(int(v)) for v in used}
    isolated = vcount - len(used)

    return {
        "vertex_count": vcount,
        "triangle_count": fcount,
        "isolated_vertices": int(isolated),
        "connected_components": int(len(roots)),
        "triangles_per_component": round(fcount / max(len(roots), 1), 3),
        "duplicate_face_count": duplicate_face_count,
        "manifold_edge_count": manifold_edges,
        "boundary_edge_count": boundary_edges,
        "non_manifold_edge_count": non_manifold_edges,
        "non_manifold_ratio": round(non_manifold_edges / max(len(uniq_edges), 1), 6),
        "boundary_ratio": round(boundary_edges / max(len(uniq_edges), 1), 6),
        "zero_area_triangles": int((area <= ZERO_AREA_EPS).sum()),
        "near_zero_area_triangles": int(((area > ZERO_AREA_EPS) &
                                        (area < TINY_AREA_M2)).sum()),
        "tiny_triangle_fraction": round(
            float((area < TINY_AREA_M2).mean()), 6) if area.size else 0.0,
        "sliver_fraction": round(
            float((area < SLIVER_AREA_M2).mean()), 6) if area.size else 0.0,
        "triangle_area_min_m2": float(area.min()) if area.size else 0.0,
        "triangle_area_p1_m2": _pct(area, 1),
        "triangle_area_p50_m2": _pct(area, 50),
        "triangle_area_p95_m2": _pct(area, 95),
        "triangle_area_max_m2": float(area.max()) if area.size else 0.0,
        "triangle_area_total_m2": float(area.sum()) if area.size else 0.0,
        "surface_area_m2": round(float(area.sum()), 4) if area.size else 0.0,
        "bbox_min": [round(float(v), 4) for v in lo],
        "bbox_max": [round(float(v), 4) for v in hi],
        "bbox_dimensions_m": [round(float(v), 4) for v in dims],
        "bbox_max_dimension_m": round(float(dims.max()), 4),
        "bbox_volume_m3": round(float(dims[0] * dims[1] * dims[2]), 4),
        "surface_to_volume_ratio": (
            round(float(area.sum()) / max(dims[0] * dims[1] * dims[2], 1e-9), 4)),
        "index_reuse_ratio": round(fcount * 3 / max(vcount, 1), 4),
    }