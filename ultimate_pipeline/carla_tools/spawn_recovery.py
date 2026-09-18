# carla_tools/spawn_recovery.py

from __future__ import annotations

import random
from typing import Any, TYPE_CHECKING

# Import-safety: allow importing this module without the CARLA PythonAPI installed.
try:  # pragma: no cover
    import carla  # type: ignore
    _CARLA_AVAILABLE = True
except Exception:  # pragma: no cover
    carla = None  # type: ignore
    _CARLA_AVAILABLE = False

if TYPE_CHECKING:  # pragma: no cover
    import carla as carla_type  # noqa: F401


# ======================================================================
# Top-level safe spawn function (this is the one imported everywhere!)
# ======================================================================

def try_safe_spawn(
    world: Any,
    blueprint: Any,
    transform: Any,
    max_tries: int = 8,
):
    """
    Robust helper used across the pipeline.
    Repeatedly attempts world.try_spawn_actor.

    Returns:
        actor (carla.Actor) or None
    """
    actor = None
    last_error = None

    for _ in range(max_tries):
        try:
            actor = world.try_spawn_actor(blueprint, transform)
            if actor is not None:
                return actor
        except RuntimeError as e:
            last_error = e
            continue

    if last_error:
        print(f"[SpawnRecovery] try_safe_spawn failed after "
              f"{max_tries} tries: {last_error}")
    else:
        print(f"[SpawnRecovery] try_safe_spawn: no free spawn found after "
              f"{max_tries} tries.")

    return None


def try_safe_spawn_from_transforms(
    world: Any,
    blueprint: Any,
    transforms: Any,
    *,
    max_tries_each: int = 2,
    shuffle: bool = True,
):
    """
    Try spawning an actor across a list of candidate transforms.

    This fixes a common failure mode in perception where a single spawn point is occupied
    (world.try_spawn_actor returns None repeatedly). Instead, we iterate multiple spawn points.

    Args:
        world: CARLA world-like object exposing try_spawn_actor
        blueprint: actor blueprint
        transforms: iterable of transforms
        max_tries_each: how many attempts per transform
        shuffle: whether to randomize transform order (helps avoid "always index 0" collisions)

    Returns:
        actor or None
    """
    try:
        candidates = list(transforms) if transforms is not None else []
    except Exception:
        candidates = []

    if not candidates:
        return None

    if shuffle:
        random.shuffle(candidates)

    for tf in candidates:
        actor = try_safe_spawn(world, blueprint, tf, max_tries=max_tries_each)
        if actor is not None:
            return actor
    return None


# ======================================================================
# Class wrapper for backwards compatibility
# ======================================================================

class SpawnRecovery:

    @staticmethod
    def try_manual_spawn(world: Any):
        """
        Older helper used in some fallback logic.
        Returns first successful spawn of an Audi TT.
        """
        amap = world.get_map()
        wps = amap.generate_waypoints(2.0)

        bp_lib = world.get_blueprint_library()
        vehicle_bp = bp_lib.find("vehicle.audi.tt")

        for wp in wps:
            if wp.lane_type != carla.LaneType.Driving:
                continue
            try:
                actor = world.try_spawn_actor(vehicle_bp, wp.transform)
                if actor:
                    return actor
            except Exception:
                pass
        return None

    # Keep class method alias for compatibility — internally uses the
    # top-level canonical function (avoids duplication and signature mismatch)
    @staticmethod
    def try_safe_spawn(
        world: Any,
        blueprint: Any,
        transform: Any,
        max_tries: int = 8,
    ):
        """Wrapper around the module-level function."""
        return try_safe_spawn(world, blueprint, transform, max_tries)
