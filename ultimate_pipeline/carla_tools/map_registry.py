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
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

from ultimate_pipeline.governance.inputs_manifest import sha256_file as _sha256_file


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


# =============================================================================
# OC-58 — Registry integrity machinery (schema, aliases, fingerprint,
# supersession chains, promotion contract, audit).
# =============================================================================
# The PINNED_MAP_REGISTRY below is hand-authored Python data. Nothing here
# trusts it: every entry is schema-validated, alias collisions fail loudly,
# supersession chains are walked for cycles/gaps, and verify_pinned_map()
# returns a verified receipt (bytes + sha both checked), never the raw entry.

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Explicit role vocabulary (OC-58 §3). Anything else (typos included) fails.
SUPPORTED_ROLES: Tuple[str, ...] = ("auto", "manual")

# Structured frame fields (OC-58 §15). Human-readable "frame" text is always
# kept; these add machine-usable identity where proven. Entries without them
# report frame_status = LEGACY_TEXT_ONLY (never invented values).
FRAME_STRUCTURED_FIELDS: Tuple[str, ...] = (
    "frame_id",
    "frame_kind",
    "crs_authority",
    "rebase_dx",
    "rebase_dy",
)

LEGACY_TEXT_ONLY = "LEGACY_TEXT_ONLY"
STRUCTURED_FRAME = "STRUCTURED"


class MapRegistryValidationError(Exception):
    """Registry metadata itself is malformed or contradictory.

    Distinct from MapRegistryDriftError (on-disk content vs a valid pin):
    this means the pin cannot become authoritative in the first place.
    """


def _normalize_sha256(value: Any) -> str:
    """Lowercase + strip; uppercase hex is accepted iff it normalizes (§21).

    Anything else (prefixes like 0x/sha256:, truncation, whitespace inside,
    non-hex) raises MapRegistryValidationError.
    """
    text = str(value if value is not None else "").strip().lower()
    if not SHA256_RE.match(text):
        raise MapRegistryValidationError(
            f"malformed sha256 pin {value!r}: must match ^[0-9a-f]{{64}}$ "
            "after normalization (no prefixes, truncation or whitespace)"
        )
    return text


def _normalize_alias(alias: Any) -> str:
    text = str(alias if alias is not None else "")
    if text != text.strip() or not text.strip():
        raise MapRegistryValidationError(
            f"malformed alias {alias!r}: must be a nonempty string free of "
            "surrounding whitespace"
        )
    return text.strip()


def validate_registry_entry(key: Any, entry: Any) -> Dict[str, Any]:
    """Schema-validate one registry entry; return its normalized form.

    Required: key, path, sha256, bytes (int > 0), role (vocabulary), frame
    (nonempty text). Optional: aliases (default [key]), supersedes_sha256 /
    supersedes_path (validated when present), equivalent_names, structured
    frame_* fields. Never mutates the input.
    """
    if not isinstance(key, str) or not key.strip() or key.strip() != key:
        raise MapRegistryValidationError(f"malformed registry key {key!r}")
    if not isinstance(entry, dict):
        raise MapRegistryValidationError(
            f"registry entry {key!r} must be a dict, got {type(entry).__name__}"
        )
    norm: Dict[str, Any] = {"key": key}

    raw_path = entry.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise MapRegistryValidationError(
            f"registry entry {key!r}: 'path' must be a nonempty string"
        )
    norm["path"] = raw_path.strip()

    norm["sha256"] = _normalize_sha256(entry.get("sha256"))

    raw_bytes = entry.get("bytes")
    if isinstance(raw_bytes, bool) or not isinstance(raw_bytes, int) or raw_bytes <= 0:
        raise MapRegistryValidationError(
            f"registry entry {key!r}: 'bytes' must be an integer > 0, "
            f"got {raw_bytes!r}"
        )
    norm["bytes"] = int(raw_bytes)

    role = entry.get("role")
    # Exact vocabulary match (case-sensitive): "Auto"/"MANUAL" are malformed,
    # not variants. Do not normalize typos into authority.
    if not isinstance(role, str) or role not in SUPPORTED_ROLES:
        raise MapRegistryValidationError(
            f"registry entry {key!r}: unknown role {entry.get('role')!r} "
            f"(supported: {list(SUPPORTED_ROLES)})"
        )
    norm["role"] = role

    frame = entry.get("frame")
    if not isinstance(frame, str) or not frame.strip():
        raise MapRegistryValidationError(
            f"registry entry {key!r}: 'frame' must be nonempty human-readable text"
        )
    norm["frame"] = frame.strip()

    raw_aliases = entry.get("aliases", [key])
    if not isinstance(raw_aliases, (list, tuple, set, frozenset)) or not raw_aliases:
        raise MapRegistryValidationError(
            f"registry entry {key!r}: 'aliases' must be a nonempty collection"
        )
    seen: Set[str] = set()
    aliases: List[str] = []
    for alias in raw_aliases:
        clean = _normalize_alias(alias)
        lowered = clean.lower()
        if lowered in seen:
            raise MapRegistryValidationError(
                f"registry entry {key!r}: duplicate alias {clean!r} "
                "(case-insensitive) within one entry"
            )
        seen.add(lowered)
        aliases.append(clean)
    norm["aliases"] = aliases

    for field in ("supersedes_sha256", "supersedes_path"):
        if entry.get(field) is not None:
            if field == "supersedes_sha256":
                norm[field] = _normalize_sha256(entry[field])
            else:
                if not isinstance(entry[field], str) or not entry[field].strip():
                    raise MapRegistryValidationError(
                        f"registry entry {key!r}: {field!r} must be a "
                        "nonempty string when present"
                    )
                norm[field] = entry[field].strip()

    if entry.get("equivalent_names") is not None:
        if not isinstance(entry["equivalent_names"], (list, tuple)):
            raise MapRegistryValidationError(
                f"registry entry {key!r}: 'equivalent_names' must be a list"
            )
        norm["equivalent_names"] = [_normalize_alias(a) for a in entry["equivalent_names"]]

    frame_structured = True
    for field in ("frame_id", "frame_kind", "crs_authority"):
        if entry.get(field) is None:
            frame_structured = False
        else:
            norm[field] = entry[field]
    # rebase offsets exist only for rebased frames; requiring them on a
    # projected-CRS entry would force invented values (§15).
    if norm.get("frame_kind") == "rebased_local":
        for field in ("rebase_dx", "rebase_dy"):
            value = entry.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise MapRegistryValidationError(
                    f"registry entry {key!r}: rebased frame requires numeric "
                    f"{field!r}, got {value!r}"
                )
            norm[field] = value
    elif frame_structured:
        for field in ("rebase_dx", "rebase_dy"):
            if entry.get(field) is not None:
                norm[field] = entry[field]
    norm["frame_status"] = STRUCTURED_FRAME if frame_structured else LEGACY_TEXT_ONLY
    return norm


