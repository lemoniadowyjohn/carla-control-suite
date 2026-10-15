"""Unit tests for ultimate_pipeline.geometry.mesh_quality.

These tests encode the *measured* production defect so it cannot silently come
back: the Ingolstadt building FBX files were exported with no UV channel and no
smoothing groups, which makes 100% of faces have a degenerate tangent basis under
MikkTSpace and produces UE4's tangent / bi-normal / smoothing-group warnings.

They also pin the fix's core invariant: box projection of a triangle with
non-zero area always has non-zero parametric area, so generating UVs cannot
manufacture a degenerate tangent basis.
"""
from __future__ import annotations

import numpy as np
import pytest

from ultimate_pipeline.geometry.mesh_quality import (
    GATE_THRESHOLDS,
    MeshData,
    analyze_mesh,
    box_project_corner_uvs,
    corner_uv_area_stats,
    evaluate_gate,
    plan_uv_generation,
    probe_fbx_channels,
    read_obj,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _unit_quad_z(height: float = 1.0):
    """A 1x1 horizontal square at z=height: four vertices, two triangles."""
    pos = np.array([
        [0.0, 0.0, height],
        [1.0, 0.0, height],
        [1.0, 1.0, height],
        [0.0, 1.0, height],
    ])
    fcs = np.array([[0, 1, 2], [0, 2, 3]], np.int32)
    return pos, fcs


_UP_NORMALS = np.array([[0.0, 0.0, 1.0]] * 4)


def _write_obj(path, pos, faces, *, with_uv=False, with_smoothing=False,
               normals=None, name="obj1"):
    lines = [f"o {name}"]
    for v in pos:
        lines.append("v %.6f %.6f %.6f" % tuple(v))
    if normals is not None:
        for n in normals:
            lines.append("vn %.6f %.6f %.6f" % tuple(n))
    if with_uv:
        for _ in pos:
            lines.append("vt 0.0 0.0")
    if with_smoothing:
        lines.append("s 1")
    for f in faces:
        if normals is not None and with_uv:
            lines.append("f %d/%d/%d %d/%d/%d %d/%d/%d" % (
                f[0] + 1, f[0] + 1, f[0] + 1,
                f[1] + 1, f[1] + 1, f[1] + 1,
                f[2] + 1, f[2] + 1, f[2] + 1))
        elif normals is not None:
            lines.append("f %d//%d %d//%d %d//%d" % (
                f[0] + 1, f[0] + 1, f[1] + 1, f[1] + 1, f[2] + 1, f[2] + 1))
        elif with_uv:
            lines.append("f %d/%d %d/%d %d/%d" % (
                f[0] + 1, f[0] + 1, f[1] + 1, f[1] + 1, f[2] + 1, f[2] + 1))
        else:
            lines.append("f %d %d %d" % (f[0] + 1, f[1] + 1, f[2] + 1))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# OBJ parsing
# ---------------------------------------------------------------------------
class TestObjReader:
    def test_reads_positions_and_triangles(self, tmp_path):
        pos, fcs = _unit_quad_z()
        m = read_obj(_write_obj(tmp_path / "a.obj", pos, fcs))
        assert m.vertex_count == 4
        assert m.face_count == 2
        assert m.uvs is None, "no vt records were written, so there is no UV channel"

    def test_n_gons_are_triangulated_by_fan(self, tmp_path):
        pos = np.array([[0.0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0.5, 0.5, 0]])
        p = tmp_path / "n.obj"
        p.write_text("o n\n" + "".join("v %f %f %f\n" % tuple(v) for v in pos)
                     + "f 1 2 3 4 5\n", encoding="utf-8")
        m = read_obj(p)
        assert m.face_count == 3          # 5-gon -> 3 triangles

    def test_records_per_face_object_groups(self, tmp_path):
        pos = np.array([[0.0, 0, 0], [1, 0, 0], [0, 1, 0],
                        [5.0, 0, 0], [6, 0, 0], [5, 1, 0]])
        p = tmp_path / "g.obj"
        p.write_text(
            "o A\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
            "o B\nv 5 0 0\nv 6 0 0\nv 5 1 0\nf 4 5 6\n", encoding="utf-8")
        m = read_obj(p)
        assert m.face_count == 2
        assert m.face_groups is not None
        assert m.face_groups[0] != m.face_groups[1], "two objects must get distinct ids"
        assert set(m.face_groups.tolist()) == {0, 1}


# ---------------------------------------------------------------------------
# The measured production defect
# ---------------------------------------------------------------------------
class TestMissingUvIsFatal:
    """No UV channel => every face has a degenerate tangent basis under MikkTSpace.

    This is the root cause of UE4's "has degenerate tangent bases" and "has some
    nearly zero bi-normals" warnings on the Ingolstadt building FBX files.
    """

    def test_no_uv_channel_flags_every_face(self, tmp_path):
        pos, fcs = _unit_quad_z()
        m = read_obj(_write_obj(tmp_path / "a.obj", pos, fcs))
        met = analyze_mesh(m)
        assert met.has_uv_channel is False
        assert met.face_count == 2
        assert met.tangent_degenerate_faces == 2
        assert met.near_zero_binormal_faces == 2
        assert met.predicted_ue4_warnings["degenerate_tangent_bases"] == 2

    def test_gate_rejects_missing_uv(self, tmp_path):
        pos, fcs = _unit_quad_z()
        m = read_obj(_write_obj(tmp_path / "a.obj", pos, fcs))
        gate = evaluate_gate(analyze_mesh(m))
        assert gate["status"] == "REJECTED"
        assert any("UV channel" in f for f in gate["fatal"])

    def test_clean_geometry_with_uv_passes(self, tmp_path):
        """The fix's target state: valid geometry + a real UV channel."""
        pos, fcs = _unit_quad_z()
        p = _write_obj(tmp_path / "a.obj", pos, fcs, with_uv=True)
        m = read_obj(p)
        met = analyze_mesh(m)
        # vt records exist now, so the channel is present...
        assert met.has_uv_channel is True
        # ...but a UV channel whose triangles are all collapsed is still fatal.
        assert met.uv_degenerate_faces == 2
        assert evaluate_gate(met)["status"] == "REJECTED"

    def test_non_degenerate_uvs_pass(self):
        pos, fcs = _unit_quad_z()
        uv = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
        met = analyze_mesh(MeshData(name="ok", positions=pos, faces=fcs, uvs=uv,
                                    normals=_UP_NORMALS))
        assert met.has_uv_channel is True
        assert met.uv_degenerate_faces == 0
        assert met.tangent_degenerate_faces == 0
        assert evaluate_gate(met)["status"] in ("PASS", "REPAIRED")


class TestSmoothingChannel:
    def test_absent_smoothing_is_repairable_not_fatal(self):
        pos, fcs = _unit_quad_z()
        uv = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
        met = analyze_mesh(MeshData(positions=pos, faces=fcs, uvs=uv,
                                    normals=_UP_NORMALS))
        gate = evaluate_gate(met)
        assert met.has_smoothing_channel is False
        assert gate["status"] == "REPAIRED"
        assert any("smoothing" in r.lower() for r in gate["repairable"])

    def test_present_smoothing_group_counts(self):
        pos, fcs = _unit_quad_z()
        uv = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
        met = analyze_mesh(MeshData(positions=pos, faces=fcs, uvs=uv,
                                    normals=_UP_NORMALS,
                                    smoothing=np.array([0, 1])))
        assert met.has_smoothing_channel is True
        assert met.smoothing_group_count == 2
        assert evaluate_gate(met)["status"] == "PASS"


# ---------------------------------------------------------------------------
# Geometric degeneracy detection
# ---------------------------------------------------------------------------
class TestDegeneracyDetection:
    def test_repeated_vertex_index_is_degenerate(self):
        pos = np.array([[0.0, 0, 0], [1, 0, 0], [0, 1, 0]])
        met = analyze_mesh(MeshData(positions=pos, faces=np.array([[0, 1, 1]])))
        assert met.degenerate_faces == 1
        assert evaluate_gate(met)["status"] == "REJECTED"

    def test_zero_area_collinear_face(self):
        pos = np.array([[0.0, 0, 0], [1, 0, 0], [2, 0, 0]])
        met = analyze_mesh(MeshData(positions=pos, faces=np.array([[0, 1, 2]])))
        assert met.zero_area_faces == 1
        assert met.collinear_faces == 1

    def test_sliver_is_reported_not_deleted(self):
        # thin but non-zero: must be a sliver, never a fatal zero-area face.
        # area = 0.5 * 1 m * 1e-6 m = 5e-7 m^2, i.e. above zero_area_eps
        # (1e-12) and below sliver_area_eps (1e-6).
        pos = np.array([[0.0, 0, 0], [1.0, 0, 0], [0.0, 1e-6, 0]])
        met = analyze_mesh(MeshData(
            positions=pos, faces=np.array([[0, 1, 2]]),
            uvs=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]),
            normals=np.array([[0.0, 0.0, 1.0]] * 3)))
        assert met.zero_area_faces == 0
        assert met.sliver_faces == 1
        gate = evaluate_gate(met)
        assert gate["status"] == "REPAIRED"
        assert any("sliver" in r for r in gate["repairable"])

    def test_out_of_range_index_is_degenerate(self):
        pos = np.array([[0.0, 0, 0], [1, 0, 0], [0, 1, 0]])
        met = analyze_mesh(MeshData(positions=pos, faces=np.array([[0, 1, 99]])))
        assert met.degenerate_faces == 1


