"""Tests for the Blender conversion generator's geometry governance.

The defect these guard against is measured, not hypothetical: the Ingolstadt
building FBX files were exported with no UV channel and no smoothing groups,
which makes every face have a degenerate tangent basis under MikkTSpace and is
the direct cause of UE4 4.26's tangent / bi-normal / smoothing-group warnings.

Blender is not importable in unit tests, so these tests assert on the *generated
script source*, which is what actually runs in Blender. The numeric behaviour of
the UV projection is verified separately and exactly in test_mesh_quality.py
against the real production OBJ.
"""
from __future__ import annotations

import ast
import textwrap

import pytest

from ultimate_pipeline.enrichment.blender_runner import (
    CONVERSION_SCRIPT_TEMPLATE,
    BlenderRunner,
)


@pytest.fixture(scope="module")
def src() -> str:
    return CONVERSION_SCRIPT_TEMPLATE


class TestGeneratedScriptIsValidPython:
    def test_parses(self, src):
        ast.parse(src)

    def test_is_a_complete_script(self, src):
        assert "def main():" in src
        assert '__name__ == "__main__"' in src


class TestUvChannelIsGenerated:
    """UE4/MikkTSpace needs a UV channel. It must be generated, not assumed."""

    def test_defines_uv_generation(self, src):
        assert "def generate_uvs(" in src

    def test_uses_box_projection_per_face(self, src):
        # dominant-normal-axis selection, then project onto the other two axes
        assert "_UV_AXIS_PAIRS" in src
        assert "poly.normal" in src

    def test_normalizes_per_object(self, src):
        # per-object bbox normalization, not per-tile
        assert "span = [((hi[i] - lo[i]) or 1.0) for i in range(3)]" in src

    def test_creates_uv_layer_when_missing(self, src):
        assert 'mesh.uv_layers.new(name="UVMap")' in src

    def test_does_not_disable_uvs(self, src):
        assert 'mesh_smooth_type=\'OFF\'' not in src


class TestSmoothingGroupsAreExported:
    def test_exports_face_smoothing(self, src):
        assert "mesh_smooth_type='FACE'" in src

    def test_marks_sharp_edges_by_angle(self, src):
        assert "def apply_smoothing(" in src
        assert "SHARP_ANGLE_DEG" in src
        assert "sharp_edge" in src

    def test_smooths_faces_too(self, src):
        # smooth shading + hard edges is the required policy: hard wall corners
        # and wall/roof intersections, smooth coplanar surfaces
        assert "p.use_smooth = True" in src


class TestTangentsAreNotFaked:
    """Policy: never export tangents we cannot validate offline."""

    def test_tspace_stays_disabled(self, src):
        assert "use_tspace=False" in src


class TestFailClosed:
    def test_validates_before_export(self, src):
        assert "def validate_mesh(" in src

    def test_three_state_verdict(self, src):
        # The governed policy is PASS / REPAIRED / REJECTED. REPAIRED is not
        # optional: sanitize runs first, so without it an altered mesh would be
        # indistinguishable from a pristine one.
        assert 'report["gate"] = "REJECTED"' in src
        assert 'report["gate"] = "REPAIRED"' in src
        assert 'report["gate"] = "PASS"' in src

    def test_rejects_when_degeneracy_survives(self, src):
        assert "unrepairable geometry remains after sanitize" in src

    def test_escalates_heavy_deletion_to_rejected(self, src):
        # "repair" must never be allowed to silently amputate a building.
        assert "MAX_REPAIR_FRACTION" in src
        assert "repair tolerance" in src

    def test_repaired_state_is_logged(self, src):
        assert "QUALITY_REPAIRED" in src

    def test_exits_nonzero_and_writes_no_fbx(self, src):
        assert "QUALITY_GATE_FAILED" in src
        assert 'sys.exit(2)' in src
        # the gate check must precede the FBX export call
        assert src.index("QUALITY_GATE_FAILED") < src.index("export_scene.fbx(**export_options)")

    def test_aggregate_gate_precedence(self, src):
        assert 'if quality["rejected_objects"]' in src
        assert 'elif quality["repaired_objects"]' in src

    def test_records_quality_in_manifest(self, src):
        assert 'manifest["geometry_quality"] = quality' in src
        assert 'manifest["quality_policy"]' in src
        # per-object provenance, including why a gate verdict was reached
        assert '"gate_reasons"' in src


