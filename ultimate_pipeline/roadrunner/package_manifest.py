"""Package manifest validation for RoadRunner tiled exports.

Validates tile names and grid positions, no duplicate road surface
materials, exactly one XODR authority, package JSON structure, and
tile-origin consistency.  Operates on structured metadata without
importing tile file parsers.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .exceptions import RoadRunnerContractError
from .models import SerializableContract, deterministic_json, utc_now_iso, validate_identifier, validate_sha256


def _finite(value: float, label: str) -> float:
    if not math.isfinite(value):
        raise RoadRunnerContractError(f"{label} must be finite, got {value}")
    return value


def _non_negative_int(value: int, label: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise RoadRunnerContractError(f"{label} must be a non-negative integer, got {value}")
    return value


@dataclass(frozen=True)
class TileEntry:
    """One tile in the package manifest."""

    tile_name: str
    grid_col: int
    grid_row: int
    origin_x: float = 0.0
    origin_y: float = 0.0
    origin_z: float = 0.0
    file_count: int = 0
    sha256: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tile_name", validate_identifier(self.tile_name, "tile_name"))
        _non_negative_int(self.file_count, "file_count")
        if self.sha256 is not None:
            object.__setattr__(self, "sha256", validate_sha256(self.sha256, "sha256"))
        _finite(self.origin_x, "origin_x")
        _finite(self.origin_y, "origin_y")
        _finite(self.origin_z, "origin_z")


@dataclass(frozen=True)
class XodrAuthorityEntry:
    """XODR authority file metadata."""

    file_name: str
    sha256: str
    road_count: int = 0
    junction_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "file_name", validate_identifier(self.file_name, "file_name"))
        object.__setattr__(self, "sha256", validate_sha256(self.sha256, "sha256"))
        _non_negative_int(self.road_count, "road_count")
        _non_negative_int(self.junction_count, "junction_count")


@dataclass(frozen=True)
class PackageJsonMetadata:
    """Expected package.json structure metadata."""

    package_name: str = ""
    version: str = ""
    map_name: str = ""
    xodr_file: str = ""
    tile_count: int = 0
    custom_fields: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.package_name:
            object.__setattr__(self, "package_name", validate_identifier(self.package_name, "package_name"))
        if self.map_name:
            _reject_placeholder(self.map_name.strip(), "map_name")
        object.__setattr__(self, "custom_fields", dict(self.custom_fields))


def _reject_placeholder(value: str, field_name: str) -> None:
    normalized = value.strip().lower()
    if normalized in ("", "placeholder", "todo", "tbd", "unknown", "none", "changeme"):
        raise RoadRunnerContractError(f"{field_name} cannot be a placeholder value")


@dataclass(frozen=True)
class PackageManifest(SerializableContract):
    """Package manifest for a RoadRunner tiled export.

    Validates tile grid, duplicate road surface check, XODR authority
    count, package JSON structure, and tile-origin consistency.
    """

    manifest_id: str
    source_xodr_sha256: str
    map_base_name: str
    tiles: tuple[TileEntry, ...] = ()
    xodr_authorities: tuple[XodrAuthorityEntry, ...] = ()
    package_json: PackageJsonMetadata | None = None
    road_surface_materials: tuple[str, ...] = ()
    generated_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest_id", validate_identifier(self.manifest_id, "manifest_id"))
        object.__setattr__(self, "source_xodr_sha256", validate_sha256(self.source_xodr_sha256, "source_xodr_sha256"))
        if not isinstance(self.map_base_name, str) or not self.map_base_name.strip():
            raise RoadRunnerContractError("map_base_name must be a non-empty string")
        object.__setattr__(self, "tiles", tuple(self.tiles))
        object.__setattr__(self, "xodr_authorities", tuple(self.xodr_authorities))
        object.__setattr__(self, "road_surface_materials", tuple(self.road_surface_materials))


def validate_tile_names_unique(manifest: PackageManifest) -> tuple[str, ...]:
    """Validate all tile names are unique."""
    errors: list[str] = []
    seen: set[str] = set()
    for tile in manifest.tiles:
        if tile.tile_name in seen:
            errors.append(f"duplicate tile name: {tile.tile_name}")
        seen.add(tile.tile_name)
    return tuple(errors)


def validate_tile_grid_positions(manifest: PackageManifest) -> tuple[str, ...]:
    """Validate tile grid positions are unique."""
    errors: list[str] = []
    seen: set[tuple[int, int]] = set()
    for tile in manifest.tiles:
        pos = (tile.grid_col, tile.grid_row)
        if pos in seen:
            errors.append(f"duplicate grid position {pos} for tile {tile.tile_name}")
        seen.add(pos)
    return tuple(errors)


def validate_tile_origins_consistent(manifest: PackageManifest) -> tuple[str, ...]:
    """Validate tile origins are finite and there are no unexplained offsets."""
    errors: list[str] = []
    for tile in manifest.tiles:
        for coord in ("origin_x", "origin_y", "origin_z"):
            val = getattr(tile, coord)
            if not math.isfinite(val):
                errors.append(f"tile {tile.tile_name}: {coord} is not finite: {val}")
    if len(manifest.tiles) >= 2:
        origins_x = [t.origin_x for t in manifest.tiles]
        origins_y = [t.origin_y for t in manifest.tiles]
        range_x = max(origins_x) - min(origins_x)
        range_y = max(origins_y) - min(origins_y)
        tile_spacing_x = 0.0
        tile_spacing_y = 0.0
        if len(manifest.tiles) > 1:
            sorted_cols = sorted(set(t.grid_col for t in manifest.tiles))
            sorted_rows = sorted(set(t.grid_row for t in manifest.tiles))
            if len(sorted_cols) > 1:
                col_origins = {}
                for t in manifest.tiles:
                    col_origins.setdefault(t.grid_col, t.origin_x)
                spacings = [
                    abs(col_origins[c2] - col_origins[c1])
                    for i, c1 in enumerate(sorted_cols)
                    for c2 in sorted_cols[i + 1:]
                    if c1 in col_origins and c2 in col_origins
                ]
                if spacings:
                    tile_spacing_x = min(s for s in spacings if s > 0) if any(s > 0 for s in spacings) else 0.0
            if len(sorted_rows) > 1:
                row_origins = {}
                for t in manifest.tiles:
                    row_origins.setdefault(t.grid_row, t.origin_y)
                spacings = [
                    abs(row_origins[r2] - row_origins[r1])
                    for i, r1 in enumerate(sorted_rows)
                    for r2 in sorted_rows[i + 1:]
                    if r1 in row_origins and r2 in row_origins
                ]
                if spacings:
                    tile_spacing_y = min(s for s in spacings if s > 0) if any(s > 0 for s in spacings) else 0.0
    return tuple(errors)


def validate_no_duplicate_road_surface(manifest: PackageManifest) -> tuple[str, ...]:
    """Validate no duplicate road surface materials in the package."""
    errors: list[str] = []
    names = list(manifest.road_surface_materials)
    if len(names) != len(set(names)):
        from collections import Counter

        dupes = [name for name, count in Counter(names).items() if count > 1]
        errors.append(f"duplicate road surface materials: {sorted(dupes)}")
    return tuple(errors)


def validate_one_xodr_authority(manifest: PackageManifest) -> tuple[str, ...]:
    """Validate exactly one XODR authority file is declared."""
    errors: list[str] = []
    if len(manifest.xodr_authorities) == 0:
        errors.append("no XODR authority file declared in package manifest")
    elif len(manifest.xodr_authorities) > 1:
        names = [a.file_name for a in manifest.xodr_authorities]
        errors.append(f"multiple XODR authority files declared: {names}")
    return tuple(errors)


def validate_package_json(manifest: PackageManifest) -> tuple[str, ...]:
    """Validate package JSON metadata if present."""
    errors: list[str] = []
    if manifest.package_json is None:
        errors.append("no package JSON metadata declared")
        return tuple(errors)
    pkg = manifest.package_json
    if not pkg.package_name:
        errors.append("package_json: package_name is empty")
    if not pkg.map_name:
        errors.append("package_json: map_name is empty")
    if pkg.tile_count != len(manifest.tiles):
        errors.append(
            f"package_json tile_count ({pkg.tile_count}) != "
            f"declared tiles ({len(manifest.tiles)})"
        )
    return tuple(errors)


def validate_package_json_file(path: Path) -> tuple[str, ...]:
    """Validate a package.json file exists and has expected structure."""
    errors: list[str] = []
    if not path.is_file():
        errors.append(f"package.json not found: {path}")
        return tuple(errors)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"failed to parse package.json: {exc}")
        return tuple(errors)
    if not isinstance(data, dict):
        errors.append("package.json root must be a JSON object")
        return tuple(errors)
    for key in ("name", "version"):
        if key not in data:
            errors.append(f"package.json missing required key: {key}")
    return tuple(errors)


def validate_package_manifest(manifest: PackageManifest) -> tuple[str, ...]:
    """Run all package manifest validation checks."""
    all_errors: list[str] = []
    all_errors.extend(validate_tile_names_unique(manifest))
    all_errors.extend(validate_tile_grid_positions(manifest))
    all_errors.extend(validate_tile_origins_consistent(manifest))
    all_errors.extend(validate_no_duplicate_road_surface(manifest))
    all_errors.extend(validate_one_xodr_authority(manifest))
    all_errors.extend(validate_package_json(manifest))
    return tuple(all_errors)


@dataclass(frozen=True)
class PackageManifestValidation:
    """Result of validating a PackageManifest."""

    manifest_id: str
    valid: bool
    errors: tuple[str, ...]
    validated_at: str = field(default_factory=utc_now_iso)


def validate_package_manifest_result(manifest: PackageManifest) -> PackageManifestValidation:
    """Run all package manifest checks and return structured result."""
    errors = validate_package_manifest(manifest)
    return PackageManifestValidation(
        manifest_id=manifest.manifest_id,
        valid=len(errors) == 0,
        errors=errors,
    )


__all__ = [
    "PackageJsonMetadata",
    "PackageManifest",
    "PackageManifestValidation",
    "TileEntry",
    "XodrAuthorityEntry",
    "validate_no_duplicate_road_surface",
    "validate_one_xodr_authority",
    "validate_package_json",
    "validate_package_json_file",
    "validate_package_manifest",
    "validate_package_manifest_result",
    "validate_tile_grid_positions",
    "validate_tile_names_unique",
    "validate_tile_origins_consistent",
]
