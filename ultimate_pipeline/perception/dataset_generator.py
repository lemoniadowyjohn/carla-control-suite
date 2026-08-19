#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ultimate_pipeline/perception/dataset_generator.py
"""
DatasetGenerator (FIXED + compatible)

Why your current version is problematic
- It hardcodes a generic camera transform (not Dominik-calibrated)
- It assumes async capture but uses world.tick() without synchronous settings
- It relies on cv2 for writing (often missing on HPC nodes)
- It logs to Database unguarded (can crash if DB not configured)
- It doesn’t align with the fixed DominikSensorSetup / calibration semantics

This version
✅ Uses DominikSensorSetup (calib_data.json) correctly
✅ Runs CARLA in synchronous mode (deterministic, aligned frames)
✅ Records ONE chosen calibrated camera (or all cameras) using save_to_disk (no cv2 required)
✅ Supports label_mode=semantic (raw class-id PNG masks) or none (explicit no-op, no fabricated labels)
✅ Augmentation is optional and auto-disables if OpenCV isn’t installed
✅ Database logging is optional and guarded

Typical:
python -m ultimate_pipeline.perception.dataset_generator \
  --map-type auto \
  --frames 2000 \
  --out-root datasets \
  --calib calib_data.json \
  --xodr path/to/map.xodr \
  --camera front_left_camera \
  --fps 20

Label schema (C8 fix — unified with min_train_segmentation / eval_sim_labeled
/ class_weights, via ultimate_pipeline.perception.capture_writer):
- rgb/<camera>/<frame>.png              RGB image
- semseg_raw/<camera>/<frame>.png       label_mode=semantic training label:
                                         single-channel uint8, R channel of
                                         the raw sensor buffer == class id
                                         (NOT CityScapes-palette colorized)
- semseg_viz/<camera>/<frame>.png       optional human-viewable palette copy
                                         (never read by any trainer/eval)
- meta/label_schema.json records label_mode and format
- label_mode="none" (detection): explicit no-op, no fabricated empty
  YOLO .txt labels (no 2D bbox projector exists in this codebase; see C8
  spec boundaries)
"""

from __future__ import annotations

import argparse
import os
import json
import time
from pathlib import Path
from typing import Literal, Optional, Dict, Any, List

import carla
import numpy as np

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.sensors.dominik_sensor_setup import DominikSensorSetup
from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world, load_builtin_world

from ultimate_pipeline.carla_tools.reload_ready_for_sensors import _reload_ready_for_sensors
from ultimate_pipeline.perception.capture_writer import save_capture_frame
# Optional dependencies (don’t crash on HPC)
try:
    import cv2  # type: ignore
    _HAS_CV2 = True
except Exception:
    cv2 = None  # type: ignore
    _HAS_CV2 = False

try:
    from ultimate_pipeline.database.db_manager import Database  # type: ignore
except Exception:
    Database = None  # type: ignore

try:
    from ultimate_pipeline.augmentation.realism_augmentor import RealismAugmentor  # type: ignore
except Exception:
    RealismAugmentor = None  # type: ignore


MapType = Literal["auto", "manual"]


def _ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def _set_sync(world: carla.World, fps: int) -> carla.WorldSettings:
    prev = world.get_settings()
    new = carla.WorldSettings(
        synchronous_mode=True,
        fixed_delta_seconds=1.0 / float(fps),
        no_rendering_mode=prev.no_rendering_mode,
    )
    world.apply_settings(new)
    return prev


def _restore_settings(world: carla.World, prev: carla.WorldSettings) -> None:
    try:
        world.apply_settings(prev)
    except Exception:
        pass


