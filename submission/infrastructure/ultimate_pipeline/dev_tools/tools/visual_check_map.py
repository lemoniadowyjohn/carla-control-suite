import carla
import time

def main(host="127.0.0.1", port=2000):
    client = carla.Client(host, port)
    client.set_timeout(20.0)
    world = client.get_world()

    # Put world into sync for consistent stepping (optional but recommended)
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.05
    world.apply_settings(settings)

    # Spawn ego vehicle
    bp_lib = world.get_blueprint_library()
    vehicle_bp = bp_lib.filter("vehicle.*model3*")[0]
    spawn_points = world.get_map().get_spawn_points()
    ego = world.try_spawn_actor(vehicle_bp, spawn_points[0])
    if ego is None:
        ego = world.spawn_actor(vehicle_bp, spawn_points[0])

    # Move spectator above ego
    spectator = world.get_spectator()
    transform = ego.get_transform()
    spectator.set_transform(carla.Transform(
        transform.location + carla.Location(z=60),
        carla.Rotation(pitch=-90)
    ))

    # Tick a bit so everything settles
    for _ in range(20):
        world.tick()

    print("Map loaded:", world.get_map().name)
    print("Ego id:", ego.id)
    print("Fly around with spectator (WASD+mouse) in the CARLA window.")
    time.sleep(10)

    # Cleanup
    ego.destroy()
    settings.synchronous_mode = False
    world.apply_settings(settings)

if __name__ == "__main__":
    main()
