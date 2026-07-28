"""Export inventory validation for RoadRunner/FBX/Datasmith/tiled outputs.

Validates expected files, SHA-256 digests, matching base names, object/mesh
counts, finite coordinates, bounding boxes, units, axis convention, origin
and CRS transform, vertical range, material count, texture references,
semantic groups, collision intent, LOD inventory, tile names and grid
positions, no duplicate road surface, no missing Road/RoadLines/Sidewalk/
Terrain class, package JSON, and one XODR authority.

FBX existence alone does not prove CARLA readiness.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .exceptions import RoadRunnerContractError
from .models import (
    SerializableContract,
    deterministic_json,
    utc_now_iso,
    validate_identifier,
    validate_sha256,
)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_SEMANTIC_CLASSES = ("Road", "RoadLines", "Sidewalk", "Terrain")

KNOWN_AXIS_CONVENTIONS = ("Y_UP", "Z_UP", "UNREAL_Y_FORWARD")

KNOWN_UNITS = ("centimeters", "meters", "millimeters")

_EXPECTED_XODR_EXTENSIONS = (".xodr",)
_EXPECTED_FBX_EXTENSIONS = (".fbx",)
_EXPECTED_DATASMITH_EXTENSIONS = (".udatasmith",)

DEFAULT_TOLERANCE = 1e-9


def _finite(value: float, label: str) -> float:
    if not math.isfinite(value):
        raise RoadRunnerContractError(f"{label} must be finite, got {value}")
    return value


def _positive(value: float, label: str) -> float:
    _finite(value, label)
    if value <= 0:
        raise RoadRunnerContractError(f"{label} must be positive, got {value}")
    return value


def _non_negative(value: float, label: str) -> float:
    _finite(value, label)
    if value < 0:
        raise RoadRunnerContractError(f"{label} must be non-negative, got {value}")
    return value


def _non_negative_int(value: int, label: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise RoadRunnerContractError(f"{label} must be a non-negative integer, got {value}")
    return value


@dataclass(frozen=True)
class FileRecord:
    """One expected file in the export inventory."""

    rel_path: str
    sha256: str
    size_bytes: int = 0
    media_type: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "sha256", validate_sha256(self.sha256, "sha256"))
        _non_negative_int(self.size_bytes, "size_bytes")
        if not isinstance(self.rel_path, str) or not self.rel_path.strip():
            raise RoadRunnerContractError("rel_path must be a non-empty string")
        normalized = self.rel_path.strip().replace("\\", "/")
        object.__setattr__(self, "rel_path", normalized)


@dataclass(frozen=True)
class BoundingBox:
    """Axis-aligned bounding box in meters."""

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
class TileRecord:
    """Record for a single tile in a tiled export."""

    tile_name: str
    grid_col: int
    grid_row: int
    origin_x: float = 0.0
    origin_y: float = 0.0
    origin_z: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "tile_name", validate_identifier(self.tile_name, "tile_name"))
        _finite(self.origin_x, "origin_x")
        _finite(self.origin_y, "origin_y")
        _finite(self.origin_z, "origin_z")


@dataclass(frozen=True)
class MaterialRecord:
    """Material metadata entry."""

    material_name: str
    texture_refs: tuple[str, ...] = ()
    is_road_surface: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "material_name", validate_identifier(self.material_name, "material_name"))


@dataclass(frozen=True)
class SemanticGroupRecord:
    """Semantic group assignment."""

    group_name: str
    object_count: int = 0
    collision_enabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "group_name", validate_identifier(self.group_name, "group_name"))
        _non_negative_int(self.object_count, "object_count")


@dataclass(frozen=True)
class LodEntry:
    """LOD level inventory entry."""

    lod_level: int
    mesh_count: int = 0
    triangle_count: int = 0

    def __post_init__(self) -> None:
        _non_negative_int(self.mesh_count, "mesh_count")
        _non_negative_int(self.triangle_count, "triangle_count")


@dataclass(frozen=True)
class MeshStats:
    """Mesh statistics snapshot."""

    total_vertices: int = 0
    total_faces: int = 0
    mesh_count: int = 0
    object_count: int = 0

    def __post_init__(self) -> None:
        _non_negative_int(self.total_vertices, "total_vertices")
        _non_negative_int(self.total_faces, "total_faces")
        _non_negative_int(self.mesh_count, "mesh_count")
        _non_negative_int(self.object_count, "object_count")


@dataclass(frozen=True)
class ExportInventory(SerializableContract):
    """Full export inventory for a RoadRunner visual build.

    Validates file presence, hashes, base names, object/mesh counts, finite
    coordinates, bounding boxes, units, axis convention, origin and CRS
    transform, vertical range, material and texture counts, semantic groups,
    collision intent, LOD inventory, tile grid, and XODR authority count.
    """

    export_id: str
    source_xodr_sha256: str
    expected_files: tuple[FileRecord, ...]
    base_name: str
    units: str = "meters"
    axis_convention: str = "Y_UP"
    origin_x: float = 0.0
    origin_y: float = 0.0
    origin_z: float = 0.0
    crs_epsg: str | None = None
    crs_wkt: str | None = None
    vertical_min: float = -10.0
    vertical_max: float = 200.0
    bounding_box: BoundingBox | None = None
    mesh_stats: MeshStats = field(default_factory=MeshStats)
    materials: tuple[MaterialRecord, ...] = ()
    semantic_groups: tuple[SemanticGroupRecord, ...] = ()
    lod_entries: tuple[LodEntry, ...] = ()
    tiles: tuple[TileRecord, ...] = ()
    package_json_path: str | None = None
    generated_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        object.__setattr__(self, "export_id", validate_identifier(self.export_id, "export_id"))
        object.__setattr__(self, "source_xodr_sha256", validate_sha256(self.source_xodr_sha256, "source_xodr_sha256"))
        if not isinstance(self.base_name, str) or not self.base_name.strip():
            raise RoadRunnerContractError("base_name must be a non-empty string")
        _reject_invalid_unit(self.units)
        _reject_invalid_axis(self.axis_convention)
        _finite(self.origin_x, "origin_x")
        _finite(self.origin_y, "origin_y")
        _finite(self.origin_z, "origin_z")
        _finite(self.vertical_min, "vertical_min")
        _finite(self.vertical_max, "vertical_max")
        if self.vertical_min >= self.vertical_max:
            raise RoadRunnerContractError(
                f"vertical_min ({self.vertical_min}) must be < vertical_max ({self.vertical_max})"
            )
        if self.bounding_box is not None:
            _finite(self.bounding_box.min_x, "bounding_box.min_x")
        if self.package_json_path is not None:
            _reject_placeholder(self.package_json_path.strip(), "package_json_path")
        object.__setattr__(self, "materials", tuple(self.materials))
        object.__setattr__(self, "semantic_groups", tuple(self.semantic_groups))
        object.__setattr__(self, "lod_entries", tuple(self.lod_entries))
        object.__setattr__(self, "tiles", tuple(self.tiles))


def _reject_placeholder(value: str, field_name: str) -> None:
    normalized = value.strip().lower()
    if normalized in ("", "placeholder", "todo", "tbd", "unknown", "none", "changeme"):
        raise RoadRunnerContractError(f"{field_name} cannot be a placeholder value")


def _reject_invalid_unit(unit: str) -> None:
    if unit not in KNOWN_UNITS:
        raise RoadRunnerContractError(f"units must be one of {KNOWN_UNITS}, got {unit!r}")


def _reject_invalid_axis(axis: str) -> None:
    if axis not in KNOWN_AXIS_CONVENTIONS:
        raise RoadRunnerContractError(f"axis_convention must be one of {KNOWN_AXIS_CONVENTIONS}, got {axis!r}")


def _extract_base_name(rel_path: str) -> str:
    stem = Path(rel_path).stem
    for suffix in (".mesh", ".obj", ".fbx", ".datasmith", ".bin", ".json", ".xml", ".xodr"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
    return stem


def validate_expected_files(inventory: ExportInventory) -> tuple[str, ...]:
    """Return error messages for missing expected files."""
    errors: list[str] = []
    for record in inventory.expected_files:
        candidate = Path(inventory.export_id) / record.rel_path
        if not candidate.is_file():
            errors.append(f"expected file not found: {record.rel_path}")
    return tuple(errors)


def validate_file_hashes(export_dir: Path, inventory: ExportInventory) -> tuple[str, ...]:
    """Verify SHA-256 digests of exported files against the inventory."""
    import hashlib

    errors: list[str] = []
    for record in inventory.expected_files:
        candidate = export_dir / record.rel_path
        if not candidate.is_file():
            continue
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if digest != record.sha256:
            errors.append(f"hash mismatch for {record.rel_path}: expected {record.sha256}, got {digest}")
    return tuple(errors)


def validate_base_names(inventory: ExportInventory) -> tuple[str, ...]:
    """Verify that all exported files share the expected base name."""
    errors: list[str] = []
    for record in inventory.expected_files:
        extracted = _extract_base_name(record.rel_path)
        if extracted.lower() != inventory.base_name.lower():
            errors.append(
                f"base name mismatch in {record.rel_path}: expected {inventory.base_name!r}, got {extracted!r}"
            )
    return tuple(errors)


def validate_mesh_stats(inventory: ExportInventory) -> tuple[str, ...]:
    """Validate mesh statistics are consistent and non-zero."""
    errors: list[str] = []
    stats = inventory.mesh_stats
    if stats.mesh_count == 0:
        errors.append("mesh_count is zero: export has no meshes")
    if stats.object_count == 0:
        errors.append("object_count is zero: export has no objects")
    if stats.total_vertices == 0 and stats.mesh_count > 0:
        errors.append("total_vertices is zero despite having meshes")
    if stats.total_faces == 0 and stats.mesh_count > 0:
        errors.append("total_faces is zero despite having meshes")
    if stats.mesh_count > 0 and stats.total_vertices < stats.mesh_count:
        errors.append(f"total_vertices ({stats.total_vertices}) < mesh_count ({stats.mesh_count})")
    return tuple(errors)


def validate_bounding_box(inventory: ExportInventory) -> tuple[str, ...]:
    """Validate bounding box coordinates are finite and ordered."""
    errors: list[str] = []
    if inventory.bounding_box is None:
        errors.append("no bounding box provided")
        return tuple(errors)
    bb = inventory.bounding_box
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


def validate_units_and_axes(inventory: ExportInventory) -> tuple[str, ...]:
    """Validate unit and axis convention are recognized."""
    errors: list[str] = []
    if inventory.units not in KNOWN_UNITS:
        errors.append(f"unknown units: {inventory.units!r}")
    if inventory.axis_convention not in KNOWN_AXIS_CONVENTIONS:
        errors.append(f"unknown axis_convention: {inventory.axis_convention!r}")
    return tuple(errors)


def validate_origin_and_crs(inventory: ExportInventory) -> tuple[str, ...]:
    """Validate origin coordinates and CRS transform presence."""
    errors: list[str] = []
    for name in ("origin_x", "origin_y", "origin_z"):
        val = getattr(inventory, name)
        if not math.isfinite(val):
            errors.append(f"origin coordinate {name} is not finite: {val}")
    if inventory.crs_epsg is None and inventory.crs_wkt is None:
        errors.append("no CRS reference provided (set crs_epsg or crs_wkt)")
    return tuple(errors)


def validate_vertical_range(inventory: ExportInventory) -> tuple[str, ...]:
    """Validate vertical range is finite and ordered."""
    errors: list[str] = []
    if not math.isfinite(inventory.vertical_min):
        errors.append(f"vertical_min is not finite: {inventory.vertical_min}")
    if not math.isfinite(inventory.vertical_max):
        errors.append(f"vertical_max is not finite: {inventory.vertical_max}")
    if inventory.vertical_min >= inventory.vertical_max:
        errors.append(f"vertical_min ({inventory.vertical_min}) >= vertical_max ({inventory.vertical_max})")
    return tuple(errors)


def validate_materials(inventory: ExportInventory) -> tuple[str, ...]:
    """Validate material count and texture references."""
    errors: list[str] = []
    if not inventory.materials:
        errors.append("no materials declared in export inventory")
    for mat in inventory.materials:
        for tex in mat.texture_refs:
            if not isinstance(tex, str) or not tex.strip():
                errors.append(f"empty texture reference in material {mat.material_name}")
    return tuple(errors)


def validate_semantic_groups(inventory: ExportInventory) -> tuple[str, ...]:
    """Validate semantic groups include required classes."""
    errors: list[str] = []
    if not inventory.semantic_groups:
        errors.append("no semantic groups declared")
        return tuple(errors)
    present = {sg.group_name.lower() for sg in inventory.semantic_groups}
    for required in REQUIRED_SEMANTIC_CLASSES:
        if required.lower() not in present:
            errors.append(f"missing required semantic class: {required}")
    return tuple(errors)


def validate_collision_intent(inventory: ExportInventory) -> tuple[str, ...]:
    """Validate collision intent is declared for semantic groups."""
    errors: list[str] = []
    for sg in inventory.semantic_groups:
        if sg.group_name.lower() == "road" and not sg.collision_enabled:
            errors.append("Road semantic group must have collision_enabled=True")
    return tuple(errors)


def validate_lod_inventory(inventory: ExportInventory) -> tuple[str, ...]:
    """Validate LOD inventory has at least one level."""
    errors: list[str] = []
    if not inventory.lod_entries:
        errors.append("no LOD entries declared")
    levels = {entry.lod_level for entry in inventory.lod_entries}
    if 0 not in levels and inventory.lod_entries:
        errors.append("LOD level 0 (highest detail) is missing")
    return tuple(errors)


def validate_tile_grid(inventory: ExportInventory) -> tuple[str, ...]:
    """Validate tile names and grid positions are unique and consistent."""
    errors: list[str] = []
    if not inventory.tiles:
        return tuple(errors)
    seen_names: set[str] = set()
    seen_positions: set[tuple[int, int]] = set()
    for tile in inventory.tiles:
        if tile.tile_name in seen_names:
            errors.append(f"duplicate tile name: {tile.tile_name}")
        seen_names.add(tile.tile_name)
        pos = (tile.grid_col, tile.grid_row)
        if pos in seen_positions:
            errors.append(f"duplicate grid position {pos} for tile {tile.tile_name}")
        seen_positions.add(pos)
    return tuple(errors)


def validate_no_duplicate_road_surface(inventory: ExportInventory) -> tuple[str, ...]:
    """Validate no duplicate road surface materials."""
    errors: list[str] = []
    road_surfaces = [m for m in inventory.materials if m.is_road_surface]
    names = [m.material_name for m in road_surfaces]
    if len(names) != len(set(names)):
        from collections import Counter

        dupes = [name for name, count in Counter(names).items() if count > 1]
        errors.append(f"duplicate road surface materials: {sorted(dupes)}")
    return tuple(errors)


def validate_xodr_authority(inventory: ExportInventory) -> tuple[str, ...]:
    """Validate exactly one XODR authority file exists in expected files."""
    errors: list[str] = []
    xodr_files = [
        r for r in inventory.expected_files
        if any(r.rel_path.lower().endswith(ext) for ext in _EXPECTED_XODR_EXTENSIONS)
    ]
    if len(xodr_files) == 0:
        errors.append("no XODR authority file in expected files")
    elif len(xodr_files) > 1:
        paths = [r.rel_path for r in xodr_files]
        errors.append(f"multiple XODR authority files found: {paths}")
    return tuple(errors)


def validate_package_json(inventory: ExportInventory) -> tuple[str, ...]:
    """Validate package JSON path is present when expected."""
    errors: list[str] = []
    if inventory.package_json_path is not None:
        pkg = Path(inventory.package_json_path)
        if not pkg.is_file():
            errors.append(f"package_json_path does not exist: {inventory.package_json_path}")
    return tuple(errors)


def validate_fbx_not_sufficient_for_carla(inventory: ExportInventory) -> tuple[str, ...]:
    """Warn that FBX existence alone does not prove CARLA readiness.

    FBX presence without an XODR authority file does not guarantee the
    output can be loaded into CARLA.  This check returns a diagnostic
    message rather than a hard failure.
    """
    errors: list[str] = []
    fbx_files = [
        r for r in inventory.expected_files
        if r.rel_path.lower().endswith(".fbx")
    ]
    xodr_files = [
        r for r in inventory.expected_files
        if r.rel_path.lower().endswith(".xodr")
    ]
    if fbx_files and not xodr_files:
        errors.append(
            "FBX files present but no XODR authority: "
            "FBX existence alone does not prove CARLA readiness"
        )
    return tuple(errors)


@dataclass(frozen=True)
class ExportInventoryValidation:
    """Result of validating an ExportInventory."""

    inventory_id: str
    valid: bool
    errors: tuple[str, ...]
    validated_at: str = field(default_factory=utc_now_iso)


def validate_export_inventory(
    inventory: ExportInventory,
    export_dir: Path | None = None,
) -> ExportInventoryValidation:
    """Run all validation checks on an ExportInventory.

    Returns an ExportInventoryValidation with collected errors.
    """

    all_errors: list[str] = []

    all_errors.extend(validate_expected_files(inventory))
    all_errors.extend(validate_base_names(inventory))
    all_errors.extend(validate_mesh_stats(inventory))
    all_errors.extend(validate_bounding_box(inventory))
    all_errors.extend(validate_units_and_axes(inventory))
    all_errors.extend(validate_origin_and_crs(inventory))
    all_errors.extend(validate_vertical_range(inventory))
    all_errors.extend(validate_materials(inventory))
    all_errors.extend(validate_semantic_groups(inventory))
    all_errors.extend(validate_collision_intent(inventory))
    all_errors.extend(validate_lod_inventory(inventory))
    all_errors.extend(validate_tile_grid(inventory))
    all_errors.extend(validate_no_duplicate_road_surface(inventory))
    all_errors.extend(validate_xodr_authority(inventory))
    all_errors.extend(validate_package_json(inventory))
    all_errors.extend(validate_fbx_not_sufficient_for_carla(inventory))

    if export_dir is not None and export_dir.is_dir():
        all_errors.extend(validate_file_hashes(export_dir, inventory))

    return ExportInventoryValidation(
        inventory_id=inventory.export_id,
        valid=len(all_errors) == 0,
        errors=tuple(all_errors),
    )


__all__ = [
    "BoundingBox",
    "ExportInventory",
    "ExportInventoryValidation",
    "FileRecord",
    "LodEntry",
    "MaterialRecord",
    "MeshStats",
    "SemanticGroupRecord",
    "TileRecord",
    "validate_base_names",
    "validate_bounding_box",
    "validate_collision_intent",
    "validate_expected_files",
    "validate_export_inventory",
    "validate_file_hashes",
    "validate_fbx_not_sufficient_for_carla",
    "validate_lod_inventory",
    "validate_materials",
    "validate_mesh_stats",
    "validate_no_duplicate_road_surface",
    "validate_origin_and_crs",
    "validate_package_json",
    "validate_semantic_groups",
    "validate_tile_grid",
    "validate_units_and_axes",
    "validate_vertical_range",
    "validate_xodr_authority",
]
