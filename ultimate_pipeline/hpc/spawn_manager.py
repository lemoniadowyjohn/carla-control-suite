#!/usr/bin/env python3
"""spawn_manager.py

Small, robust spawning helpers for CARLA experiments.

Why this exists:
- After importing OpenDRIVE, spawn points can be sparse/weird.
- `try_spawn_actor` can fail for reasons that are hard to reproduce.
- A bit of "retry + clear-space heuristics" makes experiments much less flaky.
"""

from __future__ import annotations

import random
import time
from typing import Optional, Sequence, Tuple

try:
    import carla
except Exception as e:  # pragma: no cover
    carla = None  # type: ignore


def _shuffle(seq):
    seq = list(seq)
    random.shuffle(seq)
    return seq


def pick_spawn_points(
    world: "carla.World",
    k: int = 10,
    min_xy_separation_m: float = 8.0,
) -> Sequence["carla.Transform"]:
    """Pick up to k spawn points, trying to avoid points too close to each other."""
    sp = list(world.get_map().get_spawn_points())
    if not sp:
        return []

    chosen = []
    for t in _shuffle(sp):
        if len(chosen) >= k:
            break
        ok = True
        for c in chosen:
            dx = t.location.x - c.location.x
            dy = t.location.y - c.location.y
            if (dx * dx + dy * dy) ** 0.5 < min_xy_separation_m:
                ok = False
                break
        if ok:
            chosen.append(t)
    return chosen


def safe_spawn_vehicle(
    world: "carla.World",
    blueprint_filter: str = "vehicle.*",
    transform: Optional["carla.Transform"] = None,
    role_name: str = "ego",
    max_attempts: int = 25,
    sleep_s: float = 0.05,
) -> "carla.Actor":
    """Spawn a vehicle with retries. Raises RuntimeError if it cannot spawn."""
    if carla is None:  # pragma: no cover
        raise RuntimeError("CARLA PythonAPI not importable")

    blueprints = world.get_blueprint_library().filter(blueprint_filter)
    if not blueprints:
        raise RuntimeError(f"No blueprints match: {blueprint_filter}")

    if transform is None:
        sp = pick_spawn_points(world, k=20)
        if not sp:
            raise RuntimeError("No spawn points available in the current map")
        candidates = list(sp)
    else:
        candidates = [transform]

    for attempt in range(1, max_attempts + 1):
        bp = random.choice(blueprints)
        try:
            bp.set_attribute("role_name", role_name)
        except Exception:
            pass

        t = random.choice(candidates)
        actor = world.try_spawn_actor(bp, t)
        if actor is not None:
            return actor

        time.sleep(sleep_s)

    raise RuntimeError(f"Failed to spawn vehicle after {max_attempts} attempts")


def destroy_actors(world: "carla.World", actors: Sequence["carla.Actor"]) -> None:
    """Best-effort destroy."""
    for a in actors:
        try:
            a.destroy()
        except Exception:
            pass
