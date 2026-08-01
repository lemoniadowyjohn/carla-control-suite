# -*- coding: utf-8 -*-
"""P10 O2W-BLD-001 tests: naming, OBJ validation, alignment, FBX round-trip."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.enrichment.output_artifacts import (
    artifact_name,
    assert_completeness_claim,
    cache_identity,
    classify_osm2world_output,
    measure_alignment,
    record_blender_provenance,
    validate_fbx_round_trip,
    validate_obj,
)


class TestArtifactName:
    def test_deterministic_name(self):
        name = artifact_name(map_id="ingolstadt", campaign_id="perception_v1",
                             source_hash8="b9e07465", tile_id="t_0_0", ext="fbx")
        assert name == "ingolstadt_perception_v1_b9e07465_t_0_0.fbx"

    def test_kind_suffix(self):
        name = artifact_name(map_id="m", campaign_id="c", source_hash8="01234567",
                             tile_id="t1", ext="obj", kind="terrain")
        assert name == "m_c_01234567_t1_terrain.obj"

    def test_invalid_hash_rejected(self):
        with pytest.raises(ValueError):
            artifact_name(map_id="m", campaign_id="c", source_hash8="ZZZ",
                          tile_id="t1", ext="fbx")

    def test_invalid_ext_rejected(self):
        with pytest.raises(ValueError):
            artifact_name(map_id="m", campaign_id="c", source_hash8="01234567",
                          tile_id="t1", ext=".fbx")


class TestClassification:
    def test_supplemental_when_roads_disabled(self):
        res = classify_osm2world_output({"roads": False, "terrain": False})
        assert res["classification"] == "supplemental"

    def test_complete_claim_requires_roads_and_terrain(self):
        res = classify_osm2world_output({"roads": True, "terrain": True})
        assert res["classification"] == "complete"

    def test_completeness_claim_rejected_when_disabled(self):
        res = assert_completeness_claim({"roads": False, "terrain": False},
                                        "complete road network")
        assert res["ok"] is False

    def test_completeness_claim_allowed_when_enabled(self):
        res = assert_completeness_claim({"roads": True, "terrain": True},
                                        "complete road network")
        assert res["ok"] is True


class TestCacheIdentity:
    def test_deterministic(self):
        a = cache_identity(osm_sha256="a" * 64, config_sha256="b" * 64,
                           osm2world_version="0.10.6", java_version="17",
                           runner_version="1.0", cli_args=["-q"], output_format="obj")
        b = cache_identity(osm_sha256="a" * 64, config_sha256="b" * 64,
                           osm2world_version="0.10.6", java_version="17",
                           runner_version="1.0", cli_args=["-q"], output_format="obj")
        assert a == b
        assert len(a) == 16

    def test_changes_on_any_component(self):
        a = cache_identity(osm_sha256="a" * 64, config_sha256="b" * 64,
                           osm2world_version="0.10.6", java_version="17",
                           runner_version="1.0", cli_args=["-q"], output_format="obj")
        b = cache_identity(osm_sha256="a" * 64, config_sha256="b" * 64,
                           osm2world_version="0.10.7", java_version="17",
                           runner_version="1.0", cli_args=["-q"], output_format="obj")
        assert a != b


class TestOBJValidation:
    def _write(self, tmp_path, text):
        p = tmp_path / "out.obj"
        p.write_text(text, encoding="utf-8")
        return str(p)

    def test_valid_obj(self, tmp_path):
        path = self._write(tmp_path, "o obj1\ng g1\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
        res = validate_obj(path)
        assert res["ok"] is True
        assert res["vertices"] == 3
        assert res["faces"] == 1
        assert res["objects"] == 1

    def test_nonfinite_vertex_fails(self, tmp_path):
        path = self._write(tmp_path, "v 0 0 nan\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
        res = validate_obj(path)
        assert res["ok"] is False
        assert any("non-finite" in i for i in res["issues"])

    def test_out_of_range_face_index_fails(self, tmp_path):
        path = self._write(tmp_path, "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 99\n")
        res = validate_obj(path)
        assert res["ok"] is False
        assert any("out of range" in i for i in res["issues"])

    def test_bad_face_corner_count_fails(self, tmp_path):
        path = self._write(tmp_path, "v 0 0 0\nv 1 0 0\nf 1 2\n")
        res = validate_obj(path)
        assert res["ok"] is False

    def test_missing_file_fails(self, tmp_path):
        res = validate_obj(str(tmp_path / "nope.obj"))
        assert res["ok"] is False
        assert any("missing" in i for i in res["issues"])

    def test_empty_obj_fails(self, tmp_path):
        path = self._write(tmp_path, "# nothing\n")
        res = validate_obj(path)
        assert res["ok"] is False
        assert any("no vertices" in i for i in res["issues"])


class TestAlignment:
    def _xodr(self, tmp_path, x0, y0, x1, y1):
        root = ET.Element("OpenDRIVE")
        road = ET.SubElement(root, "road", id="1")
        pv = ET.SubElement(road, "planView")
        for x, y in ((x0, y0), (x1, y1)):
            ET.SubElement(pv, "geometry", x=str(x), y=str(y), hdg="0", length="10")
        p = tmp_path / "map.xodr"
        ET.ElementTree(root).write(str(p), encoding="utf-8")
        return str(p)

    def test_aligned_bounds(self, tmp_path):
        xodr = self._xodr(tmp_path, 100.0, 200.0, 110.0, 200.0)
        objp = tmp_path / "o.obj"
        objp.write_text("v 100 200 0\nv 110 200 0\nv 105 210 0\nf 1 2 3\n", encoding="utf-8")
        res = measure_alignment(xodr, str(objp))
        assert res["ok"] is True
        assert abs(res["x_offset_m"]) < 5.0

    def test_misaligned_bounds(self, tmp_path):
        xodr = self._xodr(tmp_path, 100.0, 200.0, 110.0, 200.0)
        objp = tmp_path / "o.obj"
        objp.write_text("v 500 500 0\nv 510 500 0\nv 505 510 0\nf 1 2 3\n", encoding="utf-8")
        res = measure_alignment(xodr, str(objp))
        assert res["ok"] is False


class TestBlender:
    def test_missing_blender_blocked_not_passed(self, tmp_path):
        res = validate_fbx_round_trip("C:/nonexistent/blender.exe", "script.py",
                                      "x.fbx", out_dir=str(tmp_path))
        assert res["ok"] is False
        assert res["blocked"] is True
        assert "BLOCKED" in res["reason"] or "blender not found" in res["reason"]

    def test_provenance_record(self):
        rec = record_blender_provenance(blender_version="4.3.0",
                                        script_sha256="ab" * 32,
                                        import_options={"axis": "ZUP"},
                                        export_options={"apply_unit_scale": True},
                                        coordinate_transform={"rotation": "XYZ"},
                                        units="METERS")
        assert rec["blender_version"] == "4.3.0"
        assert rec["units"] == "METERS"
