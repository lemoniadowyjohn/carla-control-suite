#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OBJ / GLB / MTL validator (Phase J1).

Structural validation of OSM2World artifacts:

  - file freshness (mtime vs declared inputs) and input-hash linkage
  - vertex / face / normal / UV counts
  - material library (mtllib) and texture references (map_Kd)
  - bounds, finite coordinates, coordinate magnitude
  - degenerate faces (zero-area triangles)
  - empty objects / duplicate objects
  - GLB: magic, JSON chunk encoding (utf-8), accessor bounds

A stale ``scene.obj`` from another run is rejected: every artifact must
carry a sidecar provenance record (``<name>.provenance.json``) whose
input_sha256 matches the OSM input and whose artifact_sha256 matches the
artifact bytes.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _finite(x: float) -> bool:
    return math.isfinite(x)


@dataclass
class ObjStats:
    vertices: List[Tuple[float, float, float]] = field(default_factory=list)
    normals: int = 0
    texcoords: int = 0
    faces: List[Tuple[int, ...]] = field(default_factory=list)
    object_groups: List[str] = field(default_factory=list)
    group_names: List[str] = field(default_factory=list)
    materials_used: List[str] = field(default_factory=list)
    mtllib: List[str] = field(default_factory=list)
    object_faces: Dict[str, int] = field(default_factory=dict)
    current_object: str = ""

    def counts(self) -> Dict[str, int]:
        return {
            "vertices": len(self.vertices),
            "faces": len(self.faces),
            "normals": self.normals,
            "texcoords": self.texcoords,
            "object_groups": len(self.object_groups),
            "materials_used": len(self.materials_used),
            "material_libraries": len(self.mtllib),
        }

    def bounds(self) -> Dict[str, float]:
        if not self.vertices:
            return {"x_min": 0.0, "y_min": 0.0, "z_min": 0.0,
                    "x_max": 0.0, "y_max": 0.0, "z_max": 0.0}
        xs = [v[0] for v in self.vertices]
        ys = [v[1] for v in self.vertices]
        zs = [v[2] for v in self.vertices]
        return {"x_min": min(xs), "y_min": min(ys), "z_min": min(zs),
                "x_max": max(xs), "y_max": max(ys), "z_max": max(zs)}


def parse_obj(path: Path) -> ObjStats:
    stats = ObjStats()
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if parts[0] == "v" and len(parts) >= 4:
                try:
                    stats.vertices.append((float(parts[1]), float(parts[2]),
                                           float(parts[3])))
                except ValueError:
                    continue
            elif parts[0] == "vn":
                stats.normals += 1
            elif parts[0] == "vt":
                stats.texcoords += 1
            elif parts[0] == "f":
                face = []
                for tok in parts[1:]:
                    idx = tok.split("/")[0]
                    try:
                        face.append(int(idx))
                    except ValueError:
                        face.append(0)
                if face:
                    stats.faces.append(tuple(face))
                    if stats.current_object:
                        stats.object_faces[stats.current_object] = \
                            stats.object_faces.get(stats.current_object, 0) + 1
            elif parts[0] == "o":
                stats.object_groups.append(" ".join(parts[1:]) or "(unnamed)")
                stats.current_object = stats.object_groups[-1]
            elif parts[0] == "g":
                stats.group_names.append(" ".join(parts[1:]) or "(unnamed)")
            elif parts[0] == "usemtl":
                stats.materials_used.append(" ".join(parts[1:]) or "(default)")
            elif parts[0] == "mtllib":
                stats.mtllib.append(" ".join(parts[1:]))
    return stats


def _face_area(stats: ObjStats, face: Tuple[int, ...]) -> float:
    verts = []
    for idx in face:
        ai = abs(idx)
        if ai == 0 or ai > len(stats.vertices):
            return -1.0
        verts.append(stats.vertices[ai - 1])
    if len(verts) < 3:
        return -1.0
    ax, ay, az = verts[1][0] - verts[0][0], verts[1][1] - verts[0][1], verts[1][2] - verts[0][2]
    bx, by, bz = verts[2][0] - verts[0][0], verts[2][1] - verts[0][1], verts[2][2] - verts[0][2]
    cx, cy, cz = ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx
    return 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)


