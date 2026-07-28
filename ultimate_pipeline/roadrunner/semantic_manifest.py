"""Semantic manifest validation for RoadRunner visual builds.

Validates semantic group assignments, material-to-semantic mappings,
collision intent, required CARLA classes (Road, RoadLines, Sidewalk,
Terrain), no missing semantic coverage, and consistent group membership
counts.  Does not import CARLA or any external semantic classifier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .exceptions import RoadRunnerContractError
from .models import SerializableContract, deterministic_json, utc_now_iso, validate_identifier

REQUIRED_SEMANTIC_CLASSES = ("Road", "RoadLines", "Sidewalk", "Terrain")

OPTIONAL_SEMANTIC_CLASSES = (
    "Building",
    "Vegetation",
    "Fence",
    "Pole",
    "TrafficLight",
    "TrafficSign",
    "Sky",
    "Ground",
    "RailTrack",
    "Water",
    "GuardRail",
    "Bridge",
    "Tunnel",
    "Crosswalk",
    "Parking",
    "Median",
    "BikeLane",
)


def _non_negative_int(value: int, label: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise RoadRunnerContractError(f"{label} must be a non-negative integer, got {value}")
    return value


@dataclass(frozen=True)
class SemanticClassEntry:
    """One semantic class with expected object count and collision flag."""

    class_name: str
    expected_object_count: int = 0
    collision_enabled: bool = True
    material_names: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_name", validate_identifier(self.class_name, "class_name"))
        _non_negative_int(self.expected_object_count, "expected_object_count")
        object.__setattr__(self, "material_names", tuple(self.material_names))


@dataclass(frozen=True)
class SemanticMaterialMapping:
    """Maps a material name to its assigned semantic class."""

    material_name: str
    semantic_class: str
    is_road_surface: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "material_name", validate_identifier(self.material_name, "material_name"))
        object.__setattr__(self, "semantic_class", validate_identifier(self.semantic_class, "semantic_class"))


@dataclass(frozen=True)
class CollisionProfile:
    """Collision profile for the export: which classes participate."""

    enabled_classes: tuple[str, ...] = ()
    disabled_classes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "enabled_classes", tuple(
            validate_identifier(c, "enabled_classes") for c in self.enabled_classes
        ))
        object.__setattr__(self, "disabled_classes", tuple(
            validate_identifier(c, "disabled_classes") for c in self.disabled_classes
        ))
        overlap = set(self.enabled_classes) & set(self.disabled_classes)
        if overlap:
            raise RoadRunnerContractError(
                f"classes cannot be both enabled and disabled: {sorted(overlap)}"
            )


@dataclass(frozen=True)
class SemanticManifest(SerializableContract):
    """Semantic manifest for a RoadRunner visual build.

    Captures semantic class inventory, material-to-class mappings,
    collision profile, and validation metadata.  Ensures all required
    CARLA semantic classes are present and no group is missing.
    """

    manifest_id: str
    source_sha256: str
    semantic_classes: tuple[SemanticClassEntry, ...] = ()
    material_mappings: tuple[SemanticMaterialMapping, ...] = ()
    collision_profile: CollisionProfile = field(default_factory=CollisionProfile)
    total_objects: int = 0
    classified_objects: int = 0
    generated_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        from .models import validate_sha256

        object.__setattr__(self, "manifest_id", validate_identifier(self.manifest_id, "manifest_id"))
        object.__setattr__(self, "source_sha256", validate_sha256(self.source_sha256, "source_sha256"))
        _non_negative_int(self.total_objects, "total_objects")
        _non_negative_int(self.classified_objects, "classified_objects")
        if self.classified_objects > self.total_objects and self.total_objects > 0:
            raise RoadRunnerContractError(
                f"classified_objects ({self.classified_objects}) > total_objects ({self.total_objects})"
            )
        object.__setattr__(self, "semantic_classes", tuple(self.semantic_classes))
        object.__setattr__(self, "material_mappings", tuple(self.material_mappings))


def validate_required_classes(manifest: SemanticManifest) -> tuple[str, ...]:
    """Validate all required CARLA semantic classes are present."""
    errors: list[str] = []
    present = {entry.class_name.lower() for entry in manifest.semantic_classes}
    for required in REQUIRED_SEMANTIC_CLASSES:
        if required.lower() not in present:
            errors.append(f"missing required semantic class: {required}")
    return tuple(errors)


def validate_semantic_class_counts(manifest: SemanticManifest) -> tuple[str, ...]:
    """Validate declared object counts are consistent with totals."""
    errors: list[str] = []
    total_declared = sum(entry.expected_object_count for entry in manifest.semantic_classes)
    if manifest.total_objects > 0 and total_declared != manifest.total_objects:
        errors.append(
            f"sum of class expected_object_count ({total_declared}) != "
            f"total_objects ({manifest.total_objects})"
        )
    if manifest.total_objects > 0 and manifest.classified_objects == 0:
        errors.append("classified_objects is zero despite having objects")
    return tuple(errors)


def validate_material_class_mapping(manifest: SemanticManifest) -> tuple[str, ...]:
    """Validate material-to-semantic-class mappings reference valid classes."""
    errors: list[str] = []
    if not manifest.material_mappings:
        errors.append("no material-to-semantic-class mappings declared")
        return tuple(errors)
    class_names = {entry.class_name.lower() for entry in manifest.semantic_classes}
    for mapping in manifest.material_mappings:
        if mapping.semantic_class.lower() not in class_names:
            errors.append(
                f"material {mapping.material_name} references unknown semantic class: "
                f"{mapping.semantic_class}"
            )
    return tuple(errors)


def validate_no_duplicate_road_surface(manifest: SemanticManifest) -> tuple[str, ...]:
    """Validate no duplicate road surface materials are declared."""
    errors: list[str] = []
    road_surfaces = [m for m in manifest.material_mappings if m.is_road_surface]
    names = [m.material_name for m in road_surfaces]
    if len(names) != len(set(names)):
        from collections import Counter

        dupes = [name for name, count in Counter(names).items() if count > 1]
        errors.append(f"duplicate road surface materials: {sorted(dupes)}")
    return tuple(errors)


def validate_collision_profile(manifest: SemanticManifest) -> tuple[str, ...]:
    """Validate collision profile is consistent with semantic classes."""
    errors: list[str] = []
    profile = manifest.collision_profile
    class_names = {entry.class_name.lower() for entry in manifest.semantic_classes}
    for cls_name in profile.enabled_classes:
        if cls_name.lower() not in class_names:
            errors.append(f"collision enabled class {cls_name!r} not in semantic class inventory")
    for cls_name in profile.disabled_classes:
        if cls_name.lower() not in class_names:
            errors.append(f"collision disabled class {cls_name!r} not in semantic class inventory")
    return tuple(errors)


def validate_road_collision_enabled(manifest: SemanticManifest) -> tuple[str, ...]:
    """Validate Road semantic class has collision enabled."""
    errors: list[str] = []
    for entry in manifest.semantic_classes:
        if entry.class_name.lower() == "road" and not entry.collision_enabled:
            errors.append("Road semantic class must have collision_enabled=True")
    if "Road" in manifest.collision_profile.disabled_classes:
        errors.append("Road class must not be in collision disabled_classes")
    return tuple(errors)


def validate_semantic_coverage(manifest: SemanticManifest) -> tuple[str, ...]:
    """Warn about semantic classes with zero expected objects."""
    errors: list[str] = []
    for entry in manifest.semantic_classes:
        if entry.expected_object_count == 0 and entry.class_name.lower() in {c.lower() for c in REQUIRED_SEMANTIC_CLASSES}:
            errors.append(
                f"required semantic class {entry.class_name} has zero expected objects"
            )
    return tuple(errors)


def validate_semantic_manifest(manifest: SemanticManifest) -> tuple[str, ...]:
    """Run all semantic manifest validation checks."""
    all_errors: list[str] = []
    all_errors.extend(validate_required_classes(manifest))
    all_errors.extend(validate_semantic_class_counts(manifest))
    all_errors.extend(validate_material_class_mapping(manifest))
    all_errors.extend(validate_no_duplicate_road_surface(manifest))
    all_errors.extend(validate_collision_profile(manifest))
    all_errors.extend(validate_road_collision_enabled(manifest))
    all_errors.extend(validate_semantic_coverage(manifest))
    return tuple(all_errors)


@dataclass(frozen=True)
class SemanticManifestValidation:
    """Result of validating a SemanticManifest."""

    manifest_id: str
    valid: bool
    errors: tuple[str, ...]
    validated_at: str = field(default_factory=utc_now_iso)


def validate_semantic_manifest_result(manifest: SemanticManifest) -> SemanticManifestValidation:
    """Run all semantic manifest checks and return a structured result."""
    errors = validate_semantic_manifest(manifest)
    return SemanticManifestValidation(
        manifest_id=manifest.manifest_id,
        valid=len(errors) == 0,
        errors=errors,
    )


__all__ = [
    "CollisionProfile",
    "REQUIRED_SEMANTIC_CLASSES",
    "SemanticClassEntry",
    "SemanticManifest",
    "SemanticManifestValidation",
    "SemanticMaterialMapping",
    "validate_collision_profile",
    "validate_material_class_mapping",
    "validate_no_duplicate_road_surface",
    "validate_required_classes",
    "validate_road_collision_enabled",
    "validate_semantic_class_counts",
    "validate_semantic_coverage",
    "validate_semantic_manifest",
    "validate_semantic_manifest_result",
]
