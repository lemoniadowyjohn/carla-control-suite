"""Offline mesh-quality analysis and gating for the building mesh pipeline.

This module is the *evidence layer* for the geometry-degeneracy work. It reads
the two artifacts the production pipeline actually emits -- Wavefront OBJ
(OSM2World output) and FBX (Blender output, binary 7.x or ASCII) -- and reports
the geometric conditions that make Unreal Engine 4.26 emit:

  * ``has degenerate tangent bases which will result in incorrect shading``
  * ``has some nearly zero bi-normals``
  * ``has no smoothing group information`` / missing smoothing groups
  * geometry/mesh import warnings for degenerate triangles

Everything here is pure stdlib + numpy: no Blender, no UE, no CARLA. That is
deliberate -- the gate must be runnable on any machine that can read the
artifacts, so a warning can be *predicted and attributed* offline before
anyone spends an hour in an editor import.

The central idea: UE4 does not export explicit tangents for these FBX files
(``use_tspace=False``), so the engine derives them with MikkTSpace from the
normal plus the UV channel. A tangent basis is degenerate exactly when the UV
triangle has (near) zero parametric area, or the triangle has (near) zero
geometric area, or the normal is not usable. So the actionable metric is
``uv_degenerate_face_ratio`` and ``has_uv_channel`` -- not "are the exported
tangents valid", because there are none.

Policy (governed):
  * Analysis never mutates geometry. Repair lives in the generator stage.
  * A face is degenerate only if it is unrepairable-by-construction:
    a repeated vertex index, or zero geometric area with a zero-length
    geometric basis (a collapsed sliver). Faces that are merely *thin* are
    reported as slivers, not silently deleted.
  * Gate statuses are ``PASS``, ``REPAIRED``, ``REJECTED``.
"""

from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

__all__ = [
    "GATE_THRESHOLDS",
    "MeshData",
    "MeshMetrics",
    "box_project_corner_uvs",
    "corner_uv_area_stats",
    "plan_uv_generation",
    "probe_fbx_channels",
    "read_obj",
    "analyze_mesh",
    "evaluate_gate",
]


# ---------------------------------------------------------------------------
# Gate thresholds
# ---------------------------------------------------------------------------
# Distances are metres, areas are m^2, ratios are 0..1. The numeric choices are
# deliberately *loose* on slivers (we report them, we do not fail on them) and
# *strict* on the two things that provably cause the UE4 tangent warnings:
# a missing UV channel and UV-parametric-area collapse.
GATE_THRESHOLDS: dict[str, float] = {
    # geometric
    "zero_area_eps_m2": 1e-12,
    "sliver_area_eps_m2": 1e-6,
    "degenerate_face_ratio_max": 0.0,          # any unrepairable face -> REJECTED
    "sliver_face_ratio_max": 0.02,             # advisory; drives REPAIRED
    # normals
    "normal_length_eps": 1e-9,
    "normal_unit_tolerance": 1e-3,
    "missing_normal_ratio_max": 0.0,           # every vertex needs a normal
    # UV / MikkTSpace precondition
    "uv_degenerate_area_eps": 1e-12,
    "uv_degenerate_face_ratio_max": 0.0,       # any collapsed UV tri -> REJECTED
    # smoothing
    "smoothing_group_count_min": 1,
}


@dataclass
class MeshData:
    """A triangle mesh in the shape the analyzers need.

    ``faces`` is (M, 3) int32. ``normals``/``uvs``/``tangents`` are per-vertex
    arrays or ``None`` when the source file carries no such channel at all --
    ``None`` is meaningfully different from an all-zero array.
    """

    name: str = "mesh"
    positions: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), np.float64))
    faces: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), np.int32))
    normals: np.ndarray | None = None
    uvs: np.ndarray | None = None
    tangents: np.ndarray | None = None
    smoothing: np.ndarray | None = None          # per-face smoothing group id
    face_groups: np.ndarray | None = None        # per-face object id (from OBJ o/g)
    object_names: list[str] = field(default_factory=list)
    source_path: str | None = None
    source_format: str = "unknown"

    @property
    def vertex_count(self) -> int:
        return int(self.positions.shape[0])

    @property
    def face_count(self) -> int:
        return int(self.faces.shape[0])


