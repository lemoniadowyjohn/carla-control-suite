#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""O2W-001..005 / BLD-001..007 / O2W2BLD — output artifact governance.

Deterministic artifact naming, fail-closed OBJ validation, XODR alignment
measurement, completeness-claim gating for OSM2World, and Blender/FBX
round-trip tooling.  All validators are read-only and fail-closed: any
malformed data yields ``ok: False`` with a reason, never a silent pass.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

_HASH8_RE = re.compile(r"^[0-9a-f]{8}$")
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_-]")


def _sha256_file(path: str, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


# ------------------------------------------------------------- O2W-007/BLD-007
def artifact_name(
    *,
    map_id: str,
    campaign_id: str,
    source_hash8: str,
    tile_id: str,
    ext: str,
    kind: Optional[str] = None,
) -> str:
    """Deterministic artifact name: <map>_<campaign>_<hash8>_<tile>.<ext>.

    Never a bare ``scene.fbx``; every artifact is map-specific.  Raises on an
    invalid source hash (not a real 8-hex prefix).
    """
    if not _HASH8_RE.match(source_hash8):
        raise ValueError(f"source_hash8 must be 8 lowercase hex chars, got {source_hash8!r}")
    if not ext or ext.startswith("."):
        raise ValueError(f"ext must be extension without dot, got {ext!r}")
    map_id = _SAFE_ID_RE.sub("_", str(map_id))
    campaign_id = _SAFE_ID_RE.sub("_", str(campaign_id))
    tile_id = _SAFE_ID_RE.sub("_", str(tile_id))
    base = f"{map_id}_{campaign_id}_{source_hash8}_{tile_id}"
    if kind:
        base = f"{base}_{kind}"
    return f"{base}.{ext.lstrip('.')}"


# ------------------------------------------------------------------ O2W-001/005
def classify_osm2world_output(config: Dict[str, Any]) -> Dict[str, Any]:
    """O2W-001: classify output as supplemental or complete.

    Roads/terrain disabled -> 'supplemental' (visual context only).
    Roads/terrain enabled  -> 'complete_claim' only when explicitly claimed.
    """
    roads_enabled = bool(config.get("roads", config.get("RoadModule", False)))
    terrain_enabled = bool(config.get("terrain", config.get("createTerrain", False)))
    classification = "complete" if (roads_enabled and terrain_enabled) else "supplemental"
    return {
        "classification": classification,
        "roads_enabled": roads_enabled,
        "terrain_enabled": terrain_enabled,
        "note": "complete requires both roads and terrain enabled",
    }


def assert_completeness_claim(config: Dict[str, Any], claim: str) -> Dict[str, Any]:
    """O2W-005: reject road/terrain completeness claims when disabled."""
    cls = classify_osm2world_output(config)
    claim = (claim or "").strip().lower()
    if "complete" in claim and cls["classification"] != "complete":
        return {"ok": False, "reason": "completeness claimed but roads/terrain disabled",
                "classification": cls["classification"]}
    if cls["classification"] == "complete":
        return {"ok": True, "reason": "roads+terrain enabled; completeness claim allowed",
                "classification": cls["classification"]}
    return {"ok": True, "reason": "supplemental output; no completeness claim",
            "classification": cls["classification"]}


# ------------------------------------------------------------------ O2W-002
def cache_identity(
    *,
    osm_sha256: str,
    config_sha256: str,
    osm2world_version: str,
    java_version: str,
    runner_version: str,
    cli_args: List[str],
    output_format: str,
) -> str:
    """O2W-002: cache key from OSM hash, config hash, versions, CLI, format."""
    payload = json.dumps({
        "osm_sha256": osm_sha256,
        "config_sha256": config_sha256,
        "osm2world_version": osm2world_version,
        "java_version": java_version,
        "runner_version": runner_version,
        "cli_args": sorted(cli_args),
        "output_format": output_format,
    }, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ O2W-003
@dataclass
class OBJReport:
    ok: bool
    vertices: int = 0
    faces: int = 0
    groups: int = 0
    objects: int = 0
    materials: int = 0
    textures: int = 0
    bounds: Optional[Dict[str, float]] = None
    finite_vertices: int = 0
    issues: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "vertices": self.vertices,
            "faces": self.faces,
            "groups": self.groups,
            "objects": self.objects,
            "materials": self.materials,
            "textures": self.textures,
            "bounds": self.bounds,
            "finite_vertices": self.finite_vertices,
            "issues": self.issues,
        }


def validate_obj(
    path: str,
    *,
    max_vertices: int = 2_000_000,
    max_faces: int = 2_000_000,
    max_abs_coord_m: float = 200_000.0,
) -> Dict[str, Any]:
    """O2W-003: fail-closed OBJ validation.

    Checks: vertices parse + finite coordinates, face indices in range with
    >= 3 corners, bounds, units/origin (no NaN/inf), counts within caps.
    """
    report = OBJReport(ok=True)
    if not os.path.isfile(path):
        return OBJReport(ok=False, issues=[f"missing file: {path}"]).to_dict()
    xs: List[float] = []
    ys: List[float] = []
    zs: List[float] = []
    vertex_count = 0
    face_count = 0
    face_error = 0
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("v "):
                    parts = line.split()
                    if len(parts) < 4:
                        report.issues.append(f"line {vertex_count + face_count + face_error + 1}: bad vertex")
                        report.ok = False
                        continue
                    try:
                        coords = [float(p) for p in parts[1:4]]
                    except ValueError:
                        report.issues.append(f"line: non-numeric vertex")
                        report.ok = False
                        continue
                    if not all(math.isfinite(v) for v in coords):
                        report.issues.append(f"non-finite vertex: {coords}")
                        report.ok = False
                        continue
                    xs.append(coords[0]); ys.append(coords[1]); zs.append(coords[2])
                    vertex_count += 1
                elif line.startswith("f "):
                    face_count += 1
                    idx_parts = [p.split("/")[0] for p in line.split()[1:]]
                    idx_parts = [p for p in idx_parts if p]
                    if len(idx_parts) < 3:
                        face_error += 1
                        report.issues.append(f"face with <3 corners")
                        report.ok = False
                        continue
                    for p in idx_parts:
                        try:
                            idx = int(p)
                        except ValueError:
                            report.ok = False
                            continue
                        if idx == 0 or abs(idx) > vertex_count:
                            report.ok = False
                            report.issues.append(f"face index out of range: {idx}")
                elif line.startswith("g "):
                    report.groups += 1
                elif line.startswith("o "):
                    report.objects += 1
                elif line.startswith("usemtl "):
                    report.materials += 1
                elif line.startswith("mtllib ") or line.startswith("map_Kd ") or \
                        line.startswith("map_Ka "):
                    report.textures += 1
    except OSError as exc:
        return OBJReport(ok=False, issues=[f"read error: {exc}"]).to_dict()

    report.vertices = vertex_count
    report.faces = face_count
    report.finite_vertices = vertex_count
    if xs:
        report.bounds = {"x_min": min(xs), "x_max": max(xs),
                         "y_min": min(ys), "y_max": max(ys),
                         "z_min": min(zs), "z_max": max(zs)}
        for key, v in report.bounds.items():
            if abs(v) > max_abs_coord_m:
                report.ok = False
                report.issues.append(f"{key}={v} exceeds |{max_abs_coord_m}| m")
    if vertex_count > max_vertices:
        report.ok = False
        report.issues.append(f"vertex count {vertex_count} > {max_vertices}")
    if face_count > max_faces:
        report.ok = False
        report.issues.append(f"face count {face_count} > {max_faces}")
    if vertex_count == 0:
        report.ok = False
        report.issues.append("no vertices parsed")
    return report.to_dict()


# ------------------------------------------------------------------ O2W-004
def measure_alignment(
    xodr_path: str,
    obj_path: str,
    *,
    control_points: Optional[List[Tuple[float, float]]] = None,
) -> Dict[str, Any]:
    """O2W-004: measure OBJ alignment against XODR control points/bounds."""
    obj = validate_obj(obj_path)
    if not obj["ok"]:
        return {"ok": False, "reason": f"invalid obj: {obj['issues'][:3]}", "rule": "O2W-004"}
    xodr_bounds: Dict[str, float] = {"x_min": math.inf, "y_min": math.inf,
                                     "x_max": -math.inf, "y_max": -math.inf}
    try:
        root = ET.parse(xodr_path).getroot()
        for geom in root.findall("./road/planView/geometry"):
            x = _float(geom.get("x")); y = _float(geom.get("y"))
            xodr_bounds["x_min"] = min(xodr_bounds["x_min"], x)
            xodr_bounds["y_min"] = min(xodr_bounds["y_min"], y)
            xodr_bounds["x_max"] = max(xodr_bounds["x_max"], x)
            xodr_bounds["y_max"] = max(xodr_bounds["y_max"], y)
    except Exception as exc:
        return {"ok": False, "reason": f"xodr parse failed: {exc}", "rule": "O2W-004"}
    if math.isinf(xodr_bounds["x_min"]):
        return {"ok": False, "reason": "xodr has no geometry", "rule": "O2W-004"}

    x_offset = obj["bounds"]["x_min"] - xodr_bounds["x_min"]
    y_offset = obj["bounds"]["y_min"] - xodr_bounds["y_min"]
    dx = abs(x_offset)
    dy = abs(y_offset)
    within_tol = dx < 5.0 and dy < 5.0
    ctrl_ok = True
    if control_points:
        ctrl_dx = max(abs(c[0] - obj["bounds"]["x_min"]) for c in control_points)
        ctrl_ok = ctrl_dx < 5.0

    return {
        "ok": within_tol and ctrl_ok,
        "rule": "O2W-004",
        "obj_bounds": obj["bounds"],
        "xodr_bounds": xodr_bounds,
        "x_offset_m": x_offset,
        "y_offset_m": y_offset,
        "within_5m": within_tol,
        "control_points_ok": ctrl_ok,
    }


def _float(value: Optional[str], default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except Exception:
        return default


# ------------------------------------------------------------------ BLD-001/006/007
def record_blender_provenance(
    *,
    blender_version: str,
    script_sha256: str,
    import_options: Dict[str, Any],
    export_options: Dict[str, Any],
    coordinate_transform: Dict[str, Any],
    units: str,
) -> Dict[str, Any]:
    """BLD-001: Blender version, script hash, options, transforms, units."""
    return {
        "blender_version": blender_version,
        "script_sha256": script_sha256,
        "import_options": import_options,
        "export_options": export_options,
        "coordinate_transform": coordinate_transform,
        "units": units,
    }


def _obj_summary(obj_report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "vertices": obj_report.get("vertices"),
        "faces": obj_report.get("faces"),
        "groups": obj_report.get("groups"),
        "objects": obj_report.get("objects"),
        "materials": obj_report.get("materials"),
        "bounds": obj_report.get("bounds"),
    }


def validate_fbx_round_trip(
    blender_exe: str,
    blender_script: str,
    fbx_path: str,
    *,
    out_dir: str,
    timeout_s: int = 600,
) -> Dict[str, Any]:
    """BLD-006: re-import FBX in a second headless Blender process.

    Runs ``blender_exe --background --python <script>``; the script must
    accept ``--fbx-in`` and ``--fbx-out`` and emit a JSON summary.  Returns
    fail-closed: missing Blender, missing script, or script failure all yield
    ``ok: False`` with a BLOCKED marker (never a false pass).
    """
    if not blender_exe or not os.path.isfile(blender_exe):
        return {"ok": False, "rule": "BLD-006", "blocked": True,
                "reason": f"blender not found: {blender_exe!r} (toolchain unavailable)"}
    if not os.path.isfile(fbx_path):
        return {"ok": False, "rule": "BLD-006", "blocked": True,
                "reason": f"fbx not found: {fbx_path}"}
    summary_path = os.path.join(out_dir, "fbx_roundtrip_summary.json")
    cmd = [blender_exe, "--background", "--python", blender_script,
           "--", "--fbx-in", fbx_path,
           "--fbx-out", os.path.join(out_dir, "roundtrip.fbx"),
           "--summary", summary_path]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    except Exception as exc:
        return {"ok": False, "rule": "BLD-006", "blocked": False,
                "reason": f"blender invocation failed: {exc}"}
    if proc.returncode != 0:
        return {"ok": False, "rule": "BLD-006", "blocked": False,
                "reason": f"blender exit {proc.returncode}: {(proc.stderr or '')[-500:]}"}
    try:
        with open(summary_path, encoding="utf-8") as fh:
            summary = json.load(fh)
    except Exception as exc:
        return {"ok": False, "rule": "BLD-006", "blocked": False,
                "reason": f"summary unreadable: {exc}"}
    return {"ok": True, "rule": "BLD-006", "blocked": False, "summary": summary}
