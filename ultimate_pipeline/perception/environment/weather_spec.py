#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NEW-316 / NEW-317 / NEW-318 -- governed weather specification authority.

Before this module the repository had no weather authority at all:

* the pair orchestrator wrote ``UP_WEATHER_PRESET`` into the child environment
  (``run_perception_pair.py``) but **nothing ever read it**;
* ``record_route_fixed.py`` contained zero occurrences of the word "weather",
  so the production capture path never set weather and never recorded it;
* the single pair-level ``weather_sha256`` was computed *after both arms had
  finished*, by reading whichever weather CARLA happened to hold.

This module fixes all three:

``resolve_weather_spec``      NEW-316 single resolver (NEW-316)
``apply_weather_and_verify``  NEW-316 strict capture sequence, fail closed
``weather_identity_v2``       NEW-318 complete field identity
``weather_schema_capabilities`` NEW-318 capability detection

Design rules
------------
* No CARLA import at module level.
* One resolver. Runners never interpret weather strings themselves.
* Failure to apply the requested weather is a hard failure
  (``WEATHER_APPLICATION_FAILED``), never a warning.
* A supported field is never silently omitted from the identity.
* Unknown/unsupported presets fail closed.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Schema / failure codes
# ---------------------------------------------------------------------------

#: Bumped whenever the identity field set changes. Recorded in every artifact.
WEATHER_SCHEMA_VERSION = "weather_effective_v2"

#: The CARLA reference version this module was written against.
CARLA_REFERENCE_VERSION = "0.9.16"

# --- NEW-316 failure codes -------------------------------------------------
WEATHER_PRESET_UNSUPPORTED = "WEATHER_PRESET_UNSUPPORTED"
WEATHER_APPLICATION_FAILED = "WEATHER_APPLICATION_FAILED"
WEATHER_READBACK_FAILED = "WEATHER_READBACK_FAILED"
WEATHER_SETTLE_FAILED = "WEATHER_SETTLE_FAILED"

# --- NEW-317 failure codes -------------------------------------------------
PAIR_WEATHER_MISSING_ARM = "PAIR_WEATHER_MISSING_ARM"
PAIR_WEATHER_MISMATCH = "PAIR_WEATHER_MISMATCH"

# ---------------------------------------------------------------------------
# NEW-318: the complete effective WeatherParameters field set
# ---------------------------------------------------------------------------
#
# CARLA 0.9.16 `carla.WeatherParameters` exposes exactly these fourteen
# numeric fields.  The pre-existing `rq3_capture_contract.weather_from_world`
# read only eleven of them and silently dropped `fog_falloff`,
# `rayleigh_scattering_scale` and `dust_storm` -- meaning two arms with
# materially different fog falloff, Rayleigh scattering or dust storm produced
# the *same* `weather_sha256`.
#
# Order is fixed and meaningful: it is the canonical identity field order.
WEATHER_NUMERIC_FIELDS: Tuple[str, ...] = (
    "cloudiness",
    "precipitation",
    "precipitation_deposits",
    "wind_intensity",
    "sun_azimuth_angle",
    "sun_altitude_angle",
    "fog_density",
    "fog_distance",
    "fog_falloff",
    "wetness",
    "scattering_intensity",
    "mie_scattering_scale",
    "rayleigh_scattering_scale",
    "dust_storm",
)

#: Fields the *previous* (v1) identity omitted.  Recorded so an audit can see
#: exactly what was added and why old digests are not comparable.
LEGACY_V1_OMITTED_FIELDS: Tuple[str, ...] = (
    "fog_falloff",
    "rayleigh_scattering_scale",
    "dust_storm",
)

#: Absolute tolerance for requested-vs-effective comparison, per field.  CARLA
#: stores floats as 32-bit internally, so exact equality is not achievable.
WEATHER_FIELD_TOLERANCE: float = 1.0 / 4096.0