def build_alias_authority(
    registry: Dict[str, Dict[str, Any]],
) -> Dict[str, str]:
    """Build alias -> canonical-key authority with collision detection (§6, §7).

    Authority comes from canonical key + declared aliases, so a key always
    resolves even when omitted from its own aliases. Any case-insensitive
    alias claimed by two different keys (including a canonical key colliding
    with another entry's alias) raises MapRegistryValidationError instead of
    letting later assignment silently win. Deterministic: keys sorted.
    """
    authority: Dict[str, str] = {}
    owners: Dict[str, str] = {}

    def _claim(lowered: str, display: str, key: str) -> None:
        if lowered in authority and authority[lowered] != key:
            raise MapRegistryValidationError(
                f"alias collision: {display!r} claimed by both "
                f"{owners[lowered]!r} and {key!r}"
            )
        authority[lowered] = key
        owners.setdefault(lowered, key)

    for key in sorted(registry):
        entry = registry[key]
        if not isinstance(key, str) or not key.strip():
            raise MapRegistryValidationError(f"malformed registry key {key!r}")
        _claim(key.lower(), key, key)  # canonical key always resolves (§7)
        raw_aliases = entry.get("aliases", [key]) if isinstance(entry, dict) else [key]
        if isinstance(raw_aliases, (list, tuple, set, frozenset)):
            for alias in raw_aliases:
                clean = _normalize_alias(alias)
                _claim(clean.lower(), clean, key)
    return authority


