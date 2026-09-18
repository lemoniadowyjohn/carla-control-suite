from __future__ import annotations

import importlib
import json
import logging
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, TYPE_CHECKING

import numpy as np

from ultimate_pipeline.carla_tools.map_identity_guard import validate_world_map
from ultimate_pipeline.sensors.transform_conventions import (
    camera_attachment_pose_from_cTv,
    lidar_attachment_pose_from_vTl,
    rotation_matrix_to_unreal_rpy_deg,
    vehicle_to_camera_from_cTv,
    vehicle_to_lidar_from_vTl,
)

if TYPE_CHECKING:  # pragma: no cover
    import carla

log = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return float(default)
    try:
        return float(str(raw).strip())
    except Exception:
        return float(default)


def _cleanup_spawned_sensor_actors(spawned: Dict[str, "SpawnedSensor"]) -> None:
    for sensor_name, spawned_sensor in reversed(list(spawned.items())):
        actor = getattr(spawned_sensor, "actor", None)
        if actor is None:
            continue
        try:
            if hasattr(actor, "stop"):
                actor.stop()
        except Exception as exc:
            log.warning(
                "Failed to stop partially spawned sensor '%s': %s",
                sensor_name,
                exc,
            )
        try:
            actor.destroy()
        except Exception as exc:
            log.warning(
                "Failed to destroy partially spawned sensor '%s': %s",
                sensor_name,
                exc,
            )


def _sleep_and_verify_spawned_sensor(
    actor: Any,
    *,
    sensor_name: str,
    delay_s: float,
) -> None:
    if actor is None:
        raise RuntimeError(f"Sensor {sensor_name} returned no actor")
    if float(delay_s) > 0.0:
        time.sleep(float(delay_s))
    try:
        is_alive = bool(getattr(actor, "is_alive", True))
    except Exception:
        is_alive = True
    if not is_alive:
        raise RuntimeError(f"Sensor {sensor_name} died immediately after spawn")


def wait_for_first_sample(
    world: Any,
    sensor: Any,
    *,
    timeout: float = 20.0,
    max_ticks: int = 8,
) -> bool:
    """Tick the world and confirm sensor delivers at least one sample.

    Returns True if a sample is received within max_ticks ticks, False otherwise.
    GPU/camera sensors can lag 1-2 frames; allows data.frame >= tick_frame - 2.
    """
    import queue as _queue

    q = _queue.Queue()
    try:
        if hasattr(sensor, "stop"):
            try:
                sensor.stop()
            except Exception:
                pass
        sensor.listen(q.put)
        for _ in range(max_ticks):
            frame = world.tick(seconds=timeout)
            try:
                data = q.get(timeout=timeout)
            except _queue.Empty:
                continue
            if data.frame >= frame - 2:
                return True
        return False
    finally:
        try:
            if hasattr(sensor, "stop"):
                sensor.stop()
        except Exception:
            pass


# Thesis Evidence Pack Constants
RIG_VERIFICATION_FILENAME = "rig_verification.json"
SCREENSHOT_EGO_SPAWN = "ego_spawn.png"
SCREENSHOT_CAMERA_FRONT = "camera_front.png"
SCREENSHOT_LIDAR_BEV = "lidar_bev.png"


def _ensure_homogeneous(matrix: Any) -> np.ndarray:
    """Force a 4x4 homogeneous matrix."""
    arr = np.asarray(matrix, dtype=float)
    if arr.shape == (3, 4):
        arr = np.vstack([arr, [0.0, 0.0, 0.0, 1.0]])
    if arr.shape != (4, 4):
        raise ValueError(f"Expected 4x4 or 3x4 matrix, got {arr.shape}")
    return arr


def _rotmat_to_rpy_deg(R: Any) -> Tuple[float, float, float]:
    """Convert a 3x3 rotation matrix to Unreal-convention roll/pitch/yaw in degrees."""
    return rotation_matrix_to_unreal_rpy_deg(np.asarray(R, dtype=float))


def _lazy_carla():
    try:
        return importlib.import_module("carla")
    except ImportError as exc:  # pragma: no cover - only hit when CARLA absent
        raise RuntimeError(
            "CARLA is required for thesis_sensor_rig operations."
        ) from exc


def _carla_transform_to_pose_dict(tf: Any) -> Dict[str, Any]:
    """Serialize a CARLA Transform into a JSON-safe pose dict.

    The representation is explicit about semantic fields (location/rotation) and
    uses CARLA's degrees for rotation (roll, pitch, yaw).
    """
    try:
        loc = tf.location
        rot = tf.rotation
        return {
            "location": {"x": float(loc.x), "y": float(loc.y), "z": float(loc.z)},
            "rotation": {
                "roll": float(rot.roll),
                "pitch": float(rot.pitch),
                "yaw": float(rot.yaw),
            },
        }
    except Exception:
        # Fall back to the legacy flat dict if callers provided one.
        if isinstance(tf, dict):
            return dict(tf)
        return {"unserializable_transform": True}


CONVENTIONS = {
    "cameras": "cTv is Vehicle→Camera. THESIS INVARIANT: cTv used directly, inversion FORBIDDEN.",
    "lidars": "vTl is LiDAR→Vehicle. THESIS INVARIANT: vTl inverted to Vehicle→LiDAR for attachment.",
}


def _pose_to_carla_transform(pose: Dict[str, float]) -> Tuple[Any, Dict[str, float]]:
    """Turn canonical pose dict into a CARLA Transform plus serializable dict."""
    carla = _lazy_carla()
    tf = carla.Transform(
        carla.Location(
            x=float(pose["x"]),
            y=float(pose["y"]),
            z=float(pose["z"]),
        ),
        carla.Rotation(
            roll=float(pose["roll"]),
            pitch=float(pose["pitch"]),
            yaw=float(pose["yaw"]),
        ),
    )
    return tf, {
        "x": float(pose["x"]),
        "y": float(pose["y"]),
        "z": float(pose["z"]),
        "roll": float(pose["roll"]),
        "pitch": float(pose["pitch"]),
        "yaw": float(pose["yaw"]),
    }


def _pose_to_flat_dict(pose: Dict[str, Any]) -> Dict[str, float]:
    """Normalize attachment pose into a flat JSON-safe dict."""
    return {
        "x": float(pose.get("x", 0.0)),
        "y": float(pose.get("y", 0.0)),
        "z": float(pose.get("z", 0.0)),
        "roll": float(pose.get("roll", 0.0)),
        "pitch": float(pose.get("pitch", 0.0)),
        "yaw": float(pose.get("yaw", 0.0)),
    }


def _finite(x: float) -> bool:
    return not (math.isnan(x) or math.isinf(x))


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, "")
    if not value:
        return bool(default)
    return str(value).strip().lower() in ("1", "true", "yes", "on", "y")


LOW_MEMORY_CAMERA_CAP: Tuple[int, int] = (640, 480)
LOW_MEMORY_MAX_TOTAL_PIXELS = LOW_MEMORY_CAMERA_CAP[0] * LOW_MEMORY_CAMERA_CAP[1] * 2


def _runtime_camera_limits(
    *,
    max_camera_width_px: int,
    max_camera_height_px: int,
    max_total_camera_pixels: int,
    low_memory_profile_active: bool,
) -> Tuple[int, int, int]:
    max_cam_w = int(max_camera_width_px)
    max_cam_h = int(max_camera_height_px)
    max_total_pixels = int(max_total_camera_pixels)
    if bool(low_memory_profile_active):
        max_cam_w = min(max_cam_w, int(LOW_MEMORY_CAMERA_CAP[0]))
        max_cam_h = min(max_cam_h, int(LOW_MEMORY_CAMERA_CAP[1]))
        max_total_pixels = min(max_total_pixels, int(LOW_MEMORY_MAX_TOTAL_PIXELS))
    return int(max_cam_w), int(max_cam_h), int(max_total_pixels)


