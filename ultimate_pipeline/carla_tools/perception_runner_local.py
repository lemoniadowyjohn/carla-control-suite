#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import math
import os
from datetime import datetime

import carla
from ultimate_pipeline.config.settings import SETTINGS
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Backward-compatibility shim:
# Old code imported LocalPerceptionRunner from this module.
# The canonical implementation now lives in local_perception_runner.py.

from ultimate_pipeline.carla_tools.local_perception_runner import LocalPerceptionRunner  # noqa: F401

from ultimate_pipeline.carla_tools.spawn_recovery import try_safe_spawn
from ultimate_pipeline.carla_tools.tile_streamer import TileStreamer
from ultimate_pipeline.sensors.dominik_sensor_setup import DominikSensorSetup


class LocalPerceptionRunner:
    """
    Laptop-friendly road defect inspector.

    Features:
    - Streams tiles around ego vehicle (TileStreamer)
    - Attaches ALL calibrated cameras + LiDAR (DominikSensorSetup)
    - Detects stuck ego, abnormal pitch/roll (road instability proxy)
    - Stores per-sensor images + full defect log as JSON
    """

    def __init__(self, client: carla.Client, map_name: str, tiles=None):
        self.client = client
        self.world = client.get_world()
        self.map = self.world.get_map()
        self.blueprints = self.world.get_blueprint_library()

        self.tiles = tiles
        self.tile_streamer = TileStreamer(client)

        self.actor_list = []
        self.sensor_list = []
        self.sensor_setup = DominikSensorSetup(
            SETTINGS.SENSOR_CALIB_JSON,
            flip_vehicle_y=SETTINGS.SENSOR_FLIP_VEHICLE_Y,
            opencv_camera_axes=SETTINGS.SENSOR_OPENCV_CAMERA_AXES,
            lidar_axes_mode=SETTINGS.SENSOR_LIDAR_AXES_MODE,
        )

        # Output directory
        self.output_dir = os.path.join(
            SETTINGS.output_dir(),
            "perception_local_" + datetime.now().strftime("%H%M%S")
        )
        os.makedirs(self.output_dir, exist_ok=True)

        self.results = []

    # ---------------------------------------------------------------
    # Spawn ego car
    # ---------------------------------------------------------------

    def _spawn_ego(self, spawn_point: carla.Transform) -> carla.Actor:
        bp = self.blueprints.find("vehicle.tesla.model3")
        bp.set_attribute("role_name", "ego")

        ego = try_safe_spawn(self.world, bp, spawn_point)
        if not ego:
            raise RuntimeError("❌ Failed to spawn ego vehicle")

        ego.set_autopilot(SETTINGS.EGO_AUTOPILOT)
        self.actor_list.append(ego)

        return ego

    # ---------------------------------------------------------------
    # CAMERA + LIDAR attachment (via DominikSensorSetup)
    # ---------------------------------------------------------------

    def _attach_sensors(self, ego: carla.Actor):
        print("📷 Attaching calibrated sensors (DominikSensorSetup)…")
        sensors = self.sensor_setup.setup_all_sensors(self.world, ego)

        for name, sensor in sensors.items():
            # Attach listeners only for cameras
            if "camera" in name:
                sensor.listen(lambda data, n=name: self._save_image(data, n))
            self.sensor_list.append(sensor)

        print(f"✅ Attached {len(sensors)} sensors")
        return sensors

    def _save_image(self, image, sensor_name: str):
        fp = os.path.join(self.output_dir, f"{sensor_name}_{image.frame}.png")
        image.save_to_disk(fp)

    # ---------------------------------------------------------------
    # NPC Spawning
    # ---------------------------------------------------------------

    def _spawn_npcs(self, count: int) -> int:
        vehicle_bps = self.blueprints.filter("vehicle.*")
        spawn_points = self.map.get_spawn_points()

        if not spawn_points:
            print("⚠ No spawn points available for NPCs")
            return 0

        spawned = 0
        for i in range(min(count, len(spawn_points))):
            try:
                bp = vehicle_bps[i % len(vehicle_bps)]
                v = try_safe_spawn(self.world, bp, spawn_points[i])
                if v:
                    v.set_autopilot(True)
                    self.actor_list.append(v)
                    spawned += 1
            except Exception:
                continue

        print(f"🚗 Spawned {spawned} NPCs")
        return spawned

    # ---------------------------------------------------------------
    # Defect detection
    # ---------------------------------------------------------------

    def _detect_defect(self, ego: carla.Actor):
        vel = ego.get_velocity()
        speed = 3.6 * math.sqrt(vel.x**2 + vel.y**2 + vel.z**2)

        tr = ego.get_transform()
        pitch = abs(tr.rotation.pitch)
        roll = abs(tr.rotation.roll)

        loc = ego.get_location()

        try:
            wp = self.map.get_waypoint(loc, project_to_road=True)
        except RuntimeError:
            # If CARLA can't find a waypoint (off-road), treat as potential defect
            return ("off_road", loc, None, None)

        # Speed threshold: stuck
        if speed < 0.1:
            return ("stuck", loc, wp.road_id, wp.s)

        # Vehicle orientation abnormal
        if pitch > 15 or roll > 15:
            return ("unstable_orientation", loc, wp.road_id, wp.s)

        return None

    # ---------------------------------------------------------------
    # Cleanup
    # ---------------------------------------------------------------
    def _debug_save_first_frame(image, name):
        image.save_to_disk(f"_debug_{name}_%06d.png")

    def _cleanup(self):
        print("🧹 Destroying actors & sensors…")
        for s in self.sensor_list:
            try:
                s.stop()
            except Exception:
                pass
            try:
                s.destroy()
            except Exception:
                pass

        for a in self.actor_list:
            try:
                a.destroy()
            except Exception:
                pass

        self.sensor_list.clear()
        self.actor_list.clear()
        print("✅ Cleanup done.")

    # ---------------------------------------------------------------
    # MAIN LOOP
    # ---------------------------------------------------------------

    def run(self):
        print("🚀 Starting Local Perception QA…")

        if not self.map.get_spawn_points():
            raise RuntimeError("No spawn points available on this map")

        # Spawn ego
        spawn_point = self.map.get_spawn_points()[0]
        ego = self._spawn_ego(spawn_point)

        # Attach all calibrated sensors
        self._attach_sensors(ego)

        # Spawn NPCs
        npc_count = min(SETTINGS.MAX_NPCS_LOCAL, 20)
        self._spawn_npcs(npc_count)

        try:
            # Simulation loop (~45 ticks; 45 seconds if synchronous)
            sim_time = 0.0
            while sim_time < 45.0:
                self.world.tick()
                sim_time += 1.0

                # STREAM TILES each tick (safe, no-op if metadata missing)
                try:
                    self.tile_streamer.stream_once(ego)
                except Exception as e:
                    print(f"[TileStreamer] Error: {e}")

                # Detect road defects
                defect = self._detect_defect(ego)
                if defect:
                    kind, loc, rid, s = defect
                    entry = {
                        "event": kind,
                        "x": loc.x,
                        "y": loc.y,
                        "z": loc.z,
                        "road_id": rid,
                        "s": s,
                    }
                    self.results.append(entry)
                    print("⚠ Detected:", entry)

        finally:
            # Save defect logs regardless of how the loop ends
            out_path = os.path.join(self.output_dir, "defects.json")
            with open(out_path, "w") as f:
                json.dump(self.results, f, indent=2)
            print(f"🧾 Defect log written → {out_path}")

            self._cleanup()
            print("🎉 Local perception completed.")
