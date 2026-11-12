"""``carla_calib_profile/v2`` with non-destructive migrations.

Migration is **non-destructive**: the original document is kept verbatim under
``_v1_original`` so a migration can always be audited and rolled back. A future
schema version is rejected rather than guessed at.

``image_size`` is normalised to the dict form on migration, and the fact that
``sensor_rig.py:76`` requires the dict form is recorded rather than assumed.
"""

from __future__ import annotations

import copy
from typing import Any

__all__ = [
    "PROFILE_V2", "SUPPORTED_VERSIONS", "ProfileVersionError", "ProfileSchemaError",
    "migrate_to_v2", "validate_profile",
]

PROFILE_V2 = "carla_calib_profile/v2"
SUPPORTED_VERSIONS = ("carla_calib_profile/v1", PROFILE_V2)


class ProfileVersionError(ValueError):
    pass


class ProfileSchemaError(ValueError):
    pass


def _parse_image_size(value: Any) -> tuple[int, int]:
    if isinstance(value, dict):
        return int(value["width"]), int(value["height"])
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return int(value[0]), int(value[1])
    raise ProfileSchemaError(f"unsupported image_size format: {value!r}")


def migrate_to_v2(document: dict) -> dict:
    """Migrate a v1 profile to v2 without destroying the original."""
    if not isinstance(document, dict):
        raise ProfileSchemaError("profile must be a JSON object")

    schema = document.get("schema")
    if schema not in SUPPORTED_VERSIONS:
        raise ProfileVersionError(
            f"unsupported profile schema {schema!r}; supported: {list(SUPPORTED_VERSIONS)}")

    migrated = copy.deepcopy(document)
    migrations: list[str] = []

    if schema == "carla_calib_profile/v1":
        # Non-destructive: the untouched v1 document is retained.
        migrated["_v1_original"] = copy.deepcopy(document)
        migrations.append("retained original v1 document under _v1_original")

    migrated["schema"] = PROFILE_V2

    cameras = migrated.get("cameras") or {}
    for sensor_id, camera in cameras.items():
        if "image_size" in camera:
            width, height = _parse_image_size(camera["image_size"])
            if not isinstance(camera["image_size"], dict):
                migrations.append(
                    f"{sensor_id}: image_size list -> dict ({width}x{height}); "
                    "sensor_rig.py:76 requires the dict form")
            camera["image_size"] = {"width": width, "height": height}

        if "K_undistortion" in camera and "intrinsics_source" not in camera:
            camera["intrinsics_source"] = "K_undistortion_ideal_pinhole"
            migrations.append(f"{sensor_id}: pinned intrinsics_source to K_undistortion")

        if "distortion_in_carla" not in camera:
            camera["distortion_in_carla"] = "none"
            migrations.append(f"{sensor_id}: declared distortion_in_carla=none")

    if cameras:
        migrated.setdefault("cameras", cameras)

    lidars = migrated.get("lidars") or {}
    for sensor_id, spec in lidars.items():
        spec.setdefault("effective_source", "ultimate_pipeline.sensors.canonical_lidar_spec")
        spec.setdefault("point_rate_verified", False)
        if not spec.get("point_rate_verified"):
            migrations.append(
                f"{sensor_id}: point_rate UNVERIFIED (LiDAR pps cannot be read back)")

    migrated["_migrations"] = migrations
    return migrated


def validate_profile(profile: dict) -> list[str]:
    """Return structural problems. An empty list means structurally sound."""
    problems: list[str] = []
    if profile.get("schema") != PROFILE_V2:
        problems.append(f"schema is {profile.get('schema')!r}, expected {PROFILE_V2!r}")

    for sensor_id, camera in (profile.get("cameras") or {}).items():
        if "K_undistortion" not in camera:
            problems.append(f"camera {sensor_id}: missing K_undistortion")
        if "image_size" not in camera:
            problems.append(f"camera {sensor_id}: missing image_size")
            continue
        if not isinstance(camera["image_size"], dict):
            problems.append(f"camera {sensor_id}: image_size must be the dict form")
            continue
        width = camera["image_size"].get("width")
        height = camera["image_size"].get("height")
        if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
            problems.append(f"camera {sensor_id}: image_size must be positive integers")
        if "frame_id" in camera:
            problems.append(f"camera {sensor_id}: frame_id must be a verified constant, "
                            "not a per-frame value")
    return problems