def _load_world_from_xodr(client: carla.Client, xodr_path: str) -> carla.World:
    if getattr(SETTINGS, "CARLA_FORCE_BUILTIN_MAP", False):
        return load_builtin_world(client, getattr(SETTINGS, "CARLA_BUILTIN_MAP", "Town10HD_Opt"))

    with open(xodr_path, "r", encoding="utf-8") as f:
        xodr_data = f.read()
    return load_opendrive_world(
        client,
        xodr_data,
        params=None,
        timeout_s=180.0,
        retries=2,
        do_reload=True,
        fallback_enabled=getattr(SETTINGS, "CARLA_ENABLE_MAP_FALLBACK", False),
        fallback_maps=getattr(SETTINGS, "CARLA_FALLBACK_MAPS", None),
    )


def _spawn_ego(world: carla.World, vehicle_filter: str = "vehicle.audi.a2") -> carla.Actor:
    bp_lib = world.get_blueprint_library()
    ego_bp = bp_lib.filter(vehicle_filter)[0] if "*" in vehicle_filter else bp_lib.find(vehicle_filter)

    spawn_points = world.get_map().get_spawn_points()
    if not spawn_points:
        raise RuntimeError("No spawn points available in current map")

    for sp in spawn_points[:30]:
        ego = world.try_spawn_actor(ego_bp, sp)
        if ego is not None:
            return ego
    raise RuntimeError("Failed to spawn ego vehicle after multiple tries")