# ---------------------------------------------------------------------------
# OBJ reader
# ---------------------------------------------------------------------------
def read_obj(path: str | Path, *, name: str | None = None) -> MeshData:
    """Read a Wavefront OBJ as one mesh, recording per-face object groups.

    The file is returned as a single mesh (so face/area statistics are global),
    but ``MeshData.face_groups`` keeps the ``o``/``g`` object id of every face.
    That is what lets per-object UV normalization match what Blender does, where
    each building is a separate object with its own UV layout.
    """
    path = Path(path)
    positions: list[tuple[float, float, float]] = []
    normals: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    groups: list[str] = []
    group_ids: dict[str, int] = {}
    faces: list[tuple[int, int, int]] = []
    face_group: list[int] = []
    current_group = -1
    has_normal_idx = False
    has_uv_idx = False

    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line or line[0] == "#":
                continue
            if line.startswith("v "):
                x, y, z = line.split()[1:4]
                positions.append((float(x), float(y), float(z)))
            elif line.startswith("vn "):
                x, y, z = line.split()[1:4]
                normals.append((float(x), float(y), float(z)))
            elif line.startswith("vt "):
                parts = line.split()[1:]
                uvs.append((float(parts[0]), float(parts[1]) if len(parts) > 1 else 0.0))
            elif line.startswith(("o ", "g ")):
                gname = line[2:].strip()
                groups.append(gname)
                current_group = group_ids.setdefault(gname, len(group_ids))
            elif line.startswith("f "):
                toks = line.split()[1:]
                if len(toks) < 3:
                    continue
                idx: list[int] = []
                for t in toks:
                    bits = t.split("/")
                    vi = int(bits[0])
                    idx.append(vi - 1 if vi > 0 else len(positions) + vi)
                    if len(bits) > 1 and bits[1]:
                        has_uv_idx = True
                    if len(bits) > 2 and bits[2]:
                        has_normal_idx = True
                # fan-triangulate n-gons (OSM2World emits triangles, but be safe)
                for k in range(1, len(idx) - 1):
                    faces.append((idx[0], idx[k], idx[k + 1]))
                    face_group.append(max(current_group, 0))

    pos = np.asarray(positions, np.float64).reshape(-1, 3)
    fcs = np.asarray(faces, np.int32).reshape(-1, 3)
    fgid = np.asarray(face_group, np.int64)
    nrm = np.asarray(normals, np.float64).reshape(-1, 3) if normals else None
    uv = np.asarray(uvs, np.float64).reshape(-1, 2) if uvs else None

    # OBJ normals/UVs are indexed per-face-corner; fold them to per-vertex so
    # the analyzers have a single channel shape. Split vertices are collapsed,
    # which is exactly what Blender's OBJ importer does before export.
    if fcs.size and (has_normal_idx or has_uv_idx):
        pos, fcs, nrm, uv = _split_vertices_by_corner(pos, fcs, nrm, uv, has_normal_idx, has_uv_idx)

    return MeshData(
        name=name or path.stem,
        positions=pos,
        faces=fcs,
        normals=nrm,
        uvs=uv,
        smoothing=None,
        face_groups=fgid if fcs.size else np.zeros(0, np.int64),
        object_names=groups,
        source_path=str(path),
        source_format="obj" + (f" objects={len(groups)}" if groups else ""),
    )


