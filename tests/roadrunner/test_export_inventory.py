from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from ultimate_pipeline.roadrunner import (
    ExportInventory,
    FBXFileRecord,
    LODLevel,
    MaterialDef,
    SemanticGroup,
    TextureRef,
)
from ultimate_pipeline.roadrunner.exceptions import RoadRunnerContractError


class TestTextureRef:
    def test_valid_texture(self) -> None:
        t = TextureRef(texture_id="tex-01", path="/tex/albedo.png", width=1024, height=512)
        assert t.texture_id == "tex-01"
        assert t.width == 1024
        assert t.height == 512

    def test_rejects_negative_dimensions(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="width"):
            TextureRef(texture_id="tex-bad", path="/tex/bad.png", width=-1, height=0)

    def test_rejects_empty_path(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="non-empty"):
            TextureRef(texture_id="tex-empty", path="  ", width=0, height=0)


class TestMaterialDef:
    def test_valid_material(self) -> None:
        mat = MaterialDef(material_id="mat-01", name="asphalt")
        assert mat.material_id == "mat-01"

    def test_rejects_empty_name(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="non-empty"):
            MaterialDef(material_id="mat-bad", name="")

    def test_with_textures(self) -> None:
        tex = TextureRef(texture_id="t1", path="/t.png", width=256, height=256)
        mat = MaterialDef(material_id="mat-tex", name="textured", textures=(tex,))
        assert len(mat.textures) == 1


class TestLODLevel:
    def test_valid_lod(self) -> None:
        lod = LODLevel(level=0, triangle_count=1000, vertex_count=500)
        assert lod.level == 0
        assert lod.triangle_count == 1000

    def test_rejects_negative(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="non-negative"):
            LODLevel(level=0, triangle_count=-1, vertex_count=0)


class TestSemanticGroup:
    def test_valid_group(self) -> None:
        g = SemanticGroup(group_id="roads", object_count=10, label="road surface")
        assert g.group_id == "roads"
        assert g.object_count == 10

    def test_rejects_negative_count(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="object_count"):
            SemanticGroup(group_id="bad", object_count=-1)


class TestFBXFileRecord:
    def test_valid_record(self) -> None:
        rec = FBXFileRecord(file_id="fbx-01", path="/out/tile_0_0.fbx", tile_x=0, tile_y=0, file_size_bytes=2048)
        assert rec.file_id == "fbx-01"
        assert rec.tile_x == 0

    def test_rejects_negative_size(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="file_size_bytes"):
            FBXFileRecord(file_id="fbx-bad", path="/out/bad.fbx", file_size_bytes=-1)

    def test_rejects_empty_path(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="non-empty"):
            FBXFileRecord(file_id="fbx-empty", path="", file_size_bytes=0)


class TestExportInventory:
    def test_valid_inventory(self) -> None:
        fbx = FBXFileRecord(file_id="fbx-01", path="/out/tile.fbx", file_size_bytes=1024)
        inv = ExportInventory(
            export_id="exp-001",
            fbx_files=(fbx,),
            tile_grid_cols=2,
            tile_grid_rows=2,
            has_materials=True,
        )
        assert inv.export_id == "exp-001"
        assert inv.tile_grid_cols == 2
        assert len(inv.fbx_files) == 1

    def test_rejects_empty_fbx_files(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="at least one"):
            ExportInventory(export_id="exp-empty", fbx_files=())

    def test_rejects_invalid_grid(self) -> None:
        fbx = FBXFileRecord(file_id="fbx-01", path="/out/t.fbx", file_size_bytes=100)
        with pytest.raises(RoadRunnerContractError, match="tile_grid"):
            ExportInventory(export_id="exp-bad", fbx_files=(fbx,), tile_grid_cols=0)

    def test_material_and_texture_flags(self) -> None:
        fbx = FBXFileRecord(file_id="fbx-01", path="/out/t.fbx", file_size_bytes=100)
        inv = ExportInventory(
            export_id="exp-flags",
            fbx_files=(fbx,),
            has_materials=True,
            has_textures=True,
        )
        assert inv.has_materials is True
        assert inv.has_textures is True

    def test_lod_and_semantic_groups(self) -> None:
        lod = LODLevel(level=0, triangle_count=500, vertex_count=250)
        group = SemanticGroup(group_id="buildings", object_count=5)
        fbx = FBXFileRecord(
            file_id="fbx-lod",
            path="/out/lod.fbx",
            file_size_bytes=500,
            lod_levels=(lod,),
            semantic_groups=(group,),
        )
        inv = ExportInventory(export_id="exp-lod", fbx_files=(fbx,))
        assert len(inv.fbx_files[0].lod_levels) == 1
        assert inv.fbx_files[0].semantic_groups[0].group_id == "buildings"
