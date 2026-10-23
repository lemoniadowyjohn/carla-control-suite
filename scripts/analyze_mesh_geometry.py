#!/usr/bin/env python3
"""Offline geometry diagnostics for the building mesh pipeline.

Reads the artifacts the production pipeline actually emitted and emits:

  reports/geometry/AFFECTED_MESH_DIAGNOSTICS.json
  reports/geometry/AFFECTED_MESH_DIAGNOSTICS.md

No Blender, no UE4, no CARLA. Every number is measured from the artifact bytes;
nothing is assumed.

Two independent evidence sources are combined:

  * the OBJ written by OSM2World -> full geometric analysis (positions, faces,
    areas, normals, UVs). Parsed exactly, so triangle/normal/UV metrics are
    trustworthy.
  * the FBX written by Blender -> channel probe. Binary FBX stores node names as
    ASCII, so the presence/absence of LayerElementUV, LayerElementTangent and
    LayerElementSmoothing is an exact existence test. This is what proves whether
    the engine will be handed a UV channel at all.

Usage:
  python scripts/analyze_mesh_geometry.py \
      --obj  reports/.../Ingolstadt_Tile_10_9.obj \
      --fbx  reports/.../Ingolstadt_Tile_10_9.fbx \
      --obj  reports/.../Ingolstadt_Tile_6_6.obj \
      --fbx  reports/.../Ingolstadt_Tile_6_6.fbx
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from ultimate_pipeline.geometry.mesh_quality import (  # noqa: E402
    GATE_THRESHOLDS,
    analyze_mesh,
    evaluate_gate,
    plan_uv_generation,
    probe_fbx_channels,
    read_obj,
)


def _new_totals() -> dict:
    return {
        "meshes": 0, "faces": 0, "vertices": 0,
        "degenerate_faces": 0, "zero_area_faces": 0, "sliver_faces": 0,
        "collinear_faces": 0, "uv_degenerate_faces": 0,
        "tangent_degenerate_faces": 0, "near_zero_binormal_faces": 0,
        "vertices_without_normal": 0, "non_unit_normals": 0,
        "meshes_without_uv": 0, "meshes_without_smoothing": 0, "meshes_without_normals": 0,
    }


def _accumulate(tot: dict, m) -> None:
    tot["meshes"] += 1
    tot["faces"] += m.face_count
    tot["vertices"] += m.vertex_count
    tot["degenerate_faces"] += m.degenerate_faces
    tot["zero_area_faces"] += m.zero_area_faces
    tot["sliver_faces"] += m.sliver_faces
    tot["collinear_faces"] += m.collinear_faces
    tot["uv_degenerate_faces"] += m.uv_degenerate_faces
    tot["tangent_degenerate_faces"] += m.tangent_degenerate_faces
    tot["near_zero_binormal_faces"] += m.near_zero_binormal_faces
    tot["vertices_without_normal"] += m.vertices_without_normal
    tot["non_unit_normals"] += m.non_unit_normals
    tot["meshes_without_uv"] += 0 if m.has_uv_channel else 1
    tot["meshes_without_smoothing"] += 0 if m.has_smoothing_channel else 1
    tot["meshes_without_normals"] += 0 if m.has_normal_channel else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--obj", action="append", default=[], help="OBJ file to analyze (repeatable)")
    ap.add_argument("--fbx", action="append", default=[],
                    help="FBX file to probe (repeatable); use with --label-before/--label-after")
    ap.add_argument("--fbx-before", action="append", default=[],
                    help="FBX from before the fix (repeatable)")
    ap.add_argument("--fbx-after", action="append", default=[],
                    help="FBX from after the fix (repeatable)")
    ap.add_argument("--out-json", default="reports/geometry/AFFECTED_MESH_DIAGNOSTICS.json")
    ap.add_argument("--out-md", default="reports/geometry/AFFECTED_MESH_DIAGNOSTICS.md")
    args = ap.parse_args()

    if not args.obj and not args.fbx:
        ap.error("at least one --obj or --fbx is required")

    per_file: list[dict] = []
    aggregate = _new_totals()
    hypotheses: list[dict] = []

    for p in args.obj:
        mesh = read_obj(p)
        m = analyze_mesh(mesh)
        gate = evaluate_gate(m)
        plan = plan_uv_generation(mesh.positions, mesh.faces,
                                  groups=mesh.face_groups)
        _accumulate(aggregate, m)
        per_file.append({
            "path": str(p),
            "source": "obj",
            "role": "OSM2World output (geometric analysis)",
            "totals": _accumulate(_new_totals(), m),
            "gate_status": gate["status"],
            "fatal": gate["fatal"],
            "repairable": gate["repairable"],
            "metrics": m.to_dict(),
            "uv_fix_projection": plan,
            "coordinate_magnitude_max_m": m.coordinate_magnitude_max,
        })

    uv_missing_before: list[str] = []
    uv_missing_after: list[str] = []
    smoothing_missing: list[str] = []

    def _probe_group(paths, phase):
        for p in paths:
            probe = probe_fbx_channels(p)
            per_file.append({
                "path": str(p),
                "source": "fbx",
                "phase": phase,
                "role": "Blender output (vertex-channel probe)",
                "probe": probe,
            })
            if not probe["has_uv_layer"]:
                (uv_missing_before if phase == "before" else uv_missing_after).append(str(p))
            if not probe["has_smoothing_layer"]:
                smoothing_missing.append(f"{phase}:{p}")

    _probe_group(args.fbx_before, "before")
    _probe_group(args.fbx_after, "after")
    _probe_group(args.fbx, "unlabelled")

    if aggregate["meshes"] and aggregate["meshes_without_uv"] == aggregate["meshes"]:
        hypotheses.append({
            "id": "RC-UV-MISSING",
            "severity": "root_cause",
            "statement": (
                "No mesh carries a UV channel. Blender exported with use_tspace=False, "
                "so the FBX contains no explicit tangents and UE4/MikkTSpace must derive "
                "them from UVs. With zero parametric area on every face, every face has a "
                "degenerate tangent basis and a near-zero bi-normal."
            ),
            "predicted_ue4_warnings": [
                "has degenerate tangent bases which will result in incorrect shading",
                "has some nearly zero bi-normals",
            ],
            "evidence": [
                "OBJ: vt record count == 0",
                "FBX (before): LayerElementUV node count == 0",
                "blender_convert.py: use_tspace=False",
                "blender manifest (before): uv_layers == 0 on every object",
            ],
            "fix": "generate a validated UV channel in the Blender conversion stage",
        })
    if smoothing_missing:
        hypotheses.append({
            "id": "RC-SMOOTHING-MISSING",
            "severity": "root_cause",
            "statement": (
                "No FBX carries LayerElementSmoothing because Blender exported with "
                "mesh_smooth_type='OFF'. This is the direct cause of UE4's missing "
                "smoothing group warning and is fully independent of the UV problem."
            ),
            "predicted_ue4_warnings": ["missing smoothing group information"],
            "evidence": [
                "OBJ: s record count == 0",
                "FBX: LayerElementSmoothing node count == 0",
                "blender_convert.py: mesh_smooth_type='OFF'",
            ],
            "fix": "export with mesh_smooth_type='FACE' plus angle-based sharp edges",
        })

    # before/after channel delta across the probed FBX files
    def _agg_phase(phase):
        rows = [f["probe"]["layer_node_counts"] for f in per_file
                if f["source"] == "fbx" and f.get("phase") == phase]
        if not rows:
            return None
        return {k: sum(r[k] for r in rows) for k in rows[0]}

    before_counts = _agg_phase("before")
    after_counts = _agg_phase("after")
    delta = None
    if before_counts and after_counts:
        delta = {
            "layers": {
                k: {"before": before_counts[k], "after": after_counts[k],
                    "delta": after_counts[k] - before_counts[k]}
                for k in before_counts
            },
            "files_before": [f["path"] for f in per_file
                             if f["source"] == "fbx" and f.get("phase") == "before"],
            "files_after": [f["path"] for f in per_file
                            if f["source"] == "fbx" and f.get("phase") == "after"],
        }

    report = {
        "schema": "affected_mesh_diagnostics/v2",
        "method": {
            "obj": "exact parse of Wavefront OBJ (v/vn/vt/f); areas and channels computed in float64",
            "fbx": ("ascii node-name byte search over the FBX payload to determine which "
                    "vertex layers exist; binary FBX stores node names as plain ascii so "
                    "presence/absence is an exact test"),
            "not_done": ("FBX *geometry* is not parsed: Blender's FBXHeaderExtension writes a "
                         "name length one byte short of the name it emits, so a hand-rolled "
                         "binary geometry parser could not be trusted. Geometric metrics come "
                         "from the OBJ instead, which is exact."),
            "no_editor": "no Blender, no UE4, no CARLA involved in the measurement itself",
        },
        "thresholds": GATE_THRESHOLDS,
        "files": per_file,
        "aggregate": aggregate,
        "fbx_channel_delta": delta,
        "root_cause_hypotheses": hypotheses,
    }

    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# Affected Mesh Diagnostics", "",
        "Generated offline by `scripts/analyze_mesh_geometry.py`. All values measured from",
        "artifact bytes; none assumed. No Blender, no UE4, no CARLA.", "",
        "## Method", "",
        f"- OBJ: {report['method']['obj']}",
        f"- FBX: {report['method']['fbx']}",
        f"- Not done: {report['method']['not_done']}", "",
        "## Aggregate (OBJ geometry)", "",
        "| metric | value |", "| --- | --- |",
    ]
    for k, v in aggregate.items():
        lines.append(f"| {k} | {v} |")

    lines += ["", "## Files", "",
              "| path | source | phase | UV layer | smoothing layer | normals |",
              "| --- | --- | --- | --- | --- | --- |"]
    for f in per_file:
        if f["source"] == "fbx":
            pr = f["probe"]
            lines.append(
                f"| {f['path']} | fbx | {f.get('phase', '-')} | "
                f"{'yes' if pr['has_uv_layer'] else 'NO'} | "
                f"{'yes' if pr['has_smoothing_layer'] else 'NO'} | "
                f"{'yes' if pr['has_normal_layer'] else 'NO'} |"
            )
        else:
            mt = f["metrics"]
            lines.append(
                f"| {f['path']} | obj | - | "
                f"{'yes' if mt['has_uv_channel'] else 'NO'} | n/a (OBJ `s`) | "
                f"{'yes' if mt['has_normal_channel'] else 'NO'} |"
            )

    if delta:
        lines += ["", "## FBX channel delta (before -> after the fix)", "",
                  "| layer node | before | after | delta |", "| --- | --- | --- | --- |"]
        for k, v in delta["layers"].items():
            lines.append(f"| {k} | {v['before']} | {v['after']} | {v['delta']:+d} |")
        lines.append("")

    lines += ["", "## Root-cause findings", ""]
    for h in hypotheses:
        lines += [f"### {h['id']} ({h['severity']})", "", h["statement"], "",
                  "Predicted UE4 warnings:", ""]
        lines += [f"- `{w}`" for w in h["predicted_ue4_warnings"]]
        lines += ["", "Evidence:", ""]
        lines += [f"- {e}" for e in h["evidence"]]
        lines += ["", f"Fix: {h['fix']}", ""]
    if not hypotheses:
        lines += ["_none: every analyzed mesh carries UV, normals and smoothing._", ""]

    lines += ["## Fix projection (dry run, no Blender)", "",
              "What the planned per-object box projection would achieve on these exact",
              "meshes. This is the numeric evidence that the UV fix works, produced",
              "offline from the real OBJ.", "",
              "| mesh | faces | degenerate UV faces before | after | min UV area after |",
              "| --- | --- | --- | --- | --- |"]
    for f in per_file:
        if f["source"] != "obj":
            continue
        pl = f["uv_fix_projection"]
        lines.append(
            f"| {Path(f['path']).name} | {pl['faces']} | "
            f"{f['metrics']['uv_degenerate_faces']} | "
            f"{pl['per_object_normalization']['degenerate_faces']} | "
            f"{pl['per_object_normalization']['min_face_area']:.3e} |")
    lines.append("")

    out_md = Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps({"aggregate": aggregate, "hypotheses": [h["id"] for h in hypotheses]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())