def _split_vertices_by_corner(
    pos: np.ndarray,
    fcs: np.ndarray,
    nrm: np.ndarray | None,
    uv: np.ndarray | None,
    has_normal_idx: bool,
    has_uv_idx: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None, np.ndarray | None]:
    """Split every (vertex, normal, uv) corner combination into its own vertex."""
    keys: dict[tuple[int, int, int], int] = {}
    new_pos: list[np.ndarray] = []
    new_nrm: list[np.ndarray] = []
    new_uv: list[tuple[float, float]] = []
    new_faces = np.empty_like(fcs)
    for fi in range(fcs.shape[0]):
        for ci in range(3):
            v = int(fcs[fi, ci])
            n = v if (nrm is not None and not has_normal_idx) else 0
            u = v if (uv is not None and not has_uv_idx) else 0
            key = (v, n, u)
            idx = keys.get(key)
            if idx is None:
                idx = len(new_pos)
                keys[key] = idx
                new_pos.append(pos[v])
                if nrm is not None:
                    new_nrm.append(nrm[n] if has_normal_idx else nrm[v])
                if uv is not None:
                    new_uv.append((float(uv[u, 0]), float(uv[u, 1])) if has_uv_idx
                                  else (float(uv[v, 0]), float(uv[v, 1])))
            new_faces[fi, ci] = idx
    return (
        np.asarray(new_pos, np.float64).reshape(-1, 3),
        new_faces,
        np.asarray(new_nrm, np.float64).reshape(-1, 3) if new_nrm else None,
        np.asarray(new_uv, np.float64).reshape(-1, 2) if new_uv else None,
    )


# ---------------------------------------------------------------------------
# FBX channel probe
# ---------------------------------------------------------------------------
# Why this is a probe and not a parser
# ------------------------------------
# The geometry-level facts we need (positions/faces/areas) come from the OBJ,
# which OSM2World writes as plain text and which this module parses exactly.
# For the FBX we need a different fact: *which vertex layers exist*. That is
# answerable soundly without a full binary parser, because binary FBX stores
# node names as plain ASCII -- so a byte search for "LayerElementUV" is an exact
# existence test for that layer node.
#
# A hand-rolled binary FBX geometry parser was attempted and abandoned: Blender's
# FBXHeaderExtension writes a name length one byte short of the name it emits,
# and the property/sentinel ordering differs between writers. Rather than ship a
# parser whose output might be silently wrong, this module reports only what it
# can verify, and says so.
_FBX_MAGIC = b"Kaydara FBX Binary"

_FBX_LAYER_NODES = (
    "LayerElementNormal",
    "LayerElementUV",
    "LayerElementTangent",
    "LayerElementBinormal",
    "LayerElementSmoothing",
    "LayerElementMaterial",
)


def probe_fbx_channels(path: str | Path) -> dict[str, Any]:
    """Report which vertex layers an FBX actually contains.

    Returns counts of each layer node name found in the file bytes, plus the
    header version and size. ``LayerElementUV == 0`` is the decisive signal for
    the UE4 tangent/binormal warnings, because Blender exported these files with
    ``use_tspace=False``: no explicit tangents exist, so UE4 must derive them
    from a UV channel with MikkTSpace, and there is none.
    """
    path = Path(path)
    raw = path.read_bytes()
    layers = {name: raw.count(name.encode("ascii")) for name in _FBX_LAYER_NODES}
    version = None
    if raw.startswith(_FBX_MAGIC):
        version = struct.unpack_from("<H", raw, 23)[0]
    return {
        "path": str(path),
        "size_bytes": len(raw),
        "format": "binary" if raw.startswith(_FBX_MAGIC) else "ascii",
        "fbx_version": version,
        "layer_node_counts": layers,
        "has_normal_layer": layers["LayerElementNormal"] > 0,
        "has_uv_layer": layers["LayerElementUV"] > 0,
        "has_tangent_layer": layers["LayerElementTangent"] > 0,
        "has_binormal_layer": layers["LayerElementBinormal"] > 0,
        "has_smoothing_layer": layers["LayerElementSmoothing"] > 0,
        "method": "ascii node-name byte search over the FBX payload",
    }


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
@dataclass
class MeshMetrics:
    name: str
    source_path: str | None
    source_format: str
    vertex_count: int = 0
    face_count: int = 0

    has_normal_channel: bool = False
    has_uv_channel: bool = False
    has_tangent_channel: bool = False
    has_smoothing_channel: bool = False
    smoothing_group_count: int = 0

    degenerate_faces: int = 0              # repeated vertex index
    zero_area_faces: int = 0               # geometric area <= eps
    sliver_faces: int = 0                  # thin but non-zero
    collinear_faces: int = 0
    min_face_area_m2: float = 0.0
    mean_face_area_m2: float = 0.0

    zero_length_normals: int = 0
    non_unit_normals: int = 0
    non_finite_normals: int = 0
    vertices_without_normal: int = 0

    uv_degenerate_faces: int = 0
    min_uv_face_area: float = 0.0

    tangent_degenerate_faces: int = 0
    near_zero_binormal_faces: int = 0

    coordinate_magnitude_max: float = 0.0

    predicted_ue4_warnings: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source_path": self.source_path,
            "source_format": self.source_format,
            "vertex_count": self.vertex_count,
            "face_count": self.face_count,
            "has_normal_channel": self.has_normal_channel,
            "has_uv_channel": self.has_uv_channel,
            "has_tangent_channel": self.has_tangent_channel,
            "has_smoothing_channel": self.has_smoothing_channel,
            "smoothing_group_count": self.smoothing_group_count,
            "degenerate_faces": self.degenerate_faces,
            "zero_area_faces": self.zero_area_faces,
            "sliver_faces": self.sliver_faces,
            "collinear_faces": self.collinear_faces,
            "min_face_area_m2": self.min_face_area_m2,
            "mean_face_area_m2": self.mean_face_area_m2,
            "zero_length_normals": self.zero_length_normals,
            "non_unit_normals": self.non_unit_normals,
            "non_finite_normals": self.non_finite_normals,
            "vertices_without_normal": self.vertices_without_normal,
            "uv_degenerate_faces": self.uv_degenerate_faces,
            "min_uv_face_area": self.min_uv_face_area,
            "tangent_degenerate_faces": self.tangent_degenerate_faces,
            "near_zero_binormal_faces": self.near_zero_binormal_faces,
            "coordinate_magnitude_max": self.coordinate_magnitude_max,
            "predicted_ue4_warnings": self.predicted_ue4_warnings,
        }


