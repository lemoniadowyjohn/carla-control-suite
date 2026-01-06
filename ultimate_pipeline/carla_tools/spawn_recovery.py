# carla_tools/spawn_recovery.py

import carla
import random


# ======================================================================
# Top-level safe spawn function (this is the one imported everywhere!)
# ======================================================================

def try_safe_spawn(
    world: carla.World,
    blueprint: carla.ActorBlueprint,
    transform: carla.Transform,
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


# ======================================================================
# Class wrapper for backwards compatibility
# ======================================================================

class SpawnRecovery:

    @staticmethod
    def try_manual_spawn(world: carla.World):
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
        world: carla.World,
        blueprint: carla.ActorBlueprint,
        transform: carla.Transform,
        max_tries: int = 8,
    ):
        """Wrapper around the module-level function."""
        return try_safe_spawn(world, blueprint, transform, max_tries)
