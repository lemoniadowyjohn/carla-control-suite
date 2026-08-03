from __future__ import annotations

import json
import math
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from ultimate_pipeline.sensors.transform_conventions import (
    camera_attachment_pose_from_cTv,
    lidar_attachment_pose_from_vTl,
)

# Import-safe: carla is only imported inside spawn functions


def _clamp_int(value: int, *, min_value: int, max_value: int) -> int:
    return max(min_value, min(max_value, int(value)))


def _get_env_int(env: Dict[str, str], key: str) -> Optional[int]:
    raw = env.get(key)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return int(str(raw).strip())
    except Exception:
        return None


def compute_lidar_attributes(*, low_mem: bool, env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """
    Compute LiDAR attributes, optionally downscaled for low-mem GPUs.

    Environment overrides:
      - UP_LIDAR_CHANNELS
      - UP_LIDAR_PPS
      - UP_LIDAR_HZ
    """
    env = dict(os.environ if env is None else env)

    # Defaults (kept compatible with existing semantics unless low_mem=True)
    if low_mem:
        channels = 32
        pps = 200_000
        hz = 10
        channels_max = 32
        pps_max = 200_000
        hz_max = 10
    else:
        channels = 64
        pps = 1_300_000
        hz = 20
        channels_max = 128
        pps_max = 5_000_000
        hz_max = 30

    # Apply env overrides (then clamp)
    channels_env = _get_env_int(env, "UP_LIDAR_CHANNELS")
    pps_env = _get_env_int(env, "UP_LIDAR_PPS")
    hz_env = _get_env_int(env, "UP_LIDAR_HZ")
    if channels_env is not None:
        channels = channels_env
    if pps_env is not None:
        pps = pps_env
    if hz_env is not None:
        hz = hz_env

    channels = _clamp_int(channels, min_value=1, max_value=channels_max)
    pps = _clamp_int(pps, min_value=1_000, max_value=pps_max)
    hz = _clamp_int(hz, min_value=1, max_value=hz_max)

    return {
        "rotation_frequency": str(int(hz)),
        "channels": str(int(channels)),
        "points_per_second": str(int(pps)),
    }


def _sanitize_transform_dict(raw: Dict[str, float]) -> Tuple[Dict[str, float], List[str]]:
    defaults = {"x": 0.0, "y": 0.0, "z": 1.8, "roll": 0.0, "pitch": 0.0, "yaw": 0.0}
    clamped: List[str] = []
    sanitized: Dict[str, float] = {}
    for k, default in defaults.items():
        v = raw.get(k, default)
        try:
            v = float(v)
        except Exception:
            v = default
            clamped.append(k)
        else:
            if not math.isfinite(v):
                v = default
                clamped.append(k)
        sanitized[k] = v
    return sanitized, clamped


def _bounded_sensor_spawn_ticks() -> int:
    try:
        n = int(str(os.environ.get("UP_SENSOR_SPAWN_TICK", "1")).strip())
    except Exception:
        n = 1
    return _clamp_int(n, min_value=0, max_value=10)


def _bounded_sensor_spawn_tick_timeout_s() -> float:
    raw = os.environ.get("UP_SENSOR_SPAWN_TICK_TIMEOUT_S", "2.0")
    try:
        timeout_s = float(str(raw).strip())
    except Exception:
        timeout_s = 2.0
    return max(0.2, min(30.0, float(timeout_s)))


def _bounded_sensor_spawn_actor_timeout_s() -> float:
    raw = os.environ.get("UP_SENSOR_SPAWN_ACTOR_TIMEOUT_S", "1.5")
    try:
        timeout_s = float(str(raw).strip())
    except Exception:
        timeout_s = 1.5
    return max(0.2, min(30.0, float(timeout_s)))


def _call_with_timeout(fn, *, timeout_s: float) -> Any:
    state: Dict[str, Any] = {"done": False, "result": None, "error": None}

    def _runner() -> None:
        try:
            state["result"] = fn()
        except Exception as exc:  # pragma: no cover - CARLA runtime dependent
            state["error"] = exc
        finally:
            state["done"] = True

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout=max(0.2, float(timeout_s)))
    if t.is_alive():
        raise RuntimeError(f"spawn_timeout_after_{float(timeout_s):.3f}s")
    if state.get("error") is not None:
        raise state["error"]  # type: ignore[misc]
    return state.get("result")


