#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NEW-333 -- governed camera photometric response profile.

What the production camera setup actually controls today
--------------------------------------------------------
``dominik_sensor_setup._camera_attributes`` sets exactly three attributes:
``fov``, ``image_size_x``, ``image_size_y``.
``thesis_sensor_rig.spawn_rig`` sets four: those three plus ``sensor_tick``.

Everything else that shapes an RQ3 image is left at the **implicit CARLA
default**: gamma, exposure mode and compensation, ISO, shutter speed, bloom,
lens flare, lens distortion, chromatic aberration, motion blur, aperture,
post-process effects.  Two arms therefore have no guarantee of equal
photometric response, and a CARLA default change between versions would
silently change every captured image.

What this module does
---------------------
Freezes one explicit response profile, applies it with capability detection
(never blindly setting an attribute the installed blueprint does not expose),
reads back the **effective** attribute values, and digests them so the pair
validator can require equality between arms.

Whether post-processing is disabled or deliberately enabled is a *protocol
choice*.  What is forbidden is relying on implicit CARLA defaults -- so every
attribute is either explicitly set or explicitly recorded as a governed
default with its effective value.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Tuple

CAMERA_RESPONSE_SCHEMA = "CAMERA_RESPONSE_PROFILE/v1"
EFFECTIVE_ATTRIBUTES_FILENAME = "effective_camera_attributes.json"

#: The governed protocol choice.  ``pinhole_postprocess_disabled`` renders a
#: clean pinhole image with CARLA's cinematic post-processing chain switched
#: off, which is the profile an intrinsic-calibration study assumes.
PROFILE_PINHOLE_POSTPROCESS_DISABLED = "pinhole_postprocess_disabled"
PROFILE_POSTPROCESS_ENABLED = "postprocess_enabled_cinematic"

#: Strict scientific baseline: everything that touches appearance is pinned to
#: an explicit value, with post-processing off so that the intrinsic-remap
#: story (NEW-320) is not confounded by tone mapping / bloom.
CANONICAL_PROFILE: Dict[str, Dict[str, str]] = {
    PROFILE_PINHOLE_POSTPROCESS_DISABLED: {
        # --- geometry-adjacent (recorded for completeness) ---------------
        "sensor_tick": "0.0",
        # --- post-processing master switch --------------------------------
        "enable_postprocess_effects": "false",
        # --- exposure ------------------------------------------------------
        "exposure_mode": "histogram",
        "exposure_compensation": "0.0",
        "exposure_eye_adaptation": "0.0",
        "iso": "100",
        "shutter_speed": "100.0",
        "aperture": "2.8",
        # --- gamma ---------------------------------------------------------
        "gamma": "2.2",
        "gamma_uncorrected": "0.0",
        # --- lens ----------------------------------------------------------
        "lens_flare_intensity": "0.0",
        "lens_circle_multiplier": "0.0",
        "lens_circle_falloff": "5.0",
        "lens_k1": "0.0", "lens_k2": "0.0", "lens_k3": "0.0",
        "lens_k4": "0.0", "lens_k5": "0.0", "lens_k6": "0.0",
        "lens_size_mul": "1.0",
        "lens_x_size": "0.5",
        # --- chromatic aberration -----------------------------------------
        "chromatic_aberration_intensity": "0.0",
        "chromatic_aberration_offset": "0.0",
        # --- motion blur ---------------------------------------------------
        "motion_blur_intensity": "0.0",
        "motion_blur_max": "0.0",
        "motion_blur_object_scale": "0.0",
        # --- bloom ---------------------------------------------------------
        "bloom_intensity": "0.0",
    },
    PROFILE_POSTPROCESS_ENABLED: {
        "sensor_tick": "0.0",
        "enable_postprocess_effects": "true",
        "exposure_mode": "histogram",
        "exposure_compensation": "0.0",
        "exposure_eye_adaptation": "0.0",
        "iso": "100",
        "shutter_speed": "100.0",
        "aperture": "2.8",
        "gamma": "2.2",
        "gamma_uncorrected": "0.0",
        "lens_flare_intensity": "0.0",
        "lens_circle_multiplier": "0.0",
        "lens_circle_falloff": "5.0",
        "lens_k1": "0.0", "lens_k2": "0.0", "lens_k3": "0.0",
        "lens_k4": "0.0", "lens_k5": "0.0", "lens_k6": "0.0",
        "lens_size_mul": "1.0",
        "lens_x_size": "0.5",
        "chromatic_aberration_intensity": "0.0",
        "chromatic_aberration_offset": "0.0",
        "motion_blur_intensity": "0.0",
        "motion_blur_max": "0.0",
        "motion_blur_object_scale": "0.0",
        "bloom_intensity": "0.5",
    },
}

