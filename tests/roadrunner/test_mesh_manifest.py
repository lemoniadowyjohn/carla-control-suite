from __future__ import annotations

import pytest

from ultimate_pipeline.roadrunner import (
    BoundingBox,
    MaterialBinding,
    MeshManifest,
    MeshObjectManifest,
    TextureReference,
)
from ultimate_pipeline.roadrunner.exceptions import RoadRunnerContractError


class TestBoundingBox:
    def test_valid_bbox(self) -> None:
        b = BoundingBox(min_x=0, min_y=0, min_z=0, max_x=10, max_y=20, max_z=5)
        assert b.min_x == 0
        assert b.max_x == 10

    def test_rejects_swapped_axes(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="min_x"):
            BoundingBox(min_x=10, min_y=0, min_z=0, max_x=0, max_y=20, max_z=5)

    def test_rejects_nan(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="finite"):
            BoundingBox(min_x=0, min_y=0, min_z=0, max_x=float("nan"), max_y=20, max_z=5)


class TestMaterialBinding:
    def test_valid_binding(self) -> None:
        mb = MaterialBinding(material_id="mat-01", object_name="road_segment_01")
        assert mb.material_id == "mat-01"

    def test_rejects_empty_name(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="non-empty"):
            MaterialBinding(material_id="mat-bad", object_name="")


class TestTextureReference:
    def test_valid_ref(self) -> None:
        tr = TextureReference(texture_id="tex-01", object_name="road_seg", channel="diffuse")
        assert tr.texture_id == "tex-01"
        assert tr.channel == "diffuse"

    def test_default_channel(self) -> None:
        tr = TextureReference(texture_id="tex-01", object_name="road_seg", channel="diffuse")
        assert tr.channel == "diffuse"

    def test_rejects_empty_channel(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="non-empty"):
            TextureReference(texture_id="tex-bad", object_name="obj", channel="")


class TestMeshObjectManifest:
    def test_valid_object(self) -> None:
        bbox = BoundingBox(min_x=0, min_y=0, min_z=0, max_x=5, max_y=5, max_z=3)
        obj = MeshObjectManifest(
            object_id="obj-01",
            name="road_segment_A",
            bounding_box=bbox,
            triangle_count=1200,
            vertex_count=600,
        )
        assert obj.object_id == "obj-01"
        assert obj.triangle_count == 1200

    def test_rejects_negative_counts(self) -> None:
        bbox = BoundingBox(min_x=0, min_y=0, min_z=0, max_x=1, max_y=1, max_z=1)
        with pytest.raises(RoadRunnerContractError, match="triangle_count"):
            MeshObjectManifest(
                object_id="obj-bad",
                name="bad",
                bounding_box=bbox,
                triangle_count=-1,
                vertex_count=0,
            )

    def test_with_bindings_and_textures(self) -> None:
        bbox = BoundingBox(min_x=0, min_y=0, min_z=0, max_x=2, max_y=2, max_z=1)
        mb = MaterialBinding(material_id="mat-01", object_name="obj_a")
        tr = TextureReference(texture_id="tex-01", object_name="obj_a", channel="normal")
        obj = MeshObjectManifest(
            object_id="obj-tex",
            name="textured_road",
            bounding_box=bbox,
            triangle_count=500,
            vertex_count=250,
            material_bindings=(mb,),
            texture_references=(tr,),
        )
        assert len(obj.material_bindings) == 1
        assert len(obj.texture_references) == 1


class TestMeshManifest:
    def test_valid_manifest(self) -> None:
        bbox = BoundingBox(min_x=0, min_y=0, min_z=0, max_x=1, max_y=1, max_z=1)
        obj = MeshObjectManifest(
            object_id="obj-01",
            name="road_seg",
            bounding_box=bbox,
            triangle_count=100,
            vertex_count=50,
        )
        manifest = MeshManifest(
            manifest_id="manifest-001",
            objects=(obj,),
            total_triangles=100,
            total_vertices=50,
        )
        assert manifest.manifest_id == "manifest-001"

    def test_rejects_empty_objects(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="at least one"):
            MeshManifest(manifest_id="empty", objects=())

    def test_rejects_negative_totals(self) -> None:
        bbox = BoundingBox(min_x=0, min_y=0, min_z=0, max_x=1, max_y=1, max_z=1)
        obj = MeshObjectManifest(
            object_id="obj-01",
            name="seg",
            bounding_box=bbox,
            triangle_count=10,
            vertex_count=5,
        )
        with pytest.raises(RoadRunnerContractError, match="total_triangles"):
            MeshManifest(
                manifest_id="bad-total",
                objects=(obj,),
                total_triangles=-1,
                total_vertices=0,
            )
