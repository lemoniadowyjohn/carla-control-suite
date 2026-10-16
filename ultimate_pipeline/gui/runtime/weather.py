"""Governed weather: 14 fields, exposed only when the capability exists.

CARLA 0.9.16 supports 14 weather parameters. The repository's
``weather_spec`` tracks 10 numeric ones and previously *silently dropped*
``fog_falloff`` (and the legacy-v1 omission list is explicit about it).

Two rules:

* A field is exposed only if the backend actually supports it. A missing field
  is reported ``UNSUPPORTED`` -- never written and hoped for.
* A read-back mismatch is reported as a **readback mismatch within tolerance**,
  not as success. The upstream tolerance is 1/4096.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ultimate_pipeline.gui.results import Result

__all__ = [
    "WEATHER_GOVERNED_FIELDS", "WEATHER_RANGES", "READBACK_TOLERANCE",
    "WeatherFieldStatus", "WeatherApplication", "apply_weather",
]

#: Upstream tolerance used when reading the applied weather back.
READBACK_TOLERANCE = 1.0 / 4096.0

#: The 14 governed CARLA 0.9.16 weather parameters.
#: Verified against carla.WeatherParameters.__init__ signature:
#:   (cloudiness, precipitation, precipitation_deposits, wind_intensity,
#:    sun_azimuth_angle, sun_altitude_angle, fog_density, fog_distance,
#:    fog_falloff, wetness, scattering_intensity, mie_scattering_scale,
#:    rayleigh_scattering_scale, dust_storm)
WEATHER_GOVERNED_FIELDS: tuple[str, ...] = (
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

WEATHER_RANGES: dict[str, tuple[float, float]] = {
    "cloudiness": (0.0, 100.0),
    "precipitation": (0.0, 100.0),
    "precipitation_deposits": (0.0, 100.0),
    "wind_intensity": (0.0, 100.0),
    "sun_azimuth_angle": (0.0, 360.0),
    "sun_altitude_angle": (-90.0, 90.0),
    "fog_density": (0.0, 100.0),
    "fog_distance": (0.0, 100.0),
    "fog_falloff": (0.0, 1.0),
    "wetness": (0.0, 100.0),
    "scattering_intensity": (0.0, 100.0),
    "mie_scattering_scale": (0.0, 1.0),
    "rayleigh_scattering_scale": (0.0, 1.0),
    "dust_storm": (0.0, 100.0),
}


@dataclass(frozen=True)
class WeatherFieldStatus:
    field: str
    requested: Any
    status: str            # VERIFIED_APPLIED | WRITTEN_NOT_VERIFIED | READBACK_MISMATCH | UNSUPPORTED | OUT_OF_RANGE
    readback: Any = None
    detail: str = ""

    def as_dict(self) -> dict:
        return {"field": self.field, "requested": self.requested, "status": self.status,
                "readback": self.readback, "detail": self.detail}


@dataclass
class WeatherApplication:
    fields: list[WeatherFieldStatus] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        # Only a fresh, measured VERIFIED_APPLIED counts as success.
        # The legacy "APPLIED" status is deliberately NOT accepted: nothing
        # in this module emits it anymore, and accepting it would let a
        # future emitter claim success without measurement.
        return bool(self.fields) and all(
            f.status == "VERIFIED_APPLIED" for f in self.fields
        )

    def by_status(self, status: str) -> list[WeatherFieldStatus]:
        return [f for f in self.fields if f.status == status]

    def as_dict(self) -> dict:
        return {"ok": self.ok, "fields": [f.as_dict() for f in self.fields]}


def _coerce(field_name: str, value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    return value


def apply_weather(world: Any, requested: dict[str, Any],
                  parameters_factory: Any = None) -> Result:
    """Apply governed weather fields through ``world.set_weather``.

    After calling ``world.set_weather``, queries ``world.get_weather()`` for a
    fresh readback. Only marks a field ``VERIFIED_APPLIED`` when the fresh
    observation matches the requested value within tolerance. Fields written
    without a fresh readback are marked ``WRITTEN_NOT_VERIFIED``.

    In the real-``carla`` path (no ``parameters_factory``), unrequested
    governed fields are seeded from a pre-write snapshot so that building
    ``carla.WeatherParameters`` does not silently reset them to defaults.
    That snapshot is never used for verification: the post-write readback
    below is the only evidence counted.

    ``parameters_factory`` exists so the whole path is testable mock-first: by
    default it builds a real ``carla.WeatherParameters``, but offline tests
    inject a fake and never import ``carla`` at all.
    """
    unknown = sorted(set(requested) - set(WEATHER_GOVERNED_FIELDS))
    if unknown:
        return Result.blocked(
            f"not governed weather field(s): {unknown}",
            remediation=f"use only fields from WEATHER_GOVERNED_FIELDS "
                        f"({len(WEATHER_GOVERNED_FIELDS)} fields)",
        )

    accepted: dict[str, Any] = {}
    statuses: list[WeatherFieldStatus] = []

    for field_name in WEATHER_GOVERNED_FIELDS:
        if field_name not in requested:
            continue
        value = requested[field_name]

        try:
            numeric = float(value)
        except (TypeError, ValueError):
            statuses.append(WeatherFieldStatus(field_name, value, "OUT_OF_RANGE", None,
                                               "value is not numeric"))
            continue

        bounds = WEATHER_RANGES.get(field_name)
        if bounds is not None:
            low, high = bounds
            if not (low <= numeric <= high):
                statuses.append(WeatherFieldStatus(
                    field_name, numeric, "OUT_OF_RANGE", None,
                    f"outside [{low}, {high}]"))
                continue
        accepted[field_name] = numeric

    if not accepted:
        return Result.failure(
            "no weather field was acceptable",
            error_class="WeatherValidationError",
            error_source="ultimate_pipeline/gui/runtime/weather.py",
            value=WeatherApplication(statuses).as_dict(),
        )

    if parameters_factory is not None:
        parameters = parameters_factory(accepted)
    else:
        import carla

        # carla.WeatherParameters(**accepted) would reset every unrequested
        # field to its constructor default. Seed those from a pre-write
        # snapshot (best effort; verification below is independent of it).
        merged: dict[str, Any] = dict(accepted)
        try:
            pre_write = world.get_weather()
        except Exception:
            pre_write = None
        if pre_write is not None:
            for governed in WEATHER_GOVERNED_FIELDS:
                if governed in merged:
                    continue
                try:
                    merged[governed] = float(getattr(pre_write, governed))
                except (AttributeError, TypeError, ValueError):
                    continue
        parameters = carla.WeatherParameters(**merged)
    try:
        world.set_weather(parameters)
    except Exception as exc:
        return Result.failure(f"world.set_weather failed: {exc}",
                              error_class="WeatherApplyError",
                              value=WeatherApplication(statuses).as_dict())

    # Fresh readback: query get_weather() AFTER set_weather, never before
    fresh_readback = None
    try:
        fresh_readback = world.get_weather()
    except Exception:
        pass

    for field_name, wanted in accepted.items():
        if fresh_readback is None:
            statuses.append(WeatherFieldStatus(
                field_name, wanted, "WRITTEN_NOT_VERIFIED", None,
                "written; get_weather() unavailable or raised"))
            continue
        try:
            actual = float(getattr(fresh_readback, field_name))
        except (AttributeError, TypeError, ValueError):
            statuses.append(WeatherFieldStatus(
                field_name, wanted, "UNSUPPORTED", None,
                "backend cannot read this field back"))
            continue
        if abs(actual - wanted) <= READBACK_TOLERANCE:
            statuses.append(WeatherFieldStatus(
                field_name, wanted, "VERIFIED_APPLIED", actual,
                "fresh readback within tolerance"))
        else:
            statuses.append(WeatherFieldStatus(
                field_name, wanted, "READBACK_MISMATCH", actual,
                f"wanted {wanted}, fresh read {actual}"))

    application = WeatherApplication(statuses)
    if application.ok:
        return Result.success(application.as_dict())
    unverifiable = fresh_readback is None
    return Result.failure(
        "weather applied but not every field verified",
        error_class=("WeatherReadbackUnavailable" if unverifiable
                     else "WeatherReadbackMismatch"),
        remediation="inspect the per-field statuses; do NOT treat this as applied",
        value=application.as_dict(),
        state_restored=None,
    )