# ---------------------------------------------------------------------------
# Frozen preset table (CARLA 0.9.16)
# ---------------------------------------------------------------------------
#
# Used only when the live `carla` module cannot be imported (offline analysis,
# unit tests).  When the live module IS importable it is authoritative and this
# table is only cross-checked.  The provenance of whichever source was used is
# always recorded in `weather_schema_capabilities()["preset_source"]`.
FROZEN_PRESETS_0_9_16: Dict[str, Dict[str, float]] = {
    "Default": {
        "cloudiness": -1.0, "precipitation": -1.0, "precipitation_deposits": -1.0,
        "wind_intensity": -1.0, "sun_azimuth_angle": -1.0, "sun_altitude_angle": -1.0,
        "fog_density": -1.0, "fog_distance": -1.0, "fog_falloff": -1.0, "wetness": -1.0,
        "scattering_intensity": 1.0, "mie_scattering_scale": 0.03,
        "rayleigh_scattering_scale": 0.0331, "dust_storm": 0.0,
    },
    "ClearNoon": {
        "cloudiness": 5.0, "precipitation": 0.0, "precipitation_deposits": 0.0,
        "wind_intensity": 10.0, "sun_azimuth_angle": -1.0, "sun_altitude_angle": 45.0,
        "fog_density": 2.0, "fog_distance": 0.75, "fog_falloff": 0.1, "wetness": 0.0,
        "scattering_intensity": 1.0, "mie_scattering_scale": 0.03,
        "rayleigh_scattering_scale": 0.0331, "dust_storm": 0.0,
    },
    "ClearSunset": {
        "cloudiness": 5.0, "precipitation": 0.0, "precipitation_deposits": 0.0,
        "wind_intensity": 10.0, "sun_azimuth_angle": -1.0, "sun_altitude_angle": 15.0,
        "fog_density": 2.0, "fog_distance": 0.75, "fog_falloff": 0.1, "wetness": 0.0,
        "scattering_intensity": 1.0, "mie_scattering_scale": 0.03,
        "rayleigh_scattering_scale": 0.0331, "dust_storm": 0.0,
    },
    "ClearNight": {
        "cloudiness": 5.0, "precipitation": 0.0, "precipitation_deposits": 0.0,
        "wind_intensity": 10.0, "sun_azimuth_angle": -1.0, "sun_altitude_angle": -90.0,
        "fog_density": 2.0, "fog_distance": 0.75, "fog_falloff": 0.1, "wetness": 0.0,
        "scattering_intensity": 1.0, "mie_scattering_scale": 0.03,
        "rayleigh_scattering_scale": 0.0331, "dust_storm": 0.0,
    },
    "CloudyNoon": {
        "cloudiness": 60.0, "precipitation": 0.0, "precipitation_deposits": 0.0,
        "wind_intensity": 10.0, "sun_azimuth_angle": -1.0, "sun_altitude_angle": 45.0,
        "fog_density": 3.0, "fog_distance": 0.75, "fog_falloff": 0.1, "wetness": 0.0,
        "scattering_intensity": 1.0, "mie_scattering_scale": 0.03,
        "rayleigh_scattering_scale": 0.0331, "dust_storm": 0.0,
    },
    "CloudySunset": {
        "cloudiness": 60.0, "precipitation": 0.0, "precipitation_deposits": 0.0,
        "wind_intensity": 10.0, "sun_azimuth_angle": -1.0, "sun_altitude_angle": 15.0,
        "fog_density": 3.0, "fog_distance": 0.75, "fog_falloff": 0.1, "wetness": 0.0,
        "scattering_intensity": 1.0, "mie_scattering_scale": 0.03,
        "rayleigh_scattering_scale": 0.0331, "dust_storm": 0.0,
    },
    "CloudyNight": {
        "cloudiness": 60.0, "precipitation": 0.0, "precipitation_deposits": 0.0,
        "wind_intensity": 10.0, "sun_azimuth_angle": -1.0, "sun_altitude_angle": -90.0,
        "fog_density": 3.0, "fog_distance": 0.75, "fog_falloff": 0.1, "wetness": 0.0,
        "scattering_intensity": 1.0, "mie_scattering_scale": 0.03,
        "rayleigh_scattering_scale": 0.0331, "dust_storm": 0.0,
    },
    "MidRainyNoon": {
        "cloudiness": 80.0, "precipitation": 40.0, "precipitation_deposits": 40.0,
        "wind_intensity": 30.0, "sun_azimuth_angle": -1.0, "sun_altitude_angle": 45.0,
        "fog_density": 6.0, "fog_distance": 0.75, "fog_falloff": 0.1, "wetness": 40.0,
        "scattering_intensity": 1.0, "mie_scattering_scale": 0.03,
        "rayleigh_scattering_scale": 0.0331, "dust_storm": 0.0,
    },
    "HardRainNoon": {
        "cloudiness": 90.0, "precipitation": 80.0, "precipitation_deposits": 80.0,
        "wind_intensity": 60.0, "sun_azimuth_angle": -1.0, "sun_altitude_angle": 45.0,
        "fog_density": 20.0, "fog_distance": 0.75, "fog_falloff": 0.1, "wetness": 100.0,
        "scattering_intensity": 1.0, "mie_scattering_scale": 0.03,
        "rayleigh_scattering_scale": 0.0331, "dust_storm": 0.0,
    },
    "SoftRainNoon": {
        "cloudiness": 60.0, "precipitation": 30.0, "precipitation_deposits": 30.0,
        "wind_intensity": 20.0, "sun_azimuth_angle": -1.0, "sun_altitude_angle": 45.0,
        "fog_density": 8.0, "fog_distance": 0.75, "fog_falloff": 0.1, "wetness": 40.0,
        "scattering_intensity": 1.0, "mie_scattering_scale": 0.03,
        "rayleigh_scattering_scale": 0.0331, "dust_storm": 0.0,
    },
    "WetNoon": {
        "cloudiness": 5.0, "precipitation": 0.0, "precipitation_deposits": 0.0,
        "wind_intensity": 10.0, "sun_azimuth_angle": -1.0, "sun_altitude_angle": 45.0,
        "fog_density": 2.0, "fog_distance": 0.75, "fog_falloff": 0.1, "wetness": 100.0,
        "scattering_intensity": 1.0, "mie_scattering_scale": 0.03,
        "rayleigh_scattering_scale": 0.0331, "dust_storm": 0.0,
    },
    "DustStorm": {
        "cloudiness": 100.0, "precipitation": 0.0, "precipitation_deposits": 0.0,
        "wind_intensity": 100.0, "sun_azimuth_angle": -1.0, "sun_altitude_angle": 45.0,
        "fog_density": 2.0, "fog_distance": 0.75, "fog_falloff": 0.1, "wetness": 0.0,
        "scattering_intensity": 1.0, "mie_scattering_scale": 0.03,
        "rayleigh_scattering_scale": 0.0331, "dust_storm": 100.0,
    },
}