def _tick_once_bounded(world, *, sync: bool, timeout_s: float) -> bool:
    result: Dict[str, Any] = {"ok": False}

    def _runner() -> None:
        try:
            if sync:
                world.tick(float(timeout_s))
            else:
                world.wait_for_tick(float(timeout_s))
            result["ok"] = True
        except Exception:
            result["ok"] = False

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout=max(0.2, float(timeout_s) + 0.2))
    return bool(result.get("ok", False))


def _tick_between_spawns(world, *, n: int) -> None:
    if n <= 0:
        return
    tick_timeout_s = _bounded_sensor_spawn_tick_timeout_s()
    try:
        settings = world.get_settings()
        sync = bool(getattr(settings, "synchronous_mode", False))
    except Exception:
        sync = True

    for _ in range(int(n)):
        if _tick_once_bounded(world, sync=bool(sync), timeout_s=float(tick_timeout_s)):
            continue
        if _tick_once_bounded(world, sync=False, timeout_s=float(tick_timeout_s)):
            continue
        return


def _matrix_to_transform(mat: np.ndarray) -> Dict[str, float]:
    """Convert 4x4 homogeneous transform to CARLA-style dict {x,y,z,roll,pitch,yaw}.

    Rotation: uses ZYX Euler convention (yaw-pitch-roll) to match CARLA.
    """
    # Extract translation
    x, y, z = float(mat[0, 3]), float(mat[1, 3]), float(mat[2, 3])

    # Extract rotation matrix (3x3 upper-left)
    R = mat[:3, :3]

    # ZYX Euler angles (yaw, pitch, roll) extraction
    # R = Rz(yaw) * Ry(pitch) * Rx(roll)
    sy = math.sqrt(R[0, 0] ** 2 + R[1, 0] ** 2)
    singular = sy < 1e-6

    if not singular:
        roll = math.atan2(R[2, 1], R[2, 2])
        pitch = math.atan2(-R[2, 0], sy)
        yaw = math.atan2(R[1, 0], R[0, 0])
    else:
        roll = math.atan2(-R[1, 2], R[1, 1])
        pitch = math.atan2(-R[2, 0], sy)
        yaw = 0.0

    # Convert radians to degrees for CARLA
    roll_deg = math.degrees(roll)
    pitch_deg = math.degrees(pitch)
    yaw_deg = math.degrees(yaw)

    return {"x": x, "y": y, "z": z, "roll": roll_deg, "pitch": pitch_deg, "yaw": yaw_deg}


def _invert_transform(mat: np.ndarray) -> np.ndarray:
    """Invert a 4x4 homogeneous transformation matrix."""
    return np.linalg.inv(mat)


def _fov_from_intrinsics_fx(fx: float, image_width: int) -> float:
    """Calculate horizontal FOV in degrees from fx and image width."""
    fov_rad = 2.0 * math.atan(float(image_width) / (2.0 * float(fx)))
    return math.degrees(fov_rad)


def _parse_image_size(value: Any) -> Tuple[int, int]:
    """Support both schema variants seen in this repo:
      - [w, h]
      - {"width": w, "height": h}
    """
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return int(value[0]), int(value[1])
    if isinstance(value, dict):
        if "width" in value and "height" in value:
            return int(value["width"]), int(value["height"])
    # Fallback
    return 1920, 1080


@dataclass
class SensorSpec:
    name: str
    type: str
    transform: Dict[str, float]
    attributes: Dict[str, str]


