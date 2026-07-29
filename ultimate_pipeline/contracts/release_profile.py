from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping, Any
from .stage_contracts import ReleaseProfile


@dataclass(frozen=True)
class ReleaseDefaults:
    profile: ReleaseProfile
    enable_sidewalks: bool = False
    enable_realism: bool = False
    enable_realism_rules: bool = False
    enable_synthetic_traffic_lights: bool = False
    enable_lane_synthesis: bool = False
    strict_tile_semantics: bool = True
    strict_quality_gates: bool = True
    carla_enable_map_fallback: bool = False
    allow_tile_qa_failure: bool = False
    auto_repair_during_validation: bool = False
    experimental_unsafe: bool = False


DEFAULTS: Mapping[ReleaseProfile, ReleaseDefaults] = {
    "structural_release": ReleaseDefaults(
        profile="structural_release",
        strict_quality_gates=True,
        experimental_unsafe=False,
    ),
    "visual_build": ReleaseDefaults(
        profile="visual_build",
        strict_quality_gates=True,
        experimental_unsafe=False,
    ),
    "scenario_augmentation": ReleaseDefaults(
        profile="scenario_augmentation",
        strict_quality_gates=False,
        experimental_unsafe=False,
    ),
    "debug": ReleaseDefaults(
        profile="debug",
        strict_quality_gates=False,
        experimental_unsafe=True,
    ),
    "experimental_unsafe": ReleaseDefaults(
        profile="experimental_unsafe",
        strict_quality_gates=False,
        experimental_unsafe=True,
    ),
}


_TRUTHY = {"1", "true", "yes", "on"}
_FALSEY = {"0", "false", "no", "off", ""}


def parse_optional_bool_env(name: str) -> bool | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    normalized = raw.strip().lower()
    if normalized in _TRUTHY:
        return True
    if normalized in _FALSEY:
        return False
    raise ValueError(
        f"{name} must be one of "
        f"{sorted(_TRUTHY | _FALSEY)}, got {raw!r}"
    )


def _resolve_profile_default(
    profile_name: str,
    attr: str,
    default: bool,
) -> bool:
    if profile_name in DEFAULTS:
        return bool(getattr(DEFAULTS[profile_name], attr, default))
    return default


def resolve_strict_quality_gates(
    profile_name: str,
    *,
    env_override: str | None = None,
    default: bool = False,
) -> bool:
    if env_override is not None:
        lowered = env_override.strip().lower()
        if lowered in _TRUTHY:
            return True
        if lowered in _FALSEY:
            return False
    return _resolve_profile_default(profile_name, "strict_quality_gates", default)


def resolve_experimental_unsafe(
    profile_name: str,
    *,
    default: bool = False,
) -> bool:
    normalized = str(profile_name or "").strip().lower()
    uppercase_aliases = {
        "development": "structural_release",
        "structural_release": "structural_release",
        "carla_release": "structural_release",
        "visual_release": "visual_build",
        "perception_release": "visual_build",
        "experimental_unsafe": "experimental_unsafe",
    }
    normalized = uppercase_aliases.get(normalized, normalized)
    return _resolve_profile_default(normalized, "experimental_unsafe", default)


def unsafe_lanelink_regen_enabled(settings_obj) -> bool:
    """LaneLink regeneration requires explicit opt-in AND profile permission.

    Returns True only when both conditions hold:
      1) User requested it via ENABLE_LANELINK_REGEN or UP_ENABLE_LANELINK_REGEN
      2) The active release profile permits experimental unsafe operations
    """
    profile_name = str(
        getattr(settings_obj, "RELEASE_PROFILE", "structural_release")
        or "structural_release"
    )
    settings_requested = bool(
        getattr(settings_obj, "ENABLE_LANELINK_REGEN", False)
    )
    env_requested = parse_optional_bool_env("UP_ENABLE_LANELINK_REGEN")
    requested = env_requested if env_requested is not None else settings_requested
    if not requested:
        return False
    return resolve_experimental_unsafe(profile_name)


