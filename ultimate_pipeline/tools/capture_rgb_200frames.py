#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from queue import Queue, Empty
from typing import Any, Dict, Tuple

import numpy as np

FRAME_WAIT_S = 3.0


def _save_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _laplacian_variance(gray: np.ndarray) -> float:
    kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)
    padded = np.pad(gray, 1, mode="edge")
    out = (
        kernel[0, 1] * padded[0:-2, 1:-1]
        + kernel[1, 0] * padded[1:-1, 0:-2]
        + kernel[1, 2] * padded[1:-1, 2:]
        + kernel[2, 1] * padded[2:, 1:-1]
        + kernel[1, 1] * padded[1:-1, 1:-1]
    )
    return float(np.var(out))


def _extract_camera(calib: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    cameras = calib.get("cameras", {})
    if "front_left_camera" in cameras:
        return cameras["front_left_camera"], "front_left_camera"
    if cameras:
        first_key = sorted(cameras.keys())[0]
        return cameras[first_key], first_key
    raise RuntimeError("No cameras found in calib_data.json")


def _parse_image_size(image_size: Any) -> Tuple[int, int]:
    if isinstance(image_size, dict):
        return int(image_size["width"]), int(image_size["height"])
    if isinstance(image_size, (list, tuple)) and len(image_size) >= 2:
        return int(image_size[0]), int(image_size[1])
    raise ValueError(f"Unsupported image_size format: {image_size}")


def _run_capture(
    xodr: Path,
    calib: Path,
    out_dir: Path,
    host: str,
    port: int,
    frames: int,
    fps: int,
    timeout_s: float,
    frames_requested: int | None = None,
) -> Dict[str, Any]:
    from ultimate_pipeline.quality.check_lane_link_targets_exist import check_lane_link_targets_exist
    from ultimate_pipeline.carla_tools.thesis_sensor_rig import ThesisSensorRig
    from ultimate_pipeline.carla_tools.carla_readiness import wait_for_carla_ready
    from PIL import Image

    frames_requested = frames_requested if frames_requested is not None else frames
    out_dir.mkdir(parents=True, exist_ok=True)
    result_path = out_dir / "recording_summary.json"

    lane_report = check_lane_link_targets_exist(str(xodr))
    _save_json(out_dir / "lane_link_target_report.json", lane_report)
    if not lane_report.get("ok", False):
        summary = {
            "status": "FAIL",
            "failure_reason": "lane_link_targets_failed",
            "frames_recorded": 0,
            "frames_requested": frames_requested,
            "fps": fps,
            "host": host,
            "port": port,
            "frames": frames,
            "camera": "",
            "image_size": {"width": 0, "height": 0},
            "brightness_mean": 0.0,
            "brightness_std": 0.0,
            "laplacian_variance": 0.0,
            "screenshot_paths": [],
        }
        _save_json(result_path, summary)
        return summary

    readiness = wait_for_carla_ready(host, port, timeout_s=45.0, require_tick=True)
    if not readiness.get("ok", False):
        summary = {
            "status": "FAIL",
            "failure_reason": "carla_not_ready",
            "frames_recorded": 0,
            "frames_requested": frames_requested,
            "fps": fps,
            "host": host,
            "port": port,
            "frames": frames,
            "camera": "",
            "image_size": {"width": 0, "height": 0},
            "brightness_mean": 0.0,
            "brightness_std": 0.0,
            "laplacian_variance": 0.0,
            "screenshot_paths": [],
            "carla_readiness": readiness,
        }
        _save_json(result_path, summary)
        return summary

    import carla  # type: ignore

    from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world, ensure_world_ticks

    calib_data = json.loads(calib.read_text(encoding="utf-8"))
    cam_cfg, cam_name = _extract_camera(calib_data)
    width, height = _parse_image_size(cam_cfg.get("image_size", [800, 450]))

    client = carla.Client(host, port)
    client.set_timeout(45.0)

    xodr_text = xodr.read_text(encoding="utf-8", errors="ignore")
    world = None
    original_settings = None
    world = load_opendrive_world(
        client,
        xodr_text,
        params=None,
        timeout_s=45.0,
        retries=0,
        do_reload=True,
        fallback_enabled=False,
        fallback_maps=None,
    )
    ensure_world_ticks(world, n=3, timeout_per_tick_s=2.0)

    original_settings = world.get_settings()
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 1.0 / float(fps)
    settings.no_rendering_mode = False
    world.apply_settings(settings)

    actors = []
    camera = None
    camera_q: Queue = Queue(maxsize=8)
    screenshot_paths = []
    sensor_report_path = out_dir / "sensor_spawn_report.json"
    sensor_report = None
    sensor_report_written = False
    brightness_means: list[float] = []
    brightness_stds: list[float] = []
    lap_vars: list[float] = []
    status = "PASS"
    failure_reason = ""

    def _cb(img):
        try:
            camera_q.put_nowait(img)
        except Exception:
            pass

    try:
        spawn_points = world.get_map().get_spawn_points()
        if not spawn_points:
            raise RuntimeError("No spawn points found.")
        ego_tf = spawn_points[0]
        bp_lib = world.get_blueprint_library()
        vehicles = bp_lib.filter("vehicle.audi.a2") or bp_lib.filter("vehicle.*")
        ego_bp = bp_lib.find(vehicles[0].id if hasattr(vehicles[0], "id") else vehicles[0])
        ego = world.try_spawn_actor(ego_bp, ego_tf)
        if ego is None:
            raise RuntimeError("Failed to spawn ego vehicle.")
        actors.append(ego)

        tm = client.get_trafficmanager(8000)
        tm.set_synchronous_mode(True)
        tm.set_random_device_seed(7)
        tm.set_global_distance_to_leading_vehicle(2.0)
        ego.set_autopilot(True, tm.get_port())

        rig = ThesisSensorRig(calib)
        spawned = rig.spawn_rig(world, ego)
        sensor_report = {name: sp.report for name, sp in spawned.items()}
        _save_json(sensor_report_path, sensor_report)
        sensor_report_written = True
        for sp in spawned.values():
            actors.append(sp.actor)

        camera_actor = None
        camera_names = sorted(
            name for name, sp in spawned.items() if sp.report.get("type") == "camera"
        )
        if "front_left_camera" in camera_names:
            cam_name = "front_left_camera"
        elif camera_names:
            cam_name = camera_names[0]
        if cam_name in spawned and spawned[cam_name].report.get("type") == "camera":
            camera_actor = spawned[cam_name].actor
        if camera_actor is None:
            raise RuntimeError("No camera sensors spawned from calibration rig.")
        camera = camera_actor
        camera.listen(_cb)

        first_frame_saved = False
        capture_start = time.monotonic()
        deadline = capture_start + timeout_s

        for idx in range(frames):
            if time.monotonic() >= deadline:
                recorded = len(brightness_means)
                failure_reason = "timeout"
                status = "FAIL" if recorded == 0 else "PASS_PARTIAL"
                break

            world.tick()

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                recorded = len(brightness_means)
                failure_reason = "timeout"
                status = "FAIL" if recorded == 0 else "PASS_PARTIAL"
                break

            frame_timeout = min(FRAME_WAIT_S, remaining)
            if frame_timeout <= 0:
                recorded = len(brightness_means)
                failure_reason = "timeout"
                status = "FAIL" if recorded == 0 else "PASS_PARTIAL"
                break

            try:
                img = camera_q.get(timeout=frame_timeout)
            except Empty:
                recorded = len(brightness_means)
                failure_reason = "sensor_no_frames"
                status = "FAIL" if recorded == 0 else "PASS_PARTIAL"
                break

            arr = np.frombuffer(img.raw_data, dtype=np.uint8).reshape((img.height, img.width, 4))[:, :, :3]
            gray = (0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]).astype(np.float32)
            brightness_means.append(float(np.mean(gray)))
            brightness_stds.append(float(np.std(gray)))
            lap_vars.append(_laplacian_variance(gray))

            target = None
            if not first_frame_saved:
                target = out_dir / "frame_first.png"
                first_frame_saved = True
            elif idx == frames - 1:
                target = out_dir / "frame_last.png"

            if target is not None:
                Image.fromarray(arr).save(target)
                screenshot_paths.append(str(target))
    except Exception as exc:  # noqa: BLE001
        status = "FAIL"
        failure_reason = str(exc)
    finally:
        if sensor_report is not None and not sensor_report_written:
            _save_json(sensor_report_path, sensor_report)
        if world is not None and original_settings is not None:
            try:
                world.apply_settings(original_settings)
            except Exception:
                pass
        for actor in actors[::-1]:
            try:
                actor.destroy()
            except Exception:
                pass

    summary = {
        "status": status,
        "failure_reason": failure_reason,
        "frames_recorded": len(brightness_means),
        "frames_requested": frames_requested,
        "fps": fps,
        "host": host,
        "port": port,
        "frames": frames,
        "camera": cam_name,
        "brightness_mean": float(np.mean(brightness_means)) if brightness_means else 0.0,
        "brightness_std": float(np.mean(brightness_stds)) if brightness_stds else 0.0,
        "laplacian_variance": float(np.mean(lap_vars)) if lap_vars else 0.0,
        "screenshot_paths": screenshot_paths,
        "image_size": {"width": int(width), "height": int(height)},
        "carla_readiness": readiness,
    }
    _save_json(result_path, summary)
    return summary


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Capture 200 RGB frames with calibrated camera and export simple metrics.")
    ap.add_argument("--xodr", required=True, type=Path, help="Path to OpenDRIVE .xodr")
    ap.add_argument("--calib", required=True, type=Path, help="Path to calib_data.json")
    ap.add_argument("--out", required=True, type=Path, help="Output directory for frames/metrics")
    ap.add_argument("--host", default="127.0.0.1", help="CARLA host")
    ap.add_argument("--port", type=int, default=2000, help="CARLA RPC port")
    ap.add_argument("--frames", type=int, default=200, help="Number of frames to capture (max 200)")
    ap.add_argument("--fps", type=int, default=20, help="Synchronous FPS")
    ap.add_argument("--timeout-s", type=float, default=120.0, help="Maximum wall-clock time allowed for capture")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    frames = min(int(args.frames), 200)
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        summary = _run_capture(
            args.xodr,
            args.calib,
            args.out,
            args.host,
            int(args.port),
            frames,
            int(args.fps),
            timeout_s=float(args.timeout_s),
            frames_requested=int(args.frames),
        )
        print(json.dumps(summary, indent=2))
        return 0 if summary.get("status") == "PASS" else 1
    except Exception as exc:  # noqa: BLE001
        err = {
            "status": "FAIL",
            "failure_reason": str(exc),
            "frames_recorded": 0,
            "frames_requested": int(args.frames),
            "fps": int(args.fps),
            "host": args.host,
            "port": int(args.port),
            "frames": frames,
            "camera": "",
            "image_size": {"width": 0, "height": 0},
            "brightness_mean": 0.0,
            "brightness_std": 0.0,
            "laplacian_variance": 0.0,
            "screenshot_paths": [],
        }
        _save_json(args.out / "recording_summary.json", err)
        print(json.dumps(err, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
