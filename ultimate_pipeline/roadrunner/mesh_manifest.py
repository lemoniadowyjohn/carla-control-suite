from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .exceptions import RoadRunnerContractError
from .models import SerializableContract, validate_identifier


@dataclass(frozen=True)
class BoundingBox(SerializableContract):
    min_x: float
    min_y: float
    min_z: float
    max_x: float
    max_y: float
    max_z: float

    def __post_init__(self) -> None:
        if self.min_x > self.max_x:
            raise RoadRunnerContractError("min_x must not exceed max_x")
        if self.min_y > self.max_y:
            raise RoadRunnerContractError("min_y must not exceed max_y")
        if self.min_z > self.max_z:
            raise RoadRunnerContractError("min_z must not exceed max_z")
        if not all(
            isinstance(v, (int, float)) and v == v
            for v in (self.min_x, self.min_y, self.min_z, self.max_x, self.max_y, self.max_z)
        ):
            raise RoadRunnerContractError("bounding box values must be finite numbers")


@dataclass(frozen=True)
class MaterialBinding(SerializableContract):
    material_id: str
    object_name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "material_id", validate_identifier(self.material_id, "material_id"))
        if not isinstance(self.object_name, str) or not self.object_name.strip():
            raise RoadRunnerContractError("object_name must be a non-empty string")
        object.__setattr__(self, "object_name", self.object_name.strip())


@dataclass(frozen=True)
class TextureReference(SerializableContract):
    texture_id: str
    object_name: str
    channel: str = "diffuse"

    def __post_init__(self) -> None:
        object.__setattr__(self, "texture_id", validate_identifier(self.texture_id, "texture_id"))
        if not isinstance(self.object_name, str) or not self.object_name.strip():
            raise RoadRunnerContractError("object_name must be a non-empty string")
        object.__setattr__(self, "object_name", self.object_name.strip())
        if not isinstance(self.channel, str) or not self.channel.strip():
            raise RoadRunnerContractError("channel must be a non-empty string")
        object.__setattr__(self, "channel", self.channel.strip())


@dataclass(frozen=True)
class MeshObjectManifest(SerializableContract):
    object_id: str
    name: str
    bounding_box: BoundingBox
    triangle_count: int
    vertex_count: int
    material_bindings: tuple[MaterialBinding, ...] = ()
    texture_references: tuple[TextureReference, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "object_id", validate_identifier(self.object_id, "object_id"))
        if not isinstance(self.name, str) or not self.name.strip():
            raise RoadRunnerContractError("name must be a non-empty string")
        object.__setattr__(self, "name", self.name.strip())
        if self.triangle_count < 0:
            raise RoadRunnerContractError("triangle_count must be non-negative")
        if self.vertex_count < 0:
            raise RoadRunnerContractError("vertex_count must be non-negative")
        object.__setattr__(self, "material_bindings", tuple(self.material_bindings))
        object.__setattr__(self, "texture_references", tuple(self.texture_references))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class MeshManifest(SerializableContract):
    manifest_id: str
    objects: tuple[MeshObjectManifest, ...]
    total_triangles: int = 0
    total_vertices: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest_id", validate_identifier(self.manifest_id, "manifest_id"))
        object.__setattr__(self, "objects", tuple(self.objects))
        if not self.objects:
            raise RoadRunnerContractError("mesh manifest must include at least one object")
        if self.total_triangles < 0:
            raise RoadRunnerContractError("total_triangles must be non-negative")
        if self.total_vertices < 0:
            raise RoadRunnerContractError("total_vertices must be non-negative")


__all__ = [
    "BoundingBox",
    "MaterialBinding",
    "TextureReference",
    "MeshObjectManifest",
    "MeshManifest",
]