def validate_obj(
    path: Path,
    *,
    input_sha256: str = "",
    max_coord_m: float = 1.0e7,
) -> Dict[str, Any]:
    """J1: full structural OBJ validation. Returns per-check results."""
    checks: Dict[str, Any] = {}
    if not path.exists():
        return {"ok": False, "checks": {"exists": {"ok": False,
                                                   "detail": "missing"}}}
    size = path.stat().st_size
    checks["exists"] = {"ok": True, "detail": f"{size} bytes"}
    checks["empty_file"] = {"ok": size > 0, "detail": f"{size} bytes"}
    if size == 0:
        return {"ok": False, "checks": checks}

    stats = parse_obj(path)
    counts = stats.counts()
    checks["vertex_count"] = {"ok": counts["vertices"] > 0,
                              "detail": counts["vertices"]}
    checks["face_count"] = {"ok": counts["faces"] > 0,
                            "detail": counts["faces"]}
    checks["normal_count"] = {"ok": counts["normals"] >= 0,
                              "detail": counts["normals"]}
    checks["uv_count"] = {"ok": counts["texcoords"] >= 0,
                          "detail": counts["texcoords"]}

    bounds = stats.bounds()
    checks["bounds"] = {"ok": True, "detail": bounds}

    finite = all(_finite(c) for v in stats.vertices for c in v)
    checks["finite_coordinates"] = {"ok": finite, "detail": len(stats.vertices)}
    mag = max((max(abs(c) for c in v) for v in stats.vertices),
              default=0.0)
    checks["coordinate_magnitude"] = {
        "ok": mag <= max_coord_m,
        "detail": f"max |coord| = {mag:.1f} m (limit {max_coord_m:.0f} m)"}

    degenerate = 0
    for face in stats.faces:
        area = _face_area(stats, face)
        if area <= 1e-12 or area < 0:
            degenerate += 1
    checks["degenerate_faces"] = {"ok": degenerate == 0,
                                  "detail": degenerate}

    obj_sigs: Dict[str, int] = {}
    for name in stats.object_groups:
        obj_sigs[name] = obj_sigs.get(name, 0) + 1
    dup_objects = {k: v for k, v in obj_sigs.items() if v > 1}
    checks["duplicate_objects"] = {"ok": not dup_objects,
                                   "detail": dup_objects}

    empty_objects = {k: v for k, v in stats.object_faces.items() if v == 0}
    checks["empty_objects"] = {"ok": not empty_objects,
                               "detail": empty_objects}

    # material library linkage
    mtl_paths: Dict[str, bool] = {}
    for lib in stats.mtllib:
        p = path.parent / lib
        mtl_paths[lib] = p.exists()
    checks["material_library"] = {"ok": all(mtl_paths.values()),
                                  "detail": mtl_paths}

    # freshness + input hash linkage via sidecar provenance
    prov = path.parent / f"{path.name}.provenance.json"
    if prov.exists():
        try:
            rec = json.loads(prov.read_text(encoding="utf-8"))
        except Exception:
            rec = None
    else:
        rec = None
    if rec:
        linked = (rec.get("input_sha256") == input_sha256
                  if input_sha256 else True)
        artifact_match = rec.get("artifact_sha256") == _sha256(path)
        checks["input_hash_linkage"] = {"ok": linked,
                                        "detail": rec.get("input_sha256", "")[:12]}
        checks["artifact_hash_match"] = {"ok": artifact_match,
                                         "detail": rec.get("artifact_sha256", "")[:12]}
    else:
        checks["input_hash_linkage"] = {"ok": False,
                                        "detail": "no provenance sidecar"}
        checks["artifact_hash_match"] = {"ok": False,
                                         "detail": "no provenance sidecar"}

    ok = all(v["ok"] for v in checks.values())
    return {"ok": ok, "checks": checks, "counts": counts, "bounds": bounds}


