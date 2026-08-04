#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ruff: noqa: E402
"""
Phase J: OSM2World -> Blender -> FBX enrichment evidence (J1-J8).

Pipeline (per POST_AUDIT_HARDENING_PROMPT.md §1483-1657):

  J1  OBJ/GLB/MTL structural validator (freshness, hashes, counts, bounds,
      finite coords, degenerate faces, empty/duplicate objects, material and
      texture references); stale scene.obj rejected via provenance sidecars.
  J2  deterministic artifact naming
      <map_id>_<campaign_id>_<source_hash_prefix>_<tile_id>.<ext>
  J3  Blender conversion manifest (version, exe+script hashes, import/export
      options, axes/units, FBX version, inventories, stdout/stderr, duration).
  J4  semantic partition of OBJ objects.
  J5  coordinate control points: OSM2World origin / OSM window vs XODR roads.
  J6  FBX round-trip re-import in a second clean headless Blender.
  J7  collision (OBJ objects vs XODR road corridors) + LOD policy.
  J8  detached-slab validation (duplicate/coplanar faces, floating slabs).

Usage:
    python ultimate_pipeline/tools/phase_j_osm2world_blender.py [--skip-blender]
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import xml.etree.ElementTree as ET
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from ultimate_pipeline.enrichment.osm2world_runner import OSM2WorldRunner
from ultimate_pipeline.enrichment.blender_runner import BlenderRunner, DEFAULT_BLENDER_EXE
from ultimate_pipeline.enrichment.obj_validator import validate_artifact, _sha256
from ultimate_pipeline.enrichment.semantic_partition import semantic_partition
from ultimate_pipeline.enrichment.coordinate_control import coordinate_control_check
from ultimate_pipeline.enrichment.collision_lod_policy import collision_check, lod_check
from ultimate_pipeline.enrichment.detached_slab_check import detached_slab_check
from ultimate_pipeline.enrichment.fbx_roundtrip import run_fbx_roundtrip

RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
EVIDENCE_DIR = REPO_ROOT / "reports" / "post_audit_hardening" / RUN_ID
ARTIFACTS = EVIDENCE_DIR / "artifacts"

INPUT_XODR = (
    REPO_ROOT / "reports" / "post_audit_hardening" / "20260804T050000Z"
    / "candidate_h_signal_enrichment.xodr"
)
OSM_SOURCE = (
    REPO_ROOT / "campaigns" / "ingolstadt_cooked_perception_v1" / "source"
    / "ingolstadt_authoritative.osm"
)
OSM2WORLD_HOME = REPO_ROOT / "carla_governed" / "OSM2World-latest-bin"

MAP_ID = "ingolstadt"
CAMPAIGN_ID = "cooked_perception_v1"
TILE_ID = "window_osm"

# OSM window: study center +-1 km (OSM space; the campaign OSM is Ingolstadt)
CX, CY = 11.43246, 48.74934
DX = 1000.0 / (111320.0 * 0.659)
DY = 1000.0 / 110950.0
WINDOW = {"lon_min": CX - DX, "lon_max": CX + DX,
          "lat_min": CY - DY, "lat_max": CY + DY}

# Supplemental config: OSM2World provides clutter only, no roads
# (CARLA_GENERATED_ROAD is the visible-road authority, AG03A).
CONFIG_TEXT = """# OSM2World configuration (Phase J evidence; supplemental clutter only)
# Roads/rail/aeroway/parking are owned by the CARLA/OpenDRIVE map (AG03A).
createTerrain=false
renderUnderground=false
useBuildingColors=true
implicitWindowImplementation=NONE
explicitWindowImplementation=NONE
excludeWorldModule=RoadModule;RailwayModule;AerowayModule;ParkingModule
treesPerSquareMeter=0.02
defaultTreeHeight=8
defaultTreeHeightForest=12
lodDistances=100,500,2000
"""


def artifact_prefix(sha8: str) -> str:
    return f"{MAP_ID}_{CAMPAIGN_ID}_{sha8}_{TILE_ID}"


def clip_osm_window(source: Path, out: Path, window: Dict[str, float]) -> Dict[str, Any]:
    """Copy nodes/ways/relations inside the window verbatim (deep copy)."""
    root = ET.parse(str(source)).getroot()
    nodes = root.findall("node")
    by_id = {}
    keep_nodes = set()
    for n in nodes:
        try:
            lon = float(n.get("lon"))
            lat = float(n.get("lat"))
        except (TypeError, ValueError):
            continue
        by_id[n.get("id")] = n
        if window["lon_min"] <= lon <= window["lon_max"] and \
                window["lat_min"] <= lat <= window["lat_max"]:
            keep_nodes.add(n.get("id"))

    ways = root.findall("way")
    keep_ways = []
    for w in ways:
        nds = [nd.get("ref") for nd in w.findall("nd")]
        if nds and all(rid in keep_nodes for rid in nds):
            keep_ways.append(w.get("id"))

    keep_rels = set()
    for r in root.findall("relation"):
        mw = [m.get("ref") for m in r.findall("member") if m.get("type") == "way"]
        if mw and all(wid in keep_ways for wid in mw):
            keep_rels.add(r.get("id"))

    used_nodes = set()
    for w in ways:
        if w.get("id") in keep_ways:
            for nd in w.findall("nd"):
                used_nodes.add(nd.get("ref"))

    out_root = ET.Element("osm", dict(root.attrib))
    for nid in sorted(used_nodes, key=int):
        out_root.append(deepcopy(by_id[nid]))
    wmap = {w.get("id"): w for w in ways}
    for wid in keep_ways:
        out_root.append(deepcopy(wmap[wid]))
    rmap = {r.get("id"): r for r in root.findall("relation")}
    for rid in sorted(keep_rels, key=int):
        out_root.append(deepcopy(rmap[rid]))

    out.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(out_root).write(str(out), encoding="utf-8", xml_declaration=True)
    return {
        "source": str(source),
        "source_sha256": _sha256(source),
        "window_wgs84": window,
        "nodes": len(used_nodes),
        "ways": len(keep_ways),
        "relations": len(keep_rels),
        "bytes": out.stat().st_size,
        "clip_method": "verbatim deep-copy of in-window elements (dynsax-safe)",
    }


def write_provenance(path: Path, input_sha256: str) -> None:
    prov = path.parent / f"{path.name}.provenance.json"
    prov.write_text(json.dumps({
        "artifact": path.name,
        "artifact_sha256": _sha256(path),
        "input": "ingolstadt_authoritative.osm (window clip)",
        "input_sha256": input_sha256,
        "generator": "OSM2World 0.5.0-SNAPSHOT (legacy CLI)",
        "run_id": RUN_ID,
    }, indent=2), encoding="utf-8")


def determinism_compare(first_obj: Path, second_obj: Path) -> Dict[str, Any]:
    """Compare object names + counts + bytes between two OSM2World runs."""
    def digest(p: Path) -> Dict[str, Any]:
        names = []
        counts = {"v": 0, "f": 0}
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "o":
                names.append(" ".join(parts[1:]))
            elif parts[0] == "v":
                counts["v"] += 1
            elif parts[0] == "f":
                counts["f"] += 1
        return {"object_names": sorted(names), "counts": counts,
                "sha256": _sha256(p), "bytes": p.stat().st_size}

    a, b = digest(first_obj), digest(second_obj)
    return {
        "byte_identical": a["sha256"] == b["sha256"],
        "sha256_a": a["sha256"][:16],
        "sha256_b": b["sha256"][:16],
        "object_names_equal": a["object_names"] == b["object_names"],
        "vertex_counts_equal": a["counts"]["v"] == b["counts"]["v"],
        "face_counts_equal": a["counts"]["f"] == b["counts"]["f"],
        "objects": len(a["object_names"]),
        "verdict": "DETERMINISTIC" if (a["sha256"] == b["sha256"])
        else ("STABLE_STRUCTURE" if (a["object_names"] == b["object_names"]
                                     and a["counts"] == b["counts"]) else "NON_DETERMINISTIC"),
    }


def main() -> int:
    skip_blender = "--skip-blender" in sys.argv
    evidence: Dict[str, Any] = {
        "run_id": RUN_ID,
        "verdict": "IN_PROGRESS",
        "tools": {},
        "checks": {},
        "artifacts": {},
    }

    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    # ---- 0. window clip (J2 input provenance) ----
    clip = clip_osm_window(OSM_SOURCE, ARTIFACTS / "window_osm.osm", WINDOW)
    evidence["tools"]["clip"] = clip
    sha8 = clip["source_sha256"][:8]
    prefix = artifact_prefix(sha8)
    evidence["artifacts"]["name_prefix"] = prefix
    evidence["artifacts"]["naming_scheme"] = (
        "<map_id>_<campaign_id>_<source_hash_prefix>_<tile_id>.<ext> = "
        f"{prefix}.<ext>")

    # ---- 1. OSM2World run (J2 naming) ----
    config_path = ARTIFACTS / "osm2world.properties"
    config_path.write_text(CONFIG_TEXT, encoding="ascii", newline="\n")
    runner = OSM2WorldRunner(
        osm_path=str(ARTIFACTS / "window_osm.osm"),
        output_dir=str(ARTIFACTS),
        osm2world_home=str(OSM2WORLD_HOME),
        timeout_sec=1800,
        config_path=str(config_path),
        name_prefix=prefix,
    )
    os.environ["OSM2WORLD_OUTPUTS"] = "obj,png,glb"
    o2w = runner.run()
    evidence["tools"]["osm2world"] = o2w.to_dict()

    obj_path = ARTIFACTS / f"{prefix}.obj"
    glb_path = ARTIFACTS / f"{prefix}.glb"
    mtl_path = ARTIFACTS / f"{prefix}.obj.mtl"
    if not mtl_path.exists():
        mtl_path = ARTIFACTS / f"{prefix}.mtl"
    if not mtl_path.exists():
        # OSM2World writes <name>.obj.mtl next to the OBJ
        mtl_path = Path(str(obj_path) + ".mtl")

    if obj_path.exists():
        write_provenance(obj_path, clip["source_sha256"])
        if mtl_path.exists():
            write_provenance(mtl_path, clip["source_sha256"])
        if glb_path.exists():
            write_provenance(glb_path, clip["source_sha256"])
        evidence["artifacts"]["obj"] = str(obj_path.relative_to(REPO_ROOT))
        evidence["artifacts"]["glb"] = str(glb_path.relative_to(REPO_ROOT))
        evidence["artifacts"]["mtl"] = str(mtl_path.relative_to(REPO_ROOT))

    # ---- 2. determinism rerun (J2 stable naming) ----
    scratch = REPO_ROOT / "work" / "phase_j_scratch"
    if scratch.exists():
        shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True, exist_ok=True)
    runner2 = OSM2WorldRunner(
        osm_path=str(ARTIFACTS / "window_osm.osm"),
        output_dir=str(scratch),
        osm2world_home=str(OSM2WORLD_HOME),
        timeout_sec=1800,
        config_path=str(config_path),
        name_prefix=prefix,
    )
    os.environ["OSM2WORLD_OUTPUTS"] = "obj"
    o2w2 = runner2.run()
    if obj_path.exists() and (scratch / f"{prefix}.obj").exists():
        evidence["tools"]["determinism"] = determinism_compare(
            obj_path, scratch / f"{prefix}.obj")
    else:
        evidence["tools"]["determinism"] = {
            "verdict": "SKIPPED",
            "reason": f"osm2world statuses: {o2w.status}/{o2w2.status}",
        }
    shutil.rmtree(scratch, ignore_errors=True)

    # ---- 3. J1 structural validation ----
    if obj_path.exists():
        evidence["checks"]["J1_obj"] = validate_artifact(
            obj_path, kind="obj", input_sha256=clip["source_sha256"])
    if mtl_path.exists():
        evidence["checks"]["J1_mtl"] = validate_artifact(mtl_path, kind="mtl")
    if glb_path.exists():
        evidence["checks"]["J1_glb"] = validate_artifact(glb_path, kind="glb")

    # ---- 4. J4 semantic partition ----
    if obj_path.exists():
        evidence["checks"]["J4_semantic_partition"] = semantic_partition(obj_path)

    # ---- 5. J5 coordinate control points ----
    if obj_path.exists():
        evidence["checks"]["J5_coordinate_control"] = coordinate_control_check(
            obj_path, INPUT_XODR,
            os_window_bounds_wgs84={
                "lon_min": WINDOW["lon_min"], "lon_max": WINDOW["lon_max"],
                "lat_min": WINDOW["lat_min"], "lat_max": WINDOW["lat_max"],
            })

    # ---- 6. J7 collision + LOD ----
    if obj_path.exists():
        evidence["checks"]["J7_collision"] = collision_check(obj_path, INPUT_XODR)
        evidence["checks"]["J7_lod"] = lod_check(config_path, obj_path, None)

    # ---- 7. J8 detached slabs ----
    if obj_path.exists():
        evidence["checks"]["J8_detached_slabs"] = detached_slab_check(obj_path)

    # ---- 8. J3 Blender conversion -> FBX (J2 naming) ----
    blender_result: Dict[str, Any] = {}
    if skip_blender or not obj_path.exists():
        blender_result = {"status": "skipped", "reason": "--skip-blender"}
    else:
        bconv = BlenderRunner(
            obj_path=str(obj_path),
            output_dir=str(ARTIFACTS),
            name_prefix=prefix,
            timeout_sec=900,
        )
        bres = bconv.run()
        blender_result = bres.to_dict()
    evidence["tools"]["blender_fbx"] = blender_result

    # ---- 9. J6 FBX round-trip in a second clean Blender ----
    fbx_path = ARTIFACTS / f"{prefix}.fbx"
    if fbx_path.exists() and DEFAULT_BLENDER_EXE.exists():
        source_manifest = blender_result.get("manifest", {})
        ok, report = run_fbx_roundtrip(
            fbx_path, ARTIFACTS, DEFAULT_BLENDER_EXE,
            source_manifest=source_manifest, timeout_sec=900)
        evidence["checks"]["J6_fbx_roundtrip"] = {
            "ok": ok,
            **report,
        }
    else:
        evidence["checks"]["J6_fbx_roundtrip"] = {
            "ok": None,
            "reason": "no FBX produced or Blender unavailable",
        }

    # ---- verdict ----
    j1 = evidence["checks"].get("J1_obj", {}).get("ok")
    verdicts = []
    if j1 is not None:
        verdicts.append("J1_PASS" if j1 else "J1_FAIL")
    j4 = evidence["checks"].get("J4_semantic_partition", {})
    if j4:
        verdicts.append("J4_OK" if not j4.get("duplicate_object_names")
                        else "J4_DUPLICATE_NAMES")
    j5 = evidence["checks"].get("J5_coordinate_control", {})
    if j5:
        verdicts.append(f"J5_{j5.get('verdict', 'N/A')}")
    j7c = evidence["checks"].get("J7_collision", {})
    if j7c:
        verdicts.append(f"J7_{j7c.get('verdict', 'N/A')}")
    j8 = evidence["checks"].get("J8_detached_slabs", {})
    if j8:
        verdicts.append(f"J8_{j8.get('verdict', 'N/A')}")
    j6 = evidence["checks"].get("J6_fbx_roundtrip", {})
    if j6.get("ok") is not None:
        verdicts.append("J6_PASS" if j6["ok"] else "J6_FAIL")

    evidence["verdict"] = "; ".join(verdicts) if verdicts else "NO_ARTIFACTS"
    evidence["generated_at"] = datetime.now(timezone.utc).isoformat()

    (EVIDENCE_DIR / "PHASE_J_OSM2WORLD_BLENDER.json").write_text(
        json.dumps(_to_jsonable(evidence), indent=2, sort_keys=True),
        encoding="utf-8")
    write_markdown(evidence, EVIDENCE_DIR / "PHASE_J_OSM2WORLD_BLENDER.md")
    print(json.dumps({"verdict": evidence["verdict"], "evidence": str(EVIDENCE_DIR)},
                     indent=2))
    return 0


def _to_jsonable(obj: Any) -> Any:
    """Deep-convert non-JSON-native types (bytes, numpy scalars) for dumping."""
    if isinstance(obj, (bytes, bytearray)):
        return repr(obj)
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    return obj


def write_markdown(evidence: Dict[str, Any], path: Path) -> None:
    lines = [
        "# Phase J: OSM2World + Blender/FBX enrichment evidence",
        "",
        f"- Run ID: `{evidence['run_id']}`",
        f"- Verdict: `{evidence['verdict']}`",
        f"- Evidence directory: `reports/post_audit_hardening/{evidence['run_id']}/`",
        "",
        "## J2 Artifact naming",
        f"- Scheme: `{evidence['artifacts'].get('naming_scheme', 'n/a')}`",
        "",
        "## J1 OBJ/GLB/MTL structural validation",
    ]
    for key in ("J1_obj", "J1_mtl", "J1_glb"):
        c = evidence["checks"].get(key)
        if not c:
            continue
        lines.append(f"### {key}: {'PASS' if c.get('ok') else 'FAIL'}")
        for name, res in c.get("checks", {}).items():
            lines.append(f"- {name}: {'ok' if res.get('ok') else 'FAIL'} "
                         f"({res.get('detail')})")

    j4 = evidence["checks"].get("J4_semantic_partition")
    if j4:
        lines += ["", "## J4 Semantic partition", f"- objects: {j4.get('objects_total')}"]
        for cls, stats in j4.get("classes", {}).items():
            lines.append(f"- `{cls}`: {stats['objects']} objects, "
                         f"{stats['faces']} faces, materials={stats['materials']}")

    j5 = evidence["checks"].get("J5_coordinate_control")
    if j5:
        lines += ["", "## J5 Coordinate control points",
                  f"- Verdict: `{j5.get('verdict')}`",
                  f"- OBJ header origin (WGS84): `{j5.get('obj_header_origin_wgs84')}`",
                  f"- OBJ origin in XODR frame: `{j5.get('obj_origin_xodr_frame')}`",
                  f"- Nearest XODR road control point: "
                  f"{j5.get('nearest_xodr_road_point_m')} m"]
        if j5.get("detail"):
            lines.append(f"- Detail: {j5['detail']}")

    j7c = evidence["checks"].get("J7_collision")
    if j7c:
        lines += ["", "## J7 Collision + LOD",
                  f"- Collision verdict: `{j7c.get('verdict')}` "
                  f"({j7c.get('intrusion_count', 0)} intrusions, "
                  f"{j7c.get('violation_count', 0)} violations)",
                  f"- Corridors checked: {j7c.get('road_corridors_checked')}"]

    j8 = evidence["checks"].get("J8_detached_slabs")
    if j8:
        lines += ["", "## J8 Detached-slab validation",
                  f"- Verdict: `{j8.get('verdict')}`",
                  f"- exact duplicate faces: {j8.get('exact_duplicate_faces_total')}",
                  f"- coplanar overlapping pairs: "
                  f"{j8.get('coplanar_overlapping_pairs_total')}",
                  f"- degenerate faces: {j8.get('degenerate_faces_total')}",
                  f"- floating slabs: {j8.get('floating_slab_count')}"]

    j6 = evidence["checks"].get("J6_fbx_roundtrip")
    if j6:
        comp = j6.get("comparison", {})
        lines += ["", "## J6 FBX round-trip",
                  f"- ok: {j6.get('ok')}",
                  f"- verdict: `{comp.get('verdict')}`"]
        if j6.get("error"):
            lines.append(f"- error: {j6['error']}")

    det = evidence["tools"].get("determinism", {})
    if det:
        lines += ["", "## Determinism (J2 stable naming)",
                  f"- verdict: `{det.get('verdict')}`",
                  f"- byte-identical: {det.get('byte_identical')}",
                  f"- object names equal: {det.get('object_names_equal')}"]

    blender = evidence["tools"].get("blender_fbx", {})
    if blender:
        lines += ["", "## J3 Blender manifest",
                  f"- status: `{blender.get('status')}`",
                  f"- blender: `{blender.get('blender_version')}` "
                  f"(exe sha256 {str(blender.get('blender_exe_hash', ''))[:12]}…)",
                  f"- script sha256: {str(blender.get('script_hash', ''))[:16]}…",
                  f"- exit code: {blender.get('exit_code')}",
                  f"- fbx: {blender.get('output_fbx')}"]
        manifest = blender.get("manifest") or {}
        if manifest:
            lines.append(f"- FBX header: `{manifest.get('fbx_header')}` "
                         f"(version {manifest.get('fbx_version')})")
            lines.append(f"- units: {manifest.get('scene_unit_system')} "
                         f"scale {manifest.get('scene_unit_scale')}")
            lines.append(f"- import: {manifest.get('import_operator')} "
                         f"{manifest.get('import_options')}")
            lines.append(f"- export axes: "
                         f"forward={manifest.get('export_options', {}).get('axis_forward')}, "
                         f"up={manifest.get('export_options', {}).get('axis_up')}, "
                         f"global_scale={manifest.get('export_options', {}).get('global_scale')}")
            lines.append(f"- objects: {manifest.get('objects_total')}, "
                         f"materials: {manifest.get('materials_total')}, "
                         f"images: {manifest.get('images_total')}")
            lines.append(f"- input obj sha256: {str(manifest.get('input_obj_hash', ''))[:16]}…")
            lines.append(f"- output fbx sha256: {str(manifest.get('output_fbx_hash', ''))[:16]}…")

    clip = evidence["tools"].get("clip", {})
    if clip:
        lines += ["", "## Window clip (J2 input)",
                  f"- source: `{clip.get('source')}`",
                  f"- source sha256: `{clip.get('source_sha256')}`",
                  f"- window: {clip.get('window_wgs84')}",
                  f"- nodes {clip.get('nodes')}, ways {clip.get('ways')}, "
                  f"relations {clip.get('relations')}",
                  f"- bytes: {clip.get('bytes')}",
                  f"- method: {clip.get('clip_method')}"]

    o2w = evidence["tools"].get("osm2world", {})
    if o2w:
        lines += ["", "## OSM2World run",
                  f"- status: `{o2w.get('status')}`",
                  f"- reason: {o2w.get('reason')}",
                  f"- jar: `{o2w.get('osm2world_jar')}`",
                  f"- java: {o2w.get('java_version')}",
                  f"- command: {o2w.get('command_lines')}",
                  f"- outputs: {o2w.get('outputs')}",
                  f"- duration: {o2w.get('duration_sec')} s"]
        if o2w.get("glb_valid") is not None:
            lines.append(f"- GLB valid: {o2w.get('glb_valid')} "
                         f"({o2w.get('glb_validation_reason')})")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
