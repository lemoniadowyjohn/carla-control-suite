"""Deterministic ``CarlaBackend`` mock.

Simulates ``probe``, ``server_version``, ``available_maps``, ``load_world``,
``reset_world``, ``acquire_tick``/``release_tick``, ``spawn_actor``,
``destroy_actor``, ``attach_sensor``, ``apply_weather`` and ``read_settings``.

Determinism: every actor id, tick and sensor handle is derived from a
monotonic counter, so two runs of the same script produce identical output.

``carla`` is never imported here.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

from ultimate_pipeline.gui.cancellation import CancellationToken
from ultimate_pipeline.gui.health import SessionAuthority
from ultimate_pipeline.gui.results import Result, Tri, TriState, UnsupportedCapability

__all__ = [
    "MockCarlaBackend", "WorldSettings", "ActorSpec", "OwnedActor",
    "TickGrant", "SensorBinding", "WorldSpec", "WeatherSpec", "DEFAULT_MAPS",
]

DEFAULT_MAPS = ("Town01", "Town02", "Town03", "Town04", "Town05")


@dataclass(frozen=True)
class WorldSettings:
    available: bool
    synchronous_mode: bool = False
    fixed_delta_seconds: float = 0.0
    loaded_map: str = ""


@dataclass(frozen=True)
class ActorSpec:
    blueprint: str
    transform: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


@dataclass(frozen=True)
class OwnedActor:
    actor_id: int
    blueprint: str
    owned: bool = True


@dataclass(frozen=True)
class TickGrant:
    granted: bool
    holder: str = ""
    reason: str = ""


@dataclass(frozen=True)
class SensorBinding:
    sensor_id: str
    attached: bool
    calibration_id: str = ""


@dataclass(frozen=True)
class WorldSpec:
    name: str


@dataclass(frozen=True)
class WeatherSpec:
    preset: str


class MockCarlaBackend:
    """Offline stand-in for the live ``CarlaBackend``."""

    def __init__(self, *, available: bool = True, maps_supported: bool = True) -> None:
        self._available = available
        self._maps_supported = maps_supported
        self._ids = itertools.count(1000)
        self._tick_ids = itertools.count(1)
        self._actor_ids: set[int] = set()
        self._tick_holder: str = ""
        self._tick_issued: set[int] = set()
        self._world = WorldSettings(available=available)
        self._authority = SessionAuthority.SHARED_READONLY

    # -- connection --------------------------------------------------------
    def probe(self, host: str, port: int, timeout_s: float) -> Result:
        if not self._available:
            return Result.blocked(
                "mock backend configured as unavailable",
                remediation="set MockCarlaBackend(available=True)",
            )
        return Result.success(f"{host}:{port}")

    def server_version(self) -> str | None:
        return "0.9.16" if self._available else None

    def available_maps(self) -> Tri:
        if not self._maps_supported:
            return Tri.unsupported("mock backend does not implement map enumeration")
        return Tri.available_value(list(DEFAULT_MAPS))

    # -- world -------------------------------------------------------------
    def load_world(self, spec: WorldSpec, token: CancellationToken | None = None) -> Result:
        if token is not None:
            token.raise_if_cancelled()
        if spec.name not in DEFAULT_MAPS:
            return Result.failure(
                f"unknown map {spec.name!r}",
                error_class="MapTravelProhibitedError",
                error_source="ultimate_pipeline/gui/adapters/mock_backend.py",
            )
        self._world = WorldSettings(available=True, loaded_map=spec.name)
        return Result.success(self._world)

    def reset_world(self, token: CancellationToken | None = None) -> Result:
        if token is not None:
            token.raise_if_cancelled()
        self._actor_ids.clear()
        self._tick_holder = ""
        self._tick_issued.clear()
        self._world = WorldSettings(available=self._available)
        return Result.success(self._world)

    def read_settings(self) -> WorldSettings:
        return self._world

    # -- tick authority ----------------------------------------------------
    def acquire_tick(self, owner: str = "") -> TickGrant:
        from ultimate_pipeline.gui.session.session import exclusive_claimed
        if not exclusive_claimed(self._authority):
            return TickGrant(
                False, "",
                f"authority {self._authority!r} is not an explicit exclusive grant")
        if self._tick_holder:
            return TickGrant(False, self._tick_holder, "tick already granted")
        self._tick_holder = owner or "mock-owner"
        return TickGrant(True, self._tick_holder)

    def release_tick(self, owner: str = "") -> Result:
        if self._tick_holder and owner and owner != self._tick_holder:
            return Result.failure(
                f"tick held by {self._tick_holder!r}, not {owner!r}",
                error_class="PermissionError",
            )
        self._tick_holder = ""
        return Result.success(True)

    @property
    def tick_holder(self) -> str:
        return self._tick_holder

    # -- actors and sensors ------------------------------------------------
    def spawn_actor(self, spec: ActorSpec) -> Result:
        if not self._available:
            return Result.blocked("mock backend unavailable")
        actor_id = next(self._ids)
        self._actor_ids.add(actor_id)
        return Result.success(OwnedActor(actor_id, spec.blueprint))

    def destroy_actor(self, actor_id: int) -> Result:
        if actor_id not in self._actor_ids:
            return Result.failure(
                f"actor {actor_id} is not owned by this session",
                error_class="RuntimeError",
            )
        self._actor_ids.discard(actor_id)
        return Result.success(True)

    def owned_actor_ids(self) -> tuple[int, ...]:
        return tuple(sorted(self._actor_ids))

    def attach_sensor(self, spec: Any, calibration: Any) -> Result:
        sensor_id = f"sensor-{next(self._ids)}"
        return Result.success(SensorBinding(sensor_id, True, getattr(calibration, "profile_id", "")))

    # -- weather -----------------------------------------------------------
    def apply_weather(self, spec: WeatherSpec, token: CancellationToken | None = None) -> Result:
        if token is not None:
            token.raise_if_cancelled()
        if spec.preset == "UnsupportedPreset":
            return Result.failure(
                f"unsupported weather preset {spec.preset!r}",
                error_class="ValueError",
                error_source="ultimate_pipeline/gui/adapters/mock_backend.py",
                remediation="choose a preset from the documented list",
            )
        return Result.success(spec.preset)

    # -- capability declaration -------------------------------------------
    def unsupported(self) -> list[UnsupportedCapability]:
        return [
            UnsupportedCapability(
                "tick grant under SHARED_READONLY",
                "mock backend holds no exclusive authority",
                "claim EXCLUSIVE_TICK in the session authority panel",
                "ultimate_pipeline/gui/health.py",
            )
        ]

    def cleanup(self) -> list[str]:
        """Report exactly what could not be cleaned, rather than hiding it."""
        failures: list[str] = []
        if self._actor_ids:
            failures.append(f"{len(self._actor_ids)} actors still alive: {sorted(self._actor_ids)}")
        if self._tick_holder:
            failures.append(f"tick still granted to {self._tick_holder!r}")
        return failures