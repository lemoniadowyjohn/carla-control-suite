"""Owned-actor registry with sensor-before-parent teardown.

Two rules the registry enforces:

* **Only caller-owned actors are destroyed.** An actor the registry did not
  create is never destroyed, even if asked to.
* **Sensors are torn down before their parent.** CARLA requires this; tearing
  down the parent first orphans the sensor and leaks it.

Liveness is checked by calling ``is_alive()`` as a **method**. The repository
has four sites that treat it as an attribute (Q21). This adapter calls it as a
method and additionally tolerates the buggy attribute-style exposure, so the
adapter stays safe even if the separate source fix is postponed.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Iterable

from ultimate_pipeline.gui.results import Result

__all__ = ["ActorRecord", "OwnedActorRegistry", "is_alive"]


def is_alive(actor: Any) -> bool:
    """Truthfully determine actor liveness.

    Tries the correct **method** call first, then tolerates the attribute-style
    bug (a bound method object is truthy even for a dead actor, and a bare bool
    is used as-is). An undecidable actor is reported dead, never alive, because
    a false "alive" would skip cleanup and leak.
    """
    if actor is None:
        return False
    probe = getattr(actor, "is_alive", None)
    if probe is None:
        return False
    if callable(probe):
        try:
            return bool(probe())
        except Exception:
            return False
    # Attribute style: ``actor.is_alive`` is a bool (or any truthy object).
    return bool(probe)


@dataclass
class ActorRecord:
    actor_id: int
    actor: Any
    kind: str = "vehicle"
    parent_id: int | None = None
    owned: bool = True

    @property
    def is_sensor(self) -> bool:
        return self.kind == "sensor"


class OwnedActorRegistry:
    """Tracks actors this session created, and destroys only those."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._actors: dict[int, ActorRecord] = {}
        #: actors observed but NOT created by us; never destroyed
        self._external: set[int] = set()

    # -- registration ------------------------------------------------------
    def register(self, actor_id: int, actor: Any, kind: str = "vehicle",
                 parent_id: int | None = None) -> ActorRecord:
        with self._lock:
            record = ActorRecord(actor_id, actor, kind, parent_id, owned=True)
            self._actors[actor_id] = record
            return record

    def register_external(self, actor_id: int) -> None:
        """Record a foreign actor so it is provably never destroyed."""
        with self._lock:
            self._external.add(actor_id)

    def owns(self, actor_id: int) -> bool:
        with self._lock:
            return actor_id in self._actors

    def __len__(self) -> int:
        with self._lock:
            return len(self._actors)

    def actor_ids(self) -> tuple[int, ...]:
        with self._lock:
            return tuple(sorted(self._actors))

    # -- teardown ----------------------------------------------------------
    def destroy(self, actor_id: int) -> Result:
        """Destroy ONE owned actor. Refuses for external or unknown ids."""
        with self._lock:
            if actor_id in self._external:
                return Result.blocked(
                    f"actor {actor_id} is not owned by this session",
                    remediation="external actors are never destroyed by this registry",
                )
            record = self._actors.get(actor_id)
            if record is None:
                return Result.blocked(f"actor {actor_id} is not in the owned registry")

            if not is_alive(record.actor):
                self._actors.pop(actor_id, None)
                return Result.success(True)  # already gone; nothing to destroy

            # A parent must outlive its sensors.
            children = [r for r in self._actors.values()
                        if r.parent_id == actor_id and r.is_sensor]
            if children:
                return Result.failure(
                    f"actor {actor_id} still owns {len(children)} sensor(s); "
                    "destroy sensors first",
                    error_class="TeardownOrderError",
                    remediation="call destroy_sensors_for() before destroy()",
                )

            # A sensor must stop listening before its actor is destroyed
            # (same ordering as carla_tools/sensor_registry.py). A failed
            # stop must never prevent destroy -- that would leak the actor.
            if record.is_sensor:
                stop = getattr(record.actor, "stop", None)
                if callable(stop):
                    try:
                        stop()
                    except Exception:
                        pass
            try:
                record.actor.destroy()
            except Exception as exc:
                return Result.failure(
                    f"destroy() raised: {exc}", error_class=type(exc).__name__,
                    error_source="ultimate_pipeline/gui/session/actor_registry.py",
                    state_restored=False,
                )
            self._actors.pop(actor_id, None)
            return Result.success(True)

    def destroy_sensors_for(self, parent_id: int) -> Result:
        """Destroy every owned sensor attached to ``parent_id``, in order."""
        with self._lock:
            children = sorted(
                (r for r in self._actors.values()
                 if r.parent_id == parent_id and r.is_sensor),
                key=lambda r: r.actor_id,
            )
        failures: list[str] = []
        for child in children:
            outcome = self.destroy(child.actor_id)
            if not outcome.ok:
                failures.append(f"{child.actor_id}: {outcome.reason}")
        if failures:
            return Result.failure("; ".join(failures), error_class="TeardownError")
        return Result.success(len(children))

    def destroy_all(self) -> Result:
        """Full ordered teardown: sensors first, then their parents.

        Returns an explicit failure listing anything that could not be cleaned.
        Never reports success while a leak remains.
        """
        with self._lock:
            records = list(self._actors.values())

        failures: list[str] = []

        for record in sorted(records, key=lambda r: r.actor_id):
            if not record.is_sensor:
                continue
            outcome = self.destroy(record.actor_id)
            if not outcome.ok:
                failures.append(f"sensor {record.actor_id}: {outcome.reason}")

        for record in sorted(records, key=lambda r: r.actor_id):
            if record.is_sensor:
                continue
            self.destroy_sensors_for(record.actor_id)
            outcome = self.destroy(record.actor_id)
            if not outcome.ok:
                failures.append(f"actor {record.actor_id}: {outcome.reason}")

        with self._lock:
            leaked = sorted(self._actors)
        if leaked:
            failures.append(f"leaked actor ids after teardown: {leaked}")
        if failures:
            return Result.failure("; ".join(failures), error_class="TeardownLeak",
                                  state_restored=False)
        return Result.success(True)

    def cleanup_report(self) -> Result:
        """Post-cleanup verification. Success requires an empty registry."""
        with self._lock:
            leaked = sorted(self._actors)
            external = sorted(self._external)
        if leaked:
            return Result.failure(
                f"{len(leaked)} actor(s) still owned: {leaked}",
                error_class="ActorLeak", state_restored=False,
                remediation="re-run teardown or destroy the remaining ids manually",
                # the ids are also carried on the value so callers can record
                # explicit leak evidence without re-parsing the reason string
                value={"leaked": len(leaked), "leaked_ids": tuple(leaked),
                       "preserved_external": tuple(external)},
            )
        return Result.success({"leaked": 0, "leaked_ids": (),
                               "preserved_external": tuple(external)})