def _canonical_registry_form(registry: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Semantically meaningful content only: sorted keys/aliases, normalized
    sha/role/paths. Excludes comments, ordering and timestamps (§9)."""
    form: Dict[str, Any] = {}
    for key in sorted(registry):
        norm = validate_registry_entry(key, registry[key])
        form[key] = {
            "path": norm["path"].replace("\\", "/"),
            "sha256": norm["sha256"],
            "bytes": norm["bytes"],
            "role": norm["role"],
            "frame": norm["frame"],
            "aliases": sorted(a.lower() for a in norm["aliases"]),
            "supersedes_sha256": norm.get("supersedes_sha256"),
            "supersedes_path": (
                norm["supersedes_path"].replace("\\", "/")
                if norm.get("supersedes_path") else None
            ),
            "equivalent_names": sorted(
                (norm.get("equivalent_names") or [])
            ),
            "frame_structured": {
                f: norm[f] for f in FRAME_STRUCTURED_FIELDS if f in norm
            },
            "frame_status": norm["frame_status"],
        }
    return form


def registry_fingerprint(registry: Dict[str, Dict[str, Any]]) -> str:
    """Deterministic registry_sha256 over canonical content (§9).

    Changing any map pin or supersession relation changes the fingerprint;
    reordering keys/aliases does not.
    """
    canonical = json.dumps(
        _canonical_registry_form(registry),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def resolve_contained_path(
    raw_path: str,
    *,
    base_dir: Path,
    allow_external_absolute_paths: bool = False,
) -> Path:
    """Resolve a registry path fail-closed against ``base_dir`` (§5).

    Relative paths must resolve inside ``base_dir`` (``../../escape`` fails).
    Absolute paths outside ``base_dir`` fail unless the explicit
    ``allow_external_absolute_paths`` test/special-workflow policy is set.
    """
    base = Path(base_dir).resolve()
    candidate = Path(raw_path)
    resolved = candidate.resolve() if candidate.is_absolute() else (base / candidate).resolve()
    try:
        resolved.relative_to(base)
        return resolved
    except ValueError:
        if candidate.is_absolute() and allow_external_absolute_paths:
            return resolved
        raise MapRegistryDriftError(
            f"registry path escapes repository: {raw_path!r} resolves to "
            f"{resolved} (outside base {base})"
        ) from None


# =============================================================================
# C13 — Content-addressed pin registry (drift guard)
# =============================================================================
# Separate concern from the name-normalization registry above: this binds
# canonical map roles to CONTENT (sha256), not just names. RQ1/RQ2 need the
# auto<->manual pair referenced by digest so a mutated/mismatched file can
# never silently masquerade as "the" pinned map.
#
# Real drift this guards against (see source/manual/MANUAL_MANIFEST.json):
# Grid0821.xodr and Grid0828.xodr under CARLA Content are byte-identical
# today (same sha256) -- only one distinct manual XODR exists under two
# names. If they ever diverge, or a name gets pointed at the wrong file,
# verify_pinned_map() must fail closed rather than silently resolve.


class MapRegistryDriftError(Exception):
    """A registry name resolved to file content that doesn't match its pin.

    Fail-closed: callers must not proceed with a mismatched, missing, or
    unresolved (LFS pointer not smudged) pinned map.
    """


def _repo_root() -> Path:
    # ultimate_pipeline/carla_tools/map_registry.py -> repo root
    return Path(__file__).resolve().parents[2]


PINNED_MAP_REGISTRY: Dict[str, Dict[str, Any]] = {
    "auto_map_of_record": {
        # 2026-09-17 promotion: regenerated the canonical map after TWO real bugs
        # were fixed in the regen pipeline since the prior pin (2ca342d8, 2026-09-05):
        # (1) 946228f9 -- xodr_carla_hardener.py::_fix_connectivity() was incorrectly
        # stripping ALL road-level <link> elements from junction-connector roads;
        # (2) a13efd91 -- GeometryValidator._validate_road() was deleting a road's
        # entire <planView> (leaving 0 <geometry> children) when every geometry
        # segment was near-zero-length, instead of repairing one segment in place.
        # This regen is the first candidate produced with both fixes applied.
        # Verified directly against final_rebased.xodr before promotion: well-formed
        # XML, 32267 <road> / 3561 <junction> elements matching the pipeline's own
        # structural_signature, ALL 5 roads that previously crashed the pipeline on
        # bug (2) -- 54601, 57919, 64775, 67658, 67798 -- now carry a valid non-empty
        # <planView> (1 repaired geometry segment each, length=0.1m floor), and a
        # full-file scan found 0 roads anywhere with an empty/missing <planView>.
        # Pipeline-internal acceptance (regen_map_of_record.py ->
        # measure_candidate_acceptance.run_gates() -> build_map_acceptance(), the
        # same and only promotion gate this repo runs): valid_for_experiments=True,
        # hard_fail_reasons=[]. Two pre-existing, always-soft-by-design warnings
        # (see map_acceptance.py: lane_count_changes never hard-fails; component_
        # reachability only hard-fails below 0.95 largest-fraction): lane_count_changes
        # unexplained=3007, and component_reachability 3 isolated lane components
        # (largest_component_fraction=0.99793, well above the 0.95 gate floor).
        # component_reachability is within precedent this repo already accepted
        # (the 2026-09-04 deep-audit promotion accepted 27 isolated lane
        # components as soft-only). lane_count_changes has NO prior baseline --
        # 2026-09-17 investigation found the gate itself (8a02e0f1, 2026-09-09)
        # postdates the previous pin (2026-09-05), so 3007 is this gate's
        # FIRST-EVER measurement against this map lineage, not a repeat of an
        # accepted number. Root-caused as non-blocking: OSM lane_count_source
        # provenance tags cover only 0.4% of lanes, so the "explained" bucket
        # is structurally almost-unreachable regardless of map quality -- spot-
        # checked several flagged boundaries and they look like ordinary lane-
        # merge/split topology, not corruption -- but this has never been
        # exhaustively reviewed and remains a genuinely open advisory item.
        # origin_centroid_distance_m=9669.6 (reasonable, post-rebase).
        "path": "campaigns/ingolstadt_cooked_perception_v1/candidate/"
        "ingolstadt_perception_map_of_record_20260916_232831.xodr",
        "sha256": "370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8",
        "bytes": 149799632,
        "role": "auto",
        "frame": "rebased-to-local (dx=832671.676 dy=5458671.104)",
        "frame_id": "ingolstadt_local_rebased",
        "frame_kind": "rebased_local",
        "crs_authority": "local Cartesian via fixed offset from UTM-32N (EPSG:32632)",
        "rebase_dx": 832671.676,
        "rebase_dy": 5458671.104,
        "aliases": ["auto", "auto_map_of_record", "map_of_record", "ingolstadt_auto"],
        # Historical claims (e.g. C14_RQ1_STRUCTURAL_GAP.json) that cite an earlier
        # pin by sha are still valid for what they measured -- resolved against this
        # supersedes chain by tools/validate_thesis_claim_provenance.py rather than
        # failing as drift. Chain: 69b1f520 (pre-C29) -> 744757f3 (C29 building patch,
        # 2026-08-26) -> a5bd01be (WS1.4 junctionfix, 2026-09-02) -> e281367e (deep-audit,
        # 2026-09-04) -> 60a36325 (round-5 hygiene-stage fix, 2026-09-04) ->
        # cb85fc14 (round-6 bridge/tunnel elevation fix, 2026-09-05) ->
        # 847d41bd (reproducibility re-regen, 2026-09-05) ->
        # 2ca342d8 (second reproducibility re-regen, 2026-09-05) ->
        # 370abbbb (this pin, junction-connector-link + degenerate-planView fix
        # regen, 2026-09-17).
        "supersedes_sha256": "2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798",
        "supersedes_path": "campaigns/ingolstadt_cooked_perception_v1/candidate/"
        "ingolstadt_perception_map_of_record_20260905_202847.xodr",
    },
    # Retired pin, kept as its own registry entry (not aliased to "auto") purely so
    # validate_thesis_claim_provenance.py's single-hop supersedes_sha256 lookup can
    # still resolve claims that cite the second-reproregen sha (2ca342d8...) one
    # promotion back. That resolver iterates every PINNED_MAP_REGISTRY entry looking
    # for a supersedes_sha256 match, not just "auto_map_of_record", so this
    # chain-link entry is sufficient without adding multi-hop walking to the
    # resolver itself.
    "auto_map_of_record_reproregen2_superseded": {
        "path": "campaigns/ingolstadt_cooked_perception_v1/candidate/"
        "ingolstadt_perception_map_of_record_20260905_202847.xodr",
        "sha256": "2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798",
        "bytes": 148949722,
        "role": "auto",
        "frame": "rebased-to-local (dx=832671.676 dy=5458671.104)",
        "aliases": ["auto_map_of_record_reproregen2_superseded"],
        "supersedes_sha256": "847d41bd11d85ff468f7e9611e1914959dad3b444ba83002911f20f86fd925bb",
        "supersedes_path": "campaigns/ingolstadt_cooked_perception_v1/candidate/"
        "ingolstadt_perception_map_of_record_20260905_180515.xodr",
    },
    # Retired pin, kept as its own registry entry (not aliased to "auto") purely so
    # validate_thesis_claim_provenance.py's single-hop supersedes_sha256 lookup can
    # still resolve claims that cite the first reproducibility-re-regen sha
    # (847d41bd...) one promotion back. That resolver iterates every
    # PINNED_MAP_REGISTRY entry looking for a supersedes_sha256 match, not just
    # "auto_map_of_record", so this chain-link entry is sufficient without adding
    # multi-hop walking to the resolver itself.
    "auto_map_of_record_reproregen1_superseded": {
        "path": "campaigns/ingolstadt_cooked_perception_v1/candidate/"
        "ingolstadt_perception_map_of_record_20260905_180515.xodr",
        "sha256": "847d41bd11d85ff468f7e9611e1914959dad3b444ba83002911f20f86fd925bb",
        "bytes": 148949722,
        "role": "auto",
        "frame": "rebased-to-local (dx=832671.676 dy=5458671.104)",
        "aliases": ["auto_map_of_record_reproregen1_superseded"],
        "supersedes_sha256": "cb85fc14420479bc5ddee432636c531df3a41377850f999960c484e530f78d46",
        "supersedes_path": "campaigns/ingolstadt_cooked_perception_v1/candidate/"
        "ingolstadt_perception_map_of_record_20260905_131617.xodr",
    },
    # Retired pin, kept as its own registry entry (not aliased to "auto") purely so
    # validate_thesis_claim_provenance.py's single-hop supersedes_sha256 lookup can
    # still resolve claims that cite the round-6 elevation-fix sha (cb85fc14...) one
    # promotion back. That resolver iterates every PINNED_MAP_REGISTRY entry looking
    # for a supersedes_sha256 match, not just "auto_map_of_record", so this
    # chain-link entry is sufficient without adding multi-hop walking to the
    # resolver itself.
    "auto_map_of_record_round6_elevationfix_superseded": {
        "path": "campaigns/ingolstadt_cooked_perception_v1/candidate/"
        "ingolstadt_perception_map_of_record_20260905_131617.xodr",
        "sha256": "cb85fc14420479bc5ddee432636c531df3a41377850f999960c484e530f78d46",
        "bytes": 148949722,
        "role": "auto",
        "frame": "rebased-to-local (dx=832671.676 dy=5458671.104)",
        "aliases": ["auto_map_of_record_round6_elevationfix_superseded"],
        "supersedes_sha256": "60a363258c29b22b4abd1151ea9aa6ab19510cf89107b72f3a2892c933ca0d75",
        "supersedes_path": "campaigns/ingolstadt_cooked_perception_v1/candidate/"
        "ingolstadt_perception_map_of_record_20260904_214501.xodr",
    },
    # Retired pin, kept as its own registry entry (not aliased to "auto") purely so
    # validate_thesis_claim_provenance.py's single-hop supersedes_sha256 lookup can
    # still resolve claims that cite the round-5 hygiene-stage-fix sha (60a36325...)
    # one promotion back. That resolver iterates every PINNED_MAP_REGISTRY entry
    # looking for a supersedes_sha256 match, not just "auto_map_of_record", so this
    # chain-link entry is sufficient without adding multi-hop walking to the
    # resolver itself.
    "auto_map_of_record_round5_hygienefix_superseded": {
        "path": "campaigns/ingolstadt_cooked_perception_v1/candidate/"
        "ingolstadt_perception_map_of_record_20260904_214501.xodr",
        "sha256": "60a363258c29b22b4abd1151ea9aa6ab19510cf89107b72f3a2892c933ca0d75",
        "bytes": 148950126,
        "role": "auto",
        "frame": "rebased-to-local (dx=832671.676 dy=5458671.104)",
        "aliases": ["auto_map_of_record_round5_hygienefix_superseded"],
        "supersedes_sha256": "e281367e5429533a25c809272de697e2a4166c042bf069f89daffbde7f638ba2",
        "supersedes_path": "campaigns/ingolstadt_cooked_perception_v1/candidate/"
        "ingolstadt_perception_map_of_record_20260904_deepaudit.xodr",
    },
    # Retired pin, kept as its own registry entry (not aliased to "auto") purely so
    # validate_thesis_claim_provenance.py's single-hop supersedes_sha256 lookup can
    # still resolve claims that cite the deep-audit sha (e281367e...) two promotions
    # back. That resolver iterates every PINNED_MAP_REGISTRY entry looking for a
    # supersedes_sha256 match, not just "auto_map_of_record", so this chain-link
    # entry is sufficient without adding multi-hop walking to the resolver itself.
    "auto_map_of_record_deepaudit_superseded": {
        "path": "campaigns/ingolstadt_cooked_perception_v1/candidate/"
        "ingolstadt_perception_map_of_record_20260904_deepaudit.xodr",
        "sha256": "e281367e5429533a25c809272de697e2a4166c042bf069f89daffbde7f638ba2",
        "bytes": 148757289,
        "role": "auto",
        "frame": "rebased-to-local (dx=832671.676 dy=5458671.104)",
        "aliases": ["auto_map_of_record_deepaudit_superseded"],
        "supersedes_sha256": "a5bd01be4ef480a09836cec89eb16f8a169f8f3d34527bc65e5d47707b162802",
        "supersedes_path": "campaigns/ingolstadt_cooked_perception_v1/candidate/"
        "ingolstadt_perception_map_of_record_20260902_junctionfix.xodr",
    },
    # Retired pin, kept as its own registry entry (not aliased to "auto") purely so
    # validate_thesis_claim_provenance.py's single-hop supersedes_sha256 lookup can
    # still resolve claims that cite the WS1.4 junctionfix sha (a5bd01be...) two
    # promotions back. That resolver iterates every PINNED_MAP_REGISTRY entry looking
    # for a supersedes_sha256 match, not just "auto_map_of_record", so this
    # chain-link entry is sufficient without adding multi-hop walking to the
    # resolver itself.
    "auto_map_of_record_junctionfix_superseded": {
        "path": "campaigns/ingolstadt_cooked_perception_v1/candidate/"
        "ingolstadt_perception_map_of_record_20260902_junctionfix.xodr",
        "sha256": "a5bd01be4ef480a09836cec89eb16f8a169f8f3d34527bc65e5d47707b162802",
        "bytes": 148757286,
        "role": "auto",
        "frame": "rebased-to-local (dx=832671.676 dy=5458671.104)",
        "aliases": ["auto_map_of_record_junctionfix_superseded"],
        "supersedes_sha256": "744757f3f01da835269b5678eeb269cf5d534984213c551b9c475699aa73aec8",
        "supersedes_path": "campaigns/ingolstadt_cooked_perception_v1/candidate/"
        "ingolstadt_perception_map_of_record_20260819_160350_C29_BUILDING_PATCH.xodr",
    },
    # Retired pin, kept as its own registry entry (not aliased to "auto") purely so
    # validate_thesis_claim_provenance.py's single-hop supersedes_sha256 lookup can
    # still resolve claims that cite the PRE-C29 sha (69b1f520...) three promotions
    # back. That resolver iterates every PINNED_MAP_REGISTRY entry looking for a
    # supersedes_sha256 match, not just "auto_map_of_record", so this chain-link entry
    # is sufficient without adding multi-hop walking to the resolver itself.
    "auto_map_of_record_c29_superseded": {        "path": "campaigns/ingolstadt_cooked_perception_v1/candidate/"
        "ingolstadt_perception_map_of_record_20260819_160350_C29_BUILDING_PATCH.xodr",
        "sha256": "744757f3f01da835269b5678eeb269cf5d534984213c551b9c475699aa73aec8",
        "bytes": 144385542,
        "role": "auto",
        "frame": "rebased-to-local (dx=832671.676 dy=5458671.104)",
        "aliases": ["auto_map_of_record_c29_superseded"],
        "supersedes_sha256": "69b1f52016ebdc3e643616f86161d85789624c94d48e5caf56c53004d534de6e",
        "supersedes_path": "campaigns/ingolstadt_cooked_perception_v1/candidate/"
        "ingolstadt_perception_map_of_record_20260819_160350.xodr",
    },
    # OC-58: chain tail (no predecessor of its own). The 69b1f520 pre-C29 pin
    # was previously referenced only as a supersedes_sha256 with no owning
    # entry, which the chain validator correctly flagged as a missing
    # predecessor. Verified 2026-09-21 against the file on disk (sha256
    # 69b1f520..., 144142210 bytes) before adding: metadata completion only,
    # no active pin changed, no map bytes touched.
    "auto_map_of_record_prec29_superseded": {
        "path": "campaigns/ingolstadt_cooked_perception_v1/candidate/"
        "ingolstadt_perception_map_of_record_20260819_160350.xodr",
        "sha256": "69b1f52016ebdc3e643616f86161d85789624c94d48e5caf56c53004d534de6e",
        "bytes": 144142210,
        "role": "auto",
        "frame": "rebased-to-local (dx=832671.676 dy=5458671.104)",
        "aliases": ["auto_map_of_record_prec29_superseded"],
    },
    "manual_grid0828": {
        "path": "campaigns/ingolstadt_cooked_perception_v1/source/manual/Grid0828.xodr",
        "sha256": "5eaece230e02f6c1b2075db851894870790e86ac64710abb3465bcfc533e9b0c",
        "bytes": 66530869,
        "role": "manual",
        "frame": "UTM-32N (+proj=tmerc +lon_0=9 +k=0.9996 +x_0=500000)",
        "frame_id": "UTM-32N",
        "frame_kind": "projected_crs",
        "crs_authority": "EPSG:32632 (+proj=tmerc +lon_0=9 +k=0.9996 +x_0=500000)",
        # Grid0821 is byte-identical to Grid0828 on this machine (verified
        # sha256 match) -- both names resolve to this ONE pinned entry.
        # OC-58 §13: same-content/same-role sharing must be EXPLICIT, never
        # inferred from a hash coincidence.
        "equivalent_names": ["Grid0821", "Grid0828"],
        "aliases": ["manual_grid0828", "Grid0828", "Grid0821", "manual", "manual_reference"],
    },
}

# Built through the collision-detecting authority (§6): import time is the
# first registry validation gate -- a duplicate alias fails loudly here,
# never silently resolves to whichever entry was assigned last.
_ALIAS_TO_KEY: Dict[str, str] = build_alias_authority(PINNED_MAP_REGISTRY)


def verify_pinned_map(
    name: str,
    *,
    base_dir: Optional[Path] = None,
    registry: Optional[Dict[str, Dict[str, Any]]] = None,
    allow_external_absolute_paths: bool = True,
) -> Dict[str, Any]:
    """Resolve ``name`` to its pinned registry entry and verify on-disk content.

    Fail-closed: raises MapRegistryValidationError for malformed registry
    metadata (bad SHA/bytes/role/alias/path) or alias collisions, LookupError
    for an unregistered name, and MapRegistryDriftError for a missing file,
    un-smudged git-LFS pointer, byte-size mismatch, or content drift.

    Args:
        name: canonical key or any registered alias (case-insensitive).
        base_dir: repo root for resolving relative paths (default: this
            file's actual repo root -- override only for tests).
        registry: pin registry to resolve against (default: the real,
            module-level PINNED_MAP_REGISTRY -- override only for tests).
        allow_external_absolute_paths: explicit policy permitting absolute
            registry paths outside ``base_dir`` (test/special-workflow
            affordance; production entries must be repository-contained).
            Relative-path escape (``../../x``) always fails.

    Returns:
        A verified receipt (never the raw registry entry). Backward
        compatible: ``result["path"]`` (declared path) and
        ``result["sha256"]`` (verified digest) keep their historical meaning;
        the verified identity is explicit in ``resolved_path``,
        ``sha256_expected/actual``, ``bytes_expected/actual``,
        ``registry_key`` and ``verification_status``.
    """
    reg = registry if registry is not None else PINNED_MAP_REGISTRY
    alias_map = build_alias_authority(reg)

    requested = str(name)
    key = alias_map.get(requested.lower())
    if key is None:
        raise LookupError(
            f"'{name}' is not a registered pinned map (known: {sorted(alias_map)})"
        )
    norm = validate_registry_entry(key, reg[key])

    root = base_dir if base_dir is not None else _repo_root()
    resolved = resolve_contained_path(
        norm["path"],
        base_dir=Path(root),
        allow_external_absolute_paths=allow_external_absolute_paths,
    )
    if not resolved.is_file():
        raise MapRegistryDriftError(
            f"pinned map '{name}' -> '{key}': file not found at {resolved}"
        )

    # A real git-lfs pointer stub is a small text file starting with the
    # spec header; catch it before hashing so the error is actionable
    # instead of a confusing sha256 mismatch.
    try:
        head = resolved.read_bytes()[:64]
    except OSError as exc:
        raise MapRegistryDriftError(f"pinned map '{name}' -> '{key}': cannot read {resolved}: {exc}") from exc
    if head.startswith(b"version https://git-lfs"):
        raise MapRegistryDriftError(
            f"pinned map '{name}' -> '{key}': {resolved} is an un-smudged git-LFS pointer, "
            "not the real content. Run `git lfs pull` (or `git lfs install` first)."
        )

    actual_bytes = resolved.stat().st_size
    if actual_bytes != norm["bytes"]:
        raise MapRegistryDriftError(
            f"pinned map '{name}' -> '{key}': byte-size mismatch at {resolved} "
            f"(expected bytes={norm['bytes']}, actual bytes={actual_bytes})"
        )

    actual_sha256 = _sha256_file(resolved)
    expected_sha256 = norm["sha256"]
    if actual_sha256 != expected_sha256:
        raise MapRegistryDriftError(
            f"pinned map '{name}' -> '{key}': content drift at {resolved} "
            f"(expected sha256={expected_sha256}, actual={actual_sha256})"
        )

    return {
        # Backward-compatible pin identity (declared values, now proven).
        "path": norm["path"],
        "sha256": actual_sha256,
        "bytes": actual_bytes,
        "role": norm["role"],
        "frame": norm["frame"],
        # Explicit verified identity (§8).
        "registry_key": key,
        "requested_name": requested,
        "resolved_path": str(resolved),
        "declared_path": norm["path"],
        "sha256_expected": expected_sha256,
        "sha256_actual": actual_sha256,
        "bytes_expected": norm["bytes"],
        "bytes_actual": actual_bytes,
        "verification_status": "VERIFIED",
        "registry_sha256": registry_fingerprint(reg),
    }


# =============================================================================
# OC-58 §10/§12 — Supersession-chain validation
# =============================================================================

def _predecessor_key_for(
    key: str,
    norm_entries: Dict[str, Dict[str, Any]],
) -> Optional[str]:
    """Registry key of ``key``'s direct predecessor, or None for chain tails.

    The predecessor is the entry whose sha256 equals this entry's
    supersedes_sha256. A supersedes_sha256 matching NO entry's sha256 is a
    missing predecessor (reported by the caller, not silently skipped).
    """
    supersedes = norm_entries[key].get("supersedes_sha256")
    if not supersedes:
        return None
    for other, other_norm in norm_entries.items():
        if other != key and other_norm["sha256"] == supersedes:
            return other
    return None


def validate_supersession_chains(
    registry: Dict[str, Dict[str, Any]],
    *,
    base_dir: Optional[Path] = None,
    verify_historical_files: bool = True,
) -> Dict[str, Any]:
    """Walk every entry's supersession chain fail-closed (§10, §12).

    Detects cycles (including A-supersedes-A), missing predecessors,
    supersedes_sha256 values that match no registry entry, supersedes_path
    pointing at a different entry's file than the sha-matched predecessor,
    role changes through a chain, repeated SHAs with incompatible metadata,
    and hash-mismatched historical files still on disk. Missing historical
    files are warnings (pruned history), not errors.

    Returns per-entry chains: chain_depth / chain_keys / chain_sha256s /
    chain_status, plus global errors/warnings.
    """
    norm_entries: Dict[str, Dict[str, Any]] = {}
    for key in registry:
        norm_entries[key] = validate_registry_entry(key, registry[key])

    errors: List[str] = []
    warnings: List[str] = []
    chains: Dict[str, Dict[str, Any]] = {}

    sha_owners: Dict[str, List[str]] = {}
    for key, norm in norm_entries.items():
        sha_owners.setdefault(norm["sha256"], []).append(key)
    for sha, owners in sha_owners.items():
        if len(owners) > 1:
            roles = {norm_entries[o]["role"] for o in owners}
            byted = {norm_entries[o]["bytes"] for o in owners}
            cross_role_override = any(
                isinstance(registry.get(o), dict)
                and registry[o].get("allow_cross_role_content") is True
                for o in owners
            )
            # Same-content classification is owned by
            # validate_content_and_roles (explicit equivalent_names /
            # test-only cross-role override); the chain validator only
            # reports genuinely incompatible metadata here.
            if (len(roles) > 1 or len(byted) > 1) and not cross_role_override:
                errors.append(
                    f"repeated sha256 {sha[:12]}... with incompatible metadata "
                    f"in {sorted(owners)} (roles={sorted(roles)}, bytes={sorted(byted)})"
                )

    root = Path(base_dir) if base_dir is not None else _repo_root()

    for key in sorted(norm_entries):
        chain_keys: List[str] = [key]
        chain_shas: List[str] = [norm_entries[key]["sha256"]]
        seen: Set[str] = {key}
        status = "OK"
        cursor = key
        while True:
            norm = norm_entries[cursor]
            supersedes = norm.get("supersedes_sha256")
            if not supersedes:
                break
            if supersedes == norm["sha256"]:
                status = "CYCLE"
                errors.append(
                    f"supersession cycle detected: {cursor!r} supersedes itself"
                )
                break
            pred = _predecessor_key_for(cursor, norm_entries)
            if pred is None:
                status = "MISSING_PREDECESSOR"
                errors.append(
                    f"chain break at {cursor!r}: supersedes_sha256 "
                    f"{supersedes[:12]}... matches no registry entry sha256"
                )
                break
            if pred in seen:
                cycle = chain_keys[chain_keys.index(pred):] + [pred] if pred in chain_keys else [cursor, pred]
                status = "CYCLE"
                errors.append(
                    f"supersession cycle detected: {' -> '.join(cycle)}"
                )
                break
            # supersedes_path must name the predecessor's file, not another
            # entry's (§10 "pointing to the wrong registry entry").
            pred_path = norm_entries[pred]["path"].replace("\\", "/")
            declared_prev = (norm.get("supersedes_path") or "").replace("\\", "/")
            if declared_prev and declared_prev != pred_path:
                status = "WRONG_PREDECESSOR_PATH"
                errors.append(
                    f"{cursor!r}: supersedes_path {declared_prev!r} does not "
                    f"name the sha-matched predecessor {pred!r} "
                    f"(path {pred_path!r})"
                )
                break
            if norm_entries[pred]["role"] != norm_entries[key]["role"]:
                status = "ROLE_CHANGE"
                errors.append(
                    f"{cursor!r}: role change through supersession chain "
                    f"({norm_entries[key]['role']!r} -> "
                    f"{norm_entries[pred]['role']!r} at {pred!r})"
                )
                break
            if verify_historical_files and declared_prev:
                hist = (root / declared_prev).resolve() if not Path(declared_prev).is_absolute() else Path(declared_prev)
                if hist.is_file():
                    try:
                        actual = _sha256_file(hist)
                    except OSError as exc:
                        status = "HISTORICAL_UNREADABLE"
                        errors.append(f"{cursor!r}: cannot read historical {hist}: {exc}")
                        break
                    if actual != supersedes:
                        status = "HISTORICAL_DRIFT"
                        errors.append(
                            f"{cursor!r}: historical file {hist} drifted "
                            f"(expected {supersedes[:12]}..., actual {actual[:12]}...)"
                        )
                        break
                else:
                    warnings.append(
                        f"{cursor!r}: historical supersedes_path not on disk "
                        f"({declared_prev!r}) -- history pruned, chain trusted "
                        "by registry metadata only"
                    )
            seen.add(pred)
            chain_keys.append(pred)
            chain_shas.append(norm_entries[pred]["sha256"])
            cursor = pred

        chains[key] = {
            "chain_depth": len(chain_keys) - 1,
            "chain_keys": chain_keys,
            "chain_sha256s": chain_shas,
            "chain_status": status,
        }

    predecessor_keys = {
        _predecessor_key_for(k, norm_entries) for k in norm_entries
    } - {None}
    heads = sorted(set(norm_entries) - predecessor_keys)
    return {
        "chains": chains,
        "head_keys": heads,
        "errors": errors,
        "warnings": warnings,
        "valid": not errors,
    }


# =============================================================================
# OC-58 §11/§18 — Historical SHA chain resolver (replaces single-hop lookup)
# =============================================================================

def resolve_historical_sha(
    sha: str,
    *,
    registry: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """Resolve ANY registered historical SHA to its full chain position.

    Returns historical_registry_key / historical_sha / historical_path /
    current_successor_key / current_successor_sha / supersession_distance.
    The result remains bound to its historical SHA -- it is never reinterpreted
    as measured against the newest map. Returns None for unregistered SHAs
    (callers must then require an explicit legacy provenance record, §18).

    Deliberately structural (no full schema validation): provenance tooling
    must resolve minimal/legacy registries, not just fully valid ones.
    Malformed entries are skipped, never matched.
    """
    reg = registry if registry is not None else PINNED_MAP_REGISTRY
    try:
        needle = _normalize_sha256(sha)
    except MapRegistryValidationError:
        return None

    def _entry_sha(entry: Any) -> str:
        return _safe_norm_sha(entry.get("sha256")) if isinstance(entry, dict) else ""

    def _entry_supersedes(entry: Any) -> str:
        return _safe_norm_sha(entry.get("supersedes_sha256")) if isinstance(entry, dict) else ""
    sha_owners: Dict[str, str] = {}
    for k in sorted(reg):
        esha = _entry_sha(reg[k])
        if esha and esha not in sha_owners:
            sha_owners[esha] = k

    if needle in sha_owners:
        hist_key = sha_owners[needle]
        hist_sha = needle
        hist_entry = reg[hist_key]
        hist_path = hist_entry.get("path", "") if isinstance(hist_entry, dict) else ""
        cursor_sha = needle
        distance = 0
    else:
        # Tail beyond the registry (a supersedes_sha256 no entry owns as its
        # own sha): the child entry documents the historical file.
        child = None
        for k in sorted(reg):
            if _entry_supersedes(reg[k]) == needle:
                child = k
                break
        if child is None:
            return None
        child_entry = reg[child]
        hist_key = child
        hist_sha = needle
        hist_path = (child_entry.get("supersedes_path")
                     or child_entry.get("path", ""))
        cursor_sha = needle
        distance = 0

    # Walk forward (who supersedes this sha, transitively) to the live head.
    successor_key = hist_key
    guard = 0
    while guard <= len(reg):
        guard += 1
        parent = None
        for k in sorted(reg):
            if k != successor_key and _entry_supersedes(reg[k]) == cursor_sha:
                parent = k
                break
        if parent is None:
            break
        successor_key = parent
        cursor_sha = _entry_sha(reg[parent]) or cursor_sha
        distance += 1

    successor_sha = _entry_sha(reg[successor_key])
    return {
        "historical_registry_key": hist_key,
        "historical_sha": hist_sha,
        "historical_path": hist_path,
        "current_successor_key": successor_key,
        "current_successor_sha": successor_sha,
        "supersession_distance": int(distance),
    }


# =============================================================================
# OC-58 §9 — Registry fingerprint is registry_fingerprint() above.
# OC-58 §13/§14 — Content-identity and role-collision validation
# =============================================================================

def validate_content_and_roles(
    registry: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Classify same-content relationships; reject contradictions (§13, §14).

    - same SHA + same role: allowed ONLY when explicitly declared via
      equivalent_names on (at least) the resolving entry; classified
      same_content_same_role. Otherwise error (silent aliasing).
    - same SHA in both auto and manual authority: error unless the entry
      carries an explicit test-only override
      (allow_cross_role_content: true). An auto-vs-manual comparison is
      meaningless if both sides are the same bytes.
    """
    norm_entries = {k: validate_registry_entry(k, v) for k, v in registry.items()}
    errors: List[str] = []
    warnings: List[str] = []
    groups: List[Dict[str, Any]] = []

    by_sha: Dict[str, List[str]] = {}
    for key, norm in norm_entries.items():
        by_sha.setdefault(norm["sha256"], []).append(key)

    for sha in sorted(by_sha):
        owners = sorted(by_sha[sha])
        if len(owners) < 2:
            continue
        roles = sorted({norm_entries[o]["role"] for o in owners})
        if len(roles) > 1:
            override = any(
                registry[o].get("allow_cross_role_content") is True for o in owners
            )
            if not override:
                errors.append(
                    f"cross-role content collision: sha {sha[:12]}... is "
                    f"authoritative as {roles} in {owners} -- auto-vs-manual "
                    "comparison would be vacuous (override: "
                    "allow_cross_role_content: true, test-only)"
                )
                groups.append({
                    "sha256": sha, "keys": owners, "roles": roles,
                    "classification": "REJECTED_cross_role_authority",
                })
                continue
            groups.append({
                "sha256": sha, "keys": owners, "roles": roles,
                "classification": "OVERRIDDEN_cross_role_test_only",
            })
            warnings.append(
                f"cross-role content collision for {sha[:12]}... explicitly "
                "overridden (test-only)"
            )
            continue
        declared = set()
        for o in owners:
            declared.update(norm_entries[o].get("equivalent_names") or [])
        if not declared:
            errors.append(
                f"undeclared content sharing: sha {sha[:12]}... shared by "
                f"{owners} (role {roles[0]!r}) without equivalent_names -- "
                "declare the relationship explicitly or split the pins"
            )
            groups.append({
                "sha256": sha, "keys": owners, "roles": roles,
                "classification": "REJECTED_undeclared_sharing",
            })
            continue
        groups.append({
            "sha256": sha, "keys": owners, "roles": roles,
            "classification": "same_content_same_role",
            "equivalent_names": sorted(declared),
        })
    return {"groups": groups, "errors": errors, "warnings": warnings,
            "valid": not errors}


def validate_frame_metadata(
    registry: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Report structured vs legacy frame status per entry (§15)."""
    report: Dict[str, Any] = {}
    for key in sorted(registry):
        norm = validate_registry_entry(key, registry[key])
        report[key] = {
            "frame": norm["frame"],
            "frame_status": norm["frame_status"],
            "frame_structured": {
                f: norm[f] for f in FRAME_STRUCTURED_FIELDS if f in norm
            },
        }
    return report


def validate_registry(
    registry: Dict[str, Dict[str, Any]],
    *,
    base_dir: Optional[Path] = None,
    verify_historical_files: bool = True,
    require_repo_contained_paths: bool = True,
) -> Dict[str, Any]:
    """Registry-wide validation: schema, aliases, content/roles, chains (§20).

    Returns a machine-readable verdict (valid/errors/warnings/...). Raises
    nothing: use ``assert_valid_registry`` for fail-closed gating.
    """
    errors: List[str] = []
    warnings: List[str] = []

    norm_entries: Dict[str, Dict[str, Any]] = {}
    for key in registry:
        try:
            norm_entries[key] = validate_registry_entry(key, registry[key])
        except MapRegistryValidationError as exc:
            errors.append(str(exc))

    alias_map: Dict[str, str] = {}
    try:
        alias_map = build_alias_authority(registry)
    except MapRegistryValidationError as exc:
        errors.append(str(exc))

    if require_repo_contained_paths:
        root = Path(base_dir) if base_dir is not None else _repo_root()
        for key, norm in norm_entries.items():
            raw = norm["path"]
            if Path(raw).is_absolute():
                errors.append(
                    f"{key!r}: production registry entry uses absolute path "
                    f"{raw!r} -- must be repository-contained"
                )
                continue
            resolved = (root.resolve() / raw).resolve()
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                errors.append(
                    f"{key!r}: path escapes repository: {raw!r} -> {resolved}"
                )

    content = validate_content_and_roles(registry) if not errors else None
    if content is None:
        content = {"groups": [], "errors": [], "warnings": [], "valid": True}
    errors.extend(content["errors"])
    warnings.extend(content["warnings"])

    chains = validate_supersession_chains(
        registry, base_dir=base_dir, verify_historical_files=verify_historical_files,
    )
    errors.extend(chains["errors"])
    warnings.extend(chains["warnings"])

    return {
        "valid": not errors,
        "registry_sha256": (
            registry_fingerprint(registry) if not errors else "INVALID"
        ),
        "entry_count": len(registry),
        "alias_count": len(alias_map),
        "active_map_roles": sorted({n["role"] for n in norm_entries.values()}),
        "errors": errors,
        "warnings": warnings,
        "content_groups": content["groups"],
        "supersession_chains": chains["chains"],
        "head_keys": chains["head_keys"],
        "frame_report": validate_frame_metadata(registry),
    }


def assert_valid_registry(
    registry: Dict[str, Dict[str, Any]],
    *,
    base_dir: Optional[Path] = None,
    verify_historical_files: bool = True,
    require_repo_contained_paths: bool = True,
) -> Dict[str, Any]:
    """Fail-closed gate: raise MapRegistryValidationError unless valid."""
    report = validate_registry(
        registry,
        base_dir=base_dir,
        verify_historical_files=verify_historical_files,
        require_repo_contained_paths=require_repo_contained_paths,
    )
    if not report["valid"]:
        raise MapRegistryValidationError(
            "map registry INVALID:\n- " + "\n- ".join(report["errors"])
        )
    return report


# =============================================================================
# OC-58 §16 — Map-of-record promotion contract (validates, never edits)
# =============================================================================

def validate_candidate_registry_entry(
    *,
    key: str,
    path: str,
    sha256: str,
    bytes: int,
    role: str,
    frame: str,
    aliases: List[str],
    registry: Dict[str, Dict[str, Any]],
    base_dir: Optional[Path] = None,
    supersedes_sha256: Optional[str] = None,
    supersedes_path: Optional[str] = None,
    allow_external_absolute_paths: bool = False,
) -> Dict[str, Any]:
    """Pre-pin contract for a new map-of-record candidate (§16).

    Checks file existence, LFS-pointer absence, SHA/bytes match, role/frame/
    path validity, alias non-conflict, predecessor validity, and that the
    registry as a whole still validates WITH the candidate added. Returns a
    report dict (ok/checks/errors) -- promotion itself stays an explicit,
    separate edit of PINNED_MAP_REGISTRY.
    """
    checks: Dict[str, Any] = {}
    errors: List[str] = []

    candidate = {
        "path": path, "sha256": sha256, "bytes": bytes, "role": role,
        "frame": frame, "aliases": list(aliases),
    }
    if supersedes_sha256 is not None:
        candidate["supersedes_sha256"] = supersedes_sha256
    if supersedes_path is not None:
        candidate["supersedes_path"] = supersedes_path

    try:
        norm = validate_registry_entry(key, candidate)
        checks["schema"] = "PASS"
    except MapRegistryValidationError as exc:
        checks["schema"] = f"FAIL: {exc}"
        errors.append(f"schema: {exc}")
        return {"ok": False, "checks": checks, "errors": errors}

    root = Path(base_dir) if base_dir is not None else _repo_root()
    try:
        resolved = resolve_contained_path(
            norm["path"], base_dir=root,
            allow_external_absolute_paths=allow_external_absolute_paths,
        )
        checks["path_containment"] = f"PASS: {resolved}"
    except (MapRegistryDriftError, MapRegistryValidationError) as exc:
        checks["path_containment"] = f"FAIL: {exc}"
        errors.append(f"path_containment: {exc}")
        return {"ok": False, "checks": checks, "errors": errors}

    if not resolved.is_file():
        checks["file_exists"] = f"FAIL: not found at {resolved}"
        errors.append(f"file_exists: not found at {resolved}")
        return {"ok": False, "checks": checks, "errors": errors}
    checks["file_exists"] = "PASS"

    try:
        if resolved.read_bytes()[:64].startswith(b"version https://git-lfs"):
            checks["lfs_pointer"] = "FAIL: un-smudged git-LFS pointer"
            errors.append("lfs_pointer: un-smudged git-LFS pointer")
            return {"ok": False, "checks": checks, "errors": errors}
    except OSError as exc:
        checks["lfs_pointer"] = f"FAIL: unreadable: {exc}"
        errors.append(f"lfs_pointer: {exc}")
        return {"ok": False, "checks": checks, "errors": errors}
    checks["lfs_pointer"] = "PASS"

    actual_bytes = resolved.stat().st_size
    if actual_bytes != norm["bytes"]:
        checks["bytes_match"] = (
            f"FAIL: expected {norm['bytes']}, actual {actual_bytes}"
        )
        errors.append(checks["bytes_match"])
    else:
        checks["bytes_match"] = "PASS"

    actual_sha = _sha256_file(resolved)
    if actual_sha != norm["sha256"]:
        checks["sha_match"] = (
            f"FAIL: expected {norm['sha256'][:12]}..., actual {actual_sha[:12]}..."
        )
        errors.append(checks["sha_match"])
    else:
        checks["sha_match"] = "PASS"

    # Alias non-conflict against the live registry (plus own key).
    try:
        trial = dict(registry)
        trial[key] = candidate
        build_alias_authority(trial)
        checks["alias_set_non_conflicting"] = "PASS"
    except MapRegistryValidationError as exc:
        checks["alias_set_non_conflicting"] = f"FAIL: {exc}"
        errors.append(f"alias_set_non_conflicting: {exc}")

    if norm.get("supersedes_sha256"):
        match = [
            k for k, e in registry.items()
            if isinstance(e, dict)
            and _safe_norm_sha(e.get("sha256")) == norm["supersedes_sha256"]
        ]
        if not match:
            checks["supersession_predecessor"] = (
                f"FAIL: supersedes_sha256 {norm['supersedes_sha256'][:12]}... "
                "matches no registry entry"
            )
            errors.append(checks["supersession_predecessor"])
        else:
            checks["supersession_predecessor"] = f"PASS: {match}"
    else:
        checks["supersession_predecessor"] = "SKIP (no predecessor claimed)"

    if not errors:
        trial = dict(registry)
        trial[key] = candidate
        report = validate_registry(
            trial, base_dir=root,
            verify_historical_files=True,
            # Absolute-path test workflows opt out of containment here, exactly
            # as they do for the candidate itself; production (external paths
            # disallowed) still enforces repository containment registry-wide.
            require_repo_contained_paths=not allow_external_absolute_paths,
        )
        if report["valid"]:
            checks["registry_wide_still_valid"] = "PASS"
        else:
            checks["registry_wide_still_valid"] = (
                f"FAIL: {report['errors']}"
            )
            errors.extend(f"registry_wide: {e}" for e in report["errors"])
    else:
        checks["registry_wide_still_valid"] = "SKIP (earlier failures)"

    return {"ok": not errors, "checks": checks, "errors": errors,
            "resolved_path": str(resolved)}


def _safe_norm_sha(value: Any) -> str:
    try:
        return _normalize_sha256(value)
    except MapRegistryValidationError:
        return ""


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


# =============================================================================
# OC-58 §19 — Deterministic audit tool (no map mutation)
# =============================================================================

def audit_registry(
    registry: Optional[Dict[str, Dict[str, Any]]] = None,
    *,
    base_dir: Optional[Path] = None,
    verify_historical_files: bool = True,
    verify_active_files: bool = True,
) -> Dict[str, Any]:
    """Machine-readable registry audit (§19).

    No map mutation. Verifies active pinned files on disk when present
    (missing active files are ERRORS -- an authority that cannot be read
    cannot be authoritative), then runs the full registry validation.
    """
    reg = registry if registry is not None else PINNED_MAP_REGISTRY
    root = Path(base_dir) if base_dir is not None else _repo_root()
    errors: List[str] = []
    warnings: List[str] = []
    entries: Dict[str, Any] = {}

    try:
        alias_map = build_alias_authority(reg)
        alias_collisions: List[str] = []
    except MapRegistryValidationError as exc:
        alias_map = {}
        alias_collisions = [str(exc)]
        errors.append(str(exc))

    for key in sorted(reg):
        raw = reg[key]
        rec: Dict[str, Any] = {"key": key}
        try:
            norm = validate_registry_entry(key, raw)
            rec["schema"] = "PASS"
        except MapRegistryValidationError as exc:
            rec["schema"] = f"FAIL: {exc}"
            errors.append(f"{key!r}: {exc}")
            entries[key] = rec
            continue
        rec.update({
            "path": norm["path"],
            "sha256": norm["sha256"],
            "bytes": norm["bytes"],
            "role": norm["role"],
            "frame": norm["frame"],
            "frame_status": norm["frame_status"],
            "aliases": norm["aliases"],
        })
        if verify_active_files:
            try:
                resolved = resolve_contained_path(
                    norm["path"], base_dir=root,
                    allow_external_absolute_paths=False,
                )
            except (MapRegistryDriftError, MapRegistryValidationError) as exc:
                rec["file"] = f"FAIL: {exc}"
                errors.append(f"{key!r}: {exc}")
                entries[key] = rec
                continue
            if not resolved.is_file():
                rec["file"] = f"FAIL: not found at {resolved}"
                errors.append(f"{key!r}: active file missing: {resolved}")
            else:
                actual_bytes = resolved.stat().st_size
                actual_sha = _sha256_file(resolved)
                rec["file"] = str(resolved)
                rec["bytes_match"] = actual_bytes == norm["bytes"]
                rec["sha_match"] = actual_sha == norm["sha256"]
                if not rec["bytes_match"] or not rec["sha_match"]:
                    errors.append(
                        f"{key!r}: on-disk drift at {resolved} "
                        f"(bytes {actual_bytes}/{norm['bytes']}, "
                        f"sha {actual_sha[:12]}.../{norm['sha256'][:12]}...)"
                    )
        entries[key] = rec

    validation = validate_registry(
        reg, base_dir=root, verify_historical_files=verify_historical_files,
    )
    errors.extend(e for e in validation["errors"] if e not in errors)
    warnings.extend(validation["warnings"])

    return {
        "registry_valid": not errors,
        "registry_sha256": (
            registry_fingerprint(reg) if not errors else "INVALID"
        ),
        "entry_count": len(reg),
        "alias_count": len(alias_map),
        "active_map_roles": validation["active_map_roles"],
        "entries": entries,
        "alias_collisions": alias_collisions,
        "content_collisions": validation["content_groups"],
        "supersession_chains": validation["supersession_chains"],
        "errors": errors,
        "warnings": warnings,
    }


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="Fail-closed audit of PINNED_MAP_REGISTRY (no mutation)."
    )
    ap.add_argument("--audit", action="store_true",
                    help="write machine-readable map_registry_audit.json")
    ap.add_argument("--out", type=Path,
                    default=Path("map_registry_audit.json"))
    ap.add_argument("--no-verify-files", action="store_true",
                    help="skip on-disk verification (metadata-only audit)")
    args = ap.parse_args(argv)

    if not args.audit:
        ap.print_help()
        return 2
    report = audit_registry(verify_historical_files=not args.no_verify_files,
                            verify_active_files=not args.no_verify_files)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"[map_registry] valid={report['registry_valid']} "
          f"registry_sha256={report['registry_sha256']} -> {args.out}")
    for err in report["errors"]:
        print(f"[map_registry] ERROR: {err}")
    return 0 if report["registry_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
