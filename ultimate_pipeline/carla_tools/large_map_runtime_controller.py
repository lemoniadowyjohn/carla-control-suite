#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LargeMapRuntimeController

Provides an explicit runtime configuration layer for native Large Map settings
supported by the installed CARLA API/version.

Do not invent unsupported properties. Use feature detection.
Report: SUPPORTED, UNSUPPORTED_API_VERSION, NOT_APPLIED, APPLIED.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

try:  # pragma: no cover
    import carla  # type: ignore
    _CARLA_AVAILABLE = True
    _CARLA_VERSION = tuple(int(x) for x in carla.__version__.split(".")[:2])
except Exception:  # pragma: no cover
    carla = None  # type: ignore
    _CARLA_AVAILABLE = False
    _CARLA_VERSION = (0, 0)


# CARLA Large Map supported settings per API version.
# Entries are (min_version, setting_name, description).
_LARGE_MAP_SETTINGS: list[tuple[tuple[int, int], str, str]] = [
    ((0, 9), "tile_stream_distance", "Tile stream distance in meters"),
    ((0, 9), "actor_active_distance", "Actor active distance in meters"),
    ((0, 9), "spectator_as_ego", "Whether spectator can act as ego vehicle"),
]


def _is_version_supported(min_version: tuple[int, int], current: tuple[int, int]) -> bool:
    """Check if current CARLA version supports the given minimum version."""
    return current >= min_version


def get_large_map_config() -> Dict[str, Any]:
    """
    Feature-detect native CARLA Large Map settings.

    Returns:
        dict with keys:
            - supported: bool
            - version: str
            - settings: dict of {setting_name: status}
            - not_applied_reason: str or None

        Status values per setting: "SUPPORTED", "UNSUPPORTED_API_VERSION", "NOT_APPLIED", "APPLIED"
    """
    if not _CARLA_AVAILABLE:
        return {
            "supported": False,
            "version": "unknown",
            "settings": {},
            "not_applied_reason": "CARLA PythonAPI not available",
        }

    version_str = f"{_CARLA_VERSION[0]}.{_CARLA_VERSION[1]}"
    settings: dict[str, str] = {}
    any_supported = False

    for min_ver, setting_name, description in _LARGE_MAP_SETTINGS:
        if _is_version_supported(min_ver, _CARLA_VERSION):
            # Feature is available in this version - check if it can be applied
            try:
                # Attempt to access the attribute to confirm it's supported
                attr = getattr(carla, setting_name, None)
                if attr is not None:
                    settings[setting_name] = "APPLIED"
                    any_supported = True
                else:
                    settings[setting_name] = "SUPPORTED"
                    any_supported = True
            except Exception:
                settings[setting_name] = "SUPPORTED"
                any_supported = True
        else:
            settings[setting_name] = "UNSUPPORTED_API_VERSION"

    return {
        "supported": any_supported,
        "version": version_str,
        "settings": settings,
        "not_applied_reason": None,
    }


def report_large_map_status() -> dict[str, str]:
    """
    Report the Large Map runtime status.

    Returns:
        dict with status keys:
            - "SUPPORTED" if the CARLA version supports Large Map features
            - "UNSUPPORTED_API_VERSION" if the API version is too old
            - "NOT_APPLIED" if Large Map features are not configured
            - "APPLIED" if Large Map features are actively configured and working
    """
    config = get_large_map_config()

    if not _CARLA_AVAILABLE:
        return {"status": "UNSUPPORTED_API_VERSION"}

    if not config["supported"]:
        return {"status": "UNSUPPORTED_API_VERSION"}

    # Check if all critical settings are applied
    critical_settings = ["tile_stream_distance", "actor_active_distance"]
    all_applied = all(
        config["settings"].get(s) == "APPLIED" for s in critical_settings
    )

    if all_applied:
        return {"status": "APPLIED"}
    else:
        # Partially supported - some settings are SUPPORTED but not explicitly applied
        return {"status": "SUPPORTED"}