def _safe_ratio(num: int, den: int) -> float:
    return float(num) / float(den) if den else 0.0


def analyze_mesh(mesh: MeshData, *, thresholds: dict[str, float] | None = None) -> MeshMetrics:
    th = dict(GATE_THRESHOLDS)
    if thresholds:
        th.update(thresholds)

    m = MeshMetrics(
        name=mesh.name,
        source_path=mesh.source_path,
        source_format=mesh.source_format,
        vertex_count=mesh.vertex_count,
        face_count=mesh.face_count,
        coordinate_magnitude_max=float(np.abs(mesh.positions).max()) if mesh.positions.size else 0.0,
    )
    faces = mesh.faces
    if faces.size == 0:
        m.predicted_ue4_warnings = {
            "degenerate_tangent_bases": 0,
            "nearly_zero_binormals": 0,
            "missing_smoothing_group": 1 if not m.has_smoothing_channel else 0,
        }
        return m

    idx = faces.astype(np.int64)
    in_range = (idx >= 0) & (idx < mesh.positions.shape[0])
    m.degenerate_faces = int(np.sum(
        (idx[:, 0] == idx[:, 1]) | (idx[:, 1] == idx[:, 2]) | (idx[:, 0] == idx[:, 2])
        | ~in_range.all(axis=1)
    ))

    # Out-of-range indices are already counted as degenerate above; clamp them so
    # the area/normal statistics below can still be computed without crashing.
    safe_idx = np.clip(idx, 0, max(mesh.positions.shape[0] - 1, 0))
    tri = mesh.positions[safe_idx]                 # (F, 3, 3)
    e1 = tri[:, 1] - tri[:, 0]
    e2 = tri[:, 2] - tri[:, 0]
    cross = np.cross(e1, e2)
    two_area = np.linalg.norm(cross, axis=1)
    area = 0.5 * two_area
    m.min_face_area_m2 = float(area.min()) if area.size else 0.0
    m.mean_face_area_m2 = float(area.mean()) if area.size else 0.0
    m.zero_area_faces = int(np.sum(area <= th["zero_area_eps_m2"]))
    m.sliver_faces = int(np.sum((area > th["zero_area_eps_m2"]) & (area < th["sliver_area_eps_m2"])))
    # collinear: cross magnitude tiny while the two edges are long => numerically
    # a line, so the face normal direction is arbitrary.
    edge_len = np.maximum(np.linalg.norm(e1, axis=1), np.linalg.norm(e2, axis=1))
    m.collinear_faces = int(np.sum(
        (two_area <= 1e-12) & (edge_len > th["zero_area_eps_m2"])
    ))

    # ---- normals -------------------------------------------------------
    m.has_normal_channel = mesh.normals is not None and mesh.normals.size > 0
    if m.has_normal_channel:
        nrm = np.asarray(mesh.normals, np.float64)
        if nrm.shape[0] != mesh.vertex_count:
            # per-corner normals indexed by face already; pad/truncate safely
            fixed = np.zeros((mesh.vertex_count, 3), np.float64)
            k = min(nrm.shape[0], mesh.vertex_count)
            fixed[:k] = nrm[:k]
            nrm = fixed
        nlen = np.linalg.norm(nrm, axis=1)
        m.non_finite_normals = int(np.sum(~np.isfinite(nrm)))
        m.zero_length_normals = int(np.sum(np.isfinite(nlen) & (nlen <= th["normal_length_eps"])))
        with np.errstate(invalid="ignore"):
            dev = np.abs(nlen[np.isfinite(nlen)] - 1.0)
        m.non_unit_normals = int(np.sum(dev > th["normal_unit_tolerance"]))
        used = np.unique(safe_idx)
        m.vertices_without_normal = int(np.sum(nlen[used] <= th["normal_length_eps"]))
    else:
        m.vertices_without_normal = mesh.vertex_count

    # ---- UV / tangent basis -------------------------------------------
    m.has_uv_channel = mesh.uvs is not None and mesh.uvs.size > 0
    if m.has_uv_channel:
        uv = np.asarray(mesh.uvs, np.float64)
        if uv.shape[0] != mesh.vertex_count:
            fixed = np.zeros((mesh.vertex_count, 2), np.float64)
            k = min(uv.shape[0], mesh.vertex_count)
            fixed[:k] = uv[:k]
            uv = fixed
        fuv = uv[safe_idx]                         # (F, 3, 2)
        duv1 = fuv[:, 1] - fuv[:, 0]
        duv2 = fuv[:, 2] - fuv[:, 0]
        det = duv1[:, 0] * duv2[:, 1] - duv1[:, 1] * duv2[:, 0]
        uv_area = 0.5 * np.abs(det)
        m.min_uv_face_area = float(uv_area.min()) if uv_area.size else 0.0
        m.uv_degenerate_faces = int(np.sum(uv_area <= th["uv_degenerate_area_eps"]))
    else:
        # No UV channel at all: every face has zero parametric area, so every
        # face has a degenerate tangent basis under MikkTSpace.
        m.uv_degenerate_faces = m.face_count
        m.min_uv_face_area = 0.0

    # ---- explicit tangents (only present when a producer exported them) --
    if mesh.tangents is not None and mesh.tangents.size:
        m.has_tangent_channel = True
        tan = np.asarray(mesh.tangents, np.float64).reshape(-1, 4) if mesh.tangents.size % 4 == 0 \
            else np.asarray(mesh.tangents, np.float64).reshape(-1, 3)
        if tan.shape[1] == 4:
            w = np.abs(tan[:, 3])
            m.tangent_degenerate_faces = int(np.sum(w <= th["normal_length_eps"]))
        else:
            tl = np.linalg.norm(tan[:, :3], axis=1)
            m.tangent_degenerate_faces = int(np.sum(tl <= th["normal_length_eps"]))
    else:
        m.tangent_degenerate_faces = m.uv_degenerate_faces

    m.near_zero_binormal_faces = m.tangent_degenerate_faces

    # ---- smoothing groups ---------------------------------------------
    if mesh.smoothing is not None and np.asarray(mesh.smoothing).size:
        m.has_smoothing_channel = True
        m.smoothing_group_count = int(np.unique(np.asarray(mesh.smoothing)).size)

    # ---- prediction of the literal UE4 warning strings ------------------
    m.predicted_ue4_warnings = {
        "degenerate_tangent_bases": m.tangent_degenerate_faces,
        "nearly_zero_binormals": m.near_zero_binormal_faces,
        "missing_smoothing_group": 0 if m.has_smoothing_channel else 1,
        "degenerate_triangles": m.degenerate_faces + m.zero_area_faces,
    }
    return m


