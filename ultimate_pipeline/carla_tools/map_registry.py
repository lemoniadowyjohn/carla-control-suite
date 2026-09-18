#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Map Registry - Single source of truth for CARLA map identity and type.

Defines cooked maps, XODR-only maps, and name normalization logic.
Used by map_only_probe.py and run_perception_safe.py to ensure consistent
map identity verification.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple


# =============================================================================
# Cooked Map Registry
# =============================================================================
# Maps canonical name -> set of acceptable raw name variants.
# This is a candidate registry only. Runtime loaders MUST still gate on
# `client.get_available_maps()` before calling `load_world()`.

COOKED_MAP_ALIASES: Dict[str, FrozenSet[str]] = {
    # Grid maps (runtime-gated cooked candidates)
    "Grid0828": frozenset({
        "Grid0828",
        "grid0828",
        "Carla/Maps/Grid0828",
        "/Game/Carla/Maps/Grid0828",
        "Grid0828/Maps/Grid0828/Grid0828",  # CARLA actual return format
    }),
    "Grid0821": frozenset({
        "Grid0821",
        "grid0821",
        "Carla/Maps/Grid0821",
        "/Game/Carla/Maps/Grid0821",
        "Grid0821/Maps/Grid0821/Grid0821",  # CARLA actual return format
    }),
    # Standard CARLA towns
    "Town01": frozenset({"Town01", "Carla/Maps/Town01", "/Game/Carla/Maps/Town01"}),
    "Town01_Opt": frozenset({"Town01_Opt", "Carla/Maps/Town01_Opt", "/Game/Carla/Maps/Town01_Opt"}),
    "Town02": frozenset({"Town02", "Carla/Maps/Town02", "/Game/Carla/Maps/Town02"}),
    "Town02_Opt": frozenset({"Town02_Opt", "Carla/Maps/Town02_Opt", "/Game/Carla/Maps/Town02_Opt"}),
    "Town03": frozenset({"Town03", "Carla/Maps/Town03", "/Game/Carla/Maps/Town03"}),
    "Town03_Opt": frozenset({"Town03_Opt", "Carla/Maps/Town03_Opt", "/Game/Carla/Maps/Town03_Opt"}),
    "Town04": frozenset({"Town04", "Carla/Maps/Town04", "/Game/Carla/Maps/Town04"}),
    "Town04_Opt": frozenset({"Town04_Opt", "Carla/Maps/Town04_Opt", "/Game/Carla/Maps/Town04_Opt"}),
    "Town05": frozenset({"Town05", "Carla/Maps/Town05", "/Game/Carla/Maps/Town05"}),
    "Town05_Opt": frozenset({"Town05_Opt", "Carla/Maps/Town05_Opt", "/Game/Carla/Maps/Town05_Opt"}),
    "Town10HD": frozenset({"Town10HD", "Carla/Maps/Town10HD", "/Game/Carla/Maps/Town10HD"}),
    "Town10HD_Opt": frozenset({"Town10HD_Opt", "Carla/Maps/Town10HD_Opt", "/Game/Carla/Maps/Town10HD_Opt"}),
}

# Build reverse lookup: normalized name -> canonical name
_NORMALIZED_TO_CANONICAL: Dict[str, str] = {}
for canonical, aliases in COOKED_MAP_ALIASES.items():
    for alias in aliases:
        _NORMALIZED_TO_CANONICAL[alias.lower()] = canonical


# =============================================================================
# XODR-only maps (require generate_opendrive_world)
# =============================================================================
XODR_ONLY_MAPS: Dict[str, str] = {
    # Custom XODR maps that must be loaded via generate_opendrive_world
    # Format: canonical name -> relative path from repo root
    # Currently empty since Grid maps are now cooked
}


# =============================================================================
# Normalization Functions
# =============================================================================

def normalize_map_name(raw: str) -> str:
    """
    Normalize a CARLA map name to a canonical lowercase form.

    Strips path prefixes, converts to lowercase, and handles common variants.

    Examples:
        "Carla/Maps/Grid0828" -> "grid0828"
        "/Game/Carla/Maps/Town10HD_Opt" -> "town10hd_opt"
        "Grid0828" -> "grid0828"
        "Grid0828/Maps/Grid0828/Grid0828" -> "grid0828"
    """
    if not raw:
        return ""

    name = str(raw).strip()

    # Strip common path prefixes
    prefixes = [
        "/Game/Carla/Maps/",
        "Carla/Maps/",
        "/Game/",
    ]
    for prefix in prefixes:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break

    # Also handle leading slashes
    name = name.lstrip("/")

    # Handle CARLA cooked map path pattern: "{MapName}/Maps/{MapName}/{MapName}"
    # Extract just the base map name
    if "/Maps/" in name:
        parts = name.split("/")
        # Take the first component (the map name before /Maps/)
        if len(parts) >= 1:
            name = parts[0]

    # Lowercase for comparison
    return name.lower()