def _augment_numpy_rgb(rgb: np.ndarray) -> np.ndarray:
    """
    Very lightweight augmentation (no geometry change).
    Requires no extra deps; saves only if cv2 exists (for jpg/png).
    """
    # brightness jitter
    alpha = np.random.uniform(0.8, 1.2)
    beta = np.random.uniform(-10, 10)
    out = np.clip(rgb.astype(np.float32) * alpha + beta, 0, 255).astype(np.uint8)

    # gaussian noise
    noise = np.random.normal(0, 5.0, size=out.shape).astype(np.float32)
    out = np.clip(out.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    return out


class DatasetGenerator:
    def __init__(
        self,
        *,
        map_type: MapType,
        n_frames: int,
        output_root: str,
        calib_file: str,
        camera_name: Optional[str] = None,
        record_all_cameras: bool = False,
        fps: int = 20,
        apply_augmentation: bool = True,
        label_mode: str = "none",
        vehicle_bp: str = "vehicle.audi.a2",
        xodr_path: Optional[str] = None,
        map_name: Optional[str] = None,
        host: str = None,
        port: int = None,
    ):
        self.map_type = map_type
        self.n_frames = int(n_frames)
        self.output_root = Path(output_root)
        self.calib_file = calib_file
        self.camera_name = camera_name
        self.record_all_cameras = bool(record_all_cameras)
        self.fps = int(fps)
        self.apply_augmentation = bool(apply_augmentation)
        self.label_mode = str(label_mode or "none").strip().lower()
        self.vehicle_bp = vehicle_bp
        self.xodr_path = xodr_path
        self.map_name = map_name

        self.host = host or getattr(SETTINGS, "CARLA_HOST", "127.0.0.1")
        self.port = int(port or getattr(SETTINGS, "CARLA_PORT", 2000))

        self.client = carla.Client(self.host, self.port)
        self.client.set_timeout(60.0)

        # world selection
        if self.xodr_path:
            self.world = _load_world_from_xodr(self.client, self.xodr_path)
        else:
            self.world = self.client.get_world()

        # Output dirs (rgb/ + semseg_raw/ unified layout; created lazily by
        # capture_writer.save_capture_frame per-camera as frames are saved)
        dataset_name = getattr(SETTINGS, "AUTO_DATASET_NAME", "auto_dataset") if map_type == "auto" else getattr(SETTINGS, "MANUAL_DATASET_NAME", "manual_dataset")
        self.dataset_dir = _ensure_dir(self.output_root / dataset_name)
        self.meta_dir = _ensure_dir(self.dataset_dir / "meta")

        # Optional DB / augmentor
        self.db = Database() if Database is not None else None
        self.augmentor = RealismAugmentor() if (RealismAugmentor is not None) else None

        # Actors
        self.ego: Optional[carla.Actor] = None
        self.sensors: Dict[str, carla.Actor] = {}
        self._prev_settings: Optional[carla.WorldSettings] = None

        # Calibrated rig
        self.sensor_setup = DominikSensorSetup(self.calib_file, verbose=True)

    def _choose_camera_names(self) -> List[str]:
        cams = list(self.sensor_setup.cameras.keys())
        if not cams:
            raise RuntimeError("No cameras found in calib_data.json")

        if self.record_all_cameras:
            return cams

        if self.camera_name and self.camera_name in cams:
            return [self.camera_name]

        # sensible default preference
        for pref in ("front_left_camera", "front_right_camera", "left_camera", "right_camera"):
            if pref in cams:
                return [pref]

        return [cams[0]]

    def _setup_world(self):
        # Optionally load by map name (only if you want)
        if self.map_name:
            try:
                _reload_ready_for_sensors(self.client, map_name=self.map_name, tm_port=8000)
                self.world = self.client.get_world()
            except Exception:
                # If loading fails, just keep current world
                pass

        self.world.set_weather(carla.WeatherParameters.ClearNoon)

        # Sync mode for deterministic frame alignment
        self._prev_settings = _set_sync(self.world, self.fps)

        # Make TrafficManager sync too (best effort)
        try:
            tm = self.client.get_trafficmanager()
            tm.set_synchronous_mode(True)
        except Exception:
            pass

    @staticmethod
    def _rgb_key(cam_name: str) -> str:
        return f"rgb_{cam_name}"

    @staticmethod
    def _seg_key(cam_name: str) -> str:
        return f"seg_{cam_name}"

    def _spawn_and_attach(self):
        self.ego = _spawn_ego(self.world, self.vehicle_bp)

        # autopilot is optional
        try:
            self.ego.set_autopilot(True)
        except Exception:
            pass

        cam_names = self._choose_camera_names()

        # Attach all calibrated sensors first (Dominik rig)
        self.sensors = self.sensor_setup.spawn_on_vehicle(
            self.world,
            self.ego,
            include_segmentation=(self.label_mode == "semantic"),
            out_dir=str(self.meta_dir),
            strict=True,
        )

        # Keep only cameras we actually want to record (others can exist but we won’t listen to them)
        self._record_cams = cam_names

        # Sanity
        for cn in self._record_cams:
            rgb_key = self._rgb_key(cn)
            if rgb_key not in self.sensors:
                raise RuntimeError(f"Requested camera '{cn}' not attached. Attached: {list(self.sensors.keys())}")
            if self.label_mode == "semantic":
                seg_key = self._seg_key(cn)
                if seg_key not in self.sensors:
                    raise RuntimeError(f"Requested segmentation camera '{seg_key}' not attached.")

    def generate(self):
        self._setup_world()
        self._spawn_and_attach()

        run_tag = time.strftime("%Y%m%d_%H%M%S")
        run_info = {
            "schema_version": 1,
            "map_type": self.map_type,
            "frames": self.n_frames,
            "fps": self.fps,
            "host": self.host,
            "port": self.port,
            "xodr_path": self.xodr_path,
            "map_name": getattr(self.world.get_map(), "name", None),
            "calib_file": self.calib_file,
            "record_all_cameras": self.record_all_cameras,
            "record_cameras": self._record_cams,
            "augmentation_enabled": self.apply_augmentation,
            "augmentation_backend": ("cv2" if _HAS_CV2 else "disabled_no_cv2"),
            "label_mode": self.label_mode,
        }
        (self.meta_dir / f"run_{run_tag}.json").write_text(json.dumps(run_info, indent=2), encoding="utf-8")

        if self.label_mode == "semantic":
            schema = {
                "schema_version": 2,
                "label_mode": "semantic",
                "format": "png",
                "encoding": "raw_class_id",
                "path_template": "semseg_raw/<camera>/<frame>.png",
                "viz_path_template": "semseg_viz/<camera>/<frame>.png",
                "viz_palette": "carla_cityscapes",
            }
            (self.meta_dir / "label_schema.json").write_text(json.dumps(schema, indent=2), encoding="utf-8")
        else:
            schema = {
                "schema_version": 2,
                "label_mode": "none",
                "detection_status": "explicit_noop",
                "note": (
                    "No 2D bounding-box projector exists in this codebase; "
                    "detection labels are an explicit no-op and no fabricated "
                    "empty label files are written."
                ),
            }
            (self.meta_dir / "label_schema.json").write_text(json.dumps(schema, indent=2), encoding="utf-8")

        # Listener queues per camera
        import queue
        queues: Dict[str, "queue.Queue[carla.Image]"] = {cn: queue.Queue(maxsize=32) for cn in self._record_cams}
        seg_queues: Dict[str, "queue.Queue[carla.Image]"] = {}
        if self.label_mode == "semantic":
            seg_queues = {cn: queue.Queue(maxsize=32) for cn in self._record_cams}

        def _mk_cb_queue(qmap: Dict[str, "queue.Queue[carla.Image]"], key: str):
            def _cb(img: carla.Image):
                try:
                    qmap[key].put_nowait(img)
                except Exception:
                    # drop if full
                    try:
                        _ = qmap[key].get_nowait()
                        qmap[key].put_nowait(img)
                    except Exception:
                        pass
            return _cb

        for cn in self._record_cams:
            cam = self.sensors[self._rgb_key(cn)]
            if not isinstance(cam, carla.Sensor):
                raise RuntimeError(f"Camera actor '{cn}' is not a Sensor")
            cam.listen(_mk_cb_queue(queues, cn))
            if self.label_mode == "semantic":
                seg = self.sensors[self._seg_key(cn)]
                if not isinstance(seg, carla.Sensor):
                    raise RuntimeError(f"Segmentation actor '{cn}' is not a Sensor")
                seg.listen(_mk_cb_queue(seg_queues, cn))

        print(f"🚀 Generating {self.n_frames} frames on map_type='{self.map_type}' cameras={self._record_cams} ...")

        try:
            # Warm-up ticks
            for _ in range(10):
                self.world.tick()

            saved = 0
            while saved < self.n_frames:
                frame = self.world.tick()

                for cn in self._record_cams:
                    # Wait (briefly) for matching frame
                    img: Optional[carla.Image] = None
                    deadline = time.time() + 1.0  # 1 sec timeout per camera
                    while time.time() < deadline:
                        try:
                            cand = queues[cn].get(timeout=0.05)
                        except Exception:
                            continue
                        if cand.frame == frame:
                            img = cand
                            break

                    if img is None:
                        # Missing frame; skip this frame to keep dataset consistent
                        continue

                    seg_img: Optional[carla.Image] = None
                    if self.label_mode == "semantic":
                        deadline = time.time() + 1.0
                        while time.time() < deadline:
                            try:
                                cand = seg_queues[cn].get(timeout=0.05)
                            except Exception:
                                continue
                            if cand.frame == frame:
                                seg_img = cand
                                break
                        if seg_img is None:
                            continue

                    # Save via the shared writer: rgb/<cam>/ + semseg_raw/<cam>/
                    # (raw class ids; palette conversion applied only to the
                    # optional semseg_viz/ artifact, never to the training
                    # label). Detection (label_mode != "semantic") is an
                    # explicit no-op — no fabricated empty YOLO labels.
                    write_result = save_capture_frame(
                        self.dataset_dir,
                        camera=cn,
                        frame=frame,
                        rgb_image=img,
                        seg_image=seg_img if self.label_mode == "semantic" else None,
                        label_mode=self.label_mode,
                        write_viz=(self.label_mode == "semantic"),
                    )
                    img_path = write_result.rgb_path
                    label_path = write_result.semseg_raw_path

                    cam_out_dir = _ensure_dir(self.dataset_dir / "rgb" / cn)

                    # Optional augmentation (only if cv2 exists)
                    if self.apply_augmentation and _HAS_CV2:
                        # decode RGBA -> RGB numpy
                        arr = np.frombuffer(img.raw_data, dtype=np.uint8).reshape((img.height, img.width, 4))[:, :, :3]
                        aug = _augment_numpy_rgb(arr)
                        aug_path = cam_out_dir / f"{frame:08d}_aug.png"
                        # cv2 wants BGR
                        cv2.imwrite(str(aug_path), cv2.cvtColor(aug, cv2.COLOR_RGB2BGR))
                        # Note: augmented copies are RGB-only; no fabricated
                        # detection label is written for them either.

                    # Optional DB logging (guarded)
                    if self.db is not None:
                        try:
                            self.db.log_dataset_entry(
                                timestamp=str(frame),
                                dataset_name=self.dataset_dir.name,
                                image_path=str(img_path) if img_path else "",
                                label_path=str(label_path) if label_path else "",
                                map_type=self.map_type,
                                augmentation=0,
                                metadata_json="{}",
                            )
                        except Exception:
                            pass

                    saved += 1
                    if saved >= self.n_frames:
                        break

            # Stop camera streams
            for cn in self._record_cams:
                try:
                    cam = self.sensors[cn]
                    if isinstance(cam, carla.Sensor):
                        cam.stop()
                except Exception:
                    pass

        finally:
            self._cleanup()
            print(f"✅ Dataset generation finished: {self.dataset_dir}")

    def _cleanup(self):
        # Stop + destroy sensors
        for a in self.sensors.values():
            try:
                if isinstance(a, carla.Sensor):
                    a.stop()
            except Exception:
                pass
        for a in self.sensors.values():
            try:
                a.destroy()
            except Exception:
                pass
        self.sensors.clear()

        # Destroy ego
        if self.ego is not None:
            try:
                self.ego.destroy()
            except Exception:
                pass
            self.ego = None

        # Restore world settings
        if self._prev_settings is not None:
            _restore_settings(self.world, self._prev_settings)
            self._prev_settings = None


def main():
    parser = argparse.ArgumentParser(description="Ultimate Pipeline Dataset Generator (calibrated)")
    parser.add_argument("--map-type", choices=["auto", "manual"], default="auto")
    parser.add_argument("--frames", type=int, default=200)
    parser.add_argument("--out-root", type=str, default=str(getattr(SETTINGS, "DATASET_ROOT", "datasets")))
    parser.add_argument("--calib", type=str, required=True, help="Path to calib_data.json")
    parser.add_argument("--camera", type=str, default=None, help="Record only this camera (e.g., front_left_camera)")
    parser.add_argument("--all-cameras", action="store_true", help="Record all calibrated cameras")
    parser.add_argument("--fps", type=int, default=20)
    parser.add_argument("--label-mode", choices=["none", "semantic"], default="none")

    parser.add_argument("--xodr", type=str, default=None, help="Optional: load world from this OpenDRIVE file")
    parser.add_argument("--map-name", type=str, default=None, help="Optional: client.load_world(map_name)")

    parser.add_argument("--host", type=str, default=getattr(SETTINGS, "CARLA_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(getattr(SETTINGS, "CARLA_PORT", 2000)))

    parser.add_argument("--no-augment", action="store_true", help="Disable augmentation")
    parser.add_argument("--vehicle", type=str, default="vehicle.audi.a2")

    args = parser.parse_args()

    gen = DatasetGenerator(
        map_type=args.map_type,  # type: ignore[arg-type]
        n_frames=args.frames,
        output_root=args.out_root,
        calib_file=args.calib,
        camera_name=args.camera,
        record_all_cameras=args.all_cameras,
        fps=args.fps,
        apply_augmentation=not args.no_augment,
        label_mode=args.label_mode,
        vehicle_bp=args.vehicle,
        xodr_path=args.xodr,
        map_name=args.map_name,
        host=args.host,
        port=args.port,
    )
    gen.generate()


if __name__ == "__main__":
    main()
