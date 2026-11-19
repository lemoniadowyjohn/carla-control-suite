#!/usr/bin/env python3
"""CARLA 0.9.16 live camera/LiDAR intrinsic acceptance harness.

This tool captures actual CARLA sensor frames and binds their byte hashes to
the committed calibration and source.  It does not self-approve calibration:
rendered landmark annotations and an independent review are required before an
exact-intrinsic claim can be made.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import queue
import re
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence


# At a 10 m reference range and the largest current focal length (~2063 px),
# 1 mm translation contributes ~0.21 px and 0.01 degree rotation ~0.36 px.
# These remain subpixel checks of the CARLA mounting transform; the independent
# rendered-landmark thresholds below remain the empirical acceptance gate.
ATTACHMENT_TRANSLATION_TOLERANCE_M = 0.001
ATTACHMENT_ANGLE_TOLERANCE_DEG = 0.01


def _canonical_sha(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def project_point(k: Sequence[Sequence[float]], c_tv: Sequence[Sequence[float]],
                  point_vehicle: Sequence[float]) -> tuple[float, float] | None:
    """Project one known vehicle-frame point with the effective rendered K."""
    x, y, z = (float(v) for v in point_vehicle[:3])
    if not all(math.isfinite(v) for v in (x, y, z)):
        raise ValueError("point_vehicle_nonfinite")
    xc = float(c_tv[0][0]) * x + float(c_tv[0][1]) * y + float(c_tv[0][2]) * z + float(c_tv[0][3])
    yc = float(c_tv[1][0]) * x + float(c_tv[1][1]) * y + float(c_tv[1][2]) * z + float(c_tv[1][3])
    zc = float(c_tv[2][0]) * x + float(c_tv[2][1]) * y + float(c_tv[2][2]) * z + float(c_tv[2][3])
    if zc <= 1e-9:
        return None
    uv = (float(k[0][0]) * xc / zc + float(k[0][2]),
          float(k[1][1]) * yc / zc + float(k[1][2]))
    if not all(math.isfinite(v) for v in uv):
        raise ValueError("projected_pixel_nonfinite")
    return uv


def _apply_4x4(matrix: Sequence[Sequence[float]], point: Sequence[float]) -> tuple[float, float, float]:
    x, y, z = (float(v) for v in point[:3])
    return tuple(
        float(matrix[row][0]) * x + float(matrix[row][1]) * y
        + float(matrix[row][2]) * z + float(matrix[row][3])
        for row in range(3)
    )


def transform_error(expected: Mapping[str, Sequence[float]],
                    actual: Mapping[str, Sequence[float]]) -> Dict[str, float]:
    """Compare CARLA world transforms using translation and wrapped Euler deltas."""
    e_loc, a_loc = expected["location"], actual["location"]
    e_rot, a_rot = expected["rotation"], actual["rotation"]
    translation = math.sqrt(sum((float(e_loc[k]) - float(a_loc[k])) ** 2
                                for k in ("x", "y", "z")))
    angles = {}
    for key in ("roll", "pitch", "yaw"):
        delta = (float(e_rot[key]) - float(a_rot[key]) + 180.0) % 360.0 - 180.0
        angles[key] = abs(delta)
    return {"translation_m": translation, "max_angle_deg": max(angles.values()),
            "roll_error_deg": angles["roll"], "pitch_error_deg": angles["pitch"],
            "yaw_error_deg": angles["yaw"]}


def score_camera_annotations(
    *, calibration: Mapping[str, Any], capture_frames: Mapping[str, Any],
    annotations: Mapping[str, Any],
) -> Dict[str, Any]:
    """Score annotations only when they name the exact captured frame bytes."""
    from ultimate_pipeline.perception.environment.live_calibration_assay import (
        ACCEPTANCE_THRESHOLDS, error_statistics,
    )
    calib_cameras = dict(calibration.get("cameras") or {})
    errors: Dict[str, list[float]] = {name: [] for name in calib_cameras}
    seen_landmarks: set[tuple[str, str, str]] = set()
    invalid: list[str] = []
    items = annotations.get("camera_observations")
    if not isinstance(items, list) or not items:
        return {"verdict": "BLOCKED_EXTERNAL", "reason": "rendered_landmark_annotations_missing",
                "per_camera": {}, "thresholds": dict(ACCEPTANCE_THRESHOLDS)}
    for index, item in enumerate(items):
        camera = str(item.get("camera", ""))
        frame_id = str(item.get("frame_id", ""))
        frame = dict(capture_frames.get(frame_id, {}) or {}).get(camera)
        if camera not in calib_cameras or frame is None:
            invalid.append(f"annotation[{index}]:unknown_camera_or_frame")
            continue
        if item.get("image_sha256") != frame.get("image_sha256"):
            invalid.append(f"annotation[{index}]:image_digest_mismatch")
            continue
        intrinsic = frame.get("K_effective")
        c_tv = calib_cameras[camera].get("cTv")
        landmarks = item.get("landmarks")
        if not isinstance(landmarks, list) or not landmarks:
            invalid.append(f"annotation[{index}]:landmarks_missing")
            continue
        for landmark in landmarks:
            key = (frame_id, camera, str(landmark.get("name", "")))
            if not key[2] or key in seen_landmarks:
                invalid.append(f"annotation[{index}]:duplicate_or_empty_landmark_name")
                continue
            seen_landmarks.add(key)
            predicted = project_point(intrinsic, c_tv, landmark.get("point_vehicle", ()))
            observed = landmark.get("observed_uv")
            if (predicted is None or not isinstance(observed, (list, tuple)) or len(observed) != 2
                    or not all(math.isfinite(float(v)) for v in observed)):
                invalid.append(f"annotation[{index}]:invalid_landmark:{landmark.get('name','')}")
                continue
            if not (0.0 <= float(observed[0]) < float(frame["width"])
                    and 0.0 <= float(observed[1]) < float(frame["height"])):
                invalid.append(f"annotation[{index}]:observed_landmark_outside_image")
                continue
            if not (0.0 <= predicted[0] < float(frame["width"])
                    and 0.0 <= predicted[1] < float(frame["height"])):
                invalid.append(f"annotation[{index}]:predicted_landmark_outside_image")
                continue
            errors[camera].append(math.hypot(predicted[0] - float(observed[0]),
                                             predicted[1] - float(observed[1])))
    per_camera = {name: error_statistics(values) for name, values in sorted(errors.items())}
    for camera, stats in per_camera.items():
        if stats["count"] < int(ACCEPTANCE_THRESHOLDS["min_detected_targets_per_camera"]):
            invalid.append(f"{camera}:insufficient_independent_landmarks:{stats['count']}")
        if stats["mean"] is not None and stats["mean"] > ACCEPTANCE_THRESHOLDS["max_mean_reprojection_error_px"]:
            invalid.append(f"{camera}:mean_residual_exceeded:{stats['mean']}")
        if stats["p95"] is not None and stats["p95"] > ACCEPTANCE_THRESHOLDS["max_p95_reprojection_error_px"]:
            invalid.append(f"{camera}:p95_residual_exceeded:{stats['p95']}")
        if stats["max"] is not None and stats["max"] > ACCEPTANCE_THRESHOLDS["max_reprojection_error_px"]:
            invalid.append(f"{camera}:max_residual_exceeded:{stats['max']}")
    return {
        "verdict": "ANNOTATION_RESIDUAL_PASS" if not invalid else "ANNOTATION_RESIDUAL_FAIL",
        "per_camera": per_camera,
        "invalid_reasons": invalid,
        "thresholds": dict(ACCEPTANCE_THRESHOLDS),
        "observation_source": "human_annotated_rendered_carla_frames",
        "evidence_kind": "RESIDUAL_CALCULATION_ONLY_REQUIRES_CAPTURE_AND_REVIEW_BINDING",
        "independent_review": "PENDING",
    }


def score_lidar_camera_annotations(
    *, calibration: Mapping[str, Any], capture_frames: Mapping[str, Any],
    annotations: Mapping[str, Any], dataset_root: str | Path,
) -> Dict[str, Any]:
    """Measure pixel residuals from indexed returns in the actual LiDAR files."""
    import numpy as np
    from ultimate_pipeline.perception.environment.live_calibration_assay import (
        ACCEPTANCE_THRESHOLDS, error_statistics,
    )
    camera_calib = dict(calibration.get("cameras") or {})
    lidar_calib = dict(calibration.get("lidars") or {})
    errors: Dict[str, list[float]] = {name: [] for name in camera_calib}
    invalid: list[str] = []
    seen_points: set[tuple[str, str, int]] = set()
    rows = annotations.get("lidar_observations")
    if not isinstance(rows, list) or not rows:
        return {"verdict": "BLOCKED_EXTERNAL", "reason": "lidar_camera_landmark_annotations_missing",
                "per_camera": {}, "thresholds": dict(ACCEPTANCE_THRESHOLDS)}
    root = Path(dataset_root)
    for index, row in enumerate(rows):
        frame_id = str(row.get("frame_id", ""))
        camera, lidar = str(row.get("camera", "")), str(row.get("lidar", ""))
        frame = dict(capture_frames.get(frame_id, {}) or {})
        cam_capture, lid_capture = frame.get(camera), frame.get(lidar)
        if camera not in camera_calib or lidar not in lidar_calib or not cam_capture or not lid_capture:
            invalid.append(f"lidar_annotation[{index}]:unknown_camera_lidar_or_frame")
            continue
        if row.get("camera_image_sha256") != cam_capture.get("image_sha256"):
            invalid.append(f"lidar_annotation[{index}]:camera_image_digest_mismatch")
            continue
        if row.get("lidar_data_sha256") != lid_capture.get("data_sha256"):
            invalid.append(f"lidar_annotation[{index}]:lidar_data_digest_mismatch")
            continue
        raw_path = root / str(lid_capture["path"])
        raw = np.frombuffer(raw_path.read_bytes(), dtype="<f4")
        if raw.size % 4:
            invalid.append(f"lidar_annotation[{index}]:malformed_lidar_bytes")
            continue
        points = raw.reshape((-1, 4))
        point_index = int(row.get("point_index", -1))
        point_key = (frame_id, camera, point_index)
        if point_key in seen_points:
            invalid.append(f"lidar_annotation[{index}]:duplicate_camera_point_match")
            continue
        seen_points.add(point_key)
        if point_index < 0 or point_index >= len(points):
            invalid.append(f"lidar_annotation[{index}]:point_index_out_of_range")
            continue
        point_lidar = points[point_index, :3].tolist()
        if not all(math.isfinite(float(value)) for value in point_lidar):
            invalid.append(f"lidar_annotation[{index}]:nonfinite_lidar_point")
            continue
        point_vehicle = _apply_4x4(lidar_calib[lidar]["vTl"], point_lidar)
        projected = project_point(cam_capture["K_effective"], camera_calib[camera]["cTv"], point_vehicle)
        observed = row.get("observed_uv")
        if (projected is None or not isinstance(observed, (list, tuple)) or len(observed) != 2
                or not all(math.isfinite(float(value)) for value in observed)):
            invalid.append(f"lidar_annotation[{index}]:invalid_projection_or_pixel")
            continue
        width, height = float(cam_capture["width"]), float(cam_capture["height"])
        if not (0.0 <= projected[0] < width and 0.0 <= projected[1] < height):
            invalid.append(f"lidar_annotation[{index}]:projected_point_outside_image")
            continue
        if not (0.0 <= float(observed[0]) < width and 0.0 <= float(observed[1]) < height):
            invalid.append(f"lidar_annotation[{index}]:observed_pixel_outside_image")
            continue
        errors[camera].append(math.hypot(projected[0] - float(observed[0]),
                                        projected[1] - float(observed[1])))
    per_camera = {name: error_statistics(values) for name, values in sorted(errors.items())}
    for camera, stats in per_camera.items():
        if stats["count"] < int(ACCEPTANCE_THRESHOLDS["min_detected_targets_per_camera"]):
            invalid.append(f"{camera}:insufficient_lidar_camera_matches:{stats['count']}")
        if stats["mean"] is not None and stats["mean"] > ACCEPTANCE_THRESHOLDS["max_mean_reprojection_error_px"]:
            invalid.append(f"{camera}:lidar_camera_mean_residual_exceeded:{stats['mean']}")
        if stats["p95"] is not None and stats["p95"] > ACCEPTANCE_THRESHOLDS["max_p95_reprojection_error_px"]:
            invalid.append(f"{camera}:lidar_camera_p95_residual_exceeded:{stats['p95']}")
        if stats["max"] is not None and stats["max"] > ACCEPTANCE_THRESHOLDS["max_reprojection_error_px"]:
            invalid.append(f"{camera}:lidar_camera_max_residual_exceeded:{stats['max']}")
    return {
        "verdict": "ANNOTATION_RESIDUAL_PASS" if not invalid else "ANNOTATION_RESIDUAL_FAIL",
        "per_camera": per_camera,
        "invalid_reasons": invalid,
        "thresholds": dict(ACCEPTANCE_THRESHOLDS),
        "point_source": "indexed_actual_carla_lidar_returns",
        "observation_source": "human_annotated_rendered_carla_frames",
        "evidence_kind": "RESIDUAL_CALCULATION_ONLY_REQUIRES_CAPTURE_AND_REVIEW_BINDING",
        "independent_review": "PENDING",
    }


def _sensor_name_set(calibration: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    cameras = set(dict(calibration.get("cameras") or {}))
    lidars = dict(calibration.get("lidars") or {})
    # Active LiDAR selection is resolved by the canonical thesis helper at runtime.
    if not cameras or not lidars:
        raise ValueError("calibration_requires_camera_and_lidar_entries")
    return cameras, set(lidars)


def _start_sensor_listeners(spawned: Mapping[str, Any]) -> Dict[str, queue.Queue[Any]]:
    queues: Dict[str, queue.Queue[Any]] = {}
    for name, wrapped in spawned.items():
        q: queue.Queue[Any] = queue.Queue(maxsize=64)
        queues[name] = q
        def callback(data: Any, target: queue.Queue[Any] = q) -> None:
            try:
                target.put_nowait(data)
            except queue.Full:
                # The consumer observes a missing frame and fails closed.
                pass
        wrapped.actor.listen(callback)
    return queues


def _stop_sensor_listeners(spawned: Mapping[str, Any]) -> None:
    for wrapped in spawned.values():
        try:
            wrapped.actor.stop()
        except Exception:
            pass


def _record_one_frame(world: Any, spawned: Mapping[str, Any],
                      queues: Mapping[str, queue.Queue[Any]], output_dir: Path,
                      timeout_s: float) -> Dict[str, Any]:
    frame_id = int(world.tick())
    deadline = time.monotonic() + timeout_s
    measurements: Dict[str, Any] = {}
    frame_dir = output_dir / f"frame_{frame_id:08d}"
    frame_dir.mkdir(parents=True, exist_ok=False)
    for name, wrapped in spawned.items():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"sensor_frame_timeout:{name}:{frame_id}")
        try:
            data = queues[name].get(timeout=remaining)
        except queue.Empty as exc:
            raise TimeoutError(f"sensor_frame_timeout:{name}:{frame_id}") from exc
        observed_id = int(getattr(data, "frame", -1))
        while observed_id < frame_id:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"sensor_stale_callback_timeout:{name}:{frame_id}")
            try:
                data = queues[name].get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError(
                    f"sensor_stale_callback_timeout:{name}:{frame_id}"
                ) from exc
            observed_id = int(getattr(data, "frame", -1))
        if observed_id != frame_id:
            raise RuntimeError(f"sensor_frame_mismatch:{name}:{observed_id}!={frame_id}")
        timestamp = float(getattr(data, "timestamp", float("nan")))
        if not math.isfinite(timestamp):
            raise RuntimeError(f"sensor_timestamp_invalid:{name}:{frame_id}")
        if name in dict(spawned) and "camera" in str(getattr(wrapped.actor, "type_id", "")):
            width, height, fov = int(data.width), int(data.height), float(data.fov)
            expected_attrs = dict(wrapped.report.get("attributes") or {})
            if width != int(expected_attrs.get("width", -1)) or height != int(expected_attrs.get("height", -1)):
                raise RuntimeError(f"camera_image_size_mismatch:{name}:{width}x{height}")
            if abs(fov - float(expected_attrs.get("fov", float("nan")))) > 1e-3:
                raise RuntimeError(f"camera_image_fov_mismatch:{name}:{fov}")
            from ultimate_pipeline.perception.environment.camera_intrinsics import native_carla_intrinsics
            k_actual = native_carla_intrinsics(width, height, fov)["K"]
            path = frame_dir / f"{name}.png"
            data.save_to_disk(str(path))
            raw_path = frame_dir / f"{name}.bgra"
            raw_bytes = bytes(getattr(data, "raw_data", b""))
            if not raw_bytes or len(raw_bytes) != width * height * 4:
                raise RuntimeError(f"camera_raw_frame_invalid:{name}:{len(raw_bytes)}")
            raw_path.write_bytes(raw_bytes)
            measurements[name] = {
                "kind": "camera", "frame_id": frame_id, "timestamp": timestamp,
                "width": width, "height": height, "fov_deg": fov,
                "K_effective": k_actual, "path": path.relative_to(output_dir).as_posix(),
                "image_sha256": _sha_file(path),
                "raw_path": raw_path.relative_to(output_dir).as_posix(),
                "raw_sha256": _sha_file(raw_path),
                "sensor_actor_id": int(wrapped.actor.id),
            }
        else:
            path = frame_dir / f"{name}.bin"
            raw = bytes(getattr(data, "raw_data", b""))
            if not raw:
                raise RuntimeError(f"lidar_frame_empty:{name}:{frame_id}")
            path.write_bytes(raw)
            measurements[name] = {
                "kind": "lidar", "frame_id": frame_id, "timestamp": timestamp,
                "path": path.relative_to(output_dir).as_posix(),
                "data_sha256": _sha_file(path), "sensor_actor_id": int(wrapped.actor.id),
                "point_count": len(raw) // 16,
            }
    timestamps = [float(value["timestamp"]) for value in measurements.values()]
    if max(timestamps) - min(timestamps) > 1e-6:
        raise RuntimeError(f"sensor_timestamp_mismatch:{frame_id}:{max(timestamps)-min(timestamps)}")
    return {"world_frame_id": frame_id, "timestamp": timestamps[0], "sensors": measurements}


def _verify_spawned_mounts(carla: Any, ego: Any, spawned: Mapping[str, Any]) -> Dict[str, Any]:
    ego_transform = ego.get_transform()
    results: Dict[str, Any] = {}
    for name, wrapped in spawned.items():
        relative = dict(wrapped.report.get("carla_transform") or {})
        if not relative:
            raise RuntimeError(f"sensor_attachment_transform_missing:{name}")
        rel_tf = carla.Transform(
            carla.Location(x=float(relative["x"]), y=float(relative["y"]), z=float(relative["z"])),
            carla.Rotation(roll=float(relative["roll"]), pitch=float(relative["pitch"]), yaw=float(relative["yaw"])),
        )
        expected = ego_transform * rel_tf
        actual = wrapped.actor.get_transform()
        def pose(transform: Any) -> Dict[str, Any]:
            return {
                "location": {key: float(getattr(transform.location, key)) for key in ("x", "y", "z")},
                "rotation": {key: float(getattr(transform.rotation, key)) for key in ("roll", "pitch", "yaw")},
            }
        error = transform_error(pose(expected), pose(actual))
        if (error["translation_m"] > ATTACHMENT_TRANSLATION_TOLERANCE_M
                or error["max_angle_deg"] > ATTACHMENT_ANGLE_TOLERANCE_DEG):
            raise RuntimeError(f"sensor_attachment_transform_mismatch:{name}:{error}")
        parent = None
        try:
            parent = wrapped.actor.get_parent()
        except Exception:
            parent = getattr(wrapped.actor, "parent", None)
        if parent is None or int(getattr(parent, "id", -1)) != int(ego.id):
            raise RuntimeError(f"sensor_parent_mismatch:{name}")
        results[name] = {
            "expected_world_transform": pose(expected),
            "observed_world_transform": pose(actual),
            "residual": error,
            "parent_actor_id": int(parent.id),
            "verdict": "PASS",
        }
    return results


def run_live(args: argparse.Namespace) -> int:
    """Run one bounded CARLA capture and write source-bound evidence."""
    from ultimate_pipeline.perception.environment.calibration_lifecycle import CalibrationCleanupGuard
    from ultimate_pipeline.perception.environment.intrinsic_receipt import (
        build_calibration_receipt, write_calibration_receipt,
    )
    from ultimate_pipeline.sensors.canonical_lidar_spec import resolve_active_lidars
    from ultimate_pipeline.carla_tools.safe_spawn_ego import safe_spawn_ego
    from ultimate_pipeline.carla_tools.thesis_sensor_rig import ThesisSensorRig

    out = Path(args.output).resolve()
    repository_root = Path(__file__).resolve().parents[2]
    try:
        out.relative_to(repository_root)
    except ValueError:
        pass
    else:
        raise ValueError("runtime_output_must_be_outside_source_repository")
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"runtime_output_not_empty:{out}")
    dataset_dir = out / "captured_dataset"
    out.mkdir(parents=True, exist_ok=True)
    payload = Path(args.calibration).resolve(strict=True).read_bytes()
    calibration = json.loads(payload.decode("utf-8"))
    camera_names, _ = _sensor_name_set(calibration)
    active_lidar_names = {spec.name for spec in resolve_active_lidars(calibration, low_memory_profile=False)}
    report: Dict[str, Any] = {
        "schema": "LIVE_CAMERA_INTRINSIC_ACCEPTANCE/v1",
        "live_status": "NOT_RUN",
        "calibration_sha256": hashlib.sha256(payload).hexdigest(),
        "camera_names_expected": sorted(camera_names),
        "active_lidar_names_expected": sorted(active_lidar_names),
        "attachment_tolerances": {
            "translation_m": ATTACHMENT_TRANSLATION_TOLERANCE_M,
            "angle_deg": ATTACHMENT_ANGLE_TOLERANCE_DEG,
        },
        "exact_intrinsic_compliance": False,
        "independent_rendered_frame_verification": "PENDING",
    }
    try:
        import carla  # type: ignore
    except Exception as exc:
        report.update(live_status="BLOCKED_EXTERNAL", blocker=f"carla_python_api_unavailable:{exc}")
        (out / "live_camera_intrinsic_status.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 3

    try:
        client = carla.Client(args.host, args.port)
        client.set_timeout(args.timeout)
        server_version = str(client.get_server_version())
    except Exception as exc:
        report.update(live_status="BLOCKED_EXTERNAL", blocker=f"CARLA_RPC_unavailable:{type(exc).__name__}:{exc}")
        (out / "live_camera_intrinsic_status.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 3
    report["server_version"] = server_version
    if not server_version.startswith("0.9.16"):
        report.update(live_status="BLOCKED_EXTERNAL", blocker=f"CARLA_0_9_16_required:{server_version}")
        (out / "live_camera_intrinsic_status.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 3

    world = client.get_world()
    map_name = str(world.get_map().name)
    report["map_name"] = map_name
    if map_name != str(args.expected_map):
        report.update(live_status="FAIL", blocker=f"map_identity_mismatch:{map_name}!={args.expected_map}")
        (out / "live_camera_intrinsic_status.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 2
    weather_obj = world.get_weather()
    weather = {
        key: float(getattr(weather_obj, key))
        for key in (
            "cloudiness", "precipitation", "precipitation_deposits", "wind_intensity",
            "sun_azimuth_angle", "sun_altitude_angle", "fog_density", "fog_distance",
            "fog_falloff", "wetness",
        )
        if hasattr(weather_obj, key)
    }
    old_settings = world.get_settings()
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = float(args.fixed_delta_seconds)
    world.apply_settings(settings)
    guard = CalibrationCleanupGuard(world, out_dir=out)
    spawned: Dict[str, Any] = {}
    try:
        with guard:
            ego, ego_report = safe_spawn_ego(
                world, spawn_index=args.spawn_index, z_offset=args.z_offset,
                report_path=str(out / "ego_spawn_report.json"),
            )
            if ego is None:
                raise RuntimeError("ego_spawn_failed")
            guard.track_ego(ego)
            rig = ThesisSensorRig(args.calibration)
            rig.set_client(client)
            spawned = rig.spawn_rig(world, ego)
            for wrapped in spawned.values():
                guard.track_sensor(wrapped.actor)
            mount_checks = _verify_spawned_mounts(carla, ego, spawned)
            actual_cameras = {name for name, sp in spawned.items()
                              if "camera" in str(getattr(sp.actor, "type_id", ""))}
            actual_lidars = {name for name, sp in spawned.items()
                             if "lidar" in str(getattr(sp.actor, "type_id", ""))}
            if actual_cameras != camera_names:
                raise RuntimeError(f"camera_sensor_set_mismatch:{sorted(actual_cameras)}")
            if actual_lidars != active_lidar_names:
                raise RuntimeError(f"active_lidar_sensor_set_mismatch:{sorted(actual_lidars)}")
            dataset_dir.mkdir(parents=True, exist_ok=False)
            frame_records = []
            queues = _start_sensor_listeners(spawned)
            try:
                for _ in range(int(args.frames)):
                    frame_records.append(_record_one_frame(
                        world, spawned, queues, dataset_dir, args.sensor_timeout
                    ))
            finally:
                _stop_sensor_listeners(spawned)
            if not frame_records:
                raise RuntimeError("zero_frames_captured")

            sensor_identity = {"cameras": {}, "lidars": {}}
            effective_k: Dict[str, Any] = {}
            intrinsic_artifacts: Dict[str, Any] = {}
            from ultimate_pipeline.perception.environment.camera_intrinsics import (
                camera_intrinsic_realization, write_effective_intrinsics_artifacts,
            )
            for name, wrapped in spawned.items():
                record = frame_records[-1]["sensors"][name]
                try:
                    parent = wrapped.actor.get_parent()
                except Exception:
                    parent = getattr(wrapped.actor, "parent", None)
                if parent is None:
                    raise RuntimeError(f"sensor_parent_unavailable:{name}")
                sensor_payload = {
                    "actor_id": int(wrapped.actor.id),
                    "type_id": str(wrapped.actor.type_id),
                    "parent_id": int(parent.id),
                    "report": wrapped.report,
                    "mount_check": mount_checks[name],
                }
                if record["kind"] == "camera":
                    sensor_identity["cameras"][name] = sensor_payload
                    effective_k[name] = record["K_effective"]
                    target_k = wrapped.report["intrinsic_realization"]["K_target"]
                    measured = camera_intrinsic_realization(
                        name, target_k, record["width"], record["height"],
                        fov_deg=record["fov_deg"], k_override=record["K_effective"],
                    )
                    intrinsic_artifacts[name] = write_effective_intrinsics_artifacts(
                        str(dataset_dir / "effective_intrinsics"), measured,
                        remap_applied=False,
                    )
                else:
                    sensor_identity["lidars"][name] = sensor_payload
            report.update({
                "live_status": "CAPTURED_PENDING_REPROJECTION",
                "map_name": str(world.get_map().name),
                "ego_actor_id": int(ego.id),
                "ego_spawn_report": ego_report,
                "world_settings": {
                    "synchronous_mode": bool(settings.synchronous_mode),
                    "fixed_delta_seconds": settings.fixed_delta_seconds,
                },
                "weather": weather,
                "sensor_identity": sensor_identity,
                "attachment_checks": mount_checks,
                "effective_intrinsic_artifacts": intrinsic_artifacts,
                "frames": frame_records,
            })
            if args.annotations:
                annotation_bytes = Path(args.annotations).resolve(strict=True).read_bytes()
                annotations = json.loads(annotation_bytes.decode("utf-8"))
                (dataset_dir / "landmark_observations.json").write_bytes(annotation_bytes)
                report["camera_reprojection"] = score_camera_annotations(
                    calibration=calibration,
                    capture_frames={
                        str(frame["world_frame_id"]): frame["sensors"]
                        for frame in frame_records
                    },
                    annotations=annotations,
                )
                report["lidar_camera_correspondence"] = score_lidar_camera_annotations(
                    calibration=calibration,
                    capture_frames={
                        str(frame["world_frame_id"]): frame["sensors"]
                        for frame in frame_records
                    },
                    annotations=annotations,
                    dataset_root=dataset_dir,
                )
            else:
                report["camera_reprojection"] = {
                    "verdict": "BLOCKED_EXTERNAL",
                    "reason": "independent_rendered_landmark_annotations_required",
                }
                report["lidar_camera_correspondence"] = {
                    "verdict": "BLOCKED_EXTERNAL",
                    "reason": "frame_bound_lidar_camera_correspondence_annotations_required",
                }
            from ultimate_pipeline.perception.environment.intrinsic_receipt import current_source_identity
            source_identity = current_source_identity(repository_root)
            capture_manifest = {
                "schema": "LIVE_CAMERA_CAPTURE_MANIFEST/v1",
                "calibration_sha256": report["calibration_sha256"],
                "source_commit": source_identity["commit"],
                "source_tree_clean": source_identity["working_tree_clean"],
                "server_version": server_version,
                "client_version": str(client.get_client_version()),
                "map_name": report["map_name"],
                "ego_actor_id": report["ego_actor_id"],
                "world_settings": report["world_settings"],
                "weather": report["weather"],
                "sensor_identity": sensor_identity,
                "attachment_checks": mount_checks,
                "frames": frame_records,
                "camera_reprojection": report["camera_reprojection"],
                "lidar_camera_correspondence": report["lidar_camera_correspondence"],
                "annotations_sha256": (
                    hashlib.sha256(annotation_bytes).hexdigest()
                    if args.annotations else None
                ),
            }
            (dataset_dir / "capture_manifest.json").write_text(
                json.dumps(capture_manifest, indent=2, sort_keys=True), encoding="utf-8"
            )
            receipt = build_calibration_receipt(
                calibration_path=args.calibration,
                repository_root=repository_root,
                effective_intrinsics=effective_k,
                sensor_identity=sensor_identity,
                runtime_settings={
                    "server_version": server_version,
                    "map_name": report["map_name"],
                    **report["world_settings"],
                    "weather": report["weather"],
                    "client_version": str(client.get_client_version()),
                    "sensor_timeout_s": float(args.sensor_timeout),
                },
                dataset_root=dataset_dir,
            )
            write_calibration_receipt(out / "calibration_receipt.json", receipt)
            report["calibration_receipt_sha256"] = receipt["receipt_sha256"]
            report["exact_intrinsic_compliance"] = False
            camera_ok = report["camera_reprojection"].get("verdict") == "ANNOTATION_RESIDUAL_PASS"
            lidar_ok = report["lidar_camera_correspondence"].get("verdict") == "ANNOTATION_RESIDUAL_PASS"
            if camera_ok and lidar_ok:
                report["live_status"] = "PENDING_INDEPENDENT_REVIEW"
            elif (report["camera_reprojection"].get("verdict") == "ANNOTATION_RESIDUAL_FAIL"
                  or report["lidar_camera_correspondence"].get("verdict") == "ANNOTATION_RESIDUAL_FAIL"):
                report["live_status"] = "FAIL"
            else:
                report["live_status"] = "BLOCKED_EXTERNAL"
    except Exception as exc:
        report.update(live_status="FAIL", failure=f"{type(exc).__name__}:{exc}")
    finally:
        try:
            world.apply_settings(old_settings)
            report["world_settings_restored"] = True
        except Exception as exc:
            report["world_settings_restored"] = False
            report.setdefault("cleanup_errors", []).append(f"world_settings_restore:{exc}")
    path = out / "live_camera_intrinsic_status.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return 0 if report.get("live_status") == "PENDING_INDEPENDENT_REVIEW" else 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-map", required=True,
                        help="Exact CARLA world.get_map().name expected for this run")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--sensor-timeout", type=float, default=5.0)
    parser.add_argument("--fixed-delta-seconds", type=float, default=0.05)
    parser.add_argument("--frames", type=int, default=10)
    parser.add_argument("--spawn-index", type=int, default=0)
    parser.add_argument("--z-offset", type=float, default=0.5)
    parser.add_argument("--annotations", help="JSON of manually measured, capture-frame-bound 3D/2D landmarks")
    args = parser.parse_args(argv)
    if args.frames <= 0 or args.sensor_timeout <= 0 or args.fixed_delta_seconds <= 0:
        parser.error("frames and timeout values must be positive")
    return run_live(args)


if __name__ == "__main__":
    raise SystemExit(main())
