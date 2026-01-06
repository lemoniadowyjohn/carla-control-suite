#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Screenshot Generator for CARLA Maps
-----------------------------------

Capabilities:
- capture top-down tile-overview screenshots
- capture first-person ego-view screenshots
- capture multiple random spawn locations
- produce batches for documentation/thesis
"""

from __future__ import annotations
import os
import time
import random
import numpy as np

# pygame is optional at import time because main_pipeline imports this module
# even when screenshots are disabled or when running headless.
try:
    import pygame  # type: ignore
    _PYGAME_AVAILABLE = True
except Exception:  # pragma: no cover
    pygame = None  # type: ignore
    _PYGAME_AVAILABLE = False

try:
    import carla
except ImportError:
    raise RuntimeError("CARLA PythonAPI not found on PYTHONPATH")


class ScreenshotGenerator:

    def __init__(self, client: "carla.Client", out_dir: str):
        self.client = client
        # Do NOT lower the timeout if it was already set higher (e.g. by main_pipeline)
        current_timeout = client.get_timeout()
        if current_timeout < 10.0:
            self.client.set_timeout(10.0)
        self.world = client.get_world()
        self.out_dir = out_dir

        os.makedirs(out_dir, exist_ok=True)

        if _PYGAME_AVAILABLE:
            pygame.init()

    # ---------------------------
    # Top-Down Screenshot
    # ---------------------------

    def capture_topdown(self, filename="topdown.png", altitude=120.0):
        """
        Capture a vertical overhead screenshot of the whole map.
        Works in sync or async mode.
        """

        spectator = self.world.get_spectator()

        spawns = self.world.get_map().get_spawn_points()
        if spawns:
            ego = random.choice(spawns).location
        else:
            ego = carla.Location(x=0, y=0, z=0)

        spectator.set_transform(
            carla.Transform(
                carla.Location(ego.x, ego.y, altitude),
                carla.Rotation(pitch=-90.0)
            )
        )

        out_path = os.path.join(self.out_dir, filename)

        bp = self.world.get_blueprint_library().find("sensor.camera.rgb")
        bp.set_attribute("image_size_x", "1600")
        bp.set_attribute("image_size_y", "1200")
        bp.set_attribute("fov", "60")

        cam = self.world.spawn_actor(
            bp,
            carla.Transform(
                location=carla.Location(ego.x, ego.y, altitude),
                rotation=carla.Rotation(pitch=-90.0),
            ),
        )

        img_holder = {}

        def cb(img):
            # Keep the raw CARLA image for headless fallback.
            if "image" not in img_holder:
                img_holder["image"] = img
            if _PYGAME_AVAILABLE:
                arr = np.frombuffer(img.raw_data, dtype=np.uint8)
                arr = arr.reshape((img.height, img.width, 4))[:, :, :3]
                img_holder["frame"] = arr

        cam.listen(cb)

        # Drive the sim forward until we get a frame (tick-based, not sleep-based)
        for _ in range(30):
            try:
                self.world.tick()
            except Exception:
                self.world.wait_for_tick()
            if "frame" in img_holder:
                break

        if _PYGAME_AVAILABLE and "frame" in img_holder:
            pygame.image.save(
                pygame.surfarray.make_surface(img_holder["frame"].swapaxes(0, 1)),
                out_path,
            )
            print(f"📸 Saved top-down screenshot → {out_path}")
        elif "image" in img_holder:
            # Headless fallback: CARLA can write PNG directly.
            try:
                img_holder["image"].save_to_disk(out_path)
                print(f"📸 Saved top-down screenshot (headless) → {out_path}")
            except Exception as e:
                print(f"⚠ Failed to save screenshot (headless): {e}")
        else:
            print("⚠ No camera frame received (topdown).")

        cam.stop()
        cam.destroy()

    # -----------------------------------------------------------
    # Multiple random spawn screenshots
    # -----------------------------------------------------------

    def batch_random(self, count: int, prefix: str = ""):
        """
        Capture N ego-view screenshots from random spawn points.

        prefix: optional string (e.g. timestamp) added to filenames,
                so runs from different pipeline executions do not overwrite each other.
        """
        spawns = self.world.get_map().get_spawn_points()
        if not spawns:
            print("No spawn points → cannot batch capture")
            return

        for i in range(count):
            sp = random.choice(spawns)
            filename = f"{prefix}_random_spawn_{i+1}.png" if prefix else f"random_spawn_{i+1}.png"
            out_path = os.path.join(self.out_dir, filename)
            self._capture_from_transform(sp, out_path)


    def _capture_from_transform(self, transform: "carla.Transform", out_path: str):
        bp = self.world.get_blueprint_library().find("sensor.camera.rgb")
        bp.set_attribute("image_size_x", "1280")
        bp.set_attribute("image_size_y", "720")
        bp.set_attribute("fov", "90")

        cam = self.world.try_spawn_actor(bp, transform)
        if not cam:
            return

        frame_store = {}

        def cb(img):
            if "image" not in frame_store:
                frame_store["image"] = img
            if _PYGAME_AVAILABLE:
                arr = np.frombuffer(img.raw_data, dtype=np.uint8)
                arr = arr.reshape((img.height, img.width, 4))[:, :, :3]
                frame_store["frame"] = arr

        cam.listen(cb)
        for _ in range(20):
            try:
                self.world.tick()
            except Exception:
                self.world.wait_for_tick()
            if "frame" in frame_store or "image" in frame_store:
                break

        if _PYGAME_AVAILABLE and "frame" in frame_store:
            pygame.image.save(
                pygame.surfarray.make_surface(frame_store["frame"].swapaxes(0, 1)),
                out_path,
            )
            print(f"📸 Saved → {out_path}")
        elif "image" in frame_store:
            try:
                frame_store["image"].save_to_disk(out_path)
                print(f"📸 Saved (headless) → {out_path}")
            except Exception as e:
                print(f"⚠ Failed to save screenshot (headless): {e}")

        cam.stop()
        cam.destroy()
