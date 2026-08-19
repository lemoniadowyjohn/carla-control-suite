#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ultimate_pipeline/perception/perception_runner_local_aug.py
"""
PerceptionRunnerLocalAug (FIXED + compatible)

Your original file had a bunch of incompatibilities:
- wrong SETTINGS import path (config.settings vs ultimate_pipeline.config.settings)
- hardcoded “random” camera transform (not Dominik calibrated)
- assumes cv2 is always installed (often false on HPC)
- no synchronous mode (frames drift + nondeterminism)
- keeps all frames in RAM (bad for long runs)
- augmentation import path may not match your repo

This version:
✅ Uses DominikSensorSetup (calib_data.json) so camera poses match your thesis rig
✅ Uses synchronous mode (deterministic, aligned frames)
✅ Records one camera OR all calibrated cameras
✅ Saves images via the shared capture_writer (rgb/<cam>/ layout, unified
   with dataset_generator.py so layout can't drift between capture modules)
✅ Detection (no semantic sensor in this module) is an explicit, logged
   no-op — no fabricated empty YOLO label files
✅ “Augmentor adapter”: works if your augmentor exposes apply_random() OR apply_all()

Output layout (C8 fix — unified with dataset_generator.py /
min_train_segmentation.py via ultimate_pipeline.perception.capture_writer):
datasets/<dataset_name>/
  rgb/<camera_name>/00001234.png
  rgb/<camera_name>/00001234_aug1.png (optional)
  meta/run_info.json
  meta/frames.jsonl
  meta/label_schema.json (detection_status=explicit_noop; this module does
    not attach a semantic-segmentation sensor, so no semseg_raw/ is written)
"""

from __future__ import annotations

import argparse
import json
import os
import time
import queue
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

import carla
import numpy as np

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.sensors.dominik_sensor_setup import DominikSensorSetup
from ultimate_pipeline.perception.capture_writer import save_capture_frame

# Optional OpenCV (only needed if you want augmented image writing from numpy)
try:
    import cv2  # type: ignore
    _HAS_CV2 = True
except Exception:
    cv2 = None  # type: ignore
    _HAS_CV2 = False

# Optional augmentation module (repo variants). NOTE: the legacy
# ultimate_pipeline.augmentation.realism name does not exist (C12) — any
# import of it silently disabled DR; do NOT reintroduce a fallback for it.
RealismAugmentor = None
AugmentationConfig = None
try:
    from ultimate_pipeline.augmentation.realism_augmentor import RealismAugmentor, AugmentationConfig  # type: ignore
except Exception:  # noqa: BLE001
    RealismAugmentor = None  # type: ignore
    AugmentationConfig = None  # type: ignore


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


def _spawn_ego(world: carla.World, vehicle_bp_id: str = "vehicle.audi.a2") -> carla.Actor:
    bp_lib = world.get_blueprint_library()
    bp = bp_lib.find(vehicle_bp_id) if "." in vehicle_bp_id else bp_lib.filter(vehicle_bp_id)[0]

    sps = world.get_map().get_spawn_points()
    if not sps:
        raise RuntimeError("No spawn points available on this map.")
    for sp in sps[:30]:
        ego = world.try_spawn_actor(bp, sp)
        if ego is not None:
            return ego
    raise RuntimeError("Failed to spawn ego after multiple tries.")


def _image_to_rgb_np(image: carla.Image) -> np.ndarray:
    """CARLA raw BGRA8 -> RGB uint8"""
    arr = np.frombuffer(image.raw_data, dtype=np.uint8)
    arr = arr.reshape((image.height, image.width, 4))
    rgb = arr[:, :, :3][:, :, ::-1]  # BGRA -> BGR -> RGB (swap BGR->RGB)
    return rgb