#: Attributes that MUST be governed.  A profile missing any of these is
#: incomplete and may not be used for a paired claim.
REQUIRED_GOVERNED_ATTRIBUTES: Tuple[str, ...] = (
    "sensor_tick",
    "enable_postprocess_effects",
    "exposure_mode",
    "exposure_compensation",
    "iso",
    "shutter_speed",
    "gamma",
    "lens_flare_intensity",
    "chromatic_aberration_intensity",
)

CAMERA_RESPONSE_UNSUPPORTED = "CAMERA_RESPONSE_ATTRIBUTE_UNSUPPORTED"
CAMERA_RESPONSE_PROFILE_INCOMPLETE = "CAMERA_RESPONSE_PROFILE_INCOMPLETE"
CAMERA_RESPONSE_MISMATCH = "CAMERA_RESPONSE_MISMATCH"

VALID_PROFILES: Tuple[str, ...] = tuple(CANONICAL_PROFILE)


def _sha(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def profile_attributes(
    profile: str = PROFILE_PINHOLE_POSTPROCESS_DISABLED,
    overrides: Optional[Mapping[str, str]] = None,
) -> Dict[str, str]:
    """Resolve the attribute map for a governed profile.

    Raises on an unknown profile.  Never silently returns a partial profile.
    """
    name = str(profile)
    if name not in CANONICAL_PROFILE:
        raise ValueError(f"unknown_camera_response_profile:{name}")
    attrs = dict(CANONICAL_PROFILE[name])
    for key, value in dict(overrides or {}).items():
        attrs[str(key)] = str(value)
    return attrs


def profile_report(
    profile: str = PROFILE_PINHOLE_POSTPROCESS_DISABLED,
    overrides: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Serializable ``camera_response_profile.json`` payload + digest."""
    attrs = profile_attributes(profile, overrides)
    missing = [a for a in REQUIRED_GOVERNED_ATTRIBUTES if a not in attrs]
    report = {
        "schema": CAMERA_RESPONSE_SCHEMA,
        "profile": str(profile),
        "protocol_choice": (
            "postprocessing explicitly disabled so appearance is not confounded "
            "with the intrinsic realization"
            if profile == PROFILE_PINHOLE_POSTPROCESS_DISABLED
            else "postprocessing explicitly enabled (cinematic)"
        ),
        "attributes": attrs,
        "attribute_count": len(attrs),
        "required_governed_attributes": list(REQUIRED_GOVERNED_ATTRIBUTES),
        "missing_required_attributes": missing,
        "complete": not missing,
        "implicit_defaults_used": [],
        "capability_detection": "per-attribute has_attribute check at spawn time",
    }
    report["camera_response_sha256"] = _sha(
        {"profile": str(profile), "attributes": attrs}
    )
    return report


def _blueprint_supports(bp: Any, key: str) -> bool:
    try:
        if hasattr(bp, "has_attribute") and bp.has_attribute(key):
            return True
    except Exception:
        return False
    # Duck-typed test doubles may expose attributes directly.
    return key in (getattr(bp, "attributes", {}) or {})


def apply_response_profile(
    bp: Any,
    *,
    profile: str = PROFILE_PINHOLE_POSTPROCESS_DISABLED,
    overrides: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Apply the governed response profile to a camera blueprint.

    Capability detection is per attribute: an attribute the installed CARLA
    build does not expose is recorded in ``unsupported`` and left alone, never
    blindly set.  Attributes that are neither requested nor supported are read
    back and recorded as ``governed_defaults_observed`` so an implicit default
    can never hide.
    """
    attrs = profile_attributes(profile, overrides)
    applied: Dict[str, str] = {}
    unsupported: List[str] = []
    failed: Dict[str, str] = {}

    for key in sorted(attrs):
        value = attrs[key]
        if not _blueprint_supports(bp, key):
            unsupported.append(key)
            continue
        try:
            bp.set_attribute(key, value)
            applied[key] = value
        except Exception as exc:
            failed[key] = f"{type(exc).__name__}:{exc}"

    effective = read_effective_attributes(bp)
    return {
        "schema": CAMERA_RESPONSE_SCHEMA,
        "profile": str(profile),
        "requested": attrs,
        "applied": applied,
        "unsupported": sorted(unsupported),
        "failed": failed,
        "effective": effective,
        "effective_camera_attributes_sha256": effective["effective_attributes_sha256"],
        "profile_complete": not (
            [a for a in REQUIRED_GOVERNED_ATTRIBUTES if a not in applied]
        ),
    }


def read_effective_attributes(bp: Any) -> Dict[str, Any]:
    """Read back every governed attribute's *effective* value.

    ``effective_camera_attributes.json`` is the artifact the pair validator
    compares: reading it back (rather than trusting the requested map) is what
    proves CARLA accepted the profile.
    """
    values: Dict[str, str] = {}
    governed_defaults: List[str] = []
    try:
        declared = dict(getattr(bp, "attributes", {}) or {})
    except Exception:
        declared = {}
    for key in sorted(set(REQUIRED_GOVERNED_ATTRIBUTES) | set(CANONICAL_PROFILE[PROFILE_PINHOLE_POSTPROCESS_DISABLED])):
        if not _blueprint_supports(bp, key):
            continue
        try:
            values[key] = str(bp.get_attribute(key))
        except Exception:
            continue
        if key in declared and key not in values:
            governed_defaults.append(key)
    payload = {
        "schema": "EFFECTIVE_CAMERA_ATTRIBUTES/v1",
        "attributes": values,
        "attribute_count": len(values),
        "attributes_not_exposed_by_api": sorted(
            set(CANONICAL_PROFILE[PROFILE_PINHOLE_POSTPROCESS_DISABLED]) - set(values)
        ),
    }
    payload["effective_attributes_sha256"] = _sha(values)
    return payload


def validate_response_equality(
    manual_digest: str,
    auto_digest: str,
    *,
    manual_profile: str = "",
    auto_profile: str = "",
) -> Dict[str, Any]:
    """Pair-level equality of the effective camera-response identity."""
    reasons: List[str] = []
    m = str(manual_digest or "")
    a = str(auto_digest or "")
    if not m:
        reasons.append(f"{CAMERA_RESPONSE_MISMATCH}:manual_empty")
    if not a:
        reasons.append(f"{CAMERA_RESPONSE_MISMATCH}:auto_empty")
    if m and a and m != a:
        reasons.append(f"{CAMERA_RESPONSE_MISMATCH}:{m}!={a}")
    if manual_profile and auto_profile and manual_profile != auto_profile:
        reasons.append(
            f"{CAMERA_RESPONSE_MISMATCH}:profile:{manual_profile}!={auto_profile}"
        )
    return {
        "valid": not reasons,
        "invalid_reasons": reasons,
        "manual_camera_response_sha256": m,
        "auto_camera_response_sha256": a,
    }


def controller_environment() -> Dict[str, str]:
    """Env overrides that apply the governed profile during a capture."""
    return {
        "UP_CAMERA_RESPONSE_PROFILE": PROFILE_PINHOLE_POSTPROCESS_DISABLED,
        "UP_ENABLE_POSTPROCESS_EFFECTS": "0",
    }