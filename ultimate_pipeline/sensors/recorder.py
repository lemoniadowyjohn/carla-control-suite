#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ultimate_pipeline/sensors/recorder.py  (FIXED + thesis-friendly)

What this fixes vs your current recorder:
✅ Uses Dominik-calibrated sensor rig (via DominikSensorSetup) instead of hardcoded transforms
✅ Optional semantic segmentation cameras aligned to each RGB camera (same extrinsics)
✅ Synchronous capture (deterministic, frame-aligned across sensors)
✅ Writes per-frame metadata (ego pose, weather, sensor poses) to meta.jsonl
✅ LiDAR saving supports fast NPZ (recommended on HPC) or PLY (CARLA default)
✅ Clean shutdown + restores CARLA world settings

Typical usage:

    recorder = SensorRecorder(
        world,
        base_logs_dir=".../logs",
        calib_file=".../calib_data.json",
        lidar_format="npz",   # fast on HPC
        add_segmentation=True,
        fps=20
    )

    sensors = recorder.attach_to_vehicle(ego_vehicle)
    recorder.record(num_frames=2000)   # blocks, ticks the world
    recorder.stop()

If you already tick the world elsewhere, you can use recorder.record_step() per tick.
"""

from __future__ import annotations

import os
import json
import time
import queue
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

import carla
import numpy as np

# Use the FIXED DominikSensorSetup you asked for.
# If this import fails, your environment is not using the fixed version.
try:
    from ultimate_pipeline.sensors.dominik_sensor_setup import DominikSensorSetup
except Exception as e:  # noqa: BLE001
    DominikSensorSetup = None  # type: ignore
    _DOMINIK_SENSOR_SETUP_IMPORT_ERROR = e
else:
    _DOMINIK_SENSOR_SETUP_IMPORT_ERROR = None


def _ensure_dir(p: str) -> str:
    os.makedirs(p, exist_ok=True)
    return p


def _now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _jsonable(x: Any) -> Any:
    """Make objects JSON-serializable (Path, numpy, CARLA objects, etc.)."""
    if x is None or isinstance(x, (str, int, float, bool)):
        return x
    if isinstance(x, Path):
        return str(x)
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, set):
        return sorted([_jsonable(v) for v in x])
    if isinstance(x, (np.integer, np.floating)):
        return float(x)
    if isinstance(x, np.ndarray):
        return x.tolist()
    # CARLA types
    if isinstance(x, carla.Location):
        return {"x": x.x, "y": x.y, "z": x.z}
    if isinstance(x, carla.Rotation):
        return {"roll": x.roll, "pitch": x.pitch, "yaw": x.yaw}
    if isinstance(x, carla.Transform):
        return {"location": _jsonable(x.location), "rotation": _jsonable(x.rotation)}
    # fallback
    return str(x)


@dataclass
class RecorderConfig:
    fps: int = 20
    synchronous: bool = True
    fixed_delta_seconds: Optional[float] = None  # if None -> 1/fps
    sensor_timeout_s: float = 2.0

    # Output formats
    lidar_format: str = "npz"  # "npz" (fast) or "ply"
    image_format: str = "png"  # CARLA save_to_disk uses png for cameras

    # Optional extra sensors
    add_segmentation: bool = False
    seg_converter: str = "cityscapes"  # "raw" or "cityscapes"

    # Calibration / mounting assumptions (must match how you attach sensors elsewhere)
    flip_vehicle_y: bool = True
    opencv_camera_axes: bool = True

    # Storage policy
    write_sensor_transforms: bool = True
    write_world_snapshot: bool = True


class SensorRecorder:
    """
    Attaches Dominik-calibrated RGB cameras + LiDARs and records synchronized data to disk.
    Optionally attaches semantic segmentation cameras at the same extrinsics as RGB cameras.
    """

    def __init__(
        self,
        world: carla.World,
        base_logs_dir: str,
        calib_file: str,
        *,
        run_name: Optional[str] = None,
        config: Optional[RecorderConfig] = None,
        verbose: bool = True,
    ):
        self.world = world
        self.verbose = verbose
        self.cfg = config or RecorderConfig()

        # Determine run directory
        tag = _now_tag()
        run_name = run_name or f"run_{tag}"
        self.run_dir = _ensure_dir(os.path.join(base_logs_dir, run_name))

        # Subfolders
        self.rgb_root = _ensure_dir(os.path.join(self.run_dir, "rgb"))
        self.seg_root = _ensure_dir(os.path.join(self.run_dir, "seg")) if self.cfg.add_segmentation else None
        self.lidar_root = _ensure_dir(os.path.join(self.run_dir, "lidar"))

        self.meta_path = os.path.join(self.run_dir, "meta.jsonl")

        # Calibration-based setup
        if DominikSensorSetup is None:
            raise RuntimeError(
        f"DominikSensorSetup import failed: {_DOMINIK_SENSOR_SETUP_IMPORT_ERROR}. "
        "Fix ultimate_pipeline/sensors/dominik_sensor_setup.py or use a sensor setup that does not require it."
        )
        
        self.sensor_setup = DominikSensorSetup(
            calib_file,
            flip_vehicle_y=self.cfg.flip_vehicle_y,
            opencv_camera_axes=self.cfg.opencv_camera_axes,
            verbose=verbose,
        )

        # Internals
        self._sensors: Dict[str, carla.Actor] = {}
        self._queues: Dict[str, "queue.Queue[Tuple[int, Any]]"] = {}
        self._expected_per_frame: List[str] = []
        self._prev_world_settings: Optional[carla.WorldSettings] = None
        self._frame0_walltime = None

        # Write run info
        self._write_run_info(calib_file)

        if self.verbose:
            print(f"📼 SensorRecorder logging to: {self.run_dir}")
            print(f"   lidar_format={self.cfg.lidar_format}, add_segmentation={self.cfg.add_segmentation}")

    # --------------------------
    # World settings (sync mode)
    # --------------------------

    def _apply_sync_settings(self):
        if not self.cfg.synchronous:
            return

        settings = self.world.get_settings()
        self._prev_world_settings = settings

        new_settings = carla.WorldSettings(
            no_rendering_mode=settings.no_rendering_mode,
            synchronous_mode=True,
            fixed_delta_seconds=self.cfg.fixed_delta_seconds or (1.0 / float(self.cfg.fps)),
            deterministic_ragdolls=getattr(settings, "deterministic_ragdolls", False),
            max_substep_delta_time=getattr(settings, "max_substep_delta_time", 0.0),
            max_substeps=getattr(settings, "max_substeps", 0),
        )
        self.world.apply_settings(new_settings)

        if self.verbose:
            print("🧭 World set to synchronous mode")
            print(f"   fixed_delta_seconds={new_settings.fixed_delta_seconds}")

    def _restore_world_settings(self):
        if self._prev_world_settings is None:
            return
        try:
            self.world.apply_settings(self._prev_world_settings)
            if self.verbose:
                print("↩ Restored previous world settings")
        except Exception:
            pass
        self._prev_world_settings = None

    # --------------------------
    # Attach sensors
    # --------------------------

    def attach_to_vehicle(self, ego_vehicle: carla.Actor) -> Dict[str, carla.Actor]:
        """
        Attaches Dominik calibrated sensors to ego vehicle and starts listeners.
        Returns dict of {sensor_name: actor}.
        """
        self._apply_sync_settings()

        # Attach calibrated RGB cameras + LiDARs (and any additional sensors in calib)
        sensors = self.sensor_setup.setup_all_sensors(self.world, ego_vehicle)

        # Optionally attach semantic segmentation cameras at the same transforms as RGB cameras
        if self.cfg.add_segmentation:
            seg_sensors = self._attach_segmentation_cameras_like_rgb(ego_vehicle)
            sensors.update(seg_sensors)

        self._sensors = sensors

        # Create queues + listeners
        self._queues = {}
        self._expected_per_frame = []

        for name, actor in self._sensors.items():
            if not isinstance(actor, carla.Sensor):
                continue

            q: "queue.Queue[Tuple[int, Any]]" = queue.Queue(maxsize=256)
            self._queues[name] = q
            self._expected_per_frame.append(name)

            actor.listen(self._make_callback(name, q))

        if self.verbose:
            print(f"✅ Recorder attached {len(self._expected_per_frame)} sensor streams")

        # Warm up a few ticks (helps ensure streams are live)
        if self.cfg.synchronous:
            for _ in range(5):
                self.world.tick()

        self._frame0_walltime = time.time()
        return self._sensors

    def _attach_segmentation_cameras_like_rgb(self, ego_vehicle: carla.Actor) -> Dict[str, carla.Actor]:
        """
        Create segmentation cameras mirroring each RGB camera's extrinsics.
        Names become: seg_<camera_name>
        """
        bp_lib = self.world.get_blueprint_library()
        seg_bp = bp_lib.find("sensor.camera.semantic_segmentation")

        seg_sensors: Dict[str, carla.Actor] = {}

        # Build a lookup of camera configs so we can reuse image_size/FOV from calib.
        for cam_name, cam_cfg in self.sensor_setup.cameras.items():
            # Match image size / FOV to RGB
            width, height = int(cam_cfg["image_size"][0]), int(cam_cfg["image_size"][1])

            # The RGB setup sets these on its blueprint; we replicate here.
            seg_bp_local = seg_bp  # blueprint objects are shared; safer to copy via find each time
            seg_bp_local = bp_lib.find("sensor.camera.semantic_segmentation")
            seg_bp_local.set_attribute("image_size_x", str(width))
            seg_bp_local.set_attribute("image_size_y", str(height))

            # Approximate FOV from K_undistortion (same as Dominik setup)
            K = np.asarray(cam_cfg["K_undistortion"], dtype=float)
            fx = float(K[0, 0])
            fov = 2.0 * np.degrees(np.arctan(width / (2.0 * fx)))
            seg_bp_local.set_attribute("fov", str(float(fov)))

            # Use the exact same calibration math as DominikSensorSetup
            tf = self.sensor_setup.get_camera_transform(cam_name)

            seg_name = f"seg_{cam_name}"
            seg_actor = self.world.spawn_actor(seg_bp_local, tf, attach_to=ego_vehicle, attachment_type=carla.AttachmentType.Rigid)
            seg_sensors[seg_name] = seg_actor

            if self.verbose:
                loc = tf.location
                rot = tf.rotation
                print(f"   🟦 {seg_name}: {width}x{height} pos=({loc.x:.2f},{loc.y:.2f},{loc.z:.2f}) "
                      f"rpy=({rot.roll:.1f},{rot.pitch:.1f},{rot.yaw:.1f})")

        return seg_sensors

    def _make_callback(self, sensor_name: str, q: "queue.Queue[Tuple[int, Any]]"):
        def _cb(data):
            try:
                q.put_nowait((data.frame, data))
            except queue.Full:
                # Drop oldest if queue is full
                try:
                    _ = q.get_nowait()
                    q.put_nowait((data.frame, data))
                except Exception:
                    pass
        return _cb

    # --------------------------
    # Recording loop (sync)
    # --------------------------

    def record(self, *, num_frames: int, ego_vehicle: Optional[carla.Actor] = None) -> None:
        """
        Blocking recording loop. Ticks the world and writes one sample per frame.

        :param num_frames: number of frames to record
        :param ego_vehicle: optional; if provided, writes ego transform per frame
        """
        if not self._sensors or not self._queues:
            raise RuntimeError("Call attach_to_vehicle() before record().")

        if self.verbose:
            print(f"⏺ Recording {num_frames} frames...")

        for _ in range(int(num_frames)):
            self.record_step(ego_vehicle=ego_vehicle)

        if self.verbose:
            print("✅ Recording complete")

    def record_step(self, *, ego_vehicle: Optional[carla.Actor] = None) -> int:
        """
        Record exactly one simulation tick (one frame).
        Returns the frame id recorded.
        """
        if self.cfg.synchronous:
            frame = self.world.tick()
        else:
            # Best-effort for async mode (not recommended for synchronized datasets)
            time.sleep(1.0 / float(self.cfg.fps))
            frame = self.world.get_snapshot().frame

        bundle = self._collect_frame(frame, timeout_s=self.cfg.sensor_timeout_s)
        self._write_frame(frame, bundle, ego_vehicle=ego_vehicle)
        return frame

    def _collect_frame(self, frame: int, timeout_s: float) -> Dict[str, Any]:
        """
        Gather one message per sensor for a given frame.
        Returns dict {sensor_name: data} for that frame (may contain missing entries if timeout).
        """
        out: Dict[str, Any] = {}
        deadline = time.time() + float(timeout_s)

        pending = set(self._expected_per_frame)

        # Keep pulling until we have all sensors for this frame or time runs out.
        while pending and time.time() < deadline:
            progressed = False
            for name in list(pending):
                q = self._queues[name]
                try:
                    f, data = q.get_nowait()
                except queue.Empty:
                    continue

                progressed = True
                if f == frame:
                    out[name] = data
                    pending.remove(name)
                else:
                    # Not the frame we need; we ignore it (or you could buffer it).
                    # In synchronous mode, this typically doesn't happen much.
                    pass

            if not progressed:
                time.sleep(0.001)

        if pending and self.verbose:
            print(f"⚠ Frame {frame}: missing sensors: {sorted(pending)}")

        return out

    # --------------------------
    # Writing to disk
    # --------------------------

    def _write_frame(self, frame: int, bundle: Dict[str, Any], *, ego_vehicle: Optional[carla.Actor]):
        # Make per-frame folder optional (flat is faster); we keep flat folders by sensor type.
        # Cameras: use CARLA save_to_disk (fast and correct encoding).
        # LiDAR: optionally NPZ for speed.

        # Save sensor data
        for name, data in bundle.items():
            if name.startswith("seg_"):
                self._save_seg(frame, name, data)
            elif self._is_camera_data(data):
                self._save_rgb(frame, name, data)
            elif self._is_lidar_data(data):
                self._save_lidar(frame, name, data)
            else:
                # unknown sensor; ignore
                pass

        # Save metadata JSONL (one line per frame)
        meta: Dict[str, Any] = {
            "frame": int(frame),
            "walltime_sec": float(time.time() - (self._frame0_walltime or time.time())),
        }

        if self.cfg.write_world_snapshot:
            snap = self.world.get_snapshot()
            meta["timestamp"] = {
                "elapsed_seconds": snap.timestamp.elapsed_seconds,
                "delta_seconds": snap.timestamp.delta_seconds,
                "platform_timestamp": snap.timestamp.platform_timestamp,
                "frame_count": snap.timestamp.frame_count,
            }
            # weather is not in snapshot; ask world
            try:
                w = self.world.get_weather()
                meta["weather"] = {
                    "cloudiness": w.cloudiness,
                    "precipitation": w.precipitation,
                    "precipitation_deposits": w.precipitation_deposits,
                    "wind_intensity": w.wind_intensity,
                    "sun_azimuth_angle": w.sun_azimuth_angle,
                    "sun_altitude_angle": w.sun_altitude_angle,
                    "fog_density": w.fog_density,
                    "fog_distance": w.fog_distance,
                    "wetness": w.wetness,
                }
            except Exception:
                pass

        if ego_vehicle is not None:
            try:
                meta["ego_transform"] = _jsonable(ego_vehicle.get_transform())
                meta["ego_velocity"] = _jsonable(ego_vehicle.get_velocity())
                meta["ego_angular_velocity"] = _jsonable(ego_vehicle.get_angular_velocity())
            except Exception:
                pass

        if self.cfg.write_sensor_transforms:
            tf = {}
            for name, actor in self._sensors.items():
                try:
                    tf[name] = _jsonable(actor.get_transform())
                except Exception:
                    tf[name] = None
            meta["sensor_transforms"] = tf

        with open(self.meta_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(_jsonable(meta)) + "\n")

    def _save_rgb(self, frame: int, name: str, data: carla.Image):
        # Folder per camera name for cleaner datasets
        out_dir = _ensure_dir(os.path.join(self.rgb_root, name))
        out_path = os.path.join(out_dir, f"{frame:08d}.{self.cfg.image_format}")
        try:
            data.save_to_disk(out_path)
        except Exception:
            # Fallback: raw numpy
            arr = np.frombuffer(data.raw_data, dtype=np.uint8).reshape((data.height, data.width, 4))
            np.save(os.path.join(out_dir, f"{frame:08d}.npy"), arr)

    def _save_seg(self, frame: int, name: str, data: carla.Image):
        if self.seg_root is None:
            return
        out_dir = _ensure_dir(os.path.join(self.seg_root, name))
        out_path = os.path.join(out_dir, f"{frame:08d}.{self.cfg.image_format}")
        try:
            if self.cfg.seg_converter == "cityscapes":
                data.convert(carla.ColorConverter.CityScapesPalette)
            data.save_to_disk(out_path)
        except Exception:
            arr = np.frombuffer(data.raw_data, dtype=np.uint8).reshape((data.height, data.width, 4))
            np.save(os.path.join(out_dir, f"{frame:08d}.npy"), arr)

    def _save_lidar(self, frame: int, name: str, data: carla.LidarMeasurement):
        out_dir = _ensure_dir(os.path.join(self.lidar_root, name))

        if self.cfg.lidar_format.lower() == "ply":
            out_path = os.path.join(out_dir, f"{frame:08d}.ply")
            try:
                data.save_to_disk(out_path)
            except Exception:
                # fallback to npz if save_to_disk fails
                pts = self._lidar_to_numpy(data)
                np.savez_compressed(os.path.join(out_dir, f"{frame:08d}.npz"), points=pts)
            return

        # Default: NPZ
        pts = self._lidar_to_numpy(data)
        np.savez_compressed(os.path.join(out_dir, f"{frame:08d}.npz"), points=pts)

    @staticmethod
    def _lidar_to_numpy(meas: carla.LidarMeasurement) -> np.ndarray:
        # CARLA LiDAR point format: x,y,z,intensity float32
        arr = np.frombuffer(meas.raw_data, dtype=np.float32)
        if arr.size % 4 != 0:
            # Unexpected; return best-effort
            return arr
        return arr.reshape((-1, 4))

    @staticmethod
    def _is_camera_data(x: Any) -> bool:
        return isinstance(x, carla.Image)

    @staticmethod
    def _is_lidar_data(x: Any) -> bool:
        return isinstance(x, carla.LidarMeasurement)

    # --------------------------
    # Stop / cleanup
    # --------------------------

    def stop(self):
        """Stop listeners, destroy sensors, restore world settings."""
        for name, actor in list(self._sensors.items()):
            try:
                if isinstance(actor, carla.Sensor):
                    actor.stop()
            except Exception:
                pass

        for name, actor in list(self._sensors.items()):
            try:
                actor.destroy()
            except Exception:
                pass

        self._sensors.clear()
        self._queues.clear()
        self._expected_per_frame.clear()

        self._restore_world_settings()

        if self.verbose:
            print("🧹 Recorder stopped and cleaned up")

    # --------------------------
    # Run info
    # --------------------------

    def _write_run_info(self, calib_file: str):
        info = {
            "schema_version": 1,
            "created_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "calib_file": str(calib_file),
            "recorder_config": _jsonable(self.cfg.__dict__),
            "map_name": None,
        }
        try:
            info["map_name"] = self.world.get_map().name
        except Exception:
            pass
        with open(os.path.join(self.run_dir, "run_info.json"), "w", encoding="utf-8") as f:
            json.dump(_jsonable(info), f, indent=2)