def unsafe_planview_mutations_enabled(settings_obj) -> bool:
    """PlanView geometry mutations require explicit opt-in AND profile permission.

    Returns True only when both conditions hold:
      1) User requested it via ENABLE_UNSAFE_PLANVIEW_MUTATIONS or env
      2) The active release profile permits experimental unsafe operations
    """
    profile_name = str(
        getattr(settings_obj, "RELEASE_PROFILE", "structural_release")
        or "structural_release"
    )
    settings_requested = bool(
        getattr(settings_obj, "ENABLE_UNSAFE_PLANVIEW_MUTATIONS", False)
    )
    env_requested = parse_optional_bool_env("UP_ENABLE_UNSAFE_PLANVIEW_MUTATIONS")
    requested = env_requested if env_requested is not None else settings_requested
    if not requested:
        return False
    return resolve_experimental_unsafe(profile_name)


def _unsafe_feature_enabled(settings_obj, attr: str, env: str | None = None) -> bool:
    profile_name = str(
        getattr(settings_obj, "RELEASE_PROFILE", "structural_release")
        or "structural_release"
    )
    settings_requested = bool(getattr(settings_obj, attr, False))
    env_requested = parse_optional_bool_env(env) if env else None
    requested = env_requested if env_requested is not None else settings_requested
    if not requested:
        return False
    return resolve_experimental_unsafe(profile_name)


def unsafe_short_segment_merge_enabled(settings_obj) -> bool:
    """Short segment merge (micro-fragment removal) requires opt-in + profile permission.

    Controlled by ENABLE_UNSAFE_SHORT_SEGMENT_MERGE or env UP_ENABLE_UNSAFE_SHORT_SEGMENT_MERGE.
    """
    return _unsafe_feature_enabled(
        settings_obj,
        "ENABLE_UNSAFE_SHORT_SEGMENT_MERGE",
        "UP_ENABLE_UNSAFE_SHORT_SEGMENT_MERGE",
    )


def unsafe_heading_only_smoothing_enabled(settings_obj) -> bool:
    """Heading-only smoothing (no geometry reconstruction) requires opt-in + profile permission.

    Controlled by ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING or env UP_ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING.
    """
    return _unsafe_feature_enabled(
        settings_obj,
        "ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING",
        "UP_ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING",
    )


def unsafe_small_geometry_merge_enabled(settings_obj) -> bool:
    """Same-type small geometry merge requires opt-in + profile permission."""
    return _unsafe_feature_enabled(
        settings_obj,
        "ENABLE_UNSAFE_SMALL_GEOMETRY_MERGE",
        "UP_ENABLE_UNSAFE_SMALL_GEOMETRY_MERGE",
    )


def unsafe_curvature_only_clamp_enabled(settings_obj) -> bool:
    """Curvature-only clamping requires opt-in + profile permission."""
    return _unsafe_feature_enabled(
        settings_obj,
        "ENABLE_UNSAFE_CURVATURE_ONLY_CLAMP",
        "UP_ENABLE_UNSAFE_CURVATURE_ONLY_CLAMP",
    )


def unsafe_geometry_start_recompute_enabled(settings_obj) -> bool:
    """Geometry start recomputation requires opt-in + profile permission."""
    legacy = bool(getattr(settings_obj, "ENABLE_GEOMETRY_START_RECOMPUTE", False))
    modern = bool(getattr(settings_obj, "ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE", False))
    if legacy and not modern:
        class _Compat:
            RELEASE_PROFILE = getattr(settings_obj, "RELEASE_PROFILE", "structural_release")
            ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE = True
        return _unsafe_feature_enabled(
            _Compat,
            "ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE",
            "UP_ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE",
        )
    return _unsafe_feature_enabled(
        settings_obj,
        "ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE",
        "UP_ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE",
    )


def straight_chord_connector_fallback_enabled(settings_obj) -> bool:
    """Straight-chord fallback in junction connector rebuild requires opt-in + profile permission.

    Controlled by ENABLE_STRAIGHT_CHORD_CONNECTOR_FALLBACK or env UP_ENABLE_STRAIGHT_CHORD_CONNECTOR_FALLBACK.
    Reserved for future connector migration; not consumed in this batch.
    """
    return _unsafe_feature_enabled(
        settings_obj,
        "ENABLE_STRAIGHT_CHORD_CONNECTOR_FALLBACK",
        "UP_ENABLE_STRAIGHT_CHORD_CONNECTOR_FALLBACK",
    )