class TestNormalChannel:
    def test_missing_normal_channel_is_fatal(self):
        pos, fcs = _unit_quad_z()
        uv = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
        met = analyze_mesh(MeshData(positions=pos, faces=fcs, uvs=uv, normals=None))
        assert met.has_normal_channel is False
        assert evaluate_gate(met)["status"] == "REJECTED"

    def test_zero_length_normal_is_fatal(self):
        pos, fcs = _unit_quad_z()
        uv = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
        nrm = np.array([[0.0, 0, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0]])
        met = analyze_mesh(MeshData(positions=pos, faces=fcs, uvs=uv, normals=nrm))
        assert met.zero_length_normals == 4
        assert evaluate_gate(met)["status"] == "REJECTED"

    def test_unit_normals_are_clean(self):
        pos, fcs = _unit_quad_z()
        uv = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
        nrm = np.tile([0.0, 0.0, 1.0], (4, 1))
        met = analyze_mesh(MeshData(positions=pos, faces=fcs, uvs=uv, normals=nrm))
        assert met.zero_length_normals == 0
        assert met.non_unit_normals == 0


# ---------------------------------------------------------------------------
# Box projection: the fix's invariant
# ---------------------------------------------------------------------------
class TestBoxProjection:
    def test_horizontal_quad_gets_nonzero_uv_area(self):
        pos, fcs = _unit_quad_z()
        stats = corner_uv_area_stats(box_project_corner_uvs(pos, fcs))
        assert stats["degenerate_faces"] == 0
        assert stats["min_face_area"] > 0.0

    def test_vertical_wall_gets_nonzero_uv_area(self):
        pos = np.array([[0.0, 0, 0], [1.0, 0, 0], [1.0, 0, 1.0], [0.0, 0, 1.0]])
        fcs = np.array([[0, 1, 2], [0, 2, 3]])
        stats = corner_uv_area_stats(box_project_corner_uvs(pos, fcs))
        assert stats["degenerate_faces"] == 0

    def test_sloped_face_gets_nonzero_uv_area(self):
        pos = np.array([[0.0, 0, 0], [1.0, 0, 0], [0.0, 1.0, 0.5]])
        stats = corner_uv_area_stats(
            box_project_corner_uvs(pos, np.array([[0, 1, 2]])))
        assert stats["degenerate_faces"] == 0

    @pytest.mark.parametrize("seed_face", [
        np.array([[0.0, 0, 0], [1.0, 0, 0], [0.0, 1.0, 0.0]]),
        np.array([[0.0, 0, 0], [1.0, 0, 0], [0.0, 0.0, 1.0]]),
        np.array([[0.0, 0, 0], [1.0, 0, 0], [1.0, 1.0, 1.0]]),
        np.array([[0.0, 0, 0], [1.0, 0, 0], [0.0, 1.0, 1.0]]),
    ])
    def test_any_oriented_triangle_projects_to_nonzero_area(self, seed_face):
        """The invariant the whole fix rests on, across orientations."""
        for perm in ([0, 1, 2], [0, 2, 1]):
            tri = seed_face[list(perm)]
            stats = corner_uv_area_stats(
                box_project_corner_uvs(tri, np.array([[0, 1, 2]])))
            assert stats["degenerate_faces"] == 0

    def test_flat_object_does_not_divide_by_zero(self):
        pos = np.array([[0.0, 0, 0], [1.0, 0, 0], [1.0, 1.0, 0]])
        uvs = box_project_corner_uvs(pos, np.array([[0, 1, 2]]))
        assert np.all(np.isfinite(uvs))

    def test_uvs_are_normalized_to_unit_range(self):
        pos, fcs = _unit_quad_z()
        uvs = box_project_corner_uvs(pos, fcs)
        assert uvs.min() >= -1e-12
        assert uvs.max() <= 1.0 + 1e-12

    def test_per_object_normalization_beats_per_tile(self, tmp_path):
        """Per-object normalization must give small buildings a larger UV area.

        Normalizing a whole tile shrinks a small building's footprint by orders
        of magnitude, needlessly approaching MikkTSpace's degenerate threshold.
        """
        big = _unit_quad_z()[0] * 100.0
        small = _unit_quad_z()[0] + np.array([1000.0, 0.0, 0.0])
        pos = np.vstack([big, small])
        fcs = np.vstack([_unit_quad_z()[1], _unit_quad_z()[1] + 4])
        groups = np.array([0, 0, 1, 1])        # per face: two faces per square
        r = plan_uv_generation(pos, fcs, groups=groups)
        assert (r["per_object_normalization"]["min_face_area"]
                > r["per_tile_normalization"]["min_face_area"])
        assert r["eliminates_degenerate_tangent_basis"] is True


