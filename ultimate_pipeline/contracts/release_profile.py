from __future__ import annotations

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


def resolve_strict_quality_gates(
    profile_name: str,
    *,
    env_override: str | None = None,
    default: bool = True,
) -> bool:
    """Resolve strict quality gates from release profile with env override.

    Precedence: env var > profile default > hardcoded default.
    """
    if env_override is not None:
        lowered = env_override.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
    if profile_name in DEFAULTS:
        return DEFAULTS[profile_name].strict_quality_gates
    return default


def resolve_experimental_unsafe(
    profile_name: str,
    *,
    env_override: str | None = None,
    default: bool = False,
) -> bool:
    """Resolve experimental_unsafe flag from release profile with env override.

    Precedence: env var > profile default > hardcoded default.
    """
    if env_override is not None:
        lowered = env_override.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
    if profile_name in DEFAULTS:
        return DEFAULTS[profile_name].experimental_unsafe
    return default
