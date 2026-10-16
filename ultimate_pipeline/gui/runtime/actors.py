"""Actor catalog, spawn-preview and route services.

All actor mutation goes through the :class:`~ultimate_pipeline.gui.session.actor_registry.OwnedActorRegistry`,
so the registry rules apply unchanged: external actors are never touched, and
sensor-before-parent teardown ordering is preserved.

Spawn is a **two-phase operation**: preview first (which reports conflicts and
requires confirmation), then commit. A preview is never silently promoted to a
commit.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from ultimate_pipeline.gui.results import Result

__all__ = ["SpawnPoint", "SpawnPreview", "ActorCatalog", "RouteSpec", "RouteResult"]


@dataclass(frozen=True)
class SpawnPoint:
    x: float
    y: float
    z: float
    yaw: float = 0.0

    def as_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "z": self.z, "yaw": self.yaw}


@dataclass
class SpawnPreview:
    blueprint: str
    location: SpawnPoint
    occupied_by: int | None = None
    too_close_to: tuple[int, ...] = ()
    safe: bool = True
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {"blueprint": self.blueprint, "location": self.location.as_dict(),
                "occupied_by": self.occupied_by, "too_close_to": list(self.too_close_to),
                "safe": self.safe, "warnings": list(self.warnings)}


@dataclass(frozen=True)
class RouteSpec:
    waypoints: tuple[SpawnPoint, ...]
    loop: bool = False


@dataclass(frozen=True)
class RouteResult:
    assigned: bool
    actor_ids: tuple[int, ...] = ()
    reason: str = ""
    detail: str = ""

    def as_dict(self) -> dict:
        return {"assigned": self.assigned, "actor_ids": list(self.actor_ids),
                "reason": self.reason, "detail": self.detail}


class ActorCatalog:
    """Spawn preview, commit, and route assignment for owned actors."""

    def __init__(self, registry: Any, *, min_separation_m: float = 2.0) -> None:
        self.registry = registry
        self.min_separation_m = float(min_separation_m)
        self._ids = itertools.count(5000)

    # -- preview -----------------------------------------------------------
    def preview_spawn(self, blueprint: str, location: SpawnPoint,
                      occupied: Iterable[tuple[int, SpawnPoint]] = ()) -> SpawnPreview:
        """Report what WOULD happen. Never mutates."""
        occupied_by: int | None = None
        too_close: list[int] = []
        for actor_id, other in occupied:
            distance = (
                (location.x - other.x) ** 2
                + (location.y - other.y) ** 2
                + (location.z - other.z) ** 2
            ) ** 0.5
            if distance < 0.01:
                occupied_by = actor_id
            if distance < self.min_separation_m:
                too_close.append(actor_id)

        warnings: list[str] = []
        if occupied_by is not None:
            warnings.append(f"spawn point is occupied by actor {occupied_by}")
        if too_close:
            warnings.append(f"within {self.min_separation_m} m of actors {sorted(too_close)}")
        return SpawnPreview(blueprint, location, occupied_by, tuple(sorted(too_close)),
                            not warnings, tuple(warnings))

    def commit_spawn(self, preview: SpawnPreview, actor: Any,
                     kind: str = "vehicle") -> Result:
        """Turn a confirmed preview into a registered actor."""
        if not preview.safe and not preview.warnings:
            return Result.blocked("unsafe spawn cannot be committed")
        actor_id = next(self._ids)
        self.registry.register(actor_id, actor, kind=kind)
        return Result.success({"actor_id": actor_id, "blueprint": preview.blueprint})

    # -- routes ------------------------------------------------------------
    def assign_route(self, spec: RouteSpec, actor_ids: Iterable[int],
                     assign_fn: Callable[[int, tuple[SpawnPoint, ...], bool], None]) -> Result:
        """Assign a route to owned actors only.

        ``assign_fn`` is the single point that would touch the simulator, which
        keeps this module free of CARLA imports.
        """
        owned = set(self.registry.actor_ids())
        requested = tuple(actor_ids)
        unowned = sorted(set(requested) - owned)
        if unowned:
            return Result.blocked(
                f"route requested for unowned actors: {unowned}",
                remediation="routes may only be assigned to session-owned actors")
        if len(spec.waypoints) < 2:
            return Result.blocked("a route needs at least two waypoints")

        assigned: list[int] = []
        failures: list[str] = []
        for actor_id in requested:
            try:
                assign_fn(actor_id, spec.waypoints, spec.loop)
                assigned.append(actor_id)
            except Exception as exc:
                failures.append(f"{actor_id}: {type(exc).__name__}: {exc}")
        if failures:
            return Result.failure(
                "route assignment failed for: " + "; ".join(failures),
                error_class="RouteAssignError", state_restored=False,
            )
        return Result.success(RouteResult(True, tuple(assigned)).as_dict())

    # -- catalog views -----------------------------------------------------
    def owned_catalog(self) -> list[dict]:
        out = []
        for actor_id in self.registry.actor_ids():
            record = self.registry._actors[actor_id]  # single writer, internal use
            out.append({"actor_id": actor_id, "kind": record.kind,
                        "parent_id": record.parent_id, "owned": True})
        return out

    def external_catalog(self) -> list[int]:
        return sorted(getattr(self.registry, "_external", set()))