class DominikSensorSetup:
    """
    Sensor rig builder based on Dominik's calibration JSON.

    Thesis contracts implemented here:
    - Use K_undistortion only (ignore K and D).
    - Camera extrinsics: cTv is vehicle->camera; for CARLA attachment use inverse(cTv).
    - LiDAR extrinsics: vTl is lidar->vehicle; invert for CARLA attachment.
    - Axis convention mismatch: legacy behavior flips translation Y only (kept by default).
    """

    def __init__(
        self,
        calib_json_path: str,
        *,
        flip_vehicle_y: bool = True,
        opencv_camera_axes: bool = True,
        lidar_axes_mode: str = "auto",
        verbose: bool = False,
        resolution_override: Optional[Tuple[int, int]] = None,
    ):
        self.calib_path = Path(calib_json_path)
        if not self.calib_path.exists():
            raise FileNotFoundError(f"Calibration JSON not found: {self.calib_path}")

        self.flip_vehicle_y = bool(flip_vehicle_y)
        self.opencv_camera_axes = bool(opencv_camera_axes)
        self.lidar_axes_mode = str(lidar_axes_mode)
        self.verbose = bool(verbose)
        self.resolution_override = resolution_override

        self._calib = json.loads(self.calib_path.read_text(encoding="utf-8"))

    def _camera_attributes(self, *, fov: float, image_width: int, image_height: int) -> Dict[str, str]:
        w, h = image_width, image_height
        if self.resolution_override is not None:
            w, h = self.resolution_override
        return {
            "fov": str(round(float(fov), 2)),
            "image_size_x": str(int(w)),
            "image_size_y": str(int(h)),
        }

    def _parse_camera_transform(self, cam_data: Dict) -> Dict[str, float]:
        """Parse cTv matrix for CARLA attachment using canonical conventions.

        Thesis contract: cTv is vehicle->camera and MUST NOT be inverted.
        """
        cTv = np.array(cam_data["cTv"], dtype=np.float64)
        pose = camera_attachment_pose_from_cTv(
            cTv,
            flip_vehicle_y=self.flip_vehicle_y,
            opencv_camera_axes=self.opencv_camera_axes,
            ctv_invert=False,  # Enforce thesis invariant: no inversion
        )
        # Return flat dict for _sanitize_transform_dict consumption
        return {
            "x": float(pose["x"]),
            "y": float(pose["y"]),
            "z": float(pose["z"]),
            "roll": float(pose["roll"]),
            "pitch": float(pose["pitch"]),
            "yaw": float(pose["yaw"]),
        }

    def _parse_lidar_transform(self, lidar_data: Dict) -> Dict[str, float]:
        """Parse LiDAR transform using canonical conventions.

        vTl transforms points from LiDAR frame to Vehicle frame (LiDAR -> Vehicle).
        Standard CARLA attachment requires vehicle -> LiDAR (inverse(vTl)).
        """
        vTl = np.array(lidar_data["vTl"], dtype=np.float64)
        pose = lidar_attachment_pose_from_vTl(vTl, flip_vehicle_y=self.flip_vehicle_y)
        return {
            "x": float(pose["x"]),
            "y": float(pose["y"]),
            "z": float(pose["z"]),
            "roll": float(pose["roll"]),
            "pitch": float(pose["pitch"]),
            "yaw": float(pose["yaw"]),
        }

    def _make_specs(self, include_segmentation: bool, *, low_mem: bool) -> List[SensorSpec]:
        specs: List[SensorSpec] = []

        cameras_data = self._calib.get("cameras", {})
        for cam_name, cam_data in cameras_data.items():
            # Use K_undistortion only (per thesis requirement)
            K_undist = cam_data.get("K_undistortion")
            if K_undist is None:
                continue

            orig_w, orig_h = _parse_image_size(cam_data.get("image_size", [1920, 1080]))
            out_w, out_h = (orig_w, orig_h) if self.resolution_override is None else self.resolution_override

            # Scale intrinsics if we override resolution (keeps pinhole model consistent)
            # CARLA uses horizontal FOV; derive from fx.
            fx = float(K_undist[0][0])
            if orig_w > 0:
                scale_x = float(out_w) / float(orig_w)
            else:
                scale_x = 1.0
            fx_scaled = fx * scale_x

            fov = _fov_from_intrinsics_fx(fx_scaled, out_w)

            transform = self._parse_camera_transform(cam_data)

            specs.append(
                SensorSpec(
                    name=f"rgb_{cam_name}",
                    type="sensor.camera.rgb",
                    transform=transform,
                    attributes=self._camera_attributes(fov=fov, image_width=orig_w, image_height=orig_h),
                )
            )

            if include_segmentation:
                specs.append(
                    SensorSpec(
                        name=f"seg_{cam_name}",
                        type="sensor.camera.semantic_segmentation",
                        transform=transform,
                        attributes=self._camera_attributes(fov=fov, image_width=orig_w, image_height=orig_h),
                    )
                )

        lidars_data = self._calib.get("lidars", {})
        lidar_key = "middle_lidar"
        if lidar_key in lidars_data:
            lidar_data = lidars_data[lidar_key]
            lidar_transform = self._parse_lidar_transform(lidar_data)

            specs.append(
                SensorSpec(
                    name="lidar",
                    type="sensor.lidar.ray_cast",
                    transform=lidar_transform,
                    attributes={"range": "80", **compute_lidar_attributes(low_mem=bool(low_mem))},
                )
            )

        return specs

    def spawn_on_vehicle(
        self,
        world,
        vehicle,
        *,
        include_segmentation: bool = False,
        out_dir: Optional[str] = None,
        low_mem: Optional[bool] = None,
        strict: bool = True,
        min_sensors: int = 0,
    ):
        import carla  # lazy import

        low_mem_resolved = bool(self.resolution_override is not None) if low_mem is None else bool(low_mem)
        specs = self._make_specs(bool(include_segmentation), low_mem=low_mem_resolved)
        bp_lib = world.get_blueprint_library()
        actors: Dict[str, Any] = {}
        spawn_actor_timeout_s = _bounded_sensor_spawn_actor_timeout_s()

        sensor_spawn_tick = _bounded_sensor_spawn_ticks()
        report: Dict[str, Any] = {
            "schema_version": 2,
            "low_mem": bool(low_mem_resolved),
            "strict": bool(strict),
            "min_sensors": int(min_sensors),
            "sensor_spawn_tick": int(sensor_spawn_tick),
            "rig_contract": {
                "camera_intrinsics": "K_undistortion_only",
                "camera_extrinsics": "cTv_inverted_for_attachment",
                "lidar_extrinsics": "vTl_inverted_for_attachment",
                "axis_handling": "legacy_translation_y_flip" if self.flip_vehicle_y else "none",
                "resolution_override": list(self.resolution_override) if self.resolution_override else None,
            },
            "env": {
                "UP_SENSOR_SPAWN_TICK": os.environ.get("UP_SENSOR_SPAWN_TICK"),
                "UP_LIDAR_CHANNELS": os.environ.get("UP_LIDAR_CHANNELS"),
                "UP_LIDAR_PPS": os.environ.get("UP_LIDAR_PPS"),
                "UP_LIDAR_HZ": os.environ.get("UP_LIDAR_HZ"),
            },
            "sensors": [],
        }

        for spec in specs:
            entry: Dict[str, Any] = {
                "name": spec.name,
                "type": spec.type,
                "attributes_requested": dict(spec.attributes),
                "success": False,
                "exception": None,
            }
            try:
                bp = bp_lib.find(spec.type)
                entry["blueprint_id"] = getattr(bp, "id", spec.type)

                applied: Dict[str, str] = {}
                unsupported: List[str] = []
                for k, v in spec.attributes.items():
                    if not bp.has_attribute(k):
                        unsupported.append(k)
                        continue
                    try:
                        bp.set_attribute(k, str(v))
                        applied[k] = str(v)
                    except Exception as attr_exc:
                        entry.setdefault("attribute_errors", []).append({"key": k, "value": str(v), "error": str(attr_exc)})

                entry["attributes_applied"] = applied
                entry["attributes_unsupported"] = unsupported

                tf_dict, clamped_keys = _sanitize_transform_dict(spec.transform)
                entry["transform"] = {
                    "location": {"x": tf_dict["x"], "y": tf_dict["y"], "z": tf_dict["z"]},
                    "rotation": {"roll": tf_dict["roll"], "pitch": tf_dict["pitch"], "yaw": tf_dict["yaw"]},
                }
                if clamped_keys:
                    entry["transform_clamped_keys"] = list(clamped_keys)

                if spec.type.startswith("sensor.lidar"):
                    entry["key_attributes"] = {
                        "channels": spec.attributes.get("channels"),
                        "points_per_second": spec.attributes.get("points_per_second"),
                        "rotation_frequency": spec.attributes.get("rotation_frequency"),
                    }
                elif spec.type.startswith("sensor.camera"):
                    entry["key_attributes"] = {
                        "image_size_x": spec.attributes.get("image_size_x"),
                        "image_size_y": spec.attributes.get("image_size_y"),
                        "fov": spec.attributes.get("fov"),
                    }

                tf = carla.Transform(
                    carla.Location(x=tf_dict["x"], y=tf_dict["y"], z=tf_dict["z"]),
                    carla.Rotation(roll=tf_dict["roll"], pitch=tf_dict["pitch"], yaw=tf_dict["yaw"]),
                )

                actor = None
                try:
                    actor = _call_with_timeout(
                        lambda: world.try_spawn_actor(bp, tf, attach_to=vehicle),
                        timeout_s=float(spawn_actor_timeout_s),
                    )
                except Exception as spawn_exc:
                    entry["exception"] = str(spawn_exc)
                    actor = None

                entry["try_spawn_actor_returned"] = actor is not None
                if actor is not None:
                    actors[spec.name] = actor
                    entry["success"] = True
                    entry["actor_id"] = getattr(actor, "id", None)

            except Exception as exc:
                entry["exception"] = str(exc)
            finally:
                report["sensors"].append(entry)
                _tick_between_spawns(world, n=sensor_spawn_tick)

        report["summary"] = {
            "attempted": len(specs),
            "spawned": len(actors),
            "missing": sorted([s.name for s in specs if s.name not in actors]),
        }

        missing = list(report["summary"]["missing"])
        degraded_mode = False
        degraded_reason = None
        if low_mem_resolved and "lidar" in missing:
            degraded_mode = True
            degraded_reason = "lidar_spawn_failed_in_low_mem"
            missing = [m for m in missing if m != "lidar"]
            report["summary"]["missing"] = list(missing)

        report["degraded_mode"] = degraded_mode
        if degraded_reason:
            report["degraded_reason"] = degraded_reason

        min_req = int(min_sensors) if int(min_sensors) > 0 else 0
        min_violation = bool(min_req) and (len(actors) < min_req)
        report["summary"]["min_sensors_ok"] = (not min_violation)
        report["summary"]["min_sensors_required"] = int(min_req)

        if out_dir is not None:
            out_path = Path(out_dir)
            out_path.mkdir(parents=True, exist_ok=True)
            (out_path / "sensor_spawn_report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

        fatal = bool(min_violation) or (bool(missing) and bool(strict))
        if fatal:
            for a in list(actors.values()):
                try:
                    if hasattr(a, "stop"):
                        a.stop()
                except Exception:
                    pass
                try:
                    a.destroy()
                except Exception:
                    pass

            if min_violation:
                raise RuntimeError(f"Spawned {len(actors)} sensors, below min_sensors={min_req}. Missing={missing}")
            raise RuntimeError(f"Failed to spawn sensors: {missing}")
        return actors

    @staticmethod
    def validate_sensor_geometry(world, vehicle, sensors: Dict) -> Dict:
        """Minimal sanity check: verify a front camera sees forward direction (geometry-only)."""
        import carla  # lazy import

        result = {"valid": False, "checks": [], "errors": []}

        front_cam = None
        front_cam_name = None
        for name, actor in sensors.items():
            if "front" in name.lower() and "rgb" in name.lower():
                front_cam = actor
                front_cam_name = name
                break

        if front_cam is None:
            result["errors"].append("No front camera found for validation")
            return result

        try:
            veh_tf = vehicle.get_transform()
            veh_loc = veh_tf.location
            veh_fwd = veh_tf.get_forward_vector()

            cam_tf = front_cam.get_transform()
            cam_loc = cam_tf.location
            cam_fwd = cam_tf.get_forward_vector()

            dist_to_vehicle = math.sqrt((cam_loc.x - veh_loc.x) ** 2 + (cam_loc.y - veh_loc.y) ** 2 + (cam_loc.z - veh_loc.z) ** 2)
            check1 = dist_to_vehicle < 5.0
            result["checks"].append({"name": "camera_attached", "passed": check1, "distance_m": round(dist_to_vehicle, 3)})

            dot_fwd = veh_fwd.x * cam_fwd.x + veh_fwd.y * cam_fwd.y + veh_fwd.z * cam_fwd.z
            check2 = dot_fwd > 0.5
            result["checks"].append({"name": "camera_facing_forward", "passed": check2, "dot_product": round(dot_fwd, 3)})

            ref_point = carla.Location(x=veh_loc.x + veh_fwd.x * 10.0, y=veh_loc.y + veh_fwd.y * 10.0, z=veh_loc.z)
            vec_to_ref = carla.Vector3D(x=ref_point.x - cam_loc.x, y=ref_point.y - cam_loc.y, z=ref_point.z - cam_loc.z)
            dot_ref = cam_fwd.x * vec_to_ref.x + cam_fwd.y * vec_to_ref.y + cam_fwd.z * vec_to_ref.z
            check3 = dot_ref > 0
            result["checks"].append({"name": "ref_point_in_front", "passed": check3, "dot_product": round(dot_ref, 3)})

            result["valid"] = check1 and check2 and check3
            result["camera_name"] = front_cam_name
            result["camera_pose"] = {"x": round(cam_loc.x, 3), "y": round(cam_loc.y, 3), "z": round(cam_loc.z, 3)}
            result["vehicle_pose"] = {"x": round(veh_loc.x, 3), "y": round(veh_loc.y, 3), "z": round(veh_loc.z, 3)}

        except Exception as e:
            result["errors"].append(str(e))

        return result