def get_canonical_name(raw: str) -> Optional[str]:
    """
    Get the canonical map name for a raw map name.

    Returns None if not found in registry.
    """
    normalized = normalize_map_name(raw)
    return _NORMALIZED_TO_CANONICAL.get(normalized)


def is_cooked_map(requested: str) -> bool:
    """
    Check if the requested map is a cooked CARLA map (loadable via load_world).

    Args:
        requested: The map name requested by the user

    Returns:
        True if this is a known cooked map
    """
    normalized = normalize_map_name(requested)

    # Check if normalized form matches any canonical or alias
    if normalized in _NORMALIZED_TO_CANONICAL:
        return True

    # Also check canonical names directly
    for canonical in COOKED_MAP_ALIASES:
        if normalize_map_name(canonical) == normalized:
            return True

    return False


def is_xodr_only_map(requested: str) -> bool:
    """
    Check if the requested map requires XODR loading.

    Args:
        requested: The map name requested by the user

    Returns:
        True if this map must be loaded via generate_opendrive_world
    """
    normalized = normalize_map_name(requested)
    for xodr_name in XODR_ONLY_MAPS:
        if normalize_map_name(xodr_name) == normalized:
            return True
    return False


def get_map_type(requested: str) -> str:
    """
    Determine the map type for a requested map.

    Returns:
        "cooked" - Use client.load_world()
        "xodr" - Use generate_opendrive_world()
        "unknown" - Not in registry, try cooked first
    """
    if is_cooked_map(requested):
        return "cooked"
    if is_xodr_only_map(requested):
        return "xodr"
    return "unknown"


def resolve_expected_names(requested: str) -> Dict[str, any]:
    """
    Resolve the expected map names and acceptable variants for a requested map.

    Args:
        requested: The map name requested by the user

    Returns:
        Dict with:
            - expected_raw: The raw name to use in load_world()
            - expected_normalized: Normalized form for comparison
            - acceptable_normalized_set: Set of acceptable normalized names
            - canonical_name: The canonical name from registry (or None)
            - map_type: "cooked", "xodr", or "unknown"
    """
    normalized = normalize_map_name(requested)
    canonical = get_canonical_name(requested)
    map_type = get_map_type(requested)

    # Build acceptable set
    acceptable: Set[str] = set()

    if canonical and canonical in COOKED_MAP_ALIASES:
        # Add all aliases for this canonical map
        for alias in COOKED_MAP_ALIASES[canonical]:
            acceptable.add(normalize_map_name(alias))
    else:
        # For unknown maps, accept exact match and common variants
        acceptable.add(normalized)

    # Always accept the exact normalized form
    acceptable.add(normalized)

    # Determine the raw name to use for load_world
    if canonical:
        expected_raw = canonical
    else:
        # Use the original requested name
        expected_raw = requested

    return {
        "expected_raw": expected_raw,
        "expected_normalized": normalized,
        "acceptable_normalized_set": frozenset(acceptable),
        "canonical_name": canonical,
        "map_type": map_type,
    }


def map_names_match(actual: str, expected: str) -> bool:
    """
    Check if an actual map name matches an expected map name.

    Uses normalization and alias lookup for robust matching.

    Args:
        actual: The actual map name from CARLA (e.g., "Carla/Maps/Grid0828")
        expected: The expected map name (e.g., "Grid0828")

    Returns:
        True if the maps match
    """
    actual_norm = normalize_map_name(actual)
    expected_norm = normalize_map_name(expected)

    # Direct match
    if actual_norm == expected_norm:
        return True

    # Check if both resolve to the same canonical name
    actual_canonical = get_canonical_name(actual)
    expected_canonical = get_canonical_name(expected)

    if actual_canonical and expected_canonical:
        return actual_canonical == expected_canonical

    # Check if actual is in the acceptable set for expected
    resolution = resolve_expected_names(expected)
    return actual_norm in resolution["acceptable_normalized_set"]