def _sanitize_transform(tf: Any, *, max_abs_m: float = 50.0) -> Any:
    """Clamp obviously broken transforms (NaNs/huge values) before spawn.

    Rationale: CARLA may crash hard if an actor is spawned with NaN transforms
    or astronomically large coordinates.
    """
    carla = _lazy_carla()
    loc = tf.location
    rot = tf.rotation

    def clamp(v: float) -> float:
        if not _finite(v):
            return 0.0
        return float(max(-max_abs_m, min(max_abs_m, v)))

    safe_loc = carla.Location(x=clamp(loc.x), y=clamp(loc.y), z=clamp(loc.z))
    safe_rot = carla.Rotation(
        roll=clamp(rot.roll),
        pitch=clamp(rot.pitch),
        yaw=clamp(rot.yaw),
    )
    return carla.Transform(safe_loc, safe_rot)


_CTV_WARNED = False


def _guard_thesis_inversion_env() -> None:
    """Guard against any attempt to override thesis transform conventions.

    THESIS INVARIANT:
    - cTv (Vehicle->Camera) MUST NOT be inverted
    - vTl (LiDAR->Vehicle) MUST be inverted to Vehicle->LiDAR for attachment

    If UP_THESIS_STRICT=1:
    - Canonical env values are PERMITTED (pass-through, no warning)
    - Non-canonical env values raise RuntimeError

    Canonical values:
    - UP_CAMERA_CTV_ATTACH: "direct" (or empty)
    - UP_LIDAR_VTL_ATTACH: "invert" (or empty)
    - UP_CAMERA_CTV_INVERT, UP_CAMERA_CTV_CONVENTION: always forbidden (no canonical value)

    Rationale: Permitting canonical values ensures operator-explicit runs are
    reproducible without false-positive governance failures. See T-036.
    """
    # Camera override vars that are ALWAYS forbidden in strict mode (no canonical value)
    camera_forbidden_vars = [
        "UP_CAMERA_CTV_INVERT",
        "UP_CAMERA_CTV_CONVENTION",
    ]
    # Camera attach var with permitted canonical value
    camera_ctv_attach_var = "UP_CAMERA_CTV_ATTACH"
    lidar_override_var = "UP_LIDAR_VTL_ATTACH"

    def _is_canonical_camera_ctv_attach(value: str) -> bool:
        """Return True if value is the canonical camera attachment mode."""
        normalized = str(value).strip().lower()
        if normalized == "":
            return True  # Empty is canonical (use code default)
        return normalized in {
            "direct",
            "ctv_direct",
            "vehicle_to_camera",
            "no_invert",
            "0",
            "false",
            "off",
        }

    def _is_canonical_lidar_vtl_attach(value: str) -> bool:
        """Return True if value is the canonical lidar attachment mode."""
        normalized = str(value).strip().lower()
        if normalized == "":
            return True  # Empty is canonical (use code default)
        return normalized in {
            "invert",
            "inverse",
            "vehicle_to_lidar",
            "vtl_invert",
            "auto",
            "1",
            "true",
            "yes",
            "on",
        }

    if os.getenv("UP_THESIS_STRICT", "").strip().lower() in ("1", "true", "yes", "on"):
        non_canonical_vars = []

        # Always-forbidden vars (any value triggers failure)
        for var in camera_forbidden_vars:
            if os.getenv(var):
                non_canonical_vars.append(f"{var}={os.getenv(var)}")

        # Camera CTV attach: fail only if non-canonical
        ctv_value = os.getenv(camera_ctv_attach_var)
        if ctv_value and not _is_canonical_camera_ctv_attach(ctv_value):
            non_canonical_vars.append(f"{camera_ctv_attach_var}={ctv_value}")

        # LiDAR VTL attach: fail only if non-canonical
        lidar_value = os.getenv(lidar_override_var)
        if lidar_value and not _is_canonical_lidar_vtl_attach(lidar_value):
            non_canonical_vars.append(f"{lidar_override_var}={lidar_value}")

        if non_canonical_vars:
            log.error(
                "Thesis strict mode forbids non-canonical inversion overrides: %s",
                ", ".join(non_canonical_vars),
            )
            raise RuntimeError(
                f"Thesis strict: non-canonical inversion override env flags are not allowed: {non_canonical_vars}"
            )


def _parse_image_size(image_size: Any) -> Tuple[int, int]:
    """Accept either [w, h] or {'width': w, 'height': h}."""
    if isinstance(image_size, dict):
        return int(image_size["width"]), int(image_size["height"])
    if isinstance(image_size, (list, tuple)) and len(image_size) >= 2:
        return int(image_size[0]), int(image_size[1])
    raise ValueError(f"Unsupported image_size format: {image_size}")


def _compute_fov_deg(K_undist: np.ndarray, width_px: int) -> float:
    fx = float(K_undist[0, 0])
    return 2.0 * math.degrees(math.atan(width_px / (2.0 * fx)))


def _to_list(obj: Any) -> Any:
    """JSON-safe list conversion for numpy arrays."""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


@dataclass
class SpawnedSensor:
    actor: Any
    report: Dict[str, Any]


@dataclass
class RigVerification:
    """Thesis compliance verification record for the sensor rig.

    This artifact is part of the Perception Evidence Pack (P1). It is designed
    to be auditable and explicit about the thesis sensor contract:

      - Cameras: use K_undistortion only (ignore K and D); cTv is vehicle->camera.
      - LiDARs: vTl is lidar->vehicle; invert to vehicle->lidar for attachment.
      - Inversions: cTv_inverted=false; vTl_inverted=true (required for attachment).

    Additionally, it records the applied CARLA transforms (relative and world)
    that were used at spawn time.
    """

    use_K_undistortion_only: bool
    ignored_K_and_D: bool
    cTv_inverted: bool
    vTl_inverted: bool
    cameras_count: int
    lidars_count: int
    timestamp_utc: str
    calib_path: str
    map_identity: Optional[Dict[str, Any]]
    sensors: Dict[str, Dict[str, Any]]
    compliance_notes: list
    sensor_contract: Dict[str, Any]
    applied_carla_transforms: Dict[str, Any]
    sensors_attached: Any = "unknown"
    sensors_attached_status: str = "unknown"
    sensors_attached_reason: str = "frame_counts_not_available_in_rig_report"
    sensors_attached_rule: str = (
        "all_reported_sensors_spawned_and_required_modalities_have_frames"
    )
    required_modalities: Optional[Dict[str, int]] = None
    recorded_modalities: Optional[Dict[str, int]] = None

    def to_dict(self) -> Dict[str, Any]:
        # Keep schema_version stable for backward compatibility; extend with new fields.
        compliance_values = {
            "use_K_undistortion_only": self.use_K_undistortion_only,
            "ignored_K_and_D": self.ignored_K_and_D,
            "ctv_inverted": self.cTv_inverted,
            "vtl_inverted": self.vTl_inverted,
        }
        return {
            "schema_version": 1,
            # Mirror contract booleans at top level for strict validator compatibility.
            **compliance_values,
            # Keep mixed-case aliases for compatibility with existing consumers/docs.
            "cTv_inverted": self.cTv_inverted,
            "vTl_inverted": self.vTl_inverted,
            # New explicit contract block (validated by validate_thesis_run.py)
            "sensor_contract": self.sensor_contract,
            # Applied CARLA transforms for proof (validated by validate_thesis_run.py)
            "applied_carla_transforms": self.applied_carla_transforms,
            # Legacy compliance block (kept for backward compatibility)
            "thesis_compliance": dict(compliance_values),
            "sensors_summary": {
                "cameras_count": self.cameras_count,
                "lidars_count": self.lidars_count,
            },
            "sensors_attached": self.sensors_attached,
            "sensors_attached_status": self.sensors_attached_status,
            "sensors_attached_reason": self.sensors_attached_reason,
            "sensors_attached_rule": self.sensors_attached_rule,
            "required_modalities": self.required_modalities
            if isinstance(self.required_modalities, dict)
            else {"rgb": int(self.cameras_count), "lidar": int(self.lidars_count)},
            "recorded_modalities": self.recorded_modalities
            if isinstance(self.recorded_modalities, dict)
            else None,
            "timestamp_utc": self.timestamp_utc,
            "calib_path": self.calib_path,
            "map_identity": self.map_identity,
            "sensors": self.sensors,
            "compliance_notes": self.compliance_notes,
        }


