"""Mesh manifest validation for RoadRunner visual builds.

Provides typed dataclasses and validators for mesh-level metadata:
vertex and face counts, bounding boxes, units, axis convention,
material count, texture references, semantic group assignments,
collision intent, and LOD inventory.  Operates without importing
mesh file parsers; metadata is supplied as structured input.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .exceptions import RoadRunnerContractError
from .models import SerializableContract, deterministic_json, utc_now_iso, validate_identifier


def _finite(value: float, label: str) -> float:
    if not math.isfinite(value):
        raise RoadRunnerContractError(f"{label} must be finite, got {value}")
    return value


def _non_negative_int(value: int, label: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise RoadRunnerContractError(f"{label} must be a non-negative integer, got {value}")
    return value


@dataclass(frozen=True)
class MeshObjectRecord:
    """Metadata for a single mesh object in the export."""

    object_name: str
    vertex_count: int = 0
    face_count: int = 0
    material_names: tuple[str, ...] = ()
    semantic_group: str | None = None
    lod_level: int = 0
    collision_enabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "object_name", validate_identifier(self.object_name, "object_name"))
        _non_negative_int(self.vertex_count, "vertex_count")
        _non_negative_int(self.face_count, "face_count")
        object.__setattr__(self, "material_names", tuple(self.material_names))
        if self.semantic_group is not None:
            object.__setattr__(self, "semantic_group", validate_identifier(self.semantic_group, "semantic_group"))
        if self.lod_level < 0:
            raise RoadRunnerContractError(f"lod_level must be non-negative, got {self.lod_level}")


@dataclass(frozen=True)
class MeshBoundingBox:
    """Axis-aligned bounding box for a mesh object."""

    min_x: float
    min_y: float
    min_z: float
    max_x: float
    max_y: float
    max_z: float

    def __post_init__(self) -> None:
        for name in ("min_x", "min_y", "min_z", "max_x", "max_y", "max_z"):
            _finite(getattr(self, name), name)
        if self.min_x > self.max_x or self.min_y > self.max_y or self.min_z > self.max_z:
            raise RoadRunnerContractError(
                f"bounding box min must be <= max: "
                f"({self.min_x},{self.min_y},{self.min_z}) -> ({self.max_x},{self.max_y},{self.max_z})"
            )


@dataclass(frozen=True)
class TextureReference:
    """Reference to a texture file used by a material."""

    texture_name: str
    file_path: str | None = None
    resolution_x: int = 0
    resolution_y: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "texture_name", validate_identifier(self.texture_name, "texture_name"))
        if self.file_path is not None:
            if not isinstance(self.file_path, str) or not self.file_path.strip():
                raise RoadRunnerContractError("texture file_path must be a non-empty string")
        if self.resolution_x < 0 or self.resolution_y < 0:
            raise RoadRunnerContractError("texture resolution must be non-negative")


@dataclass(frozen=True)
class MaterialManifest:
    """Material manifest entry with texture references."""

    material_name: str
    texture_refs: tuple[TextureReference, ...] = ()
    is_road_surface: bool = False
    double_sided: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "material_name", validate_identifier(self.material_name, "material_name"))
        object.__setattr__(self, "texture_refs", tuple(self.texture_refs))


@dataclass(frozen=True)
class SemanticGroupManifest:
    """Semantic group manifest with object count and collision intent."""

    group_name: str
    object_count: int = 0
    collision_enabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "group_name", validate_identifier(self.group_name, "group_name"))
        _non_negative_int(self.object_count, "object_count")


@dataclass(frozen=True)
class LodLevelManifest:
    """LOD level manifest."""

    lod_level: int
    mesh_count: int = 0
    total_vertices: int = 0
    total_faces: int = 0

    def __post_init__(self) -> None:
        _non_negative_int(self.mesh_count, "mesh_count")
        _non_negative_int(self.total_vertices, "total_vertices")
        _non_negative_int(self.total_faces, "total_faces")


@dataclass(frozen=True)
class MeshManifest(SerializableContract):
    """Complete mesh manifest for a RoadRunner visual build.

    Captures per-object mesh statistics, material assignments, texture
    references, semantic groups, collision intent, and LOD inventory.
    """

    manifest_id: str
    mesh_source_sha256: str
    total_vertices: int = 0
    total_faces: int = 0
    mesh_object_count: int = 0
    units: str = "meters"
    axis_convention: str = "Y_UP"
    bounding_box: MeshBoundingBox | None = None
    objects: tuple[MeshObjectRecord, ...] = ()
    materials: tuple[MaterialManifest, ...] = ()
    semantic_groups: tuple[SemanticGroupManifest, ...] = ()
    lod_levels: tuple[LodLevelManifest, ...] = ()
    generated_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        from .models import validate_sha256

        object.__setattr__(self, "manifest_id", validate_identifier(self.manifest_id, "manifest_id"))
        object.__setattr__(self, "mesh_source_sha256", validate_sha256(self.mesh_source_sha256, "mesh_source_sha256"))
        _non_negative_int(self.total_vertices, "total_vertices")
        _non_negative_int(self.total_faces, "total_faces")
        _non_negative_int(self.mesh_object_count, "mesh_object_count")
        object.__setattr__(self, "objects", tuple(self.objects))
        object.__setattr__(self, "materials", tuple(self.materials))
        object.__setattr__(self, "semantic_groups", tuple(self.semantic_groups))
        object.__setattr__(self, "lod_levels", tuple(self.lod_levels))


def validate_mesh_object_counts(manifest: MeshManifest) -> tuple[str, ...]:
    """Validate mesh object counts are consistent with declared totals."""
    errors: list[str] = []
    if manifest.mesh_object_count == 0:
        errors.append("mesh_object_count is zero: manifest has no mesh objects")
    if manifest.total_vertices == 0 and manifest.mesh_object_count > 0:
        errors.append("total_vertices is zero despite having mesh objects")
    if manifest.total_faces == 0 and manifest.mesh_object_count > 0:
        errors.append("total_faces is zero despite having mesh objects")
    if manifest.objects:
        counted_vertices = sum(obj.vertex_count for obj in manifest.objects)
        counted_faces = sum(obj.face_count for obj in manifest.objects)
        if counted_vertices != manifest.total_vertices:
            errors.append(
                f"sum of object vertices ({counted_vertices}) != total_vertices ({manifest.total_vertices})"
            )
        if counted_faces != manifest.total_faces:
            errors.append(
                f"sum of object faces ({counted_faces}) != total_faces ({manifest.total_faces})"
            )
        if len(manifest.objects) != manifest.mesh_object_count:
            errors.append(
                f"object tuple length ({len(manifest.objects)}) != mesh_object_count ({manifest.mesh_object_count})"
            )
    return tuple(errors)


def validate_mesh_bounding_box(manifest: MeshManifest) -> tuple[str, ...]:
    """Validate bounding box is present and coordinates are finite and ordered."""
    errors: list[str] = []
    if manifest.bounding_box is None:
        errors.append("no bounding box declared in mesh manifest")
        return tuple(errors)
    bb = manifest.bounding_box
    for coord_name in ("min_x", "min_y", "min_z", "max_x", "max_y", "max_z"):
        val = getattr(bb, coord_name)
        if not math.isfinite(val):
            errors.append(f"bounding box {coord_name} is not finite: {val}")
    if bb.min_x > bb.max_x:
        errors.append(f"bounding box min_x ({bb.min_x}) > max_x ({bb.max_x})")
    if bb.min_y > bb.max_y:
        errors.append(f"bounding box min_y ({bb.min_y}) > max_y ({bb.max_y})")
    if bb.min_z > bb.max_z:
        errors.append(f"bounding box min_z ({bb.min_z}) > max_z ({bb.max_z})")
    return tuple(errors)


def validate_mesh_units_and_axes(manifest: MeshManifest) -> tuple[str, ...]:
    """Validate units and axis convention are recognized."""
    from .export_inventory import KNOWN_AXIS_CONVENTIONS, KNOWN_UNITS

    errors: list[str] = []
    if manifest.units not in KNOWN_UNITS:
        errors.append(f"unknown units: {manifest.units!r}")
    if manifest.axis_convention not in KNOWN_AXIS_CONVENTIONS:
        errors.append(f"unknown axis_convention: {manifest.axis_convention!r}")
    return tuple(errors)


def validate_mesh_materials(manifest: MeshManifest) -> tuple[str, ...]:
    """Validate material count and texture references."""
    errors: list[str] = []
    if not manifest.materials:
        errors.append("no materials declared in mesh manifest")
    for mat in manifest.materials:
        for tex in mat.texture_refs:
            if not isinstance(tex.texture_name, str) or not tex.texture_name.strip():
                errors.append(f"empty texture name in material {mat.material_name}")
    return tuple(errors)


def validate_mesh_semantic_groups(manifest: MeshManifest) -> tuple[str, ...]:
    """Validate semantic groups include required classes."""
    from .export_inventory import REQUIRED_SEMANTIC_CLASSES

    errors: list[str] = []
    if not manifest.semantic_groups:
        errors.append("no semantic groups declared in mesh manifest")
        return tuple(errors)
    present = {sg.group_name.lower() for sg in manifest.semantic_groups}
    for required in REQUIRED_SEMANTIC_CLASSES:
        if required.lower() not in present:
            errors.append(f"missing required semantic class: {required}")
    return tuple(errors)


def validate_mesh_collision_intent(manifest: MeshManifest) -> tuple[str, ...]:
    """Validate collision intent for semantic groups."""
    errors: list[str] = []
    for sg in manifest.semantic_groups:
        if sg.group_name.lower() == "road" and not sg.collision_enabled:
            errors.append("Road semantic group must have collision_enabled=True")
    return tuple(errors)


def validate_mesh_lod_inventory(manifest: MeshManifest) -> tuple[str, ...]:
    """Validate LOD inventory has at least level 0."""
    errors: list[str] = []
    if not manifest.lod_levels:
        errors.append("no LOD levels declared in mesh manifest")
    levels = {entry.lod_level for entry in manifest.lod_levels}
    if 0 not in levels and manifest.lod_levels:
        errors.append("LOD level 0 (highest detail) is missing")
    return tuple(errors)


def validate_mesh_per_object(manifest: MeshManifest) -> tuple[str, ...]:
    """Validate per-object mesh metadata: finite vertices/faces, valid LOD."""
    errors: list[str] = []
    for obj in manifest.objects:
        if obj.vertex_count == 0 and obj.face_count == 0:
            errors.append(f"object {obj.object_name}: both vertex_count and face_count are zero")
        if obj.lod_level < 0:
            errors.append(f"object {obj.object_name}: lod_level is negative ({obj.lod_level})")
    return tuple(errors)


def validate_mesh_manifest(manifest: MeshManifest) -> tuple[str, ...]:
    """Run all mesh manifest validation checks and return collected errors."""
    all_errors: list[str] = []
    all_errors.extend(validate_mesh_object_counts(manifest))
    all_errors.extend(validate_mesh_bounding_box(manifest))
    all_errors.extend(validate_mesh_units_and_axes(manifest))
    all_errors.extend(validate_mesh_materials(manifest))
    all_errors.extend(validate_mesh_semantic_groups(manifest))
    all_errors.extend(validate_mesh_collision_intent(manifest))
    all_errors.extend(validate_mesh_lod_inventory(manifest))
    all_errors.extend(validate_mesh_per_object(manifest))
    return tuple(all_errors)


@dataclass(frozen=True)
class MeshManifestValidation:
    """Result of validating a MeshManifest."""

    manifest_id: str
    valid: bool
    errors: tuple[str, ...]
    validated_at: str = field(default_factory=utc_now_iso)


def validate_mesh_manifest_result(manifest: MeshManifest) -> MeshManifestValidation:
    """Run all mesh manifest checks and return a structured result."""
    errors = validate_mesh_manifest(manifest)
    return MeshManifestValidation(
        manifest_id=manifest.manifest_id,
        valid=len(errors) == 0,
        errors=errors,
    )


__all__ = [
    "LodLevelManifest",
    "MaterialManifest",
    "MeshBoundingBox",
    "MeshManifest",
    "MeshManifestValidation",
    "MeshObjectRecord",
    "SemanticGroupManifest",
    "TextureReference",
    "validate_mesh_bounding_box",
    "validate_mesh_collision_intent",
    "validate_mesh_lod_inventory",
    "validate_mesh_manifest",
    "validate_mesh_manifest_result",
    "validate_mesh_materials",
    "validate_mesh_object_counts",
    "validate_mesh_per_object",
    "validate_mesh_semantic_groups",
    "validate_mesh_units_and_axes",
]
