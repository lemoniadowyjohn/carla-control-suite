
import math, time, carla

def settle(world, ticks=20, sleep_s=1.0):
    for _ in range(ticks):
        # CARLA 0.9.16: must use positional float, not keyword arg
        world.wait_for_tick(2.0)
    time.sleep(sleep_s)

def sane_transform(t: carla.Transform):
    loc, rot = t.location, t.rotation
    vals = [loc.x, loc.y, loc.z, rot.pitch, rot.roll, rot.yaw]
    if any([not math.isfinite(v) for v in vals]):
        return False
    if abs(rot.pitch) > 15 or abs(rot.roll) > 15:
        return False
    return True

def spawn_ego(world, blueprint, spawn_points, retries=10):
    for sp in spawn_points[:retries]:
        if not sane_transform(sp): continue
        a = world.try_spawn_actor(blueprint, sp)
        if a: return a
    raise RuntimeError("Failed to spawn ego with sane transforms")
