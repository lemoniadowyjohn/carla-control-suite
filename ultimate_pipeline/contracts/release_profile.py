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
    return _resolve_profile_default(profile_name, "experimental_unsafe", default)


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