def get_load_world_candidates(requested: str) -> List[str]:
    """
    Get a list of map names to try with client.load_world().

    Returns names in priority order.

    Args:
        requested: The requested map name

    Returns:
        List of map names to try
    """
    candidates = []
    canonical = get_canonical_name(requested)

    if canonical:
        # Primary: canonical name
        candidates.append(canonical)

        # Secondary: original request if different
        if requested != canonical:
            candidates.append(requested)
    else:
        # Unknown map: try original and common variants
        candidates.append(requested)

    return candidates


def safe_get_available_maps(
    client: Any,
    *,
    query_timeout_s: float = 20.0,
    restore_timeout_s: float = 20.0,
) -> Dict[str, Any]:
    """Safely query CARLA available maps with timeout guards and diagnostics."""
    result: Dict[str, Any] = {
        "ok": False,
        "maps": [],
        "normalized_maps": [],
        "available_maps_count": 0,
        "available_maps_sample": [],
        "available_maps_hash": "",
        "error": "",
    }
    try:
        try:
            client.set_timeout(float(query_timeout_s))
        except Exception:
            pass
        raw_maps = client.get_available_maps()
        if isinstance(raw_maps, (list, tuple, set)):
            clean = sorted(
                {
                    str(item).strip()
                    for item in raw_maps
                    if str(item).strip()
                },
                key=lambda x: x.lower(),
            )
        else:
            clean = []
        normalized = sorted(
            {normalize_map_name(name) for name in clean if normalize_map_name(name)}
        )
        payload = "\n".join(normalized).encode("utf-8", errors="replace")
        result.update(
            {
                "ok": True,
                "maps": clean,
                "normalized_maps": normalized,
                "available_maps_count": int(len(clean)),
                "available_maps_sample": list(clean[:8]),
                "available_maps_hash": hashlib.sha256(payload).hexdigest(),
                "error": "",
            }
        )
    except Exception as exc:
        result["error"] = f"{exc.__class__.__name__}: {exc}"
    finally:
        try:
            client.set_timeout(float(restore_timeout_s))
        except Exception:
            pass
    return result


def resolve_available_load_world_targets(
    requested: str,
    available_maps: List[str],
) -> Dict[str, Any]:
    """Resolve safe load_world targets restricted to maps advertised by CARLA."""
    requested = str(requested or "").strip()
    candidates = get_load_world_candidates(requested)
    available = [str(item).strip() for item in (available_maps or []) if str(item).strip()]

    matched_targets: List[str] = []
    matched_by_candidate: Dict[str, List[str]] = {}

    for candidate in candidates:
        matches = [avail for avail in available if map_names_match(avail, candidate)]
        if not matches:
            continue
        matches = sorted(set(matches), key=lambda x: (len(x), x.lower()))
        matched_by_candidate[candidate] = list(matches)
        for target in matches:
            if target not in matched_targets:
                matched_targets.append(target)

    return {
        "requested": requested,
        "requested_normalized": normalize_map_name(requested),
        "candidates": candidates,
        "matched_targets": matched_targets,
        "matched_by_candidate": matched_by_candidate,
    }


def copy_latest_carla_log(out_dir: Path) -> str:
    """Best-effort copy of the newest CARLA log to ``out_dir/carla_latest.log``."""
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    search_dirs: List[Path] = []
    env_log_dir = str(os.environ.get("UP_CARLA_LOG_DIR", "") or "").strip()
    if env_log_dir:
        search_dirs.append(Path(env_log_dir))

    local_app_data = str(os.environ.get("LOCALAPPDATA", "") or "").strip()
    if local_app_data:
        search_dirs.extend(
            [
                Path(local_app_data) / "CarlaUE4" / "Saved" / "Logs",
                Path(local_app_data) / "CarlaUE4" / "Saved" / "Crashes",
            ]
        )

    carla_root = str(os.environ.get("CARLA_ROOT", "") or "").strip()
    if carla_root:
        search_dirs.append(Path(carla_root) / "CarlaUE4" / "Saved" / "Logs")

    log_candidates: List[Path] = []
    for folder in search_dirs:
        if not folder.exists() or not folder.is_dir():
            continue
        try:
            for path in folder.rglob("*.log"):
                if path.is_file():
                    log_candidates.append(path)
        except Exception:
            continue

    if not log_candidates:
        return ""

    try:
        latest = max(log_candidates, key=lambda p: p.stat().st_mtime)
    except Exception:
        return ""

    dst = output_dir / "carla_latest.log"
    try:
        shutil.copy2(latest, dst)
    except Exception:
        return ""
    return str(dst)
