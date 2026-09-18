import argparse
import queue
import time
from pathlib import Path

import carla
import numpy as np


def safe_spawn_vehicle(world, bp_filter="vehicle.tesla.model3"):
    bp_lib = world.get_blueprint_library()
    candidates = bp_lib.filter(bp_filter) or bp_lib.filter("vehicle.*")
    if not candidates:
        raise RuntimeError("No vehicle blueprints found (possible CARLA/PythonAPI version mismatch).")
    v_bp = candidates[0]

    spawn_points = world.get_map().get_spawn_points()
    if not spawn_points:
        raise RuntimeError("No spawn points in map (map load broken?).")

    for sp in spawn_points[:80]:
        v = world.try_spawn_actor(v_bp, sp)
        if v is not None:
            return v
    raise RuntimeError("Could not spawn a vehicle (spawn points blocked/collisions).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--out", default="_perception_smoke_out")
    ap.add_argument("--no-lidar", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    client = carla.Client(args.host, args.port)
    client.set_timeout(120.0)

    world = client.get_world()

    # Wait until server is responsive
    world.wait_for_tick(seconds=10.0)

    original_settings = world.get_settings()
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.05
    world.apply_settings(settings)

    vehicle = None
    sensors = []
    rgb_q = queue.Queue()
    lidar_q = queue.Queue()

    try:
        # Spawn vehicle
        vehicle = safe_spawn_vehicle(world)

        bp_lib = world.get_blueprint_library()

        # RGB camera
        cam_bp = bp_lib.find("sensor.camera.rgb")
        cam_bp.set_attribute("image_size_x", "800")
        cam_bp.set_attribute("image_size_y", "600")
        cam_bp.set_attribute("fov", "90")
        cam_bp.set_attribute("sensor_tick", "0.0")  # every tick

        cam_tf = carla.Transform(carla.Location(x=1.5, z=2.4))
        camera = world.spawn_actor(cam_bp, cam_tf, attach_to=vehicle)
        sensors.append(camera)

        def on_rgb(img: carla.Image):
            rgb_q.put(img)

        camera.listen(on_rgb)

        # Optional LiDAR
        if not args.no_lidar:
            lidar_bp = bp_lib.find("sensor.lidar.ray_cast")
            lidar_bp.set_attribute("range", "50")
            lidar_bp.set_attribute("rotation_frequency", "20")
            lidar_bp.set_attribute("channels", "32")
            lidar_bp.set_attribute("points_per_second", "200000")
            lidar_bp.set_attribute("sensor_tick", "0.0")

            lidar_tf = carla.Transform(carla.Location(x=0.0, z=2.5))
            lidar = world.spawn_actor(lidar_bp, lidar_tf, attach_to=vehicle)
            sensors.append(lidar)

            def on_lidar(meas: carla.LidarMeasurement):
                lidar_q.put(meas)

            lidar.listen(on_lidar)

        # Warm-up ticks
        for _ in range(5):
            world.tick()

        got_rgb = 0
        got_lidar = 0

        saved_rgb = 0
        saved_lidar = 0

        for i in range(args.frames):
            world_frame = world.tick()

            # RGB
            try:
                img = rgb_q.get(timeout=2.0)
                got_rgb += 1
                if saved_rgb < 5:
                    p = out_dir / f"rgb_{img.frame:06d}.png"
                    img.save_to_disk(str(p))
                    arr = np.frombuffer(img.raw_data, dtype=np.uint8).reshape(img.height, img.width, 4)[:, :, :3]
                    print(f"[RGB] world_frame={world_frame} img_frame={img.frame} mean={arr.mean():.2f} saved={p.name}")
                    saved_rgb += 1
            except queue.Empty:
                print(f"[RGB] MISSING on world_frame={world_frame}")

            # LiDAR
            if not args.no_lidar:
                try:
                    meas = lidar_q.get(timeout=2.0)
                    got_lidar += 1
                    if saved_lidar < 3:
                        p = out_dir / f"lidar_{meas.frame:06d}.ply"
                        meas.save_to_disk(str(p))
                        print(f"[LiDAR] world_frame={world_frame} lidar_frame={meas.frame} points={len(meas)} saved={p.name}")
                        saved_lidar += 1
                except queue.Empty:
                    print(f"[LiDAR] MISSING on world_frame={world_frame}")

        print("\n=== SUMMARY ===")
        print(f"RGB   received: {got_rgb}/{args.frames}")
        if args.no_lidar:
            print("LiDAR disabled")
        else:
            print(f"LiDAR received: {got_lidar}/{args.frames}")
        print(f"Outputs: {out_dir.resolve()}")

        if got_rgb == 0:
            raise RuntimeError("No RGB frames received → sensor stream/ticking/connection is broken.")

    finally:
        for s in sensors:
            try:
                s.stop()
            except Exception:
                pass
            try:
                s.destroy()
            except Exception:
                pass
        if vehicle is not None:
            try:
                vehicle.destroy()
            except Exception:
                pass
        try:
            world.apply_settings(original_settings)
        except Exception:
            pass


if __name__ == "__main__":
    main()