# ---------------------------------------------------------------------------
# FBX channel probe
# ---------------------------------------------------------------------------
class TestFbxProbe:
    def test_detects_absent_layers_in_binary_fbx(self, tmp_path):
        p = tmp_path / "x.fbx"
        p.write_bytes(b"Kaydara FBX Binary  \x00\x1a\x00\xe8\x1c\x00\x00"
                      + b"\x00" * 20 + b"LayerElementNormal" + b"\x00" * 40)
        probe = probe_fbx_channels(p)
        assert probe["format"] == "binary"
        assert probe["fbx_version"] == 7400
        assert probe["has_normal_layer"] is True
        assert probe["has_uv_layer"] is False
        assert probe["has_smoothing_layer"] is False

    def test_detects_present_layers(self, tmp_path):
        p = tmp_path / "y.fbx"
        p.write_bytes(b"Kaydara FBX Binary  \x00\x1a\x00\xe8\x1c\x00\x00"
                      + b"LayerElementUV" + b"LayerElementSmoothing")
        probe = probe_fbx_channels(p)
        assert probe["has_uv_layer"] is True
        assert probe["has_smoothing_layer"] is True


# ---------------------------------------------------------------------------
# Gate thresholds
# ---------------------------------------------------------------------------
class TestThresholds:
    def test_gate_threshold_overrides_are_honored(self):
        pos, fcs = _unit_quad_z()
        uv = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
        met = analyze_mesh(MeshData(positions=pos, faces=fcs, uvs=uv))
        assert evaluate_gate(met)["thresholds"]["zero_area_eps_m2"] == \
            GATE_THRESHOLDS["zero_area_eps_m2"]

    def test_empty_mesh_does_not_crash(self):
        met = analyze_mesh(MeshData(name="empty"))
        assert met.face_count == 0
        gate = evaluate_gate(met)
        assert gate["status"] == "PASS"