# ---------------------------------------------------------------------------
# UV generation (reference implementation of the planned Blender fix)
# ---------------------------------------------------------------------------
# Blender's UVs are per-loop (per face-corner), not per-vertex, so this
# reference works per corner too. That matters: a vertex shared by a wall face
# and a roof face needs a *different* UV per corner under box projection.
#
# The projection picks, for each triangle, the axis its normal is most aligned
# with, then projects onto the other two axes. This is the standard cube/box
# projection. Its key property for our purpose: for a triangle of non-zero
# area, the projection onto the plane perpendicular to its dominant axis always
# has non-zero area. So box projection cannot manufacture a degenerate tangent
# basis out of valid geometry -- which is exactly the property we need, because
# the current defect is that there is no UV channel at all.
_AXIS_PAIRS = ((1, 2), (0, 2), (0, 1))


def box_project_corner_uvs(positions: np.ndarray, faces: np.ndarray, *,
                          groups: np.ndarray | None = None,
                          scale_to_unit: bool = True) -> np.ndarray:
    """Per-corner box-projected UVs, shape (F, 3, 2).

    ``groups`` optionally gives a per-face object id. Normalization is then done
    per group, which is what Blender will actually do (each building is its own
    object). Normalizing a whole 1 km tile as a single mesh would shrink a small
    building's UV footprint to near nothing, which is legal but wasteful and
    needlessly close to MikkTSpace's degenerate threshold.
    """
    pos = np.asarray(positions, np.float64)
    idx = np.asarray(faces, np.int64)
    tri = pos[idx]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    dominant = np.argmax(np.abs(n), axis=1)
    uvs = np.empty((idx.shape[0], 3, 2), np.float64)
    for axis, (a, b) in enumerate(_AXIS_PAIRS):
        sel = dominant == axis
        if not np.any(sel):
            continue
        uvs[sel, :, 0] = tri[sel][..., a]
        uvs[sel, :, 1] = tri[sel][..., b]
    if not scale_to_unit or not pos.size:
        return uvs

    ids = (np.zeros(idx.shape[0], np.int64) if groups is None
           else np.asarray(groups, np.int64))
    for gid in np.unique(ids):
        sel = ids == gid
        block = uvs[sel].reshape(-1, 2)
        lo = block.min(axis=0)
        span = block.max(axis=0) - lo
        span[span <= 0.0] = 1.0        # flat object: keep it stable, not /0
        uvs[sel] = (uvs[sel] - lo) / span
    return uvs