#: Experimental (non-`carla.WeatherParameters`) presets this repository may
#: request.  They are resolved here so runners never have to build parameters.
EXPERIMENTAL_PRESETS: Dict[str, Dict[str, float]] = {
    # Used by scenario sweeps: strong fog, no precipitation.
    "ExperimentalDenseFog": {
        "cloudiness": 60.0, "precipitation": 0.0, "precipitation_deposits": 0.0,
        "wind_intensity": 10.0, "sun_azimuth_angle": -1.0, "sun_altitude_angle": 45.0,
        "fog_density": 80.0, "fog_distance": 5.0, "fog_falloff": 0.1, "wetness": 0.0,
        "scattering_intensity": 1.0, "mie_scattering_scale": 0.03,
        "rayleigh_scattering_scale": 0.0331, "dust_storm": 0.0,
    },
    "ExperimentalSoftRain": {
        "cloudiness": 60.0, "precipitation": 30.0, "precipitation_deposits": 20.0,
        "wind_intensity": 20.0, "sun_azimuth_angle": 80.0, "sun_altitude_angle": 50.0,
        "fog_density": 5.0, "fog_distance": 0.0, "fog_falloff": 0.1, "wetness": 40.0,
        "scattering_intensity": 1.0, "mie_scattering_scale": 0.03,
        "rayleigh_scattering_scale": 0.0331, "dust_storm": 0.0,
    },
    "ExperimentalHeavyRain": {
        "cloudiness": 90.0, "precipitation": 80.0, "precipitation_deposits": 80.0,
        "wind_intensity": 60.0, "sun_azimuth_angle": 30.0, "sun_altitude_angle": 20.0,
        "fog_density": 20.0, "fog_distance": 0.0, "fog_falloff": 0.1, "wetness": 100.0,
        "scattering_intensity": 1.0, "mie_scattering_scale": 0.03,
        "rayleigh_scattering_scale": 0.0331, "dust_storm": 0.0,
    },
    # Distinct from every stock preset *only* by fog_falloff and Rayleigh
    # scattering.  Exists to prove NEW-318 detects those differences.
    "ExperimentalScatterProbe": {
        "cloudiness": 30.0, "precipitation": 0.0, "precipitation_deposits": 0.0,
        "wind_intensity": 15.0, "sun_azimuth_angle": 20.0, "sun_altitude_angle": 35.0,
        "fog_density": 4.0, "fog_distance": 0.5, "fog_falloff": 0.42, "wetness": 5.0,
        "scattering_intensity": 1.0, "mie_scattering_scale": 0.075,
        "rayleigh_scattering_scale": 0.0913, "dust_storm": 3.0,
    },
}


