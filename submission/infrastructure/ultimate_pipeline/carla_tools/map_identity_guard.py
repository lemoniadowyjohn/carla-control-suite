#!/usr/bin/env python3
"""
Map identity guard for thesis validity.

Prevents silent Town fallback when custom OpenDRIVE should be loaded.
Gate: UP_THESIS_STRICT=1 enables hard stop on Town detection.
"""
from __future__ import annotations

import json
import os
import logging
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


def validate_world_map(
    world: Any,
    *,
    expected_substring: Optional[str] = None,
    strict: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Validate loaded CARLA world map identity.

    Args:
        world: carla.World instance
        expected_substring: Optional substring that map name must contain
        strict: Override for UP_THESIS_STRICT (default: read from env)

    Returns:
        Dict with validation result and provenance fields (JSON-safe)

    Raises:
        RuntimeError: If strict mode and map is a default Town
    """
    if strict is None:
        strict = os.getenv("UP_THESIS_STRICT", "") == "1"

    result: Dict[str, Any] = {
        "thesis_strict_enabled": strict,
        "world_map_name": None,
        "is_town_fallback": False,
        "validation_passed": False,
        "error": None,
    }

    try:
        carla_map = world.get_map()
        map_name = carla_map.name if carla_map else "unknown"
        result["world_map_name"] = map_name

        # Detect Town fallback (default CARLA maps)
        is_town = (
            map_name.startswith("Town")
            or map_name.startswith("/Game/Carla/Maps/Town")
            or "/Town" in map_name
        )
        result["is_town_fallback"] = is_town

        if is_town and strict:
            err = (
                f"HARD STOP: CARLA loaded default map '{map_name}' instead of custom OpenDRIVE. "
                f"This invalidates thesis metrics. Disable with UP_THESIS_STRICT=0."
            )
            result["error"] = err
            log.error(err)
            raise RuntimeError(err)

        if is_town:
            log.warning(
                "CARLA loaded Town map '%s'. If custom OpenDRIVE was expected, "
                "set UP_THESIS_STRICT=1 to enforce.",
                map_name,
            )

        # Optional: check expected substring
        if expected_substring and expected_substring not in map_name:
            msg = f"Map name '{map_name}' does not contain expected '{expected_substring}'"
            if strict:
                result["error"] = msg
                log.error(msg)
                raise RuntimeError(msg)
            log.warning(msg)

        substring_ok = (expected_substring is None) or (expected_substring in map_name)
        result["validation_passed"] = (not is_town) and substring_ok
        log.info("World map identity: %s (strict=%s)", map_name, strict)

    except RuntimeError:
        raise
    except Exception as e:
        result["error"] = str(e)
        log.warning("Map identity check failed: %s", e)

    return result


def save_map_identity(result: Dict[str, Any], path: str) -> None:
    """Save map identity result to JSON file."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, sort_keys=True, ensure_ascii=True)
    except Exception as e:
        log.warning("Failed to save map identity to %s: %s", path, e)
