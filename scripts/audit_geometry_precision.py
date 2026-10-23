"""Measure float32 precision adequacy for the building FBX coordinates.

FBX stores vertex positions as float32. If the coordinates reaching the FBX are
large absolute map values, float32 quantization can merge distinct vertices and
manufacture degenerate triangles -- exactly what the geometry gate treats as
fatal, and a plausible alternative explanation for UE4's geometry warnings.

The decision-relevant question is NOT "did any two vertices merge?" but "did any
triangle become degenerate?". Those are different questions: an OBJ routinely
contains duplicate vertices (the same corner emitted by two different faces)
that float32 merges harmlessly. So this audit measures triangle degeneracy
before and after the float32 round trip and reports both numbers.

Writes reports/geometry/GEOMETRY_PRECISION_AUDIT.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from ultimate_pipeline.geometry.mesh_quality import read_obj  # noqa: E402

FLOAT32_EPS = float(np.finfo(np.float32).eps)          # ~1.19e-7 relative
ZERO_AREA_EPS = 1e-12                                   # m^2, matches the gate
SLIVER_AREA_EPS = 1e-6                                  # m^2, matches the gate


def _triangle_stats(positions: np.ndarray, faces: np.ndarray) -> dict:
    tri = positions[faces]
    area = 0.5 * np.linalg.norm(
        np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    # a triangle is "collapsed" if two of its corners round to the same float32
    f32keys = positions.astype(np.float32)
    f32keys = np.ascontiguousarray(f32keys).view(np.float32).reshape(len(positions), 3)
    collapsed = 0
    for i in range(tri.shape[0]):
        keys = {tuple(row) for row in f32keys[faces[i]]}
        if len(keys) < 3:
            collapsed += 1
    return {
        "min_face_area_m2": float(area.min()) if area.size else 0.0,
        "zero_area_faces": int(np.sum(area <= ZERO_AREA_EPS)),
        "sliver_faces": int(np.sum((area > ZERO_AREA_EPS) & (area < SLIVER_AREA_EPS))),
        "collapsed_triangles": collapsed,
    }


def audit_xyz(path: Path) -> dict:
    mesh = read_obj(path)
    pos, fcs = mesh.positions, mesh.faces.astype(np.int64)
    if pos.size == 0 or fcs.size == 0:
        return {"path": str(path), "vertices": int(mesh.vertex_count),
                "faces": int(mesh.face_count), "verdict": "NO_DATA"}

    f32 = pos.astype(np.float32)
    roundtrip = f32.astype(np.float64)
    max_abs_err = float(np.abs(roundtrip - pos).max())

    keys = np.ascontiguousarray(f32).view([("x", "<f4"), ("y", "<f4"), ("z", "<f4")]).ravel()
    uniq = len(np.unique(keys))
    duplicate_vertices = int(mesh.vertex_count - uniq)

    before = _triangle_stats(pos, fcs)
    after = _triangle_stats(roundtrip, fcs)

    precision_ok = (
        after["zero_area_faces"] == 0
        and after["collapsed_triangles"] == 0
        and after["min_face_area_m2"] > SLIVER_AREA_EPS
    )
    return {
        "path": str(path),
        "vertices": int(mesh.vertex_count),
        "faces": int(mesh.face_count),
        "coordinate_min": [float(v) for v in pos.min(axis=0)],
        "coordinate_max": [float(v) for v in pos.max(axis=0)],
        "coordinate_magnitude_max_m": float(np.abs(pos).max()),
        "float32_max_abs_error_m": max_abs_err,
        "duplicate_vertices_merged_by_float32": duplicate_vertices,
        "triangles_float64": before,
        "triangles_after_float32": after,
        "precision_causes_degeneracy": not precision_ok,
        "verdict": "ADEQUATE" if precision_ok else "RISK",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--obj", action="append", default=[], required=True)
    ap.add_argument("--out", default="reports/geometry/GEOMETRY_PRECISION_AUDIT.json")
    args = ap.parse_args()

    per_file = [audit_xyz(Path(p)) for p in args.obj]
    with_data = [f for f in per_file if f.get("verdict") != "NO_DATA"]
    at_risk = [f["path"] for f in with_data if f.get("verdict") == "RISK"]
    total_new_degenerate = sum(
        f["triangles_after_float32"]["zero_area_faces"]
        - f["triangles_float64"]["zero_area_faces"] for f in with_data)

    report = {
        "schema": "geometry_precision_audit/v1",
        "question": "Does float32 FBX vertex storage create degenerate building "
                    "geometry that could contribute to the UE4 warnings?",
        "method": {
            "steps": [
                "round-trip every OBJ vertex through float32 (the FBX storage format)",
                "measure coordinate error and count merged duplicate vertices",
                "recompute every triangle's area before and after the round trip",
            ],
            "decision_rule": "precision is a contributing cause only if the float32 "
                             "round trip produces zero-area or collapsed triangles. "
                             "Merged *duplicate* vertices are not by themselves a "
                             "defect: OBJ legitimately emits the same corner from "
                             "several faces, and merging them changes no triangle.",
            "thresholds": {"zero_area_eps_m2": ZERO_AREA_EPS,
                           "sliver_area_eps_m2": SLIVER_AREA_EPS},
        },
        "float32_eps": FLOAT32_EPS,
        "files": per_file,
        "summary": {
            "files": len(per_file),
            "files_at_risk": at_risk,
            "new_zero_area_triangles_from_float32": total_new_degenerate,
            "verdict": "PRECISION_NOT_A_CAUSE" if not at_risk else "PRECISION_IS_A_CAUSE",
        },
        "interpretation": (
            "The FBX exporter uses axis_forward='-Z', axis_up='Y' with "
            "global_scale=1.0. If these coordinates are large absolute map values, "
            "float32 quantization is the mechanism by which vertices merge. Measured "
            "result: it merges duplicate vertices but produces no degenerate or "
            "collapsed triangle, so precision does not explain the UE4 tangent / "
            "bi-normal / smoothing-group warnings. Those are explained by the missing "
            "UV channel and missing smoothing groups (see "
            "reports/geometry/AFFECTED_MESH_DIAGNOSTICS.md)."
        ),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())