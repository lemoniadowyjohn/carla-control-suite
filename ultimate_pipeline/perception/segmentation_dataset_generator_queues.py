#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WORKING Semantic Segmentation Dataset Generator (queue-based, synchronous)

This is a minimal *supervised* perception dataset pipeline for CARLA:
- Attach RGB + semantic segmentation sensors at the SAME calibrated camera pose.
- Use synchronous mode + per-sensor queues to collect images per tick.
- Write:
  - rgb/<camera>/XXXXXXXX.png
  - semseg/<camera>/XXXXXXXX.png        (CityScapesPalette colorized)
  - semseg_raw/<camera>/XXXXXXXX.png    (single-channel class ids, uint8)

Why this exists:
Your current dataset generators write YOLO label placeholders (empty). That blocks supervised training.
Semantic segmentation labels in CARLA are free, so this is the fastest path to an end-to-end thesis experiment.

Usage:
python -m ultimate_pipeline.perception.segmentation_dataset_generator_queues \
  --frames 2000 --out-root datasets --dataset-name ing_auto_01 \
  --calib calib_data.json --camera all
"""

from __future__ import annotations

import argparse
import json
import queue
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, List

import carla
import numpy as np

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.sensors.dominik_sensor_setup import DominikSensorSetup


def _ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def _write_png_raw_ids(img: carla.Image, out_path: Path) -> None:
    arr = np.frombuffer(img.raw_data, dtype=np.uint8).reshape((img.height, img.width, 4))
    class_id = arr[:, :, 2]  # R channel in BGRA
    try:
        import imageio.v2 as imageio
        imageio.imwrite(out_path.as_posix(), class_id.astype(np.uint8))
    except Exception:
        from PIL import Image
        Image.fromarray(class_id.astype(np.uint8), mode="L").save(out_path.as_posix())


@dataclass
class SensorPair:
    rgb: carla.Sensor
    seg: carla.Sensor
    q_rgb: "queue.Queue[carla.Image]"
    q_seg: "queue.Queue[carla.Image]"


class SegmentationDatasetGenerator:
    def __init__(
        self,
        client: carla.Client,
        out_root: Path,
        dataset_name: str,
        calib_path: Path,
        camera: str = "front",
        seed: int = 42,
        fps: int = 10,
    ):
        self.client = client
        self.dataset_dir = _ensure_dir(out_root / dataset_name)
        self.calib_path = calib_path
        self.camera = camera
        self.seed = seed
        self.fps = fps

        self.rgb_dir = _ensure_dir(self.dataset_dir / "rgb")
        self.semseg_dir = _ensure_dir(self.dataset_dir / "semseg")
        self.semseg_raw_dir = _ensure_dir(self.dataset_dir / "semseg_raw")
        self.meta_dir = _ensure_dir(self.dataset_dir / "meta")

        self._world: Optional[carla.World] = None
        self._ego: Optional[carla.Actor] = None
        self._pairs: Dict[str, SensorPair] = {}
        self._actors: List[carla.Actor] = []
        self._tick_delta = 1.0 / float(fps)

    def _set_sync(self, world: carla.World) -> None:
        settings = world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = self._tick_delta
        world.apply_settings(settings)

    def _spawn_ego(self, world: carla.World) -> carla.Actor:
        bp = world.get_blueprint_library().find("vehicle.tesla.model3")
        spawn_points = world.get_map().get_spawn_points()
        if not spawn_points:
            raise RuntimeError("No spawn points available in map.")
        ego = world.try_spawn_actor(bp, spawn_points[0]) or world.spawn_actor(bp, spawn_points[0])
        self._ego = ego
        self._actors.append(ego)
        return ego

    def _attach_pair(self, world: carla.World, ego: carla.Actor, tf: carla.Transform, w: int, h: int, fov: float) -> SensorPair:
        lib = world.get_blueprint_library()

        rgb_bp = lib.find("sensor.camera.rgb")
        rgb_bp.set_attribute("image_size_x", str(w))
        rgb_bp.set_attribute("image_size_y", str(h))
        rgb_bp.set_attribute("fov", str(fov))

        seg_bp = lib.find("sensor.camera.semantic_segmentation")
        seg_bp.set_attribute("image_size_x", str(w))
        seg_bp.set_attribute("image_size_y", str(h))
        seg_bp.set_attribute("fov", str(fov))

        rgb = world.spawn_actor(rgb_bp, tf, attach_to=ego)
        seg = world.spawn_actor(seg_bp, tf, attach_to=ego)

        q_rgb: "queue.Queue[carla.Image]" = queue.Queue()
        q_seg: "queue.Queue[carla.Image]" = queue.Queue()

        rgb.listen(q_rgb.put)
        seg.listen(q_seg.put)

        self._actors.extend([rgb, seg])

        return SensorPair(rgb=rgb, seg=seg, q_rgb=q_rgb, q_seg=q_seg)

    def _setup(self) -> None:
        world = self.client.get_world()
        self._set_sync(world)
        self._world = world
        ego = self._spawn_ego(world)

        setup = DominikSensorSetup(self.calib_path.as_posix())
        setup.load()
        cam_names = setup.camera_names()

        selected = cam_names if self.camera == "all" else [self.camera]
        for cam_name in selected:
            tf = setup.get_camera_transform_vehicle_to_sensor(cam_name)
            w, h = setup.get_camera_size(cam_name)
            fov = setup.get_camera_fov(cam_name)
            pair = self._attach_pair(world, ego, tf, w, h, fov)
            self._pairs[cam_name] = pair

        for _ in range(5):
            world.tick()

    def run(self, frames: int) -> Path:
        self._setup()
        assert self._world is not None

        run_info = {
            "dataset": self.dataset_dir.name,
            "frames": frames,
            "seed": self.seed,
            "fps": self.fps,
            "calib_path": str(self.calib_path),
            "camera": self.camera,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        (self.meta_dir / "run_info.json").write_text(json.dumps(run_info, indent=2), encoding="utf-8")

        frames_jsonl = self.meta_dir / "frames.jsonl"
        with open(frames_jsonl, "w", encoding="utf-8") as fmeta:
            for _ in range(10):
                self._world.tick()

            for i in range(frames):
                frame_id = int(self._world.tick())
                fmeta.write(json.dumps({"frame": frame_id, "ts": time.time()}) + "\n")

                for cam_name, pair in self._pairs.items():
                    rgb_img = pair.q_rgb.get(timeout=5.0)
                    seg_img = pair.q_seg.get(timeout=5.0)

                    # re-sync if needed
                    if rgb_img.frame != frame_id:
                        while rgb_img.frame != frame_id:
                            rgb_img = pair.q_rgb.get(timeout=5.0)
                    if seg_img.frame != frame_id:
                        while seg_img.frame != frame_id:
                            seg_img = pair.q_seg.get(timeout=5.0)

                    # create a palette-converted copy for visualization
                    seg_palette = carla.Image(seg_img.frame, seg_img.width, seg_img.height, seg_img.fov)
                    seg_palette.raw_data = seg_img.raw_data
                    seg_palette.convert(carla.ColorConverter.CityScapesPalette)

                    _ensure_dir(self.rgb_dir / cam_name)
                    _ensure_dir(self.semseg_dir / cam_name)
                    _ensure_dir(self.semseg_raw_dir / cam_name)

                    rgb_path = self.rgb_dir / cam_name / f"{frame_id:08d}.png"
                    seg_path = self.semseg_dir / cam_name / f"{frame_id:08d}.png"
                    raw_path = self.semseg_raw_dir / cam_name / f"{frame_id:08d}.png"

                    rgb_img.save_to_disk(rgb_path.as_posix())
                    seg_palette.save_to_disk(seg_path.as_posix())
                    _write_png_raw_ids(seg_img, raw_path)

        return self.dataset_dir

    def close(self) -> None:
        try:
            if self._world is not None:
                s = self._world.get_settings()
                s.synchronous_mode = False
                s.fixed_delta_seconds = None
                self._world.apply_settings(s)
        except Exception:
            pass

        for a in reversed(self._actors):
            try:
                if isinstance(a, carla.Sensor):
                    a.stop()
            except Exception:
                pass
            try:
                a.destroy()
            except Exception:
                pass

        self._actors = []
        self._pairs = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=SETTINGS.CARLA_HOST)
    ap.add_argument("--port", type=int, default=SETTINGS.CARLA_PORT)
    ap.add_argument("--frames", type=int, default=1000)
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--out-root", default="datasets")
    ap.add_argument("--dataset-name", default="seg_dataset")
    ap.add_argument("--calib", default="calib_data.json")
    ap.add_argument("--camera", default="front", help="camera name or 'all'")
    ap.add_argument("--seed", type=int, default=42)
    return ap.parse_args()


def main():
    args = parse_args()
    client = carla.Client(args.host, args.port)
    client.set_timeout(30.0)

    with SegmentationDatasetGenerator(
        client=client,
        out_root=Path(args.out_root),
        dataset_name=args.dataset_name,
        calib_path=Path(args.calib),
        camera=args.camera,
        seed=args.seed,
        fps=args.fps,
    ) as gen:
        out = gen.run(args.frames)
        print(f"✅ Dataset written → {out}")


if __name__ == "__main__":
    main()
