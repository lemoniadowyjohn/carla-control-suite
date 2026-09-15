from __future__ import annotations

from enum import StrEnum, auto
from dataclasses import dataclass


class ReleaseProfile(StrEnum):
    STRUCTURAL_RELEASE = "structural_release"
    VISUAL_BUILD = "visual_build"
    SCENARIO_AUGMENTATION = "scenario_augmentation"
    DEBUG = "debug"
    EXPERIMENTAL_UNSAFE = "experimental_unsafe"


# Explicit aliases for historical / env-driven profile names
_RELEASE_PROFILE_ALIASES: dict[str, ReleaseProfile] = {
    "development": ReleaseProfile.STRUCTURAL_RELEASE,
    "structural_release": ReleaseProfile.STRUCTURAL_RELEASE,
    "carla_release": ReleaseProfile.STRUCTURAL_RELEASE,
    "visual_release": ReleaseProfile.VISUAL_BUILD,
    "perception_release": ReleaseProfile.VISUAL_BUILD,
    "experimental_unsafe": ReleaseProfile.EXPERIMENTAL_UNSAFE,
}


def resolve_release_profile(profile_name: str) -> ReleaseProfile:
    """Resolve a profile name to a ReleaseProfile enum member.

    Raises ValueError if the profile name is unknown.
    """
    if profile_name is None:
        raise ValueError("Release profile name cannot be None")
    normalized = str(profile_name).strip()
    if normalized in _RELEASE_PROFILE_ALIASES:
        return _RELEASE_PROFILE_ALIASES[normalized]
    # Direct match against enum members
    try:
        return ReleaseProfile(normalized)
    except ValueError:
        raise ValueError(
            f"Unknown release profile: {profile_name!r}. "
            f"Valid profiles: {', '.join(m.value for m in ReleaseProfile)}"
        )


class QualityStatus(StrEnum):
    """Shared status vocabulary for quality checkers."""

    PASS = auto()
    FAIL = auto()
    INCOMPLETE = auto()
    NOT_RUN = auto()
    BLOCKED_EXTERNAL = auto()
    WAIVED = auto()


# Legacy Boolean mapping: True -> PASS, False -> FAIL
LEGACY_BOOLEAN_MAP = {
    True: QualityStatus.PASS,
    False: QualityStatus.FAIL,
}


def from_legacy_bool(value: bool) -> QualityStatus:
    """Convert a legacy Boolean checker result to QualityStatus.

    Rules:
        True  -> PASS
        False -> FAIL
    """
    return LEGACY_BOOLEAN_MAP[value]


def from_legacy_exception(exc: Exception | None) -> QualityStatus:
    """Convert a legacy exception-based checker to QualityStatus.

    Rules:
        exception present -> FAIL or INCOMPLETE according to explicit policy
        No exception      -> PASS (if all other checks pass)
    """
    if exc is not None:
        return QualityStatus.FAIL
    return QualityStatus.PASS


def from_skipped_mandatory() -> QualityStatus:
    """A skipped mandatory checker returns INCOMPLETE (never PASS)."""
    return QualityStatus.INCOMPLETE


def from_missing_external(runtime: str | None) -> QualityStatus:
    """Missing external runtime returns BLOCKED_EXTERNAL or NOT_RUN.

    Rules:
        runtime name provided -> BLOCKED_EXTERNAL
        no runtime name     -> NOT_RUN
    """
    if runtime:
        return QualityStatus.BLOCKED_EXTERNAL
    return QualityStatus.NOT_RUN


@dataclass(frozen=True)
class WarningDefinition:
    """Definition of a warning code in the registry."""
    code: str
    domain: str
    severity: str  # "error" | "warning" | "info"
    release_impact: str  # "FAIL" | "INCOMPLETE" | "NONE"
    waiver_allowed: bool


# Representative central warning registry
WARNING_REGISTRY: dict[WarningDefinition, str] = {}  # maps definition -> waiver_id or ""

# Convenience factory for common warnings
def warning(code: str, domain: str, severity: str = "warning",
            release_impact: str = "INCOMPLETE", waiver_allowed: bool = True) -> WarningDefinition:
    """Create a WarningDefinition with the given parameters."""
    return WarningDefinition(
        code=code,
        domain=domain,
        severity=severity,
        release_impact=release_impact,
        waiver_allowed=waiver_allowed,
    )


# Pre-register representative central subset
# geometry
_W001 = warning("GEOM-001", "geometry", severity="error", release_impact="FAIL", waiver_allowed=False)
# topology
_W002 = warning("TOPO-001", "topology", severity="error", release_impact="FAIL", waiver_allowed=True)
# lanes
_L001 = warning("LANE-001", "lanes", severity="warning", release_impact="INCOMPLETE", waiver_allowed=True)
# DEM
_D001 = warning("DEM-001", "DEM", severity="warning", release_impact="INCOMPLETE", waiver_allowed=True)
# CARLA static compatibility
_C001 = warning("CARLA-001", "carla_static_compatibility", severity="error", release_impact="FAIL", waiver_allowed=False)

# Register in the module-level dict
WARNING_REGISTRY[_W001] = ""
WARNING_REGISTRY[_W002] = ""
WARNING_REGISTRY[_L001] = ""
WARNING_REGISTRY[_D001] = ""
WARNING_REGISTRY[_C001] = ""


def register_warning(definition: WarningDefinition, waiver_id: str = "") -> None:
    """Register a new warning definition in the registry."""
    WARNING_REGISTRY[definition] = waiver_id


def lookup_warning(code: str) -> WarningDefinition | None:
    """Look up a warning definition by its code."""
    for definition in WARNING_REGISTRY:
        if definition.code == code:
            return definition
    return None