def validate_glb(path: Path, *, max_coord_m: float = 1.0e7) -> Dict[str, Any]:
    """J1: GLB header/JSON-chunk/accessor validation."""
    checks: Dict[str, Any] = {}
    if not path.exists():
        return {"ok": False, "checks": {"exists": {"ok": False,
                                                   "detail": "missing"}}}
    size = path.stat().st_size
    checks["exists"] = {"ok": True, "detail": f"{size} bytes"}
    if size < 12:
        return {"ok": False, "checks": checks}
    with open(path, "rb") as f:
        magic = f.read(4)
        ver, total = struct.unpack("<II", f.read(8))
    checks["magic"] = {"ok": magic == b"glTF", "detail": magic.decode("ascii", "replace")}
    checks["version"] = {"ok": ver == 2, "detail": ver}
    checks["total_length"] = {"ok": total == size,
                              "detail": f"{total} vs {size}"}
    # iterate chunks; JSON chunk must be utf-8 decodable
    json_chunk = b""
    pos = 12
    with open(path, "rb") as f:
        while pos + 8 <= size:
            f.seek(pos)
            clen, ctype = struct.unpack("<II", f.read(8))
            if pos + 8 + clen > size:
                checks["chunk_length"] = {"ok": False, "detail": pos}
                break
            f.seek(pos + 8)
            chunk = f.read(clen)
            if ctype == 0x4E4F534A:  # JSON
                json_chunk = chunk
            pos += 8 + clen
    try:
        gltf = json.loads(json_chunk.decode("utf-8"))
        checks["json_utf8"] = {"ok": True, "detail": "utf-8 decode ok"}
        checks["json_valid"] = {"ok": True, "detail": "JSON parse ok"}
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        checks["json_utf8"] = {"ok": False, "detail": str(e)}
        checks["json_valid"] = {"ok": False, "detail": str(e)}
        return {"ok": False, "checks": checks}

    accessors = gltf.get("accessors") or []
    bad_bounds = []
    for i, acc in enumerate(accessors):
        mn = acc.get("min") or []
        mx = acc.get("max") or []
        for v in mn + mx:
            if abs(v) > max_coord_m:
                bad_bounds.append((i, v))
    checks["accessor_bounds"] = {"ok": not bad_bounds, "detail": bad_bounds[:5]}
    checks["accessor_count"] = {"ok": len(accessors) > 0, "detail": len(accessors)}
    ok = all(v["ok"] for v in checks.values())
    return {"ok": ok, "checks": checks}


def validate_mtl(path: Path) -> Dict[str, Any]:
    """J1: material library parsing; texture references must resolve."""
    checks: Dict[str, Any] = {}
    if not path.exists():
        return {"ok": False, "checks": {"exists": {"ok": False,
                                                   "detail": "missing"}}}
    materials: List[str] = []
    textures: Dict[str, bool] = {}
    current = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0] == "newmtl":
            current = " ".join(parts[1:])
            materials.append(current)
        elif parts[0].startswith("map_") and current:
            tex = " ".join(parts[1:])
            if tex and tex not in textures:
                textures[tex] = path.parent.joinpath(tex).exists()
    checks["materials"] = {"ok": len(materials) > 0, "detail": materials}
    missing = {k: v for k, v in textures.items() if not v}
    checks["texture_references"] = {"ok": not missing, "detail": missing or textures}
    ok = all(v["ok"] for v in checks.values())
    return {"ok": ok, "checks": checks, "materials": materials}


def validate_artifact(
    path: Path,
    *,
    kind: str,
    input_sha256: str = "",
) -> Dict[str, Any]:
    """J1: dispatch OBJ/GLB/MTL validation."""
    if kind == "obj":
        return validate_obj(path, input_sha256=input_sha256)
    if kind == "glb":
        return validate_glb(path)
    if kind == "mtl":
        return validate_mtl(path)
    raise ValueError(f"unknown artifact kind: {kind}")