class TestSanitizeIsDeterministic:
    def test_only_unrepairable_faces_are_dropped(self, src):
        # a face is dropped only for <3 verts or zero area; slivers survive
        assert "len(f.verts) < 3 or f.calc_area() <= QUALITY_EPS_AREA" in src

    def test_dissolves_degenerate_edges(self, src):
        assert "dissolve_degenerate" in src


class TestGateIsExecutable:
    """Execute the emitted gate logic for real, without Blender.

    The three-state decision is pure arithmetic once the measurements are given,
    so it can be driven directly from the generated script. This guards the
    behaviour that a source-text assertion cannot: that a mostly-valid mesh is
    REPAIRED and an heavily-amputated one is REJECTED.
    """

    @staticmethod
    def _gate(removed, before, dissolved=0, degen_geo=0, degen_uv=0):
        ns: dict = {}
        code = CONVERSION_SCRIPT_TEMPLATE
        start = code.index("def validate_mesh(")
        end = code.index("def main():")
        body = code[start:end]
        # Re-wrap the post-measurement decision tail as a function so it can be
        # driven directly, with the mesh measurement stubbed out.
        tail = textwrap.dedent(body[body.index("    removed = report.get"):])
        wrapped = "def validate_mesh(mesh, report):\n" + textwrap.indent(tail, "    ")
        # the extracted tail reads the measurements the omitted loop would have
        # produced, so seed them as globals
        ns.update({"degen_geo": degen_geo, "degen_uv": degen_uv, "min_uv": 0.25})
        exec(  # noqa: S102 - executing our own generated code under test
            "QUALITY_EPS_AREA=1e-12\nMAX_REPAIR_FRACTION=0.02\n" + wrapped,
            ns,
        )
        report = {"faces_removed": removed, "faces_before": before,
                  "edges_before": before, "edges_after": before - dissolved}
        ns["report"] = report

        class _LT:
            def __init__(self, area):
                self.area = area
                self.loops = (0, 1, 2)

        class _UVData:
            uv = (0.0, 0.0)

        class _UVLayer:
            data = _UVData()

        tris = [_LT(1.0)] * 10 + [_LT(0.0)] * degen_geo

        class _Mesh:
            uv_layers = [_UVLayer()]
            loop_triangles = tris

            def calc_loop_triangles(self):
                pass

        ns["validate_mesh"](_Mesh(), report)
        return report["gate"]

    def test_clean_mesh_is_pass(self):
        assert self._gate(0, 100) == "PASS"

    def test_stray_degenerate_face_is_repaired(self):
        assert self._gate(1, 100) == "REPAIRED"

    def test_heavy_deletion_is_rejected(self):
        assert self._gate(10, 50) == "REJECTED"

    def test_dissolved_edges_alone_are_repaired(self):
        assert self._gate(0, 100, dissolved=3) == "REPAIRED"

    def test_surviving_degeneracy_is_rejected(self):
        assert self._gate(0, 100, degen_geo=1) == "REJECTED"


class TestHostSideRunnerUnchanged:
    """The generator fix must not disturb the host-side contract."""

    def test_writes_the_conversion_script(self, tmp_path):
        (tmp_path / "a.obj").write_text("o a\nv 0 0 0\n", encoding="utf-8")
        r = BlenderRunner(obj_path=str(tmp_path / "a.obj"),
                          output_dir=str(tmp_path / "out"),
                          blender_exe=str(tmp_path / "nope.exe"))
        (tmp_path / "out").mkdir()      # run() creates this; we call the writer directly
        path = r._write_conversion_script()
        assert path.exists()
        written = path.read_text(encoding="utf-8")
        assert written == CONVERSION_SCRIPT_TEMPLATE
        ast.parse(written)

    def test_blocked_without_blender(self, tmp_path):
        (tmp_path / "a.obj").write_text("o a\nv 0 0 0\n", encoding="utf-8")
        r = BlenderRunner(obj_path=str(tmp_path / "a.obj"),
                          output_dir=str(tmp_path / "out"),
                          blender_exe=str(tmp_path / "nope.exe"))
        res = r.run()
        assert res.status == "blocked"
        assert "Blender not available" in res.reason