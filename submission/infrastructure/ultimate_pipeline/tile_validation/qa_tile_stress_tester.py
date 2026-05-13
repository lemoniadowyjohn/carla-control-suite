# ultimate_pipeline/carla_tools/qa_tile_stress_tester.py

import os
import json
import math
import time
import carla
from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world
from datetime import datetime


from ultimate_pipeline.carla_tools.reload_ready_for_sensors import _reload_ready_for_sensors
class TileStressTester:
    """
    Tile-wise stress test:
    - Loads each tile individually in CARLA 0.9.16
    - Extracts spawn points
    - Tries multiple spawn offsets (~1/3 vehicle length)
    - Spawns several vehicles per spawn point
    - Evaluates:
        * spawn collisions
        * Z-jumps (floating/sinking)
        * unstable pitch/roll
        * immediate crash
    - Captures screenshots and logs
    """

    def __init__(
        self,
        client: carla.Client,
        tiles_dir: str,
        out_dir: str,
        max_spawns_per_tile=25,
        vehicles_per_spawn=5,
        offset_m=1.3
    ):
        self.client = client
        self.tiles_dir = tiles_dir
        self.max_spawns_per_tile = max_spawns_per_tile
        self.vehicles_per_spawn = vehicles_per_spawn
        self.offset_m = offset_m

        self.out_root = os.path.join(out_dir, "tile_stress")
        os.makedirs(self.out_root, exist_ok=True)

    # -------------------------------------------------------------
    # Helper: load XODR tile
    # -------------------------------------------------------------
    def _load_tile(self, xodr_path):
        with open(xodr_path, encoding="utf-8") as f:
            data = f.read()

        params = carla.OpendriveGenerationParameters()
        params.map_layers = carla.MapLayer.NONE
        world = load_opendrive_world(
            self.client,
            data,
            params=params,
            timeout_s=180.0,
            retries=2,
            do_reload=True,
        )
        # CARLA 0.9.16: must use positional float, not keyword arg
        world.wait_for_tick(2.0)
        return world

    # -------------------------------------------------------------
    # Helper: attach debug camera
    # -------------------------------------------------------------
    @staticmethod
    def _attach_debug_camera(world, vehicle, out_path):

        bp = world.get_blueprint_library().find("sensor.camera.rgb")
        bp.set_attribute("image_size_x", "640")
        bp.set_attribute("image_size_y", "360")
        bp.set_attribute("fov", "90")

        cam_tf = carla.Transform(
            carla.Location(x=1.2, z=1.6),
            carla.Rotation(pitch=-8.0)
        )

        sensor = world.spawn_actor(bp, cam_tf, attach_to=vehicle)

        def save_image(img):
            img.save_to_disk(out_path)

        sensor.listen(lambda data: save_image(data))
        return sensor

    # -------------------------------------------------------------
    # Helper: compute speed
    # -------------------------------------------------------------
    @staticmethod
    def _speed_kmh(v):
        return 3.6 * math.sqrt(v.x**2 + v.y**2 + v.z**2)

    # -------------------------------------------------------------
    # Per-spawn test
    # -------------------------------------------------------------
    def _test_spawn(self, world, spawn_tf, tile_dir, spawn_index):

        results = []
        actors = []
        cam_sensors = []

        offset_loc = carla.Location(
            spawn_tf.location.x + self.offset_m * math.cos(math.radians(spawn_tf.rotation.yaw)),
            spawn_tf.location.y + self.offset_m * math.sin(math.radians(spawn_tf.rotation.yaw)),
            spawn_tf.location.z,
        )
        offset_tf = carla.Transform(offset_loc, spawn_tf.rotation)

        bp_vehicle = world.get_blueprint_library().filter("vehicle.*model3*")[0]

        ok_count = 0
        fail_count = 0

        for i in range(self.vehicles_per_spawn):
            try:
                v = world.try_spawn_actor(bp_vehicle, offset_tf)
                if not v:
                    fail_count += 1
                    continue

                actors.append(v)
                ok_count += 1

                # Attach camera: screenshot path
                img_path = os.path.join(tile_dir, f"spawn_{spawn_index:02d}_veh{i}.png")
                cam = self._attach_debug_camera(world, v, img_path)
                cam_sensors.append(cam)

            except Exception as e:
                fail_count += 1
                continue

        # Tick physics
        world.tick()
        time.sleep(0.15)
        world.tick()

        # Analyze spawned vehicles
        for v in actors:
            loc = v.get_location()
            tr = v.get_transform()
            vel = v.get_velocity()

            speed = self._speed_kmh(vel)
            pitch = abs(tr.rotation.pitch)
            roll = abs(tr.rotation.roll)

            entry = {
                "x": loc.x,
                "y": loc.y,
                "z": loc.z,
                "speed_kmh": speed,
                "pitch": pitch,
                "roll": roll,
                "spawn_ok": True,
            }

            if loc.z < -2 or loc.z > 3:
                entry["spawn_ok"] = False
                entry["reason"] = "Z_jump"

            if pitch > 20 or roll > 20:
                entry["spawn_ok"] = False
                entry["reason"] = "unstable_orientation"

            results.append(entry)

        # cleanup
        for s in cam_sensors:
            try:
                s.stop()
                s.destroy()
            except:
                pass

        for v in actors:
            try:
                v.destroy()
            except:
                pass

        return results

    # -------------------------------------------------------------
    # MAIN RUN: per-tile stress test
    # -------------------------------------------------------------
    def run(self):

        from glob import glob
        tile_paths = sorted(glob(os.path.join(self.tiles_dir, "tile_*.xodr")))

        full_results = {}

        for tile_path in tile_paths:
            tile_name = os.path.basename(tile_path)
            print(f"\n🧪 Stress testing {tile_name}...")

            tile_dir = os.path.join(self.out_root, tile_name)
            os.makedirs(tile_dir, exist_ok=True)

            try:
                world = self._load_tile(tile_path)
            except Exception as e:
                print(f"❌ Could not load tile: {e}")
                continue

            spawn_points = world.get_map().get_spawn_points()
            spawn_points = spawn_points[:self.max_spawns_per_tile]

            tile_results = []

            for i, sp in enumerate(spawn_points):
                print(f"   → Testing spawn {i+1}/{len(spawn_points)}")
                res = self._test_spawn(world, sp, tile_dir, i)
                tile_results.append({
                    "spawn_index": i,
                    "results": res
                })

            # Save tile results
            with open(os.path.join(tile_dir, "results.json"), "w", encoding="utf-8") as f:
                json.dump(tile_results, f, indent=2)

            full_results[tile_name] = tile_results

            # unload tile → load a clean map
            try:
                _reload_ready_for_sensors(self.client, map_name="Town01", tm_port=8000)
            except:
                pass

        # Save global results
        summary_path = os.path.join(self.out_root, "summary.json")
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(full_results, f, indent=2)

        print(f"\n🏁 Tile stress test complete → {summary_path}")