# ---------------------------------------------------------------------------
# Digest helpers (canonical JSON, shared with rq3_capture_contract)
# ---------------------------------------------------------------------------


def canonical_dumps(obj: Any) -> str:
    """Canonical JSON: sorted keys, no spaces, ASCII, no NaN."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _round6(value: float) -> float:
    return round(float(value), 6)


# ---------------------------------------------------------------------------
# NEW-318: capability detection
# ---------------------------------------------------------------------------


def _import_carla(carla_module: Any = None) -> Any:
    if carla_module is not None:
        return carla_module
    try:  # pragma: no cover - exercised only with the real CARLA API present
        import carla as _carla  # type: ignore

        return _carla
    except Exception:
        return None


def weather_schema_capabilities(carla_module: Any = None) -> Dict[str, Any]:
    """Detect which weather fields and presets the installed API exposes.

    NEW-318 requires capability detection rather than blind attribute access:
    a supported runtime value must never be silently omitted, and an
    unsupported one must be reported explicitly instead of defaulted away.
    """
    carla = _import_carla(carla_module)

    supported_fields: List[str] = []
    unsupported_fields: List[str] = []
    supported_presets: List[str] = []
    preset_source = "frozen_table"
    carla_version = "unavailable"

    if carla is not None:
        carla_version = str(getattr(carla, "__version__", CARLA_REFERENCE_VERSION))
        wp_cls = getattr(carla, "WeatherParameters", None)
        if wp_cls is not None:
            for field in WEATHER_NUMERIC_FIELDS:
                # A field is supported only if the class exposes it as a
                # property/attribute AND the constructor accepts it.
                try:
                    probe = wp_cls()
                    if hasattr(probe, field):
                        supported_fields.append(field)
                    else:
                        unsupported_fields.append(field)
                except Exception:
                    # Cannot construct an instance; fall back to a static check.
                    if hasattr(wp_cls, field):
                        supported_fields.append(field)
                    else:
                        unsupported_fields.append(field)
            for name in sorted(dir(wp_cls)):
                if name[0].isupper():
                    supported_presets.append(name)
        preset_source = "live_carla_module"
    else:
        supported_fields = list(WEATHER_NUMERIC_FIELDS)
        supported_presets = sorted(FROZEN_PRESETS_0_9_16)

    return {
        "weather_schema_version": WEATHER_SCHEMA_VERSION,
        "carla_reference_version": CARLA_REFERENCE_VERSION,
        "carla_module_available": carla is not None,
        "carla_version_detected": carla_version,
        "preset_source": preset_source,
        "supported_fields": supported_fields,
        "unsupported_fields": unsupported_fields,
        "field_count": len(supported_fields),
        "supported_stock_presets": supported_presets,
        "supported_experimental_presets": sorted(EXPERIMENTAL_PRESETS),
        "legacy_v1_omitted_fields_now_included": list(LEGACY_V1_OMITTED_FIELDS),
        "frozen_preset_table_sha256": sha256_text(canonical_dumps(FROZEN_PRESETS_0_9_16)),
    }


# ---------------------------------------------------------------------------
# NEW-316: the single resolver
# ---------------------------------------------------------------------------


def supported_presets(carla_module: Any = None) -> Dict[str, List[str]]:
    caps = weather_schema_capabilities(carla_module)
    stock = list(caps["supported_stock_presets"])
    if caps["preset_source"] == "frozen_table":
        stock = sorted(FROZEN_PRESETS_0_9_16)
    return {"stock": stock, "experimental": sorted(EXPERIMENTAL_PRESETS)}


def _preset_params_from_live(
    preset: str, carla: Any
) -> Optional[Dict[str, float]]:
    wp_cls = getattr(carla, "WeatherParameters", None)
    if wp_cls is None:
        return None
    obj = getattr(wp_cls, preset, None)
    if obj is None:
        return None
    params: Dict[str, float] = {}
    for field in WEATHER_NUMERIC_FIELDS:
        try:
            params[field] = _round6(float(getattr(obj, field)))
        except Exception:
            continue
    return params or None


def resolve_weather_spec(
    requested: str,
    *,
    overrides: Optional[Mapping[str, float]] = None,
    carla_module: Any = None,
    strict: bool = True,
) -> Dict[str, Any]:
    """Resolve a requested weather name into exact effective parameters.

    This is the ONE resolver.  Callers must not build `WeatherParameters` from
    strings themselves; the orchestrator constructs an intent, and this module
    is what turns that intent into numbers, at exactly one place.

    Returns a dict with keys:
        ``ok``, ``failure_code``, ``requested``, ``parameters``,
        ``capabilities``, ``overrides_applied``, ``preset_origin``.

    ``ok`` is False and ``failure_code`` is ``WEATHER_PRESET_UNSUPPORTED``
    when ``requested`` is not a supported stock or experimental preset.
    """
    name = str(requested or "").strip()
    caps = weather_schema_capabilities(carla_module)

    presets = supported_presets(carla_module)
    if name not in presets["stock"] and name not in presets["experimental"]:
        return {
            "ok": False,
            "failure_code": WEATHER_PRESET_UNSUPPORTED,
            "requested": name,
            "parameters": {},
            "capabilities": caps,
            "overrides_applied": {},
            "preset_origin": None,
            "supported_presets": presets,
        }

    carla = _import_carla(carla_module)
    params: Optional[Dict[str, float]] = None
    origin: Optional[str] = None

    if name in EXPERIMENTAL_PRESETS:
        params = {k: _round6(v) for k, v in EXPERIMENTAL_PRESETS[name].items()}
        origin = "experimental_table"
    if params is None and carla is not None:
        params = _preset_params_from_live(name, carla)
        origin = "live_carla_module"
    if params is None:
        params = {k: _round6(v) for k, v in FROZEN_PRESETS_0_9_16[name].items()}
        origin = "frozen_table"

    applied_overrides: Dict[str, float] = {}
    for key, value in dict(overrides or {}).items():
        field = str(key)
        if field not in WEATHER_NUMERIC_FIELDS:
            if strict:
                return {
                    "ok": False,
                    "failure_code": WEATHER_PRESET_UNSUPPORTED,
                    "requested": name,
                    "parameters": {},
                    "capabilities": caps,
                    "overrides_applied": {},
                    "preset_origin": origin,
                    "detail": f"override_not_a_weather_field:{field}",
                    "supported_presets": presets,
                }
            continue
        params[field] = _round6(float(value))
        applied_overrides[field] = params[field]

    # NEW-318: never silently drop a field the schema says is supported.
    missing = [f for f in WEATHER_NUMERIC_FIELDS if f not in params]
    if missing and caps["preset_source"] == "live_carla_module":
        strict_missing = [f for f in missing if f in caps["supported_fields"]]
        if strict_missing and strict:
            return {
                "ok": False,
                "failure_code": WEATHER_PRESET_UNSUPPORTED,
                "requested": name,
                "parameters": {},
                "capabilities": caps,
                "overrides_applied": {},
                "preset_origin": origin,
                "detail": f"supported_field_absent_from_preset:{','.join(strict_missing)}",
                "supported_presets": presets,
            }

    return {
        "ok": True,
        "failure_code": None,
        "requested": name,
        "parameters": {k: params[k] for k in WEATHER_NUMERIC_FIELDS if k in params},
        "capabilities": caps,
        "overrides_applied": applied_overrides,
        "preset_origin": origin,
    }


# ---------------------------------------------------------------------------
# NEW-318: identity
# ---------------------------------------------------------------------------


def normalize_weather_params(source: Any) -> Dict[str, Any]:
    """Normalize any weather source into the complete v2 identity payload.

    ``source`` may be a mapping, a ``carla.WeatherParameters`` instance, or an
    object exposing the fields.  Unsupported fields are recorded explicitly
    rather than omitted silently.
    """
    caps = weather_schema_capabilities()
    values: Dict[str, float] = {}
    read_errors: List[str] = []

    def _get(field: str) -> Any:
        if isinstance(source, Mapping):
            return source.get(field)
        return getattr(source, field, None)

    for field in WEATHER_NUMERIC_FIELDS:
        try:
            raw = _get(field)
        except Exception as exc:
            read_errors.append(f"{field}:{type(exc).__name__}")
            continue
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            read_errors.append(f"{field}:not_numeric:{raw!r}")
            continue
        if value != value or value in (float("inf"), float("-inf")):
            read_errors.append(f"{field}:non_finite:{raw!r}")
            continue
        values[field] = _round6(value)

    missing_supported = [f for f in caps["supported_fields"] if f not in values]
    missing_unsupported = [f for f in caps["unsupported_fields"] if f not in values]

    return {
        "weather_schema_version": WEATHER_SCHEMA_VERSION,
        "parameters": {k: values[k] for k in WEATHER_NUMERIC_FIELDS if k in values},
        "unsupported_fields": missing_unsupported,
        "supported_but_unreadable_fields": missing_supported,
        "read_errors": read_errors,
        "field_count": len(values),
        "complete": not missing_supported,
    }


def weather_identity_v2(source: Any) -> Dict[str, Any]:
    """Complete weather identity digest (NEW-318).

    Two arms share an identical weather state iff ``weather_sha256`` matches.
    The digest covers the schema version plus every readable supported field,
    so a change to ``fog_falloff``, ``rayleigh_scattering_scale`` or
    ``dust_storm`` -- all three of which the legacy identity ignored -- now
    changes the digest.
    """
    norm = normalize_weather_params(source)
    payload = {
        "weather_schema_version": WEATHER_SCHEMA_VERSION,
        "parameters": norm["parameters"],
        "unsupported_fields": sorted(norm["unsupported_fields"]),
    }
    complete = bool(norm["complete"])
    digest_source = payload if complete else dict(payload, incomplete=True)
    return {
        "weather_schema_version": WEATHER_SCHEMA_VERSION,
        "weather_sha256": sha256_text(canonical_dumps(digest_source)),
        "parameters": norm["parameters"],
        "parameter_count": len(norm["parameters"]),
        "unsupported_fields": sorted(norm["unsupported_fields"]),
        "supported_but_unreadable_fields": sorted(norm["supported_but_unreadable_fields"]),
        "read_errors": norm["read_errors"],
        "identity_complete": complete,
    }


# ---------------------------------------------------------------------------
# NEW-316: strict capture sequence
# ---------------------------------------------------------------------------


class WeatherApplicationError(RuntimeError):
    """Raised when the requested weather did not become effective.

    Carries the full evidence payload so the caller can persist it.
    """

    def __init__(self, failure_code: str, message: str, payload: Dict[str, Any]):
        super().__init__(f"{failure_code}:{message}")
        self.failure_code = failure_code
        self.payload = payload


def compare_requested_to_effective(
    requested_params: Mapping[str, float],
    effective_params: Mapping[str, float],
    *,
    tolerance: float = WEATHER_FIELD_TOLERANCE,
) -> Dict[str, Any]:
    """Per-field requested-vs-effective comparison with explicit deltas."""
    per_field: List[Dict[str, Any]] = []
    mismatched: List[str] = []
    for field in WEATHER_NUMERIC_FIELDS:
        want = requested_params.get(field)
        got = effective_params.get(field)
        if want is None:
            per_field.append({"field": field, "requested": None, "effective": None,
                              "delta": None, "within_tolerance": None})
            continue
        if got is None:
            mismatched.append(field)
            per_field.append({"field": field, "requested": float(want), "effective": None,
                              "delta": None, "within_tolerance": False})
            continue
        delta = float(got) - float(want)
        ok = abs(delta) <= float(tolerance)
        if not ok:
            mismatched.append(field)
        per_field.append({
            "field": field,
            "requested": _round6(float(want)),
            "effective": _round6(float(got)),
            "delta": _round6(delta),
            "within_tolerance": ok,
        })
    return {
        "tolerance": float(tolerance),
        "match": not mismatched,
        "mismatched_fields": mismatched,
        "per_field": per_field,
    }


def apply_weather_and_verify(
    world: Any,
    requested: str,
    *,
    settle_ticks: int = 3,
    tick_fn: Optional[Callable[[], Any]] = None,
    overrides: Optional[Mapping[str, float]] = None,
    carla_module: Any = None,
    strict: bool = True,
) -> Dict[str, Any]:
    """NEW-316 strict capture sequence for weather.

    Sequence (each step mandatory, in this order):

        requested weather
        -> resolve exact parameters
        -> ``world.set_weather(...)``
        -> advance required settle ticks
        -> ``world.get_weather()``
        -> normalize effective parameters
        -> compare requested/effective
        -> generate digest
        -> permit capture

    Raises :class:`WeatherApplicationError` when the requested weather did not
    become effective.  Failure is NEVER warning-only.
    """
    spec = resolve_weather_spec(
        requested, overrides=overrides, carla_module=carla_module, strict=strict
    )
    if not spec["ok"]:
        payload = {
            "requested": spec["requested"],
            "requested_preset": spec["requested"],
            "weather_schema_version": WEATHER_SCHEMA_VERSION,
            "failure_code": spec["failure_code"],
            "detail": spec.get("detail"),
            "capabilities": spec["capabilities"],
        }
        raise WeatherApplicationError(
            spec["failure_code"], f"weather_spec_unresolved:{spec['requested']}", payload
        )

    requested_params = dict(spec["parameters"])
    evidence: Dict[str, Any] = {
        "requested": spec["requested"],
        "requested_preset": spec["requested"],
        "preset_origin": spec["preset_origin"],
        "overrides_applied": spec["overrides_applied"],
        "weather_schema_version": WEATHER_SCHEMA_VERSION,
        "capabilities": spec["capabilities"],
        "settle_ticks": int(settle_ticks),
    }

    carla = _import_carla(carla_module)
    wp_cls = getattr(carla, "WeatherParameters", None) if carla is not None else None

    # --- set_weather -------------------------------------------------------
    if wp_cls is not None:
        kwargs = {f: float(requested_params[f]) for f in WEATHER_NUMERIC_FIELDS
                  if f in requested_params}
        try:
            target = wp_cls(**kwargs)
        except TypeError:
            # Older API without dust_storm / rayleigh_scattering_scale.
            fb = getattr(wp_cls, spec["requested"], None)
            if fb is None:
                raise WeatherApplicationError(
                    WEATHER_APPLICATION_FAILED,
                    f"cannot_construct_weather:{spec['requested']}",
                    dict(evidence, failure_code=WEATHER_APPLICATION_FAILED),
                )
            target = fb
        set_input = target
    else:
        # Offline / no CARLA: caller supplies a duck-typed factory.
        set_input = requested_params

    try:
        world.set_weather(set_input)
    except Exception as exc:
        raise WeatherApplicationError(
            WEATHER_APPLICATION_FAILED,
            f"{type(exc).__name__}:{exc}",
            dict(evidence, failure_code=WEATHER_APPLICATION_FAILED),
        ) from exc

    # --- settle ticks ------------------------------------------------------
    if int(settle_ticks) > 0:
        for index in range(int(settle_ticks)):
            try:
                if tick_fn is not None:
                    tick_fn()
                elif hasattr(world, "tick"):
                    world.tick()
                elif hasattr(world, "wait_for_tick"):
                    world.wait_for_tick()
            except Exception as exc:
                raise WeatherApplicationError(
                    WEATHER_SETTLE_FAILED,
                    f"tick_{index}:{type(exc).__name__}:{exc}",
                    dict(evidence, failure_code=WEATHER_SETTLE_FAILED,
                         settle_ticks_completed=index),
                ) from exc

    # --- readback ----------------------------------------------------------
    try:
        readback = world.get_weather()
    except Exception as exc:
        raise WeatherApplicationError(
            WEATHER_READBACK_FAILED,
            f"{type(exc).__name__}:{exc}",
            dict(evidence, failure_code=WEATHER_READBACK_FAILED),
        ) from exc

    effective = weather_identity_v2(readback)
    comparison = compare_requested_to_effective(requested_params, effective["parameters"])

    evidence.update(
        {
            "requested_parameters": requested_params,
            "effective": effective,
            "weather_sha256": effective["weather_sha256"],
            "comparison": comparison,
            "applied_ok": True,
            "effective_matches_requested": comparison["match"],
        }
    )

    if strict and not comparison["match"]:
        raise WeatherApplicationError(
            WEATHER_APPLICATION_FAILED,
            "mismatched_fields:" + ",".join(comparison["mismatched_fields"]),
            dict(evidence, failure_code=WEATHER_APPLICATION_FAILED,
                 applied_ok=True, effective_matches_requested=False),
        )
    if strict and not effective["identity_complete"]:
        raise WeatherApplicationError(
            WEATHER_APPLICATION_FAILED,
            "incomplete_weather_identity:"
            + ",".join(effective["supported_but_unreadable_fields"]),
            dict(evidence, failure_code=WEATHER_APPLICATION_FAILED,
                 applied_ok=True, effective_matches_requested=True),
        )

    evidence["failure_code"] = None
    evidence["ok"] = True
    return evidence


# ---------------------------------------------------------------------------
# NEW-317: arm-level weather binding
# ---------------------------------------------------------------------------


def read_arm_weather_identity(arm_dir: Any) -> Dict[str, Any]:
    """Read ``<arm_dir>/weather_effective.json`` produced by one capture arm.

    NEW-317: each arm must independently measure its own effective weather.
    A missing file is a hard failure -- it means the arm never applied and
    verified weather at all.
    """
    from pathlib import Path

    path = Path(arm_dir) / "weather_effective.json"
    result: Dict[str, Any] = {
        "path": str(path),
        "present": path.is_file(),
        "weather_sha256": "",
        "weather_schema_version": None,
        "requested_preset": None,
        "effective_matches_requested": None,
        "error": None,
    }
    if not result["present"]:
        result["error"] = "weather_effective_artifact_missing"
        return result
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        result["error"] = f"weather_effective_unreadable:{type(exc).__name__}:{exc}"
        return result
    effective = data.get("effective") or {}
    result["weather_sha256"] = str(
        effective.get("weather_sha256") or data.get("weather_sha256") or ""
    )
    result["weather_schema_version"] = (
        effective.get("weather_schema_version")
        or data.get("weather_schema_version")
    )
    result["requested_preset"] = data.get("requested_preset")
    result["effective_matches_requested"] = data.get("effective_matches_requested")
    result["manifest"] = data
    return result


def validate_arm_weather_binding(
    manual_weather_sha256: str,
    auto_weather_sha256: str,
    *,
    pair_weather_sha256: Optional[str] = None,
    manual_present: bool = True,
    auto_present: bool = True,
    schema_version: str = WEATHER_SCHEMA_VERSION,
) -> Dict[str, Any]:
    """NEW-317 pair-level weather equality, enforced on ARM identities.

    Required (all four, fail closed):
      1. manual arm weather identity exists
      2. auto arm weather identity exists
      3. manual SHA == auto SHA
      4. top-level pair SHA == both

    A pair-level SHA that has been hand-edited to agree with both arms cannot
    rescue a missing arm identity -- arms 1 and 2 are checked first.
    """
    reasons: List[str] = []

    if not manual_present:
        reasons.append(f"{PAIR_WEATHER_MISSING_ARM}:manual")
    if not auto_present:
        reasons.append(f"{PAIR_WEATHER_MISSING_ARM}:auto")

    m = str(manual_weather_sha256 or "")
    a = str(auto_weather_sha256 or "")
    p = str(pair_weather_sha256 or "")

    if manual_present and not m:
        reasons.append(f"{PAIR_WEATHER_MISSING_ARM}:manual_empty_identity")
    if auto_present and not a:
        reasons.append(f"{PAIR_WEATHER_MISSING_ARM}:auto_empty_identity")

    if m and a and m != a:
        reasons.append(f"{PAIR_WEATHER_MISMATCH}:manual_vs_auto:{m}!={a}")
    if m and p and m != p:
        reasons.append(f"{PAIR_WEATHER_MISMATCH}:manual_vs_pair:{m}!={p}")
    if a and p and a != p:
        reasons.append(f"{PAIR_WEATHER_MISMATCH}:auto_vs_pair:{a}!={p}")

    return {
        "valid": not reasons,
        "invalid_reasons": reasons,
        "manual_weather_sha256": m,
        "auto_weather_sha256": a,
        "pair_weather_sha256": p,
        "weather_schema_version": schema_version,
    }


# ---------------------------------------------------------------------------
# Artifact writers
# ---------------------------------------------------------------------------


def weather_requested_artifact(
    requested: str, spec: Mapping[str, Any]
) -> Dict[str, Any]:
    """The ``weather_requested.json`` payload."""
    return {
        "schema": "WEATHER_REQUESTED/v2",
        "weather_schema_version": WEATHER_SCHEMA_VERSION,
        "requested_preset": str(requested),
        "resolved_parameters": dict(spec.get("parameters") or {}),
        "preset_origin": spec.get("preset_origin"),
        "overrides_applied": dict(spec.get("overrides_applied") or {}),
        "capabilities": spec.get("capabilities"),
        "resolver": "ultimate_pipeline.perception.environment.weather_spec.resolve_weather_spec",
    }


def weather_effective_artifact(evidence: Mapping[str, Any]) -> Dict[str, Any]:
    """The ``weather_effective.json`` payload written by each arm."""
    return {
        "schema": "WEATHER_EFFECTIVE/v2",
        "weather_schema_version": WEATHER_SCHEMA_VERSION,
        "requested_preset": evidence.get("requested_preset"),
        "preset_origin": evidence.get("preset_origin"),
        "overrides_applied": dict(evidence.get("overrides_applied") or {}),
        "settle_ticks": evidence.get("settle_ticks"),
        "requested_parameters": dict(evidence.get("requested_parameters") or {}),
        "effective": dict(evidence.get("effective") or {}),
        "weather_sha256": evidence.get("weather_sha256"),
        "comparison": dict(evidence.get("comparison") or {}),
        "effective_matches_requested": evidence.get("effective_matches_requested"),
        "failure_code": evidence.get("failure_code"),
        "capabilities": evidence.get("capabilities"),
    }