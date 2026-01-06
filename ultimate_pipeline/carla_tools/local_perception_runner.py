#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import math
import os
from datetime import datetime
from typing import Any, Dict, Optional

import carla

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.carla_tools.spawn_recovery import try_safe_spawn
from ultimate_pipeline.carla_tools.tile_streamer import TileStreamer
from ultimate_pipeline.sensors.dominik_sensor_setup import DominikSensorSetup


class LocalPerceptionRunner:
    """
    Laptop-friendly road-defect / local perception inspector.

    Consolidated runner (merges old perception_runner_local.py and local_perception_runner.py).

    Core features:
    - Spawns ego vehicle + optional NPCs on the CURRENT CARLA map (does not reload)
    - Attaches calibrated cameras + LiDAR via DominikSensorSetup
    - Saves camera images (.png) and LiDAR point clouds (.ply)
    - Optional TileStreamer.stream_once(ego) per tick (safe/no-op if metadata missing)
    - Defect detection heuristics:
        * stuck ego (speed < threshold)
        * abnormal pitch/roll
        * off-road (no waypoint)
    - Writes defects.json (+ minimal run metadata)
    """

    def __init__(
        self,
        client: carla.Client,
        map_name: Optional[str] = None,   # kept for backward compatibility (ignored)
        tiles=None,
        duration_ticks: int = 45,
        warmup_ticks: int = 30,
        npc_cap: int = 20,
        spawn_point_index: int = 0,
        **_ignored_kwargs,                # absorb legacy args safely
    ):
        self.client = client
        self.world = client.get_world()
        self.map = self.world.get_map()
        self.blueprints = self.world.get_blueprint_library()

        # NOTE: map_name is intentionally ignored here.
        # Map loading is handled by your pipeline / CARLA load step.
        self._map_name_hint = map_name

        self.tiles = tiles
        self.tile_streamer = TileStreamer(client)

        self.actor_list: list[carla.Actor] = []
        self.sensor_list: list[carla.Sensor] = []

        self.sensor_setup = DominikSensorSetup(
            SETTINGS.SENSOR_CALIB_JSON,
            flip_vehicle_y=SETTINGS.SENSOR_FLIP_VEHICLE_Y,
            opencv_camera_axes=SETTINGS.SENSOR_OPENCV_CAMERA_AXES,
            lidar_axes_mode=SETTINGS.SENSOR_LIDAR_AXES_MODE,
        )

        self.duration_ticks = int(duration_ticks)
        self.warmup_ticks = int(warmup_ticks)
        self.npc_cap = int(npc_cap)
        self.spawn_point_index = int(spawn_point_index)

        self.results: list[Dict[str, Any]] = []

        # Sync/async handling (important: your older file hard-called world.tick())
        world_settings = self.world.get_settings()
        self._sync = bool(getattr(world_settings, "synchronous_mode", False))

        # Output folder
        self.output_dir = os.path.join(
            SETTINGS.output_dir(),
            "perception_local_" + datetime.now().strftime("%Y%m%d_%H%M%S"),
        )
        os.makedirs(self.output_dir, exist_ok=True)

    # -----------------------------
    # Ticking helper
    # -----------------------------
    def _tick(self):
        if self._sync:
            self.world.tick()
        else:
            self.world.wait_for_tick()

    # -----------------------------
    # Ego spawn
    # -----------------------------
    def _spawn_ego(self, spawn_point: carla.Transform) -> carla.Vehicle:
        bp = self.blueprints.find("vehicle.tesla.model3")
        bp.set_attribute("role_name", "ego")

        ego = try_safe_spawn(self.world, bp, spawn_point)
        if not ego:
            raise RuntimeError("❌ Failed to spawn ego vehicle")

        ego.set_autopilot(bool(getattr(SETTINGS, "EGO_AUTOPILOT", True)))
        self.actor_list.append(ego)
        return ego

    # -----------------------------
    # Visual markers (helps quick “does it look sane?” checks)
    # -----------------------------
    def _spawn_visual_markers(self, ego: carla.Vehicle) -> int:
        candidate_ids = [
            "static.prop.trafficcone01",
            "static.prop.streetbarrier",
            "static.prop.warningconstruction",
        ]

        bps = []
        for cid in candidate_ids:
            try:
                bp = self.blueprints.find(cid)
                if bp is not None:
                    bps.append(bp)
            except Exception:
                pass

        if not bps:
            print("⚠️  No static prop blueprints found for visual markers.")
            return 0

        ego_tf = ego.get_transform()
        offsets = [
            carla.Location(x=10.0, y=0.0, z=0.2),
            carla.Location(x=12.0, y=1.5, z=0.2),
            carla.Location(x=12.0, y=-1.5, z=0.2),
            carla.Location(x=16.0, y=0.0, z=0.2),
        ]

        spawned = 0
        for i, off in enumerate(offsets):
            bp = bps[i % len(bps)]
            world_loc = ego_tf.transform(off)
            tf = carla.Transform(world_loc, carla.Rotation(yaw=ego_tf.rotation.yaw))
            try:
                a = self.world.spawn_actor(bp, tf)
                self.actor_list.append(a)
                spawned += 1
            except Exception as e:
                print(f"⚠️  Failed to spawn marker {bp.id}: {e}")

        print(f"[OK] Spawned {spawned} visual markers near ego.")
        return spawned

    # -----------------------------
    # Sensor attachment + capture
    # -----------------------------
    def _attach_sensors(self, ego: carla.Vehicle) -> Dict[str, carla.Actor]:
        print("📷 Attaching calibrated sensors (DominikSensorSetup)…")
        sensors = self.sensor_setup.setup_all_sensors(self.world, ego)
        if not sensors:
            raise RuntimeError("[Perception] No sensors attached to ego vehicle")

        for name, sensor in sensors.items():
            lname = name.lower()
            if "camera" in lname:
                sensor.listen(lambda data, n=name: self._save_image(data, n))
            elif "lidar" in lname:
                sensor.listen(lambda data, n=name: self._save_lidar(data, n))
            self.sensor_list.append(sensor)

        print(f"✅ Attached {len(sensors)} sensors")
        return sensors

    def _save_image(self, image: carla.Image, sensor_name: str):
        fp = os.path.join(self.output_dir, f"{sensor_name}_{image.frame}.png")
        try:
            image.save_to_disk(fp)
        except Exception:
            pass

    def _save_lidar(self, pc: carla.LidarMeasurement, sensor_name: str):
        fp = os.path.join(self.output_dir, f"{sensor_name}_{pc.frame}.ply")
        try:
            pc.save_to_disk(fp)
        except Exception:
            # don’t crash the run if saving fails
            pass

    # -----------------------------
    # NPC spawn
    # -----------------------------
    def _spawn_npcs(self, count: int) -> int:
        vehicle_bps = self.blueprints.filter("vehicle.*")
        spawn_points = self.map.get_spawn_points()

        if not spawn_points:
            print("⚠ No spawn points available for NPCs")
            return 0

        spawned = 0
        max_spawn = min(int(count), len(spawn_points))
        for i in range(max_spawn):
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

    # -----------------------------
    # Defect detection
    # -----------------------------
    def _detect_defect(self, ego: carla.Vehicle):
        vel = ego.get_velocity()
        speed_kmh = 3.6 * math.sqrt(vel.x**2 + vel.y**2 + vel.z**2)

        tr = ego.get_transform()
        pitch = abs(tr.rotation.pitch)
        roll = abs(tr.rotation.roll)

        loc = ego.get_location()

        # Waypoint may fail on broken maps or off-road
        try:
            wp = self.map.get_waypoint(loc, project_to_road=True)
        except RuntimeError:
            return ("off_road", loc, None, None)

        if speed_kmh < 0.1:
            return ("stuck", loc, getattr(wp, "road_id", None), getattr(wp, "s", None))

        if pitch > 15 or roll > 15:
            return ("unstable_orientation", loc, getattr(wp, "road_id", None), getattr(wp, "s", None))

        return None

    # -----------------------------
    # Cleanup
    # -----------------------------
    def _cleanup(self):
        print("🧹 Cleaning up perception actors…")

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

    # -----------------------------
    # MAIN
    # -----------------------------
    def run(self):
        print("🚀 Starting Local Perception QA…")

        # Warm-up (stabilizes physics & autopilot)
        print(f"⏳ Warming up CARLA world ({self.warmup_ticks} ticks)…")
        for _ in range(self.warmup_ticks):
            self._tick()

        spawn_points = self.map.get_spawn_points()
        if not spawn_points:
            raise RuntimeError("❌ No spawn points available on current map")

        sp_idx = max(0, min(self.spawn_point_index, len(spawn_points) - 1))
        ego = self._spawn_ego(spawn_points[sp_idx])

        # Quick visual sanity check props
        self._spawn_visual_markers(ego)

        # Attach all calibrated sensors
        self._attach_sensors(ego)

        # Spawn NPCs (bounded)
        npc_count = int(min(getattr(SETTINGS, "MAX_NPCS_LOCAL", 10), self.npc_cap))
        self._spawn_npcs(npc_count)

        # Save run metadata (helps debugging “was this really Ingolstadt?”)
        meta = {
            "carla_map_name": getattr(self.map, "name", None),
            "map_name_hint": self._map_name_hint,
            "duration_ticks": self.duration_ticks,
            "warmup_ticks": self.warmup_ticks,
            "spawn_point_index": sp_idx,
            "tile_streaming_enabled_setting": bool(getattr(SETTINGS, "ENABLE_TILE_STREAMING", False)),
            "disable_tile_streaming_during_perception_setting": bool(
                getattr(SETTINGS, "DISABLE_TILE_STREAMING_DURING_PERCEPTION", True)
            ),
        }
        with open(os.path.join(self.output_dir, "run_meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        print(f"▶ Running main perception loop ({self.duration_ticks} ticks)…")

        try:
            for tick_i in range(1, self.duration_ticks + 1):
                self._tick()

                # Tile streaming is *optional* and must never crash perception
                if (
                    bool(getattr(SETTINGS, "ENABLE_TILE_STREAMING", False))
                    and not bool(getattr(SETTINGS, "DISABLE_TILE_STREAMING_DURING_PERCEPTION", True))
                ):
                    try:
                        self.tile_streamer.stream_once(ego)
                    except Exception as e:
                        print(f"[TileStreamer] Error during perception: {e}")

                defect = self._detect_defect(ego)
                if defect:
                    kind, loc, rid, s = defect
                    entry = {
                        "event": kind,
                        "x": float(loc.x),
                        "y": float(loc.y),
                        "z": float(loc.z),
                        "road_id": rid,
                        "s": s,
                        "tick": tick_i,
                    }
                    self.results.append(entry)
                    print("⚠ Detected:", entry)

        finally:
            out_json = os.path.join(self.output_dir, "defects.json")
            with open(out_json, "w", encoding="utf-8") as f:
                json.dump(self.results, f, indent=2)
            print(f"🧾 Defect log written → {out_json}")

            self._cleanup()
            print("🎉 Local perception completed.")
