#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import hashlib
import json
import math
import time
from pathlib import Path
from queue import Queue, Empty

import carla
import numpy as np

from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world


def md5_file(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _pose_to_carla_transform(pose: dict[str, float]) -> carla.Transform:
    return carla.Transform(
        carla.Location(x=pose["x"], y=pose["y"], z=pose["z"]),
        carla.Rotation(roll=pose["roll"], pitch=pose["pitch"], yaw=pose["yaw"]),
    )


def fov_from_K_undistortion(K_undist: np.ndarray, width_px: int) -> float:
    fx = float(K_undist[0, 0])
    return 2.0 * math.degrees(math.atan(width_px / (2.0 * fx)))


def camera_transform_from_cTv(cTv: np.ndarray, flip_vehicle_y=True, opencv_camera_axes=True) -> carla.Transform:
    """Compatibility entrypoint backed by the authoritative v2 frame contract."""
    if not flip_vehicle_y or not opencv_camera_axes:
        raise ValueError("evaluate_generated_map supports only CARLA_SENSOR_MOUNTING/v2 frames")
    from ultimate_pipeline.sensors.transform_conventions import camera_attachment_pose_from_cTv

    return _pose_to_carla_transform(camera_attachment_pose_from_cTv(cTv))


def lidar_transform_from_vTl(vTl: np.ndarray, flip_vehicle_y=True) -> carla.Transform:
    """Compatibility entrypoint backed by the authoritative v2 frame contract."""
    if not flip_vehicle_y:
        raise ValueError("evaluate_generated_map supports only CARLA_SENSOR_MOUNTING/v2 frames")
    from ultimate_pipeline.sensors.transform_conventions import lidar_attachment_pose_from_vTl

    return _pose_to_carla_transform(lidar_attachment_pose_from_vTl(vTl))


def spawn_debug_props(world: carla.World, ego: carla.Actor) -> list[carla.Actor]:
    lib = world.get_blueprint_library()

    # Try a few common prop IDs (availability depends on CARLA version)
    prop_ids = [
        "static.prop.trafficcone01",
        "static.prop.streetbarrier",
        "static.prop.warningconstruction",
    ]
    prop_bps = []
    for pid in prop_ids:
        bp = lib.find(pid) if lib.has_attribute(pid) else None
        if bp is None:
            try:
                bp = lib.find(pid)
            except Exception:
                bp = None
        if bp:
            prop_bps.append(bp)

    if not prop_bps:
        print("⚠ No known debug prop blueprints found; skipping prop spawn.")
        return []

    actors = []
    base = ego.get_transform()
    for i in range(10):
        ang = (2 * math.pi) * (i / 10.0)
        dx = 8.0 * math.cos(ang)
        dy = 8.0 * math.sin(ang)
        tf = carla.Transform(
            carla.Location(
                x=base.location.x + dx,
                y=base.location.y + dy,
                z=base.location.z,
            ),
            carla.Rotation(yaw=float(base.rotation.yaw)),
        )
        bp = prop_bps[i % len(prop_bps)]
        a = world.try_spawn_actor(bp, tf)
        if a:
            actors.append(a)

    print(f"🧱 Spawned {len(actors)} debug props around ego.")
    return actors


def capture_one_image(sensor: carla.Sensor, out_png: Path, timeout_s=5.0) -> bool:
    q: Queue = Queue(maxsize=1)

    def _cb(img):
        try:
            if q.full():
                return
            q.put(img)
        except Exception:
            pass

    sensor.listen(_cb)
    try:
        img = q.get(timeout=timeout_s)
        img.save_to_disk(str(out_png))
        return True
    except Empty:
        return False
    finally:
        try:
            sensor.stop()
        except Exception:
            pass


def main(
    xodr_path: str,
    calib_json: str,
    out_dir: str,
    host="127.0.0.1",
    port=2000,
    flip_vehicle_y=True,
    opencv_camera_axes=True,
):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    manifest = {
        "xodr_path": str(Path(xodr_path).resolve()),
        "xodr_md5": md5_file(xodr_path),
        "calib_json": str(Path(calib_json).resolve()),
        "time_unix": time.time(),
    }

    client = carla.Client(host, int(port))
    client.set_timeout(120.0)

    # Load OpenDRIVE into CARLA
    xodr_str = Path(xodr_path).read_text(encoding="utf-8", errors="replace")
    if not hasattr(client, "generate_opendrive_world"):
        raise RuntimeError("Your CARLA Python API does not expose OpenDRIVE world generation.")

    world = load_opendrive_world(
        client,
        xodr_str,
        timeout_s=180.0,
        retries=2,
        do_reload=True,
    )
    world.set_weather(carla.WeatherParameters.ClearNoon)

    # Synchronous ticks for stable capture
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.05
    world.apply_settings(settings)

    for _ in range(20):
        world.tick()

    # Spawn ego
    bp = world.get_blueprint_library().find("vehicle.tesla.model3")
    bp.set_attribute("role_name", "ego")
    spawn_points = world.get_map().get_spawn_points()
    if not spawn_points:
        raise RuntimeError("No spawn points on generated map.")
    ego = world.spawn_actor(bp, spawn_points[0])

    # Spawn props
    props = spawn_debug_props(world, ego)

    # Load calibration
    calib = json.loads(Path(calib_json).read_text(encoding="utf-8"))
    cams = calib.get("cameras", {})
    lids = calib.get("lidars", {})

    sensors: dict[str, carla.Actor] = {}

    # Cameras
    for name, cfg in cams.items():
        width, height = int(cfg["image_size"][0]), int(cfg["image_size"][1])
        K_und = np.asarray(cfg["K_undistortion"], dtype=float)
        fov = fov_from_K_undistortion(K_und, width)

        cam_bp = world.get_blueprint_library().find("sensor.camera.rgb")
        cam_bp.set_attribute("image_size_x", str(width))
        cam_bp.set_attribute("image_size_y", str(height))
        cam_bp.set_attribute("fov", str(fov))

        cTv = np.asarray(cfg["cTv"], dtype=float)
        tf = camera_transform_from_cTv(cTv, flip_vehicle_y=flip_vehicle_y, opencv_camera_axes=opencv_camera_axes)
        cam = world.spawn_actor(cam_bp, tf, attach_to=ego, attachment_type=carla.AttachmentType.Rigid)
        sensors[name] = cam

        print(f"📷 {name}: {width}x{height} fov={fov:.2f} tf={tf}")

    # LiDARs
    for name, cfg in lids.items():
        lidar_bp = world.get_blueprint_library().find("sensor.lidar.ray_cast")
        vTl = np.asarray(cfg["vTl"], dtype=float)
        tf = lidar_transform_from_vTl(vTl, flip_vehicle_y=flip_vehicle_y)
        lid = world.spawn_actor(lidar_bp, tf, attach_to=ego, attachment_type=carla.AttachmentType.Rigid)
        sensors[name] = lid
        print(f"📡 {name}: tf={tf}")

    for _ in range(10):
        world.tick()

    # Capture one image from each camera
    shots_dir = out / "screens"
    shots_dir.mkdir(exist_ok=True)
    captured = {}
    for name, s in sensors.items():
        if isinstance(s, carla.Sensor) and s.type_id.startswith("sensor.camera"):
            ok = capture_one_image(s, shots_dir / f"{name}.png", timeout_s=5.0)
            captured[name] = ok
            print(f"🖼 capture {name}: {'OK' if ok else 'TIMEOUT'}")

    manifest["captured"] = captured
    manifest["spawn_points"] = len(spawn_points)

    (out / "eval_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("✅ Wrote:", out / "eval_manifest.json")

    # Cleanup
    for a in list(sensors.values()) + props + [ego]:
        try:
            a.destroy()
        except Exception:
            pass

    settings = world.get_settings()
    settings.synchronous_mode = False
    world.apply_settings(settings)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--xodr", required=True)
    ap.add_argument("--calib", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--no_flip_vehicle_y", action="store_true")
    ap.add_argument("--no_opencv_axes", action="store_true")
    args = ap.parse_args()

    main(
        xodr_path=args.xodr,
        calib_json=args.calib,
        out_dir=args.out,
        host=args.host,
        port=args.port,
        flip_vehicle_y=not args.no_flip_vehicle_y,
        opencv_camera_axes=not args.no_opencv_axes,
    )
