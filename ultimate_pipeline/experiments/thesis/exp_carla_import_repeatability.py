#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Experiment: CARLA OpenDRIVE import repeatability.

Requirement coverage:
 - "When converting OSM to CARLA, please evaluate the map and check if the created map changes when converting the same OSM map into a CARLA map."
 - "Put objects to the generated CARLA map and check them visually."

What this does:
 - Loads the same .xodr into CARLA multiple times (sync mode)
 - Spawns a few reference objects at deterministic locations (relative to ego spawn)
 - Captures a single RGB image each run
 - Compares image hashes + reports spawn point count

If OpenDRIVE import fails, it can fall back to built-in maps when enabled in settings.
"""

from __future__ import annotations

import argparse
import hashlib
import time
from pathlib import Path

import carla

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world, load_builtin_world


def _md5_bytes(b: bytes) -> str:
    h = hashlib.md5()
    h.update(b)
    return h.hexdigest()


def _sync(world: carla.World, fps: int) -> carla.WorldSettings:
    prev = world.get_settings()
    s = carla.WorldSettings(
        synchronous_mode=True,
        fixed_delta_seconds=1.0 / float(fps),
        no_rendering_mode=False,
    )
    world.apply_settings(s)
    return prev


def _spawn_ego(world: carla.World, bp_id: str) -> carla.Actor:
    bp = world.get_blueprint_library().find(bp_id)
    sps = world.get_map().get_spawn_points()
    if not sps:
        raise RuntimeError("No spawn points")
    ego = world.try_spawn_actor(bp, sps[0])
    if ego is None:
        # try a few
        for sp in sps[1:20]:
            ego = world.try_spawn_actor(bp, sp)
            if ego:
                break
    if ego is None:
        raise RuntimeError("Failed to spawn ego")
    return ego


def _spawn_debug_props(world: carla.World, ego: carla.Actor) -> list[carla.Actor]:
    """Spawn a few visible objects near ego to make visual QA easy."""
    bps = world.get_blueprint_library()
    # traffic cones are small + high contrast; fallback to any static prop.
    candidates = [
        "static.prop.trafficcone01",
        "static.prop.trafficcone02",
        "static.prop.streetbarrier",
        "static.prop.constructioncone",
    ]
    bp = None
    for c in candidates:
        try:
            bp = bps.find(c)
            break
        except Exception:
            continue
    if bp is None:
        # last resort: any static prop
        props = [x for x in bps.filter("static.prop.*")]
        if not props:
            return []
        bp = props[0]

    tf0 = ego.get_transform()
    loc = tf0.location
    yaw = tf0.rotation.yaw
    fwd = tf0.get_forward_vector()
    right = tf0.get_right_vector()

    # deterministic offsets (meters)
    offsets = [
        (6.0, 1.5),
        (8.0, -1.5),
        (10.0, 0.0),
    ]

    spawned = []
    for f, r in offsets:
        l = carla.Location(
            x=loc.x + fwd.x * f + right.x * r,
            y=loc.y + fwd.y * f + right.y * r,
            z=loc.z,
        )
        tf = carla.Transform(l, carla.Rotation(pitch=0.0, yaw=yaw, roll=0.0))
        a = world.try_spawn_actor(bp, tf)
        if a:
            spawned.append(a)
    return spawned


def _capture_one(world: carla.World, ego: carla.Actor, out_path: Path) -> str:
    bps = world.get_blueprint_library()
    cam_bp = bps.find("sensor.camera.rgb")
    cam_bp.set_attribute("image_size_x", "1024")
    cam_bp.set_attribute("image_size_y", "512")
    cam_bp.set_attribute("fov", "90")

    cam_tf = carla.Transform(carla.Location(x=1.5, z=1.6))
    cam = world.spawn_actor(cam_bp, cam_tf, attach_to=ego)

    data = {"raw": None, "w": None, "h": None}

    def _cb(img):
        # BGRA bytes
        data["raw"] = bytes(img.raw_data)
        data["w"] = int(img.width)
        data["h"] = int(img.height)

    cam.listen(_cb)
    # tick a few frames to let sensor produce a frame
    for _ in range(5):
        world.tick()
    cam.stop()
    cam.destroy()

    if not data["raw"]:
        raise RuntimeError("Camera did not produce data")

    # Write PNG for human QA + hash the saved PNG bytes.
    import numpy as np
    from PIL import Image

    w, h = int(data["w"]), int(data["h"])
    arr = np.frombuffer(data["raw"], dtype=np.uint8).reshape(h, w, 4)
    # BGRA -> RGB
    rgb = arr[:, :, :3][:, :, ::-1]
    Image.fromarray(rgb).save(out_path)
    return _md5_bytes(out_path.read_bytes())


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xodr", required=True)
    ap.add_argument("--out-dir", default="out_carla_import_repeatability")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--host", default=getattr(SETTINGS, "CARLA_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=getattr(SETTINGS, "CARLA_PORT", 2000))
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--vehicle", default="vehicle.audi.a2")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    client = carla.Client(args.host, args.port)
    client.set_timeout(60.0)

    xodr_text = Path(args.xodr).read_text(encoding="utf-8")
    hashes = []
    spawn_counts = []

    for i in range(int(args.runs)):
        # Load world (with optional fallback controlled by settings)
        if getattr(SETTINGS, "CARLA_FORCE_BUILTIN_MAP", False):
            world = load_builtin_world(client, getattr(SETTINGS, "CARLA_BUILTIN_MAP", "Town10HD_Opt"))
        else:
            world = load_opendrive_world(
                client,
                xodr_text,
                params=None,
                timeout_s=180.0,
                retries=2,
                do_reload=True,
                fallback_enabled=getattr(SETTINGS, "CARLA_ENABLE_MAP_FALLBACK", False),
                fallback_maps=getattr(SETTINGS, "CARLA_FALLBACK_MAPS", None),
            )

        prev = _sync(world, args.fps)
        actors = []
        try:
            ego = _spawn_ego(world, args.vehicle)
            actors.append(ego)
            actors += _spawn_debug_props(world, ego)
            # Let physics settle
            for _ in range(5):
                world.tick()

            img_path = out_dir / f"run_{i:03d}.png"
            h = _capture_one(world, ego, img_path)
            hashes.append(h)
            spawn_counts.append(len(world.get_map().get_spawn_points()))
            print(f"[{i}] image_md5={h} spawn_points={spawn_counts[-1]}")
        finally:
            # restore settings + cleanup
            try:
                world.apply_settings(prev)
            except Exception:
                pass
            for a in actors:
                try:
                    a.destroy()
                except Exception:
                    pass
        time.sleep(0.5)

    stable = all(h == hashes[0] for h in hashes)
    (out_dir / "report.txt").write_text(
        "\n".join([
            f"stable_image_hash={stable}",
            f"unique_hashes={sorted(set(hashes))}",
            f"spawn_point_counts={spawn_counts}",
        ]),
        encoding="utf-8",
    )
    print(f"✅ Wrote report → {out_dir / 'report.txt'}")


if __name__ == "__main__":
    main()