def corner_uv_area_stats(corner_uvs: np.ndarray, *,
                         eps: float = 1e-12) -> dict[str, float]:
    c = np.asarray(corner_uvs, np.float64)
    d1 = c[:, 1] - c[:, 0]
    d2 = c[:, 2] - c[:, 0]
    det = d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]
    area = 0.5 * np.abs(det)
    return {
        "faces": int(c.shape[0]),
        "degenerate_faces": int(np.sum(area <= eps)),
        "min_face_area": float(area.min()) if area.size else 0.0,
        "mean_face_area": float(area.mean()) if area.size else 0.0,
    }


def plan_uv_generation(positions: np.ndarray, faces: np.ndarray, *,
                       groups: np.ndarray | None = None,
                       eps: float = 1e-12) -> dict[str, Any]:
    """Dry-run the UV fix offline: what would box projection achieve?

    This is the evidence that the Blender-side fix works, produced without
    Blender. It answers "would every face get a non-degenerate parametric area?"
    for the real production OBJ, before anyone re-cooks 20 tiles.
    """
    per_object = box_project_corner_uvs(positions, faces, groups=groups)
    per_tile = box_project_corner_uvs(positions, faces, groups=None)
    stats_obj = corner_uv_area_stats(per_object, eps=eps)
    stats_tile = corner_uv_area_stats(per_tile, eps=eps)
    return {
        "method": "per-face box (cube) projection onto the plane perpendicular "
                  "to the dominant normal axis, normalized per object to [0,1]",
        "deterministic": True,
        "overlap_aware": False,
        **stats_obj,
        "eliminates_degenerate_tangent_basis": stats_obj["degenerate_faces"] == 0,
        "per_object_normalization": stats_obj,
        "per_tile_normalization": stats_tile,
    }


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------
def evaluate_gate(metrics: MeshMetrics, *, thresholds: dict[str, float] | None = None) -> dict[str, Any]:
    """Fail closed on unrepairable geometry; flag soft issues for repair."""
    th = dict(GATE_THRESHOLDS)
    if thresholds:
        th.update(thresholds)

    fatal: list[str] = []
    repairable: list[str] = []
    info: list[str] = []

    f = max(metrics.face_count, 1)
    v = max(metrics.vertex_count, 1)

    if metrics.face_count == 0 and metrics.vertex_count == 0:
        # Nothing to validate. An empty mesh has no UV channel and no smoothing
        # group, but reporting that as a defect would be nonsense.
        return {
            "status": "PASS",
            "fatal": [],
            "repairable": [],
            "info": ["empty mesh: no geometry to validate"],
            "predicted_ue4_warnings": metrics.predicted_ue4_warnings,
            "thresholds": th,
        }

    if metrics.degenerate_faces:
        fatal.append(
            f"{metrics.degenerate_faces} faces repeat a vertex index "
            f"({_safe_ratio(metrics.degenerate_faces, f):.6%} of faces)"
        )
    if metrics.zero_area_faces:
        fatal.append(
            f"{metrics.zero_area_faces} faces have zero geometric area "
            f"(<= {th['zero_area_eps_m2']:g} m^2)"
        )
    if metrics.vertices_without_normal:
        fatal.append(
            f"{metrics.vertices_without_normal} vertices lack a usable normal "
            f"({_safe_ratio(metrics.vertices_without_normal, v):.6%} of vertices)"
        )
    if not metrics.has_uv_channel:
        fatal.append(
            "no UV channel: MikkTSpace cannot derive a tangent basis, so every "
            f"face ({metrics.face_count}) predicts a degenerate-tangent and "
            "near-zero-bi-normal warning"
        )
    elif metrics.uv_degenerate_faces:
        fatal.append(
            f"{metrics.uv_degenerate_faces} faces have collapsed UV area "
            f"({_safe_ratio(metrics.uv_degenerate_faces, f):.6%} of faces)"
        )

    if not metrics.has_smoothing_channel:
        repairable.append(
            "FBX carries no LayerElementSmoothing -> UE4 'no smoothing group "
            "information' warning; regenerate with mesh_smooth_type='FACE' and "
            "angle-based sharp edges"
        )
    if metrics.sliver_faces:
        repairable.append(
            f"{metrics.sliver_faces} sliver faces (area < {th['sliver_area_eps_m2']:g} m^2)"
        )
    if metrics.collinear_faces:
        repairable.append(f"{metrics.collinear_faces} collinear faces with undefined normal direction")
    if metrics.non_unit_normals:
        info.append(f"{metrics.non_unit_normals} normals are not unit length")
    if metrics.has_tangent_channel:
        info.append("explicit tangent channel present (must be independently validated before export)")
    if metrics.coordinate_magnitude_max > 1e5:
        info.append(
            f"coordinate magnitude {metrics.coordinate_magnitude_max:.1f} exceeds 1e5 m; "
            "verify float32 FBX precision is adequate"
        )

    if fatal:
        status = "REJECTED"
    elif repairable:
        status = "REPAIRED"
    else:
        status = "PASS"

    return {
        "status": status,
        "fatal": fatal,
        "repairable": repairable,
        "info": info,
        "predicted_ue4_warnings": metrics.predicted_ue4_warnings,
        "thresholds": th,
    }


def dump_json(obj: Any, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")