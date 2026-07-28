from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .exceptions import RoadRunnerContractError
from .models import SerializableContract, validate_identifier


@dataclass(frozen=True)
class TextureRef(SerializableContract):
    texture_id: str
    path: str
    width: int = 0
    height: int = 0
    format: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "texture_id", validate_identifier(self.texture_id, "texture_id"))
        if not isinstance(self.path, str) or not self.path.strip():
            raise RoadRunnerContractError("texture path must be a non-empty string")
        if self.width < 0:
            raise RoadRunnerContractError("texture width must be non-negative")
        if self.height < 0:
            raise RoadRunnerContractError("texture height must be non-negative")
        object.__setattr__(self, "path", self.path.strip())


@dataclass(frozen=True)
class MaterialDef(SerializableContract):
    material_id: str
    name: str
    textures: tuple[TextureRef, ...] = ()
    properties: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "material_id", validate_identifier(self.material_id, "material_id"))
        if not isinstance(self.name, str) or not self.name.strip():
            raise RoadRunnerContractError("material name must be a non-empty string")
        object.__setattr__(self, "textures", tuple(self.textures))
        object.__setattr__(self, "properties", dict(self.properties))


@dataclass(frozen=True)
class LODLevel(SerializableContract):
    level: int
    triangle_count: int
    vertex_count: int

    def __post_init__(self) -> None:
        if self.level < 0:
            raise RoadRunnerContractError("LOD level must be non-negative")
        if self.triangle_count < 0:
            raise RoadRunnerContractError("triangle_count must be non-negative")
        if self.vertex_count < 0:
            raise RoadRunnerContractError("vertex_count must be non-negative")


@dataclass(frozen=True)
class SemanticGroup(SerializableContract):
    group_id: str
    object_count: int
    label: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "group_id", validate_identifier(self.group_id, "group_id"))
        if self.object_count < 0:
            raise RoadRunnerContractError("object_count must be non-negative")
        object.__setattr__(self, "label", self.label.strip() if isinstance(self.label, str) else "")
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class FBXFileRecord(SerializableContract):
    file_id: str
    path: str
    tile_x: int | None = None
    tile_y: int | None = None
    file_size_bytes: int = 0
    sha256: str | None = None
    materials: tuple[MaterialDef, ...] = ()
    lod_levels: tuple[LODLevel, ...] = ()
    semantic_groups: tuple[SemanticGroup, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "file_id", validate_identifier(self.file_id, "file_id"))
        if not isinstance(self.path, str) or not self.path.strip():
            raise RoadRunnerContractError("FBX path must be a non-empty string")
        object.__setattr__(self, "path", self.path.strip().replace("\\", "/"))
        if self.file_size_bytes < 0:
            raise RoadRunnerContractError("file_size_bytes must be non-negative")
        if self.sha256 is not None:
            from .models import validate_sha256
            object.__setattr__(self, "sha256", validate_sha256(self.sha256))
        object.__setattr__(self, "materials", tuple(self.materials))
        object.__setattr__(self, "lod_levels", tuple(self.lod_levels))
        object.__setattr__(self, "semantic_groups", tuple(self.semantic_groups))


@dataclass(frozen=True)
class ExportInventory(SerializableContract):
    export_id: str
    fbx_files: tuple[FBXFileRecord, ...]
    tile_grid_cols: int = 1
    tile_grid_rows: int = 1
    has_materials: bool = False
    has_textures: bool = False
    total_file_size_bytes: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "export_id", validate_identifier(self.export_id, "export_id"))
        object.__setattr__(self, "fbx_files", tuple(self.fbx_files))
        if not self.fbx_files:
            raise RoadRunnerContractError("export inventory must include at least one FBX file record")
        if self.tile_grid_cols < 1:
            raise RoadRunnerContractError("tile_grid_cols must be at least 1")
        if self.tile_grid_rows < 1:
            raise RoadRunnerContractError("tile_grid_rows must be at least 1")
        if self.total_file_size_bytes < 0:
            raise RoadRunnerContractError("total_file_size_bytes must be non-negative")


__all__ = [
    "TextureRef",
    "MaterialDef",
    "LODLevel",
    "SemanticGroup",
    "FBXFileRecord",
    "ExportInventory",
]
