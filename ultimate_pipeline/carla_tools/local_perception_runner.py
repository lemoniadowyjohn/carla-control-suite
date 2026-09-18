#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import math
import os
from datetime import datetime
from typing import Any, Dict, Optional, TYPE_CHECKING, Tuple

# Import-safety: this module is imported by main_pipeline even when CARLA isn't available.
try:  # pragma: no cover
    import carla  # type: ignore
    _CARLA_AVAILABLE = True
except Exception:  # pragma: no cover
    carla = None  # type: ignore
    _CARLA_AVAILABLE = False

from ultimate_pipeline.config.settings import SETTINGS

if TYPE_CHECKING:  # pragma: no cover
    from ultimate_pipeline.carla_tools.tile_streamer import TileStreamer
    from ultimate_pipeline.sensors.dominik_sensor_setup import DominikSensorSetup


class LocalPerceptionRunner:
    """
    Laptop-friendly road-defect / local perception inspector.

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
        client: "carla.Client",
        map_name: Optional[str] = None,   # kept for backward compatibility (ignored)
        tiles=None,
        duration_ticks: int = 45,
        warmup_ticks: int = 30,
        npc_cap: int = 20,
        spawn_point_index: int = 0,
        **_ignored_kwargs,                # absorb legacy args safely
    ):
        if not _CARLA_AVAILABLE:
            raise RuntimeError(
                "CARLA PythonAPI not found on PYTHONPATH. "
                "Install/activate CARLA PythonAPI before using LocalPerceptionRunner."
            )

        # Lazy CARLA-dependent imports
        from ultimate_pipeline.carla_tools.spawn_recovery import (
            try_safe_spawn,
            try_safe_spawn_from_transforms,
        )
        from ultimate_pipeline.carla_tools.tile_streamer import TileStreamer
        from ultimate_pipeline.sensors.dominik_sensor_setup import DominikSensorSetup

        self._try_safe_spawn = try_safe_spawn
        self._try_safe_spawn_from_transforms = try_safe_spawn_from_transforms
        self._TileStreamer = TileStreamer
        self._DominikSensorSetup = DominikSensorSetup

        self.client = client
        self.world = client.get_world()
        self.map = self.world.get_map()
        self.blueprints = self.world.get_blueprint_library()

        # NOTE: map_name is intentionally ignored here.
        self._map_name_hint = map_name

        self.tiles = tiles
        self.tile_streamer = TileStreamer(client)

        self.actor_list: list["carla.Actor"] = []
        self.sensor_list: list["carla.Sensor"] = []

        # Use DominikSensorSetup for consistent transform handling with record_route.py
        self.sensor_setup = DominikSensorSetup(
            SETTINGS.SENSOR_CALIB_JSON,
            flip_vehicle_y=bool(getattr(SETTINGS, "SENSOR_FLIP_VEHICLE_Y", True)),
            opencv_camera_axes=bool(getattr(SETTINGS, "SENSOR_OPENCV_CAMERA_AXES", True)),
            lidar_axes_mode=str(getattr(SETTINGS, "SENSOR_LIDAR_AXES_MODE", "auto")),
        )

        self.duration_ticks = int(duration_ticks)
        self.warmup_ticks = int(warmup_ticks)
        self.npc_cap = int(npc_cap)
        self.spawn_point_index = int(spawn_point_index)

        self.results: list[Dict[str, Any]] = []

        # Robust tick handling configuration
        self._tick_timeout_s = float(os.getenv("UP_LOCAL_PERCEPTION_TICK_TIMEOUT_S", "10.0"))
        self._tick_retries = int(os.getenv("UP_LOCAL_PERCEPTION_TICK_RETRIES", "5"))

        world_settings = self.world.get_settings()
        # Store original settings for restore on cleanup
        self._orig_sync_mode = bool(getattr(world_settings, "synchronous_mode", False))
        self._orig_fixed_dt = getattr(world_settings, "fixed_delta_seconds", None)
        self._settings_changed = False

        self._sync = self._orig_sync_mode
        self._tm_port: Optional[int] = None
        tm_seed_raw = os.getenv("UP_TM_SEED", "42").strip()
        try:
            self._tm_seed = int(tm_seed_raw)
        except (TypeError, ValueError):
            self._tm_seed = 42

        # Optional force-sync mode for stability
        force_sync = os.getenv("UP_LOCAL_PERCEPTION_FORCE_SYNC", "0").strip().lower() in (
            "1", "true", "yes", "on",
        )
        if force_sync and not self._sync:
            fixed_dt = float(os.getenv("UP_LOCAL_PERCEPTION_FIXED_DT", "0.05"))
            world_settings.synchronous_mode = True
            world_settings.fixed_delta_seconds = fixed_dt
            self.world.apply_settings(world_settings)
            self._sync = True
            self._settings_changed = True
            print(f"[LocalPerception] Force-sync enabled (fixed_dt={fixed_dt}s)")
            # Best-effort TrafficManager sync
            try:
                tm = self.client.get_trafficmanager()
                tm.set_synchronous_mode(True)
                tm.set_random_device_seed(int(self._tm_seed))
                self._tm_port = int(tm.get_port())
            except Exception:
                pass

        if self._sync:
            try:
                tm = self.client.get_trafficmanager()
                tm.set_synchronous_mode(True)
                tm.set_random_device_seed(int(self._tm_seed))
                self._tm_port = int(tm.get_port())
            except Exception:
                pass

        parent_out = os.getenv("UP_PARENT_OUT_DIR", "").strip()
        base_out = parent_out if parent_out else SETTINGS.output_dir()

        self.output_dir = os.path.join(
            base_out,
            "perception_local_" + datetime.now().strftime("%Y%m%d_%H%M%S"),
        )
        os.makedirs(self.output_dir, exist_ok=True)

        self._saved_images = 0
        self._saved_lidars = 0
        self._save_errors: list[str] = []

        self._failure_reason: Optional[str] = None
        self._warnings: list[str] = []

    def _mark_ego_destroyed(self) -> None:
        if "ego_destroyed" not in self._warnings:
            self._warnings.append("ego_destroyed")

    def _safe_actor_call(self, actor: "carla.Actor", fn_name: str, *args, **kwargs):
        try:
            if hasattr(actor, "is_alive") and not actor.is_alive:
                self._mark_ego_destroyed()
                return None
            fn = getattr(actor, fn_name)
            return fn(*args, **kwargs)
        except RuntimeError as e:
            msg = str(e).lower()
            if "destroyed" in msg:
                self._mark_ego_destroyed()
                return None
            raise
        except Exception:
            self._mark_ego_destroyed()
            return None

    def _safe_ego_transform(self, ego: "carla.Vehicle") -> Optional["carla.Transform"]:
        return self._safe_actor_call(ego, "get_transform")

    def _safe_ego_velocity(self, ego: "carla.Vehicle") -> Optional["carla.Vector3D"]:
        return self._safe_actor_call(ego, "get_velocity")

    def _safe_ego_location(self, ego: "carla.Vehicle") -> Optional["carla.Location"]:
        return self._safe_actor_call(ego, "get_location")

    def _tick(self) -> None:
        """Robust tick with retry logic for timeout recovery."""
        if self._sync:
            # Synchronous mode: use world.tick() with error recovery
            try:
                self.world.tick()
            except RuntimeError as e:
                msg = str(e).lower()
                if "time-out" in msg or "time out" in msg:
                    # Refresh world reference and retry once
                    print("[LocalPerception] Sync tick timeout, refreshing world and retrying...")
                    self.world = self.client.get_world()
                    self.world.tick()
                else:
                    raise
        else:
            # Asynchronous mode: retry loop with configurable timeout
            last_exc: Optional[Exception] = None
            for attempt in range(self._tick_retries):
                try:
                    self.world.wait_for_tick(self._tick_timeout_s)
                    return
                except RuntimeError as e:
                    msg = str(e).lower()
                    if "time-out" in msg or "time out" in msg:
                        last_exc = e
                        if attempt < self._tick_retries - 1:
                            print(
                                f"[LocalPerception] Tick timeout (attempt {attempt + 1}/{self._tick_retries}), "
                                f"refreshing world and retrying..."
                            )
                            self.world = self.client.get_world()
                            continue
                    raise
            if last_exc is not None:
                raise RuntimeError(
                    f"Tick failed after {self._tick_retries} attempts: {last_exc}"
                ) from last_exc

    def _spawn_ego_recovering(self, spawn_points: list["carla.Transform"]) -> "carla.Vehicle":
        bp = self.blueprints.find("vehicle.tesla.model3")
        bp.set_attribute("role_name", "ego")

        if not spawn_points:
            raise RuntimeError("❌ No spawn points available on current map")

        sp_idx = max(0, min(self.spawn_point_index, len(spawn_points) - 1))
        ordered = list(spawn_points[sp_idx:]) + list(spawn_points[:sp_idx])

        shuffle = os.getenv("UP_LOCAL_PERCEPTION_SHUFFLE_SPAWNS", "1").strip().lower() in (
            "1", "true", "yes", "on",
        )

        ego = self._try_safe_spawn_from_transforms(
            self.world,
            bp,
            ordered,
            max_tries_each=2,
            shuffle=shuffle,
        )

        if ego is None:
            try:
                wps = self.map.generate_waypoints(3.0)
                candidates: list["carla.Transform"] = []
                for wp in wps[:200]:
                    try:
                        if hasattr(carla, "LaneType") and getattr(wp, "lane_type", None) is not None:
                            if wp.lane_type != carla.LaneType.Driving:
                                continue
                        candidates.append(wp.transform)
                    except Exception:
                        continue
                ego = self._try_safe_spawn_from_transforms(
                    self.world,
                    bp,
                    candidates,
                    max_tries_each=1,
                    shuffle=True,
                )
            except Exception:
                ego = None

        if ego is None:
            raise RuntimeError("❌ Failed to spawn ego vehicle (all spawn recovery attempts failed)")

        ego_autopilot = bool(getattr(SETTINGS, "EGO_AUTOPILOT", True))
        if ego_autopilot:
            try:
                if self._tm_port is not None:
                    ego.set_autopilot(True, int(self._tm_port))
                else:
                    ego.set_autopilot(True)
            except TypeError:
                ego.set_autopilot(True)
        else:
            ego.set_autopilot(False)
        self.actor_list.append(ego)
        return ego

    def _spawn_visual_markers(self, ego: "carla.Vehicle") -> int:
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

        ego_tf = self._safe_ego_transform(ego)
        if ego_tf is None:
            print("WARNING: ego destroyed while spawning markers; skipping markers.")
            return 0
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

    @staticmethod
    def _parse_res(s: str) -> Optional[Tuple[int, int]]:
        s = (s or "").strip().lower().replace(",", "x")
        if "x" not in s:
            return None
        try:
            w_s, h_s = s.split("x", 1)
            w, h = int(w_s.strip()), int(h_s.strip())
            if w > 0 and h > 0:
                return (w, h)
        except Exception:
            return None
        return None

    def _attach_sensors(self, ego: "carla.Vehicle") -> Dict[str, "carla.Actor"]:
        print("📷 Attaching calibrated sensors.")

        allow_degraded = bool(getattr(SETTINGS, "LOCAL_PERCEPTION_ALLOW_DEGRADED", True))
        if bool(getattr(SETTINGS, "THESIS_STRICT", False)):
            allow_degraded = False
        min_sensors = int(getattr(SETTINGS, "LOCAL_PERCEPTION_MIN_SENSORS", 1))
        fallback_res = str(getattr(SETTINGS, "LOCAL_PERCEPTION_FALLBACK_RES", "640x360"))
        fallback_res_tuple = self._parse_res(fallback_res)

        sensors: Dict[str, carla.Actor] = {}
        try:
            try:
                sensors = self.sensor_setup.spawn_on_vehicle(
                    self.world,
                    ego,
                    include_segmentation=False,
                    out_dir=self.output_dir,
                    low_mem=False,
                    strict=True,
                    min_sensors=min_sensors,
                )
            except TypeError:
                sensors = self.sensor_setup.spawn_on_vehicle(
                    self.world,
                    ego,
                    include_segmentation=False,
                    out_dir=self.output_dir,
                    low_mem=False,
                )
        except Exception as exc:
            if not allow_degraded:
                raise
            print(f"⚠️  Sensor spawn failed (full mode): {exc}")
            print("   → Retrying sensor spawn in degraded mode (lower res, non-strict).")

            try:
                self.sensor_setup = self._DominikSensorSetup(
                    SETTINGS.SENSOR_CALIB_JSON,
                    flip_vehicle_y=bool(getattr(SETTINGS, "SENSOR_FLIP_VEHICLE_Y", True)),
                    opencv_camera_axes=bool(getattr(SETTINGS, "SENSOR_OPENCV_CAMERA_AXES", True)),
                    lidar_axes_mode=str(getattr(SETTINGS, "SENSOR_LIDAR_AXES_MODE", "auto")),
                    resolution_override=fallback_res_tuple,
                )
            except Exception:
                pass

            try:
                sensors = self.sensor_setup.spawn_on_vehicle(
                    self.world,
                    ego,
                    include_segmentation=False,
                    out_dir=self.output_dir,
                    low_mem=True,
                    strict=False,
                    min_sensors=min_sensors,
                )
            except TypeError:
                sensors = self.sensor_setup.spawn_on_vehicle(
                    self.world,
                    ego,
                    include_segmentation=False,
                    out_dir=self.output_dir,
                    low_mem=True,
                )

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

    def _save_image(self, image: "carla.Image", sensor_name: str) -> None:
        fp = os.path.join(self.output_dir, f"{sensor_name}_{image.frame}.png")
        try:
            image.save_to_disk(fp)
            self._saved_images += 1
        except Exception as e:
            self._save_errors.append(f"image_save_failed:{sensor_name}:{getattr(image,'frame',None)}:{e}")

    def _save_lidar(self, pc: "carla.LidarMeasurement", sensor_name: str) -> None:
        fp = os.path.join(self.output_dir, f"{sensor_name}_{pc.frame}.ply")
        try:
            pc.save_to_disk(fp)
            self._saved_lidars += 1
        except Exception as e:
            self._save_errors.append(f"lidar_save_failed:{sensor_name}:{getattr(pc,'frame',None)}:{e}")

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
                from ultimate_pipeline.carla_tools.spawn_recovery import try_safe_spawn
                v = try_safe_spawn(self.world, bp, spawn_points[i])
                if v:
                    try:
                        if self._tm_port is not None:
                            v.set_autopilot(True, int(self._tm_port))
                        else:
                            v.set_autopilot(True)
                    except TypeError:
                        v.set_autopilot(True)
                    self.actor_list.append(v)
                    spawned += 1
            except Exception:
                continue

        print(f"🚗 Spawned {spawned} NPCs")
        return spawned

    def _detect_defect(self, ego: "carla.Vehicle"):
        vel = self._safe_ego_velocity(ego)
        if vel is None:
            return None
        speed_kmh = 3.6 * math.sqrt(vel.x**2 + vel.y**2 + vel.z**2)

        tr = self._safe_ego_transform(ego)
        if tr is None:
            return None
        pitch = abs(tr.rotation.pitch)
        roll = abs(tr.rotation.roll)

        loc = self._safe_ego_location(ego)
        if loc is None:
            return None

        try:
            wp = self.map.get_waypoint(loc, project_to_road=True)
        except RuntimeError:
            return "off_road", loc, None, None

        if speed_kmh < 0.1:
            return "stuck", loc, getattr(wp, "road_id", None), getattr(wp, "s", None)

        if pitch > 15 or roll > 15:
            return "unstable_orientation", loc, getattr(wp, "road_id", None), getattr(wp, "s", None)

        return None

    def _cleanup(self) -> None:
        print("🧹 Cleaning up perception actors…")

        for s in self.sensor_list:
            try:
                s.stop()
            except Exception:
                pass
            try:
                if hasattr(s, "is_alive") and not s.is_alive:
                    continue
                s.destroy()
            except Exception:
                pass

        for a in self.actor_list:
            try:
                if hasattr(a, "is_alive") and not a.is_alive:
                    continue
                a.destroy()
            except Exception:
                pass

        self.sensor_list.clear()
        self.actor_list.clear()

        # Restore original world settings if we changed them
        if self._settings_changed:
            try:
                world_settings = self.world.get_settings()
                world_settings.synchronous_mode = self._orig_sync_mode
                if self._orig_fixed_dt is not None:
                    world_settings.fixed_delta_seconds = self._orig_fixed_dt
                self.world.apply_settings(world_settings)
                print("[LocalPerception] Restored original world settings")
            except Exception as e:
                print(f"[LocalPerception] Failed to restore world settings: {e}")

    def run(self) -> None:
        print("🚀 Starting Local Perception QA…")
        try:
            print(f"⏳ Warming up CARLA world ({self.warmup_ticks} ticks)…")
            for _ in range(self.warmup_ticks):
                self._tick()

            spawn_points = self.map.get_spawn_points()
            ego = self._spawn_ego_recovering(spawn_points)

            self._spawn_visual_markers(ego)
            self._attach_sensors(ego)

            npc_count = int(min(getattr(SETTINGS, "MAX_NPCS_LOCAL", 10), self.npc_cap))
            self._spawn_npcs(npc_count)

            meta = {
                "carla_map_name": getattr(self.map, "name", None),
                "map_name_hint": self._map_name_hint,
                "duration_ticks": self.duration_ticks,
                "warmup_ticks": self.warmup_ticks,
                "spawn_point_index": int(self.spawn_point_index),
            }
            with open(os.path.join(self.output_dir, "run_meta.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)

            print(f"▶ Running main perception loop ({self.duration_ticks} ticks)…")
            for tick_i in range(1, self.duration_ticks + 1):
                self._tick()

                defect = self._detect_defect(ego)
                if defect:
                    kind, loc, rid, s_val = defect
                    entry = {
                        "event": kind,
                        "x": float(loc.x),
                        "y": float(loc.y),
                        "z": float(loc.z),
                        "road_id": rid,
                        "s": s_val,
                        "tick": tick_i,
                    }
                    self.results.append(entry)
                    print("⚠ Detected:", entry)

        except Exception as e:
            self._failure_reason = f"{type(e).__name__}: {e}"
            if "destroyed" in str(e).lower():
                self._mark_ego_destroyed()
            try:
                err_path = os.path.join(self.output_dir, "stderr.log")
                with open(err_path, "w", encoding="utf-8") as f:
                    f.write(self._failure_reason)
                    f.write("\n")
            except Exception:
                pass
            raise

        finally:
            try:
                with open(os.path.join(self.output_dir, "defects.json"), "w", encoding="utf-8") as f:
                    json.dump(self.results, f, indent=2)
            except Exception:
                pass

            try:
                pngs, plys = [], []
                for root, _dirs, files in os.walk(self.output_dir):
                    for fn in files:
                        fl = fn.lower()
                        if fl.endswith(".png"):
                            pngs.append(os.path.join(root, fn))
                        elif fl.endswith(".ply"):
                            plys.append(os.path.join(root, fn))
            except Exception:
                pngs, plys = [], []

            outputs_present = bool(pngs or plys or self._saved_images > 0 or self._saved_lidars > 0)
            status = {
                "ok": bool(outputs_present),
                "failure_reason": self._failure_reason,
                "warnings": self._warnings,
                "output_dir": self.output_dir,
                "saved_images": int(self._saved_images),
                "saved_lidars": int(self._saved_lidars),
                "png_files": int(len(pngs)),
                "ply_files": int(len(plys)),
                "num_defects": int(len(self.results)),
                "save_errors_tail": self._save_errors[-10:],
            }
            try:
                with open(os.path.join(self.output_dir, "perception_status.json"), "w", encoding="utf-8") as f:
                    json.dump(status, f, indent=2, ensure_ascii=True, default=str)
            except Exception:
                pass

            try:
                self._cleanup()
            except Exception:
                pass

            if self._failure_reason:
                print(f"❌ Local perception failed: {self._failure_reason}")
            else:
                print("🎉 Local perception completed.")