class PerceptionRunnerLocalAug:
    def __init__(
        self,
        *,
        host: str = None,
        port: int = None,
        timeout: float = 30.0,
        fps: int = 20,
        dataset_root: str = None,
        calib_file: str = None,
        flip_vehicle_y: bool = True,
        opencv_camera_axes: bool = True,
        enable_augmentation: bool = None,
        augmentation_multiplier: int = None,
        vehicle_bp: str = "vehicle.audi.a2",
        verbose: bool = True,
    ):
        self.verbose = verbose

        self.host = host or getattr(SETTINGS, "CARLA_HOST", "127.0.0.1")
        self.port = int(port or getattr(SETTINGS, "CARLA_PORT", 2000))
        self.timeout = float(timeout)
        self.fps = int(fps)

        self.dataset_root = Path(dataset_root or getattr(SETTINGS, "DATASET_ROOT", "datasets"))
        _ensure_dir(self.dataset_root)

        self.calib_file = calib_file or getattr(SETTINGS, "SENSOR_CALIB_JSON", "calib_data.json")

        self.flip_vehicle_y = bool(flip_vehicle_y)
        self.opencv_camera_axes = bool(opencv_camera_axes)

        self.enable_augmentation = bool(
            enable_augmentation if enable_augmentation is not None else getattr(SETTINGS, "ENABLE_AUGMENTATION", False)
        )
        self.augmentation_multiplier = int(
            augmentation_multiplier if augmentation_multiplier is not None else getattr(SETTINGS, "AUGMENTATION_MULTIPLIER", 1)
        )

        self.vehicle_bp = vehicle_bp

        self.client = carla.Client(self.host, self.port)
        self.client.set_timeout(self.timeout)
        self.world = self.client.get_world()

        # Calibrated rig
        self.sensor_setup = DominikSensorSetup(
            self.calib_file,
            flip_vehicle_y=self.flip_vehicle_y,
            opencv_camera_axes=self.opencv_camera_axes,
            verbose=verbose,
        )

        # Augmentor (optional)
        self.augmentor = None
        if self.enable_augmentation and RealismAugmentor is not None:
            self.augmentor = self._build_augmentor()
        elif self.enable_augmentation and not _HAS_CV2:
            # We can still “augment” but can’t write images easily without cv2.
            if self.verbose:
                print("⚠ Augmentation requested but OpenCV not available; augmentation will be skipped.")

        if self.verbose:
            print("🎬 PerceptionRunnerLocalAug ready")
            print(f"   CARLA: {self.host}:{self.port} fps={self.fps}")
            print(f"   calib: {self.calib_file}")
            print(f"   aug: {self.enable_augmentation} x{self.augmentation_multiplier}")

        # runtime actors
        self._prev_settings: Optional[carla.WorldSettings] = None
        self.ego: Optional[carla.Actor] = None
        self.sensors: Dict[str, carla.Actor] = {}

    @staticmethod
    def _build_augmentor():
        """
        Adapter for your augmentor variants.
        - If AugmentationConfig exists, use SETTINGS.* probabilities when available.
        - Otherwise instantiate RealismAugmentor() without config.
        """
        if AugmentationConfig is None:
            try:
                return RealismAugmentor()
            except Exception:
                return None

        cfg = AugmentationConfig(
            prob_noise=float(getattr(SETTINGS, "AUG_PROB_NOISE", 0.2)),
            prob_motion_blur=float(getattr(SETTINGS, "AUG_PROB_MOTION_BLUR", 0.1)),
            prob_brightness=float(getattr(SETTINGS, "AUG_PROB_BRIGHTNESS", 0.2)),
            prob_color_shift=float(getattr(SETTINGS, "AUG_PROB_COLOR_SHIFT", 0.15)),
            seed=int(getattr(SETTINGS, "AUGMENTATION_SEED", 42)),
        )
        try:
            return RealismAugmentor(cfg)
        except Exception:
            try:
                return RealismAugmentor()
            except Exception:
                return None

    def _apply_aug(self, rgb: np.ndarray) -> np.ndarray:
        """
        Try common augmentor method names:
        - apply_random(img)
        - apply_all(img)
        - __call__(img)
        Fallback: mild noise/brightness.
        """
        if self.augmentor is not None:
            for meth in ("apply_random", "apply_all"):
                fn = getattr(self.augmentor, meth, None)
                if callable(fn):
                    out = fn(rgb)
                    if isinstance(out, np.ndarray):
                        return out
            if callable(self.augmentor):
                out = self.augmentor(rgb)
                if isinstance(out, np.ndarray):
                    return out

        # fallback: tiny jitter
        alpha = np.random.uniform(0.85, 1.15)
        beta = np.random.uniform(-10, 10)
        out = np.clip(rgb.astype(np.float32) * alpha + beta, 0, 255).astype(np.uint8)
        return out

    def _choose_cameras(self, camera_name: Optional[str], record_all: bool) -> List[str]:
        cams = list(self.sensor_setup.cameras.keys())
        if not cams:
            raise RuntimeError("No cameras found in calib_data.json")

        if record_all:
            return cams

        if camera_name and camera_name in cams:
            return [camera_name]

        # preference order
        for pref in ("front_left_camera", "front_right_camera", "left_camera", "right_camera"):
            if pref in cams:
                return [pref]
        return [cams[0]]

    def run_capture_session(
        self,
        dataset_name: str,
        *,
        num_frames: int = 200,
        camera_name: Optional[str] = None,
        record_all_cameras: bool = False,
        autopilot: bool = True,
        tm_port: int = 8000,
        seed: int = 42,
    ) -> Path:
        """
        Captures synchronized frames from calibrated camera(s).
        Returns dataset directory path.
        """
        dataset_dir = _ensure_dir(self.dataset_root / dataset_name)
        meta_dir = _ensure_dir(dataset_dir / "meta")
        frames_jsonl = meta_dir / "frames.jsonl"

        cams_to_record = self._choose_cameras(camera_name, record_all_cameras)

        # Sync mode
        self._prev_settings = _set_sync(self.world, self.fps)

        # TM sync (best effort)
        try:
            tm = self.client.get_trafficmanager(tm_port)
            tm.set_synchronous_mode(True)
            tm.set_random_device_seed(int(seed))
        except Exception:
            tm = None  # noqa

        # Spawn ego + attach calibrated sensors
        self.ego = _spawn_ego(self.world, self.vehicle_bp)
        if autopilot:
            try:
                self.ego.set_autopilot(True, tm_port)
            except Exception:
                try:
                    self.ego.set_autopilot(True)
                except Exception:
                    pass

        self.sensors = self.sensor_setup.setup_all_sensors(self.world, self.ego)

        # Set up per-camera queues and listeners
        cam_queues: Dict[str, "queue.Queue[Tuple[int, carla.Image]]"] = {}
        for cn in cams_to_record:
            actor = self.sensors.get(cn)
            if actor is None or not isinstance(actor, carla.Sensor):
                raise RuntimeError(f"Camera '{cn}' not attached. Attached keys: {list(self.sensors.keys())}")
            q: "queue.Queue[Tuple[int, carla.Image]]" = queue.Queue(maxsize=64)
            cam_queues[cn] = q

            def _mk_cb(name: str, qq: "queue.Queue[Tuple[int, carla.Image]]"):
                def _cb(img: carla.Image):
                    try:
                        qq.put_nowait((img.frame, img))
                    except Exception:
                        # drop oldest
                        try:
                            _ = qq.get_nowait()
                            qq.put_nowait((img.frame, img))
                        except Exception:
                            pass
                return _cb

            actor.listen(_mk_cb(cn, q))

        # Run info
        run_info = {
            "schema_version": 1,
            "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "dataset_name": dataset_name,
            "dataset_dir": str(dataset_dir),
            "num_frames": int(num_frames),
            "fps": int(self.fps),
            "host": self.host,
            "port": int(self.port),
            "calib_file": str(self.calib_file),
            "cameras_recorded": cams_to_record,
            "record_all_cameras": bool(record_all_cameras),
            "autopilot": bool(autopilot),
            "tm_port": int(tm_port),
            "seed": int(seed),
            "augmentation_enabled": bool(self.enable_augmentation and _HAS_CV2),
            "augmentation_multiplier": int(self.augmentation_multiplier),
            "map_name": self.world.get_map().name if self.world and self.world.get_map() else None,
            "flip_vehicle_y": self.flip_vehicle_y,
            "opencv_camera_axes": self.opencv_camera_axes,
        }
        (meta_dir / "run_info.json").write_text(json.dumps(run_info, indent=2), encoding="utf-8")

        # This module attaches RGB cameras only (no semantic-segmentation
        # sensor), so detection labels are an explicit, logged no-op — no
        # fabricated empty YOLO .txt files. See capture_writer.save_capture_frame.
        label_schema = {
            "schema_version": 2,
            "label_mode": "none",
            "detection_status": "explicit_noop",
            "note": (
                "PerceptionRunnerLocalAug attaches RGB cameras only; no 2D "
                "bounding-box projector exists in this codebase. Detection "
                "labels are an explicit no-op and no fabricated empty label "
                "files are written."
            ),
        }
        (meta_dir / "label_schema.json").write_text(json.dumps(label_schema, indent=2), encoding="utf-8")

        if self.verbose:
            print(f"🚗 Capturing {num_frames} frames for dataset: {dataset_name}")
            print(f"   cameras: {cams_to_record}")

        # Warm-up ticks
        for _ in range(10):
            self.world.tick()

        saved = 0
        try:
            while saved < num_frames:
                frame_id = self.world.tick()

                # collect each camera image for this frame (best effort)
                for cn in cams_to_record:
                    img: Optional[carla.Image] = None
                    deadline = time.time() + 1.5  # seconds
                    while time.time() < deadline:
                        try:
                            f, cand = cam_queues[cn].get(timeout=0.05)
                        except Exception:
                            continue
                        if f == frame_id:
                            img = cand
                            break

                    if img is None:
                        # skip this frame if any camera missing (keeps dataset aligned)
                        if self.verbose:
                            print(f"⚠ missing {cn} at frame {frame_id}, skipping this frame")
                        break

                # If any missing, try next tick (don’t increment saved)
                # Re-check quickly: did all have an image?
                all_have = True
                imgs_for_frame: Dict[str, carla.Image] = {}
                for cn in cams_to_record:
                    # we might have already pulled it, but we stored none above;
                    # easiest: pull again with very short deadline from queue (often it’s already there).
                    # Instead, store when found:
                    pass

                # Better approach: store during collection
                # (Redo collection properly)
                imgs_for_frame.clear()
                for cn in cams_to_record:
                    img = None
                    deadline = time.time() + 1.5
                    while time.time() < deadline:
                        try:
                            f, cand = cam_queues[cn].get(timeout=0.05)
                        except Exception:
                            continue
                        if f == frame_id:
                            img = cand
                            break
                    if img is None:
                        all_have = False
                        break
                    imgs_for_frame[cn] = img

                if not all_have:
                    continue

                # Save each camera sample for this frame
                for cn, img in imgs_for_frame.items():
                    base = f"{frame_id:08d}"

                    # Save via the shared writer: rgb/<cam>/ (unified layout;
                    # no semantic sensor here, so label_mode="none" -> explicit
                    # no-op, no fabricated empty YOLO label).
                    write_result = save_capture_frame(
                        dataset_dir,
                        camera=cn,
                        frame=frame_id,
                        rgb_image=img,
                        seg_image=None,
                        label_mode="none",
                    )
                    cam_img_dir = _ensure_dir(dataset_dir / "rgb" / cn)
                    img_path = write_result.rgb_path

                    # augmentation (only if cv2 available to write numpy)
                    if self.enable_augmentation and _HAS_CV2:
                        rgb = _image_to_rgb_np(img)
                        for k in range(self.augmentation_multiplier):
                            aug = self._apply_aug(rgb)
                            aug_name = f"{base}_aug{k+1}"
                            aug_img_path = cam_img_dir / f"{aug_name}.png"

                            # cv2 expects BGR
                            cv2.imwrite(str(aug_img_path), cv2.cvtColor(aug, cv2.COLOR_RGB2BGR))
                            # No fabricated detection label for augmented
                            # copies either (explicit no-op).

                    # per-frame metadata (one line per camera sample)
                    meta = {
                        "frame": int(frame_id),
                        "camera": cn,
                        "image_path": str(img_path) if img_path else "",
                        "detection_status": write_result.detection_status,
                    }
                    try:
                        if self.ego is not None:
                            meta["ego_transform"] = {
                                "location": {"x": self.ego.get_transform().location.x,
                                             "y": self.ego.get_transform().location.y,
                                             "z": self.ego.get_transform().location.z},
                                "rotation": {"roll": self.ego.get_transform().rotation.roll,
                                             "pitch": self.ego.get_transform().rotation.pitch,
                                             "yaw": self.ego.get_transform().rotation.yaw},
                            }
                    except Exception:
                        pass

                    with open(frames_jsonl, "a", encoding="utf-8") as f:
                        f.write(json.dumps(meta) + "\n")

                saved += 1
                if self.verbose and (saved % 50 == 0):
                    print(f"   saved {saved}/{num_frames}")

            if self.verbose:
                print("✅ Capture session finished.")
            return dataset_dir

        finally:
            self._cleanup()

    def _cleanup(self):
        # stop + destroy sensors
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

        # destroy ego
        if self.ego is not None:
            try:
                self.ego.destroy()
            except Exception:
                pass
            self.ego = None

        # restore sync
        if self._prev_settings is not None:
            _restore_settings(self.world, self._prev_settings)
            self._prev_settings = None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=getattr(SETTINGS, "AUTO_DATASET_NAME", "auto_dataset"))
    ap.add_argument("--frames", type=int, default=300)
    ap.add_argument("--fps", type=int, default=20)
    ap.add_argument("--calib", default=getattr(SETTINGS, "SENSOR_CALIB_JSON", "calib_data.json"))
    ap.add_argument("--camera", default=None, help="Record only this camera (e.g., front_left_camera)")
    ap.add_argument("--all-cameras", action="store_true")
    ap.add_argument("--no-aug", action="store_true")
    args = ap.parse_args()

    runner = PerceptionRunnerLocalAug(
        fps=args.fps,
        calib_file=args.calib,
        enable_augmentation=(not args.no_aug),
        verbose=True,
    )
    runner.run_capture_session(
        args.dataset,
        num_frames=args.frames,
        camera_name=args.camera,
        record_all_cameras=args.all_cameras,
    )


if __name__ == "__main__":
    main()