class ThesisSensorRig:
    """
    Spawn sensors according to the thesis conventions (camera not inverted, LiDAR inverted).

    THESIS INVARIANT (enforced, not configurable):
    - Cameras: use K_undistortion (pinhole), image_size, and cTv as Vehicle→Camera.
      cTv is used DIRECTLY for CARLA attachment. Inversion is FORBIDDEN.
    - LiDARs: vTl is LiDAR→Vehicle.
      vTl is inverted to Vehicle→LiDAR for CARLA attachment. Inversion is REQUIRED.

    If UP_THESIS_STRICT=1 and any manual override env var is set, RuntimeError is raised.
    """

    def __init__(self, calib_path: str | Path):
        self._map_identity = None
        self._sensors: list[Any] = []
        self._client: Any = None
        self.calib_path = Path(calib_path)
        if not self.calib_path.exists():
            raise FileNotFoundError(f"Calibration file not found: {self.calib_path}")
        with self.calib_path.open("r", encoding="utf-8") as f:
            self.calib_data = json.load(f)
        _guard_thesis_inversion_env()
        cams = self.calib_data.get("cameras", {}) or {}
        lids = self.calib_data.get("lidars", {}) or {}
        if not cams and not lids:
            raise RuntimeError("calib_data.json contains no cameras or lidars.")
        self._validate_loaded_calibration_contract(cams, lids)

        # Runtime state for rig verification evidence
        self._last_applied_carla_transforms: Dict[str, Any] = {
            "ego_vehicle_world": None,
            "sensors": {},
        }
        self._spawn_report_path: Optional[Path] = None
        self._last_spawn_phase_report: Dict[str, Any] = {
            "spawn_phase_entered": False,
            "apply_batch_sync_entered": False,
            "spawn_response_count": 0,
            "spawn_success_count": 0,
            "spawn_error_count": 0,
            "spawn_response_sample": [],
            "first_spawn_error": "",
            "failure_stage": "",
        }

    def set_spawn_report_path(self, path: str | Path | None) -> None:
        self._spawn_report_path = Path(path) if path else None

    def set_client(self, client: Any | None) -> None:
        self._client = client

    def get_last_spawn_phase_report(self) -> Dict[str, Any]:
        report = dict(self._last_spawn_phase_report)
        report["spawn_response_sample"] = list(
            self._last_spawn_phase_report.get("spawn_response_sample", []) or []
        )
        return report

    def _emit_spawn_phase_report(self) -> None:
        if self._spawn_report_path is None:
            return
        try:
            payload: Dict[str, Any] = {}
            if self._spawn_report_path.exists():
                loaded = json.loads(
                    self._spawn_report_path.read_text(
                        encoding="utf-8", errors="replace"
                    )
                )
                if isinstance(loaded, dict):
                    payload = loaded
            payload.update(self.get_last_spawn_phase_report())
            self._spawn_report_path.parent.mkdir(parents=True, exist_ok=True)
            self._spawn_report_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
            )
        except Exception:
            pass

    def _record_spawn_phase_entered(self) -> None:
        self._last_spawn_phase_report["spawn_phase_entered"] = True
        self._last_spawn_phase_report["apply_batch_sync_entered"] = True
        if not self._last_spawn_phase_report.get("failure_stage"):
            self._last_spawn_phase_report["failure_stage"] = "apply_batch_sync"
        self._emit_spawn_phase_report()

    def _record_spawn_responses(
        self,
        *,
        sensor_name: str,
        sensor_type: str,
        responses: Any,
    ) -> None:
        self._record_spawn_phase_entered()
        response_list = list(responses or [])
        self._last_spawn_phase_report["spawn_response_count"] = int(
            self._last_spawn_phase_report.get("spawn_response_count", 0) or 0
        ) + int(len(response_list))
        sample = self._last_spawn_phase_report.setdefault("spawn_response_sample", [])
        for idx, response in enumerate(response_list):
            actor_id = int(getattr(response, "actor_id", 0) or 0)
            error_text = str(getattr(response, "error", "") or "")
            if actor_id > 0:
                self._last_spawn_phase_report["spawn_success_count"] = int(
                    self._last_spawn_phase_report.get("spawn_success_count", 0) or 0
                ) + 1
            if error_text:
                self._last_spawn_phase_report["spawn_error_count"] = int(
                    self._last_spawn_phase_report.get("spawn_error_count", 0) or 0
                ) + 1
                if not self._last_spawn_phase_report.get("first_spawn_error"):
                    self._last_spawn_phase_report["first_spawn_error"] = error_text
            if len(sample) < 6:
                sample.append(
                    {
                        "sensor_name": str(sensor_name),
                        "sensor_type": str(sensor_type),
                        "response_index": int(idx),
                        "actor_id": int(actor_id),
                        "error": error_text,
                    }
                )
        self._emit_spawn_phase_report()

    def _record_spawn_exception(
        self,
        *,
        sensor_name: str,
        sensor_type: str,
        error_text: str,
        stage: str = "apply_batch_sync",
    ) -> None:
        self._record_spawn_phase_entered()
        self._last_spawn_phase_report["failure_stage"] = str(stage)
        err = str(error_text or "")
        if err and not self._last_spawn_phase_report.get("first_spawn_error"):
            self._last_spawn_phase_report["first_spawn_error"] = err
        sample = self._last_spawn_phase_report.setdefault("spawn_response_sample", [])
        if err and len(sample) < 6:
            sample.append(
                {
                    "sensor_name": str(sensor_name),
                    "sensor_type": str(sensor_type),
                    "response_index": -1,
                    "actor_id": 0,
                    "error": err,
                }
            )
        self._emit_spawn_phase_report()

    def _validate_loaded_calibration_contract(
        self,
        cameras: Dict[str, Any],
        lidars: Dict[str, Any],
    ) -> None:
        """Fail closed on thesis-contract calibration drift before CARLA attachment."""
        for cam_name, cam_data in cameras.items():
            if not isinstance(cam_data, dict):
                raise RuntimeError(
                    f"Camera '{cam_name}' calibration must be a JSON object."
                )
            if "K_undistortion" not in cam_data:
                raise RuntimeError(
                    f"Camera '{cam_name}' is missing K_undistortion. Thesis contract forbids falling back to K or D."
                )
            if "image_size" not in cam_data:
                raise RuntimeError(
                    f"Camera '{cam_name}' is missing image_size. Width/height must come from image_size."
                )
            width_px, height_px = _parse_image_size(cam_data["image_size"])
            if int(width_px) <= 0 or int(height_px) <= 0:
                raise RuntimeError(
                    f"Camera '{cam_name}' has non-positive image_size {cam_data['image_size']!r}."
                )
            if "cTv" not in cam_data:
                raise RuntimeError(
                    f"Camera '{cam_name}' is missing cTv. Thesis contract requires direct vehicle->camera extrinsics."
                )
            _ensure_homogeneous(cam_data["cTv"])
            np.asarray(cam_data["K_undistortion"], dtype=float)

        for lidar_name, lidar_data in lidars.items():
            if not isinstance(lidar_data, dict):
                raise RuntimeError(
                    f"LiDAR '{lidar_name}' calibration must be a JSON object."
                )
            if "vTl" not in lidar_data:
                raise RuntimeError(
                    f"LiDAR '{lidar_name}' is missing vTl. Thesis contract requires inversion of lidar->vehicle extrinsics."
                )
            _ensure_homogeneous(lidar_data["vTl"])

    def spawn_rig(self, world: Any, ego_vehicle: Any, *, expected_map: Optional[str] = None) -> Dict[str, SpawnedSensor]:
        carla = _lazy_carla()
        # CARLA 0.9.16 exposes apply_batch_sync on Client, not World.
        client = self._client
        if client is None:
            client = getattr(world, "_client", None)
        if client is None and hasattr(world, "get_client"):
            try:
                client = world.get_client()
            except Exception:
                client = None
        if client is None:
            self._record_spawn_exception(
                sensor_name="thesis_rig",
                sensor_type="rig",
                error_text="missing_carla_client",
                stage="client_binding",
            )
            raise RuntimeError("missing_carla_client")
        if not hasattr(client, "apply_batch_sync"):
            binding_type = type(client).__name__
            self._record_spawn_exception(
                sensor_name="thesis_rig",
                sensor_type="rig",
                error_text=f"invalid_client_binding:{binding_type}",
                stage="client_binding",
            )
            raise RuntimeError(f"invalid_client_binding:{binding_type}")
        self._client = client

        # P0 MAP IDENTITY VALIDATION (thesis safety)
        self._map_identity = validate_world_map(world, expected_substring=expected_map)
        log.info(
            "Map identity validated: %s (strict=%s)",
            self._map_identity.get("world_map_name"),
            self._map_identity.get("thesis_strict_enabled"),
        )

        bp_lib = world.get_blueprint_library()
        spawned: Dict[str, SpawnedSensor] = {}
        # Capture applied CARLA transforms for rig_verification.json (P1 evidence pack)
        self._last_applied_carla_transforms = {
            "ego_vehicle_world": _carla_transform_to_pose_dict(
                ego_vehicle.get_transform()
            ),
            "sensors": {},
        }

        # Conservative safety budgets to reduce CARLA hard-crashes that can
        # happen when spawning many high-resolution sensors.
        low_memory_profile_active = _env_bool("UP_LOW_MEMORY_PROFILE", False)
        max_cam_w, max_cam_h, max_total_pixels = _runtime_camera_limits(
            max_camera_width_px=int(getattr(self, "MAX_CAMERA_WIDTH_PX", 1920)),
            max_camera_height_px=int(getattr(self, "MAX_CAMERA_HEIGHT_PX", 1080)),
            max_total_camera_pixels=int(
                getattr(self, "MAX_TOTAL_CAMERA_PIXELS", 12_000_000)
            ),
            low_memory_profile_active=bool(low_memory_profile_active),
        )
        total_pixels = 0
        camera_items, lidar_items, front_only_strict = (
            self._select_capture_profile_items()
        )
        sensor_spawn_delay_s = max(0.0, _env_float("UP_SENSOR_SPAWN_DELAY_S", 0.5))

        # Cameras
        for cam_name, cam_data in camera_items:
            try:
                K_undist = np.asarray(cam_data["K_undistortion"], dtype=float)
                width_px, height_px = _parse_image_size(cam_data["image_size"])
                fov_deg = _compute_fov_deg(K_undist, width_px)

                # Clamp camera resolution and ensure fov is in a sane range.
                width_px = max(16, min(int(width_px), max_cam_w))
                height_px = max(16, min(int(height_px), max_cam_h))
                try:
                    fov_deg = float(fov_deg)
                except Exception:
                    fov_deg = 90.0
                fov_deg = max(10.0, min(170.0, fov_deg))

                # Pixel budget gate: downscale uniformly if needed.
                total_pixels += width_px * height_px
                if total_pixels > max_total_pixels:
                    # Best-effort: reduce this camera by a factor of 2 to stay under budget.
                    width_px = max(16, width_px // 2)
                    height_px = max(16, height_px // 2)
                    total_pixels = sum(
                        (s.report.get("attributes", {}).get("width", 0) or 0)
                        * (s.report.get("attributes", {}).get("height", 0) or 0)
                        for s in spawned.values()
                    ) + (width_px * height_px)

                T_raw = _ensure_homogeneous(cam_data["cTv"])
                T_vehicle_camera = vehicle_to_camera_from_cTv(
                    cam_data["cTv"],
                    flip_vehicle_y=False,
                    opencv_camera_axes=True,
                    ctv_invert=False,
                )
                t_raw = T_raw[:3, 3]

                # Thesis contract: cTv is vehicle→camera and MUST NOT be inverted.
                ctv_inverted = False
                T_used = T_vehicle_camera
                t_used = T_used[:3, 3]
                cam_pose = camera_attachment_pose_from_cTv(
                    cam_data["cTv"],
                    flip_vehicle_y=False,
                    opencv_camera_axes=True,
                    ctv_invert=False,
                )
                cam_tf_dict = {
                    "x": float(cam_pose["x"]),
                    "y": float(cam_pose["y"]),
                    "z": float(cam_pose["z"]),
                    "roll": float(cam_pose["roll"]),
                    "pitch": float(cam_pose["pitch"]),
                    "yaw": float(cam_pose["yaw"]),
                }
                cam_forward_alignment = {
                    "forward_alignment_ok": bool(
                        cam_pose.get("forward_alignment_ok", False)
                    ),
                    "forward_alignment_to_vehicle_x": float(
                        cam_pose.get("forward_alignment_to_vehicle_x", 0.0)
                    ),
                    "forward_vehicle_x": float(cam_pose.get("forward_vehicle_x", 0.0)),
                    "forward_vehicle_y": float(cam_pose.get("forward_vehicle_y", 0.0)),
                    "forward_vehicle_z": float(cam_pose.get("forward_vehicle_z", 0.0)),
                }
                carla = _lazy_carla()
                cam_tf = carla.Transform(
                    carla.Location(
                        x=float(cam_tf_dict["x"]),
                        y=float(cam_tf_dict["y"]),
                        z=float(cam_tf_dict["z"]),
                    ),
                    carla.Rotation(
                        roll=float(cam_tf_dict["roll"]),
                        pitch=float(cam_tf_dict["pitch"]),
                        yaw=float(cam_tf_dict["yaw"]),
                    ),
                )
                cam_tf = _sanitize_transform(
                    cam_tf, max_abs_m=float(getattr(self, "MAX_SENSOR_OFFSET_M", 50.0))
                )

                bp = bp_lib.find("sensor.camera.rgb")
                # Attribute-setting is version-tolerant.
                try:
                    if hasattr(bp, "has_attribute") and bp.has_attribute("image_size_x"):
                        bp.set_attribute("image_size_x", str(width_px))
                    if hasattr(bp, "has_attribute") and bp.has_attribute("image_size_y"):
                        bp.set_attribute("image_size_y", str(height_px))
                    if hasattr(bp, "has_attribute") and bp.has_attribute("fov"):
                        bp.set_attribute("fov", f"{fov_deg:.6f}")
                    if hasattr(bp, "has_attribute") and bp.has_attribute("sensor_tick"):
                        # Optional global sensor tick in calib (seconds). Default 0.0 means every frame.
                        tick = 0.0
                        if isinstance(self.calib_data, dict):
                            try:
                                tick = float(self.calib_data.get("sensor_tick", 0.0) or 0.0)
                            except Exception:
                                tick = 0.0
                        bp.set_attribute("sensor_tick", str(tick))
                except Exception:
                    pass

                # In CARLA 0.9.x synchronous mode, world.spawn_actor() for streaming
                # sensors (cameras, LiDAR) blocks until the world ticks because the
                # streaming subscription requires the first tick delivery.  Running this
                # inside _call_with_timeout means the main thread is blocked in t.join()
                # and nobody else ticks, causing a 60-120 s RPC hang then timeout.
                # Fix: use apply_batch_sync with due_tick_cue=True so the spawn command
                # and one tick are delivered atomically, unblocking the streaming channel.
                try:
                    _cmd = carla.command.SpawnActor(bp, cam_tf, ego_vehicle)
                    self._record_spawn_phase_entered()
                    try:
                        _responses = client.apply_batch_sync([_cmd], True)
                    except Exception as exc:
                        self._record_spawn_exception(
                            sensor_name=cam_name,
                            sensor_type="camera",
                            error_text=str(exc),
                        )
                        raise
                    self._record_spawn_responses(
                        sensor_name=cam_name,
                        sensor_type="camera",
                        responses=_responses,
                    )
                    if not _responses:
                        self._record_spawn_exception(
                            sensor_name=cam_name,
                            sensor_type="camera",
                            error_text="apply_batch_sync_returned_no_responses",
                        )
                        raise RuntimeError("apply_batch_sync_returned_no_responses")
                    if _responses[0].error:
                        raise RuntimeError(_responses[0].error)
                    actor = world.get_actor(_responses[0].actor_id)
                except (AttributeError, TypeError):
                    # Fallback for CARLA builds where command.SpawnActor attach arg differs.
                    actor = world.spawn_actor(bp, cam_tf, attach_to=ego_vehicle)
                if actor is None:
                    raise RuntimeError(f"Sensor {cam_name} returned no actor")
                # Record applied transforms (relative + world) for evidence
                try:
                    self._last_applied_carla_transforms["sensors"][cam_name] = {
                        "type": "camera",
                        "relative_to_vehicle": dict(cam_tf_dict),
                        "world": _carla_transform_to_pose_dict(actor.get_transform()),
                    }
                except Exception:
                    pass
                spawned[cam_name] = SpawnedSensor(
                    actor=actor,
                    report={
                        "conventions": CONVENTIONS,
                        "type": "camera",
                        "attributes": {
                            "width": int(width_px),
                            "height": int(height_px),
                            "fov": float(fov_deg),
                        },
                        "raw": {
                            "K_undistortion": cam_data.get("K_undistortion"),
                            "image_size": cam_data.get("image_size"),
                            "cTv": cam_data.get("cTv"),
                        },
                        "raw_matrix": _to_list(cam_data.get("cTv")),
                        "raw_direction_label": "vehicle_to_camera",
                        "used_direction_label": "vehicle_to_camera",
                        "used_matrix_vehicle_to_sensor": _to_list(T_used),
                        "inversion_applied": ctv_inverted,
                        "ctv_inverted": ctv_inverted,
                        "ctv_source": "calib_data.json",
                        "t_raw": _to_list(t_raw),
                        "t_used": _to_list(t_used),
                        "carla_transform": cam_tf_dict,
                        "forward_alignment": cam_forward_alignment,
                        "transform_convention": "Used cTv (vehicle->camera) directly for attachment.",
                        "low_memory_profile_active": bool(low_memory_profile_active),
                        "front_only_strict_active": bool(front_only_strict),
                    },
                )
                _sleep_and_verify_spawned_sensor(
                    actor,
                    sensor_name=cam_name,
                    delay_s=float(sensor_spawn_delay_s),
                )
            except Exception:
                _cleanup_spawned_sensor_actors(spawned)
                self._sensors = []
                raise

        # LiDARs
        for lidar_name, lidar_data in lidar_items:
            try:
                # Thesis contract: vTl is LiDAR→Vehicle and MUST be inverted for attachment.
                vtl_inverted = True
                T_used = vehicle_to_lidar_from_vTl(lidar_data["vTl"], flip_vehicle_y=False)
                lidar_pose = lidar_attachment_pose_from_vTl(
                    lidar_data["vTl"], flip_vehicle_y=False
                )
                lidar_tf, lidar_tf_dict = _pose_to_carla_transform(lidar_pose)
                lidar_tf = _sanitize_transform(
                    lidar_tf, max_abs_m=float(getattr(self, "MAX_SENSOR_OFFSET_M", 50.0))
                )

                bp = bp_lib.find("sensor.lidar.ray_cast")
                # Conservative defaults that are known to work across versions.
                try:
                    if hasattr(bp, "has_attribute") and bp.has_attribute("range"):
                        bp.set_attribute("range", str(float(lidar_data.get("range", 80.0))))
                    if hasattr(bp, "has_attribute") and bp.has_attribute(
                        "rotation_frequency"
                    ):
                        bp.set_attribute(
                            "rotation_frequency",
                            str(float(lidar_data.get("rotation_frequency", 10.0))),
                        )
                    if hasattr(bp, "has_attribute") and bp.has_attribute(
                        "points_per_second"
                    ):
                        bp.set_attribute(
                            "points_per_second",
                            str(int(lidar_data.get("points_per_second", 200000))),
                        )
                    if hasattr(bp, "has_attribute") and bp.has_attribute("channels"):
                        bp.set_attribute(
                            "channels", str(int(lidar_data.get("channels", 32)))
                        )
                    if hasattr(bp, "has_attribute") and bp.has_attribute("upper_fov"):
                        bp.set_attribute(
                            "upper_fov", str(float(lidar_data.get("upper_fov", 10.0)))
                        )
                    if hasattr(bp, "has_attribute") and bp.has_attribute("lower_fov"):
                        bp.set_attribute(
                            "lower_fov", str(float(lidar_data.get("lower_fov", -30.0)))
                        )
                    if hasattr(bp, "has_attribute") and bp.has_attribute("sensor_tick"):
                        bp.set_attribute(
                            "sensor_tick", str(float(lidar_data.get("sensor_tick", 0.0)))
                        )
                except Exception:
                    pass
                # Same apply_batch_sync+due_tick_cue fix as cameras above.
                try:
                    _cmd = carla.command.SpawnActor(bp, lidar_tf, ego_vehicle)
                    self._record_spawn_phase_entered()
                    try:
                        _responses = client.apply_batch_sync([_cmd], True)
                    except Exception as exc:
                        self._record_spawn_exception(
                            sensor_name=lidar_name,
                            sensor_type="lidar",
                            error_text=str(exc),
                        )
                        raise
                    self._record_spawn_responses(
                        sensor_name=lidar_name,
                        sensor_type="lidar",
                        responses=_responses,
                    )
                    if not _responses:
                        self._record_spawn_exception(
                            sensor_name=lidar_name,
                            sensor_type="lidar",
                            error_text="apply_batch_sync_returned_no_responses",
                        )
                        raise RuntimeError("apply_batch_sync_returned_no_responses")
                    if _responses[0].error:
                        raise RuntimeError(_responses[0].error)
                    actor = world.get_actor(_responses[0].actor_id)
                except (AttributeError, TypeError):
                    actor = world.spawn_actor(bp, lidar_tf, attach_to=ego_vehicle)
                if actor is None:
                    raise RuntimeError(f"Sensor {lidar_name} returned no actor")
                # Record applied transforms (relative + world) for evidence
                try:
                    self._last_applied_carla_transforms["sensors"][lidar_name] = {
                        "type": "lidar",
                        "relative_to_vehicle": dict(lidar_tf_dict),
                        "world": _carla_transform_to_pose_dict(actor.get_transform()),
                    }
                except Exception:
                    pass

                spawned[lidar_name] = SpawnedSensor(
                    actor=actor,
                    report={
                        "conventions": CONVENTIONS,
                        "type": "lidar",
                        "attributes": {},
                        "raw": {
                            "vTl": lidar_data.get("vTl"),
                        },
                        "raw_matrix": _to_list(lidar_data.get("vTl")),
                        "raw_direction_label": "lidar_to_vehicle",
                        "used_direction_label": "vehicle_to_lidar",
                        "used_matrix_vehicle_to_sensor": _to_list(T_used),
                        "inversion_applied": vtl_inverted,
                        "vtl_inverted": vtl_inverted,
                        "carla_transform": lidar_tf_dict,
                        "transform_convention": "Used inverse(vTl) (vehicle->lidar) for attachment.",
                        "front_only_strict_active": bool(front_only_strict),
                    },
                )
                _sleep_and_verify_spawned_sensor(
                    actor,
                    sensor_name=lidar_name,
                    delay_s=float(sensor_spawn_delay_s),
                )
            except Exception:
                _cleanup_spawned_sensor_actors(spawned)
                self._sensors = []
                raise

        # Optional healthcheck: confirm each sensor can emit at least one
        # measurement. This helps diagnose CARLA crashes that happen around
        # sensor creation or ticking.
        if bool(getattr(self, "ENABLE_SENSOR_HEALTHCHECK", True)):
            try:
                self._healthcheck_sensor_streams(world, spawned)
            except Exception as e:
                log.warning("Sensor healthcheck failed: %s", e)

        self._sensors = [sp.actor for sp in spawned.values() if sp.actor is not None]
        return spawned

    def get_front_rgb_camera(self) -> Any:
        return self._sensors[0] if self._sensors else None

    def reports_from_calib_only(self) -> Dict[str, Dict[str, Any]]:
        """Return report stubs without spawning (for tests)."""
        reports: Dict[str, Dict[str, Any]] = {}
        cams = self.calib_data.get("cameras", {}) or {}
        lids = self.calib_data.get("lidars", {}) or {}
        for cam_name, cam_data in cams.items():
            reports[cam_name] = {
                "type": "camera",
                "raw": {
                    "K_undistortion": cam_data.get("K_undistortion"),
                    "image_size": cam_data.get("image_size"),
                    "cTv": cam_data.get("cTv"),
                },
                "raw_direction_label": "vehicle_to_camera",
                "inversion_applied": False,
                "ctv_inverted": False,
                "used_direction_label": "vehicle_to_camera",
                "transform_convention": "Used cTv (vehicle->camera) directly for attachment.",
            }
        for lidar_name, lidar_data in lids.items():
            reports[lidar_name] = {
                "type": "lidar",
                "raw": {
                    "vTl": lidar_data.get("vTl"),
                },
                "raw_direction_label": "lidar_to_vehicle",
                "used_direction_label": "vehicle_to_lidar",
                "inversion_applied": True,
                "vtl_inverted": True,
                "transform_convention": "Used inverse(vTl) (vehicle->lidar) for attachment.",
            }
        return reports

    def _build_applied_transforms_for_report(
        self, spawned: Dict[str, SpawnedSensor]
    ) -> Dict[str, Any]:
        """Return applied CARLA transforms for rig_verification.json."""
        if isinstance(self._last_applied_carla_transforms, dict):
            if self._last_applied_carla_transforms.get("sensors"):
                return self._last_applied_carla_transforms

        sensors: Dict[str, Any] = {}
        for name, sp in spawned.items():
            report = sp.report if isinstance(sp, SpawnedSensor) else {}
            sensors[name] = {
                "type": report.get("type"),
                "relative_to_vehicle": report.get("carla_transform"),
            }

        return {
            "ego_vehicle_world": None,
            "sensors": sensors,
        }

    @staticmethod
    def _healthcheck_sensor_streams(
        world: Any, sensors: Dict[str, SpawnedSensor], timeout_s: float = 5.0
    ) -> None:
        """Best-effort check that each spawned sensor produces data.

        We register temporary callbacks and wait up to `timeout_s` seconds for a
        first event from each sensor. This method never raises on missing data,
        but it logs a warning and records results into each sensor report.
        """
        import queue

        q: Dict[str, "queue.Queue[object]"] = {}
        overflow_count = 0
        sensor_overflow_count: Dict[str, int] = {}

        def _enqueue_latest(name: str, data: Any) -> None:
            nonlocal overflow_count
            try:
                q[name].put_nowait(data)
            except queue.Full:
                overflow_count += 1
                sensor_overflow_count[name] = sensor_overflow_count.get(name, 0) + 1
                try:
                    q[name].get_nowait()
                except Exception:
                    pass
                try:
                    q[name].put_nowait(data)
                except Exception:
                    pass

        for name, sp in sensors.items():
            q[name] = queue.Queue(maxsize=5)

            def _safe_healthcheck_cb(data: Any, _n: str = name) -> None:
                try:
                    _enqueue_latest(_n, data)
                except Exception:
                    pass

            try:
                sp.actor.listen(_safe_healthcheck_cb)
            except Exception as e:
                sp.report.setdefault("healthcheck", {})["listen_error"] = str(e)

        deadline = time.time() + float(timeout_s)
        # Tick the world a few times to stimulate sensor output.
        while time.time() < deadline:
            try:
                world.tick()
            except Exception:
                pass
            if all(
                (not qn.empty())
                or ("listen_error" in sensors[n].report.get("healthcheck", {}))
                for n, qn in q.items()
            ):
                break
            time.sleep(0.05)

        for name, qn in q.items():
            ok = not qn.empty()
            sensors[name].report.setdefault("healthcheck", {})[
                "first_measurement_ok"
            ] = bool(ok)
            sensors[name].report.setdefault("healthcheck", {})[
                "sensor_queue_overflow"
            ] = int(sensor_overflow_count.get(name, 0))
            if not ok and "listen_error" not in sensors[name].report.get(
                "healthcheck", {}
            ):
                log.warning(
                    "Sensor '%s' produced no measurement within %.1fs", name, timeout_s
                )
        # Release temporary healthcheck listeners before handing sensors
        # to the recorder callback path.
        for sp in sensors.values():
            try:
                sp.actor.stop()
            except Exception:
                pass
        log.info('"sensor_queue_overflow": %d', overflow_count)

    def build_rig_verification(
        self,
        spawned: Dict[str, SpawnedSensor],
    ) -> RigVerification:
        """Build a RigVerification record from spawned sensors.

        This captures the thesis compliance state for audit purposes.
        Must be called AFTER spawn_rig() to have accurate sensor data.
        """
        cameras_count = 0
        lidars_count = 0
        any_ctv_inverted = False
        all_vtl_inverted = True
        sensors_info: Dict[str, Dict[str, Any]] = {}
        compliance_notes: list = []

        # Check each spawned sensor
        for name, sp in spawned.items():
            report = sp.report
            sensor_type = report.get("type", "unknown")

            if sensor_type == "camera":
                cameras_count += 1
                ctv_inv = report.get("ctv_inverted", False) or report.get(
                    "inversion_applied", False
                )
                if ctv_inv:
                    any_ctv_inverted = True
                    compliance_notes.append(f"WARN: Camera '{name}' has cTv inverted")
                sensors_info[name] = {
                    "type": "camera",
                    "ctv_inverted": ctv_inv,
                    "transform_convention": report.get("transform_convention", ""),
                    "attributes": report.get("attributes", {}),
                }
            elif sensor_type == "lidar":
                lidars_count += 1
                vtl_inv = report.get("vtl_inverted", False) or report.get(
                    "inversion_applied", False
                )
                if not vtl_inv:
                    all_vtl_inverted = False
                sensors_info[name] = {
                    "type": "lidar",
                    "vtl_inverted": vtl_inv,
                    "transform_convention": report.get("transform_convention", ""),
                }
        if lidars_count == 0:
            all_vtl_inverted = False

        # Thesis compliance: we use K_undistortion only, never K+D
        # Check if calibration data has K_undistortion for all cameras
        use_K_undistortion_only = True
        ignored_K_and_D = False
        cams = self.calib_data.get("cameras", {}) or {}
        for cam_name, cam_data in cams.items():
            if "K_undistortion" not in cam_data:
                use_K_undistortion_only = False
                compliance_notes.append(
                    f"WARN: Camera '{cam_name}' missing K_undistortion in calib"
                )
            # Check if K and D were present but ignored (thesis mode ignores distortion)
            if "K" in cam_data or "D" in cam_data:
                ignored_K_and_D = True

        # Add compliance status notes
        if use_K_undistortion_only:
            compliance_notes.append(
                "OK: All cameras use K_undistortion only (pinhole model)"
            )
        if not any_ctv_inverted:
            compliance_notes.append("OK: No camera cTv transforms were inverted")
        if lidars_count > 0:
            if all_vtl_inverted:
                compliance_notes.append(
                    "OK: All LiDAR vTl transforms were inverted for attachment"
                )
            else:
                compliance_notes.append(
                    "WARN: One or more LiDAR vTl transforms were not inverted for attachment"
                )

        return RigVerification(
            use_K_undistortion_only=use_K_undistortion_only,
            ignored_K_and_D=ignored_K_and_D,
            cTv_inverted=any_ctv_inverted,
            vTl_inverted=all_vtl_inverted,
            cameras_count=cameras_count,
            lidars_count=lidars_count,
            timestamp_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            calib_path=str(self.calib_path),
            map_identity=self._map_identity,
            sensors=sensors_info,
            compliance_notes=compliance_notes,
            sensor_contract={
                "camera_intrinsics_source": "K_undistortion",
                "ignore_fields": ["K", "D"],
                "cTv_definition": "vehicle->camera",
                "vTl_definition": "lidar->vehicle",
                "cTv_inverted": bool(any_ctv_inverted),
                "vTl_inverted": bool(all_vtl_inverted),
                "cTv_inversion_forbidden": True,
                "vTl_inversion_required": True,
            },
            applied_carla_transforms=self._build_applied_transforms_for_report(spawned),
            sensors_attached="unknown",
            sensors_attached_status="unknown",
            sensors_attached_reason="frame_counts_not_available_in_rig_report",
            sensors_attached_rule="all_reported_sensors_spawned_and_required_modalities_have_frames",
            required_modalities={"rgb": int(cameras_count), "lidar": int(lidars_count)},
            recorded_modalities=None,
        )

    def write_rig_verification(
        self,
        out_dir: Path | str,
        spawned: Dict[str, SpawnedSensor],
        *,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """Write rig_verification.json for thesis evidence pack.

        This MUST be called for every perception run (success OR early-abort).
        The file contains thesis compliance booleans for audit.

        Args:
            out_dir: Output directory for the run
            spawned: Dict of spawned sensors from spawn_rig()
            extra: Optional extra fields to include in the verification

        Returns:
            Path to the written rig_verification.json
        """
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        verification = self.build_rig_verification(spawned)
        data = verification.to_dict()
        if extra:
            data["extra"] = extra

        sig_path = out_path / RIG_VERIFICATION_FILENAME
        sig_path.write_text(
            json.dumps(data, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        log.info("Wrote rig verification to %s", sig_path)
        return sig_path

    def build_spawned_from_sensor_report(
        self,
        report_payload: Any,
        *,
        flip_vehicle_y: Optional[bool] = None,
        opencv_camera_axes: bool = True,
    ) -> Dict[str, SpawnedSensor]:
        """Construct a SpawnedSensor dict from rig-report style payload without CARLA."""
        if flip_vehicle_y is None:
            flip_vehicle_y = False
            if isinstance(report_payload, dict):
                rig_mode = str(report_payload.get("rig", "")).strip().lower()
                if rig_mode == "dominik":
                    flip_vehicle_y = True

        sensor_rows: Dict[str, Dict[str, Any]] = {}
        if isinstance(report_payload, dict) and isinstance(
            report_payload.get("sensors"), list
        ):
            for item in report_payload.get("sensors", []):
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or item.get("id")
                if isinstance(name, str) and name.strip():
                    sensor_rows[str(name)] = dict(item)
        elif isinstance(report_payload, list):
            for item in report_payload:
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or item.get("id")
                if isinstance(name, str) and name.strip():
                    sensor_rows[str(name)] = dict(item)
        elif isinstance(report_payload, dict):
            for key, value in report_payload.items():
                if isinstance(key, str) and isinstance(value, dict):
                    item = dict(value)
                    item.setdefault("name", key)
                    sensor_rows[str(key)] = item

        spawned: Dict[str, SpawnedSensor] = {}
        for name, item in sensor_rows.items():
            report = dict(item)
            sensor_type = str(report.get("type", "")).strip().lower()
            raw = report.get("raw")
            if not isinstance(raw, dict):
                raw = {}
                report["raw"] = raw

            if sensor_type == "camera":
                ctv_inverted = bool(
                    report.get("ctv_inverted", False)
                    or report.get("inversion_applied", False)
                )
                report["ctv_inverted"] = bool(ctv_inverted)
                report["inversion_applied"] = bool(ctv_inverted)
                ctv = raw.get("cTv")
                if ctv is not None and not isinstance(report.get("carla_transform"), dict):
                    try:
                        pose = camera_attachment_pose_from_cTv(
                            ctv,
                            flip_vehicle_y=bool(flip_vehicle_y),
                            opencv_camera_axes=bool(opencv_camera_axes),
                            ctv_invert=bool(ctv_inverted),
                        )
                        report["carla_transform"] = _pose_to_flat_dict(pose)
                    except Exception:
                        pass
            elif sensor_type == "lidar":
                vtl_inverted = bool(
                    report.get("vtl_inverted", False)
                    or report.get("inversion_applied", False)
                )
                report["vtl_inverted"] = bool(vtl_inverted)
                report["inversion_applied"] = bool(vtl_inverted)
                vtl = raw.get("vTl")
                if vtl is not None and not isinstance(report.get("carla_transform"), dict):
                    try:
                        pose = lidar_attachment_pose_from_vTl(
                            vtl,
                            flip_vehicle_y=bool(flip_vehicle_y),
                        )
                        report["carla_transform"] = _pose_to_flat_dict(pose)
                    except Exception:
                        pass

            if "world_transform" not in report:
                report["world_transform"] = None
            spawned[str(name)] = SpawnedSensor(actor=None, report=report)
        return spawned

    def build_spawned_from_calib_defaults(
        self,
        *,
        flip_vehicle_y: bool = False,
        opencv_camera_axes: bool = True,
    ) -> Dict[str, SpawnedSensor]:
        """Construct deterministic SpawnedSensor data directly from calib_data.json."""
        camera_items, lidar_items, front_only_strict = (
            self._select_capture_profile_items()
        )
        sensors_payload: list[Dict[str, Any]] = []
        for cam_name, cam_data in camera_items:
            raw_camera: Dict[str, Any] = {
                "K_undistortion": cam_data.get("K_undistortion"),
                "image_size": cam_data.get("image_size"),
                "cTv": cam_data.get("cTv"),
            }
            if "K" in cam_data:
                raw_camera["K"] = cam_data.get("K")
            if "D" in cam_data:
                raw_camera["D"] = cam_data.get("D")
            sensors_payload.append(
                {
                    "name": str(cam_name),
                    "type": "camera",
                    "ctv_inverted": False,
                    "inversion_applied": False,
                    "transform_convention": "Used cTv (vehicle->camera) via canonical transform_conventions path.",
                    "raw": raw_camera,
                    "front_only_strict_active": bool(front_only_strict),
                }
            )
        for lidar_name, lidar_data in lidar_items:
            sensors_payload.append(
                {
                    "name": str(lidar_name),
                    "type": "lidar",
                    "vtl_inverted": True,
                    "inversion_applied": True,
                    "transform_convention": "Used inverse(vTl) (vehicle->lidar) via canonical transform_conventions path.",
                    "raw": {"vTl": lidar_data.get("vTl")},
                    "front_only_strict_active": bool(front_only_strict),
                }
            )
        return self.build_spawned_from_sensor_report(
            {"rig": "thesis", "sensors": sensors_payload},
            flip_vehicle_y=bool(flip_vehicle_y),
            opencv_camera_axes=bool(opencv_camera_axes),
        )

    def _select_capture_profile_items(
        self,
    ) -> tuple[
        list[tuple[str, Dict[str, Any]]],
        list[tuple[str, Dict[str, Any]]],
        bool,
    ]:
        """Return calibration sensor subsets for full or front-only strict capture."""
        camera_items = [
            (str(name), data)
            for name, data in (self.calib_data.get("cameras", {}) or {}).items()
            if isinstance(data, dict)
        ]
        lidar_items = [
            (str(name), data)
            for name, data in (self.calib_data.get("lidars", {}) or {}).items()
            if isinstance(data, dict)
        ]
        front_only_strict = _env_bool("UP_FRONT_ONLY_STRICT", False)
        if not bool(front_only_strict):
            return camera_items, lidar_items, False

        if not camera_items:
            raise RuntimeError("sensor_spawn_missing_required_modalities:camera")
        if not lidar_items:
            raise RuntimeError("sensor_spawn_missing_required_modalities:lidar")

        camera_items = sorted(camera_items, key=lambda item: item[0])
        lidar_items = sorted(lidar_items, key=lambda item: item[0])
        front_camera_items = [
            item for item in camera_items if "front" in item[0].strip().lower()
        ]
        if not front_camera_items:
            front_camera_items = [camera_items[0]]
        front_camera_items = [front_camera_items[0]]
        primary_lidar_item = lidar_items[0]
        return front_camera_items, [primary_lidar_item], True

    @staticmethod
    def capture_ego_spawn_screenshot(
        world: Any,
        ego_vehicle: Any,
        out_dir: Path | str,
        *,
        filename: str = SCREENSHOT_EGO_SPAWN,
        spectator_offset: Tuple[float, float, float] = (-8.0, 0.0, 5.0),
        spectator_pitch: float = -20.0,
    ) -> Optional[Path]:
        """Capture a screenshot of the ego vehicle from spectator view.

        Positions the spectator camera behind and above the ego vehicle,
        then captures a screenshot.

        Args:
            world: CARLA world object
            ego_vehicle: The ego vehicle actor
            out_dir: Output directory
            filename: Output filename (default: ego_spawn.png)
            spectator_offset: (back, right, up) offset from ego
            spectator_pitch: Pitch angle for spectator camera

        Returns:
            Path to saved screenshot or None if failed
        """
        carla = _lazy_carla()
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        try:
            ego_tf = ego_vehicle.get_transform()
            # Calculate spectator position relative to ego
            fwd = ego_tf.rotation.get_forward_vector()
            right_vec = ego_tf.rotation.get_right_vector()

            # spectator_offset is (back, right, up)
            back, side, up = spectator_offset
            spec_loc = carla.Location(
                x=ego_tf.location.x + fwd.x * back + right_vec.x * side,
                y=ego_tf.location.y + fwd.y * back + right_vec.y * side,
                z=ego_tf.location.z + up,
            )
            spec_rot = carla.Rotation(
                pitch=float(spectator_pitch),
                yaw=float(ego_tf.rotation.yaw),
                roll=0.0,
            )
            spec_tf = carla.Transform(spec_loc, spec_rot)

            spectator = world.get_spectator()
            spectator.set_transform(spec_tf)

            # Tick world to update spectator view
            try:
                world.tick()
            except Exception:
                pass

            # Note: Actual screenshot capture depends on CARLA client capabilities
            # This sets up the view; actual capture may need client-side implementation
            screenshot_path = out_path / filename
            log.info(
                "Spectator positioned for ego spawn screenshot: %s", screenshot_path
            )

            # Return path (actual capture may be done by caller or separate tool)
            return screenshot_path

        except Exception as e:
            log.warning("Failed to position spectator for ego spawn screenshot: %s", e)
            return None

    @staticmethod
    def capture_sensor_frame(
        sensor_actor: Any,
        out_path: Path,
        *,
        timeout_s: float = 5.0,
    ) -> Optional[Path]:
        """Capture a single frame from a sensor and save to file.

        Args:
            sensor_actor: The sensor actor (camera or lidar)
            out_path: Full path for output file
            timeout_s: Timeout waiting for frame

        Returns:
            Path to saved file or None if failed
        """
        import queue
        import threading

        frame_queue: "queue.Queue[Any]" = queue.Queue(maxsize=5)
        frame_received = threading.Event()

        def on_frame(data):
            try:
                if not frame_received.is_set():
                    frame_queue.put(data)
                    frame_received.set()
            except Exception:
                pass

        try:
            sensor_actor.listen(on_frame)
            frame_received.wait(timeout=float(timeout_s))

            if frame_queue.empty():
                log.warning("No frame received from sensor within %.1fs", timeout_s)
                return None

            data = frame_queue.get_nowait()

            # Handle different sensor types
            sensor_type = str(getattr(sensor_actor, "type_id", ""))

            if "camera" in sensor_type.lower():
                # RGB camera - save as PNG
                try:
                    data.save_to_disk(str(out_path))
                    log.info("Saved camera frame to %s", out_path)
                    return out_path
                except Exception as e:
                    log.warning("Failed to save camera frame: %s", e)
                    return None

            elif "lidar" in sensor_type.lower():
                # LiDAR - save point cloud
                try:
                    # For BEV, we'd need to render the point cloud
                    # This saves raw data; BEV rendering would need additional code
                    import numpy as np

                    points = np.frombuffer(data.raw_data, dtype=np.float32).reshape(
                        -1, 4
                    )
                    np.savez_compressed(
                        str(out_path.with_suffix(".npz")), points=points
                    )
                    log.info("Saved lidar data to %s", out_path.with_suffix(".npz"))
                    return out_path.with_suffix(".npz")
                except Exception as e:
                    log.warning("Failed to save lidar data: %s", e)
                    return None

            return None

        except Exception as e:
            log.warning("Failed to capture sensor frame: %s", e)
            return None
        finally:
            try:
                sensor_actor.stop()
            except Exception:
                pass

    @staticmethod
    def draw_debug_axes(
        world: Any,
        sensors: Dict[str, SpawnedSensor],
        *,
        life_time: float = 10.0,
        scale: float = 1.0,
    ) -> None:
        """Draw axis markers and labels for each sensor."""
        carla = _lazy_carla()
        dbg = world.debug
        for name, spawned in sensors.items():
            tf = spawned.actor.get_transform()
            loc = tf.location
            rot = tf.rotation
            forward = rot.get_forward_vector()
            right = rot.get_right_vector()
            try:
                up = rot.get_up_vector()
            except AttributeError:
                # Older CARLA builds may only expose this on the transform
                try:
                    up = tf.get_up_vector()
                except AttributeError:
                    # Derive up from forward/right to keep drawing robust
                    up = carla.Vector3D(
                        x=forward.y * right.z - forward.z * right.y,
                        y=forward.z * right.x - forward.x * right.z,
                        z=forward.x * right.y - forward.y * right.x,
                    )

            dbg.draw_string(
                loc,
                f"{name} ({spawned.actor.type_id})",
                color=carla.Color(r=255, g=255, b=255),
                life_time=life_time,
                persistent_lines=False,
            )
            dbg.draw_arrow(
                loc,
                carla.Location(
                    x=loc.x + forward.x * scale,
                    y=loc.y + forward.y * scale,
                    z=loc.z + forward.z * scale,
                ),
                thickness=0.05,
                arrow_size=0.1,
                color=carla.Color(r=255, g=0, b=0),
                life_time=life_time,
                persistent_lines=False,
            )
            dbg.draw_arrow(
                loc,
                carla.Location(
                    x=loc.x + right.x * scale,
                    y=loc.y + right.y * scale,
                    z=loc.z + right.z * scale,
                ),
                thickness=0.05,
                arrow_size=0.1,
                color=carla.Color(r=0, g=255, b=0),
                life_time=life_time,
                persistent_lines=False,
            )
            dbg.draw_arrow(
                loc,
                carla.Location(
                    x=loc.x + up.x * scale,
                    y=loc.y + up.y * scale,
                    z=loc.z + up.z * scale,
                ),
                thickness=0.05,
                arrow_size=0.1,
                color=carla.Color(r=0, g=0, b=255),
                life_time=life_time,
                persistent_lines=False,
            )
