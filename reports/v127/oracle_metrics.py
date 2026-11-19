"""Independent source-frame/CARLA-client matrix comparison for V127."""
from __future__ import annotations

import json
from pathlib import Path

import carla
import numpy as np

from ultimate_pipeline.sensors.transform_conventions import (
    carla_attachment_pose_from_matrix,
    carla_ego_from_camera_from_cTv,
    carla_ego_from_lidar_from_vTl,
)


ROOT = Path(__file__).resolve().parents[2]
CALIBRATION = ROOT / "ultimate_pipeline" / "sensors" / "calib_data.json"
raw = CALIBRATION.read_bytes()
calibration = json.loads(raw)
vehicle_flu_to_carla = np.diag([1.0, -1.0, 1.0, 1.0])
camera_optical_to_carla = np.eye(4)
camera_optical_to_carla[:3, :3] = np.asarray(
    [[0.0, 1.0, 0.0], [0.0, 0.0, -1.0], [1.0, 0.0, 0.0]]
)


def oracle_matrix(kind: str, source: list[list[float]]) -> np.ndarray:
    source_matrix = np.asarray(source, dtype=np.float64)
    if kind == "camera":
        return vehicle_flu_to_carla @ np.linalg.inv(source_matrix) @ camera_optical_to_carla
    if kind == "lidar":
        return vehicle_flu_to_carla @ source_matrix @ vehicle_flu_to_carla
    raise ValueError(kind)


def compare(kind: str, source: list[list[float]], candidate: np.ndarray) -> dict:
    source_matrix = np.asarray(source, dtype=np.float64)
    expected = oracle_matrix(kind, source)
    pose = carla_attachment_pose_from_matrix(candidate)
    carla_transform = carla.Transform(
        carla.Location(x=pose["x"], y=pose["y"], z=pose["z"]),
        carla.Rotation(roll=pose["roll"], pitch=pose["pitch"], yaw=pose["yaw"]),
    )
    actual = np.asarray(carla_transform.get_matrix(), dtype=np.float64)
    relative = expected[:3, :3].T @ actual[:3, :3]
    skew_vector = np.asarray(
        [relative[2, 1] - relative[1, 2], relative[0, 2] - relative[2, 0], relative[1, 0] - relative[0, 1]]
    )
    angle_deg = float(
        np.degrees(
            np.arctan2(np.linalg.norm(skew_vector) / 2.0, (np.trace(relative) - 1.0) / 2.0)
        )
    )
    basis_errors = {}
    for index, name in enumerate(("forward", "right", "up")):
        actual_axis = actual[:3, index]
        expected_axis = expected[:3, index]
        cross_norm = float(np.linalg.norm(np.cross(actual_axis, expected_axis)))
        dot = float(actual_axis @ expected_axis)
        basis_errors[f"{name}_deg"] = float(np.degrees(np.arctan2(cross_norm, dot)))
    return {
        "source_sensor_position_xyz_m": (
            (np.linalg.inv(source_matrix) if kind == "camera" else source_matrix)[:3, 3].tolist()
        ),
        "position_error_m": float(np.linalg.norm(actual[:3, 3] - expected[:3, 3])),
        "matrix_max_abs_error": float(np.max(np.abs(actual - expected))),
        "rotation_angle_error_deg": angle_deg,
        "basis_angle_errors": basis_errors,
        "carla_position_xyz_m": actual[:3, 3].tolist(),
    }


results = {}
for sensor_name, camera in sorted(calibration["cameras"].items()):
    results[sensor_name] = compare(
        "camera",
        camera["cTv"],
        carla_ego_from_camera_from_cTv(camera["cTv"]),
    )
active_lidar_name = "middle_lidar"
lidar = calibration["lidars"][active_lidar_name]
results[active_lidar_name] = compare(
    "lidar", lidar["vTl"], carla_ego_from_lidar_from_vTl(lidar["vTl"])
)

report = {
            "verification_mode": "offline_independent_oracle_plus_installed_carla_client",
            "calibration_sha256": __import__("hashlib").sha256(raw).hexdigest(),
            "carla_client_module": carla.__file__,
            "carla_server_started": False,
            "source_vehicle_frame": "FLU",
            "carla_parent_frame": "forward_right_up",
            "active_lidar_names": [active_lidar_name],
            "sensors": results,
        }
output = json.dumps(report, indent=2, sort_keys=True) + "\n"
print(output, end="")
(ROOT / "reports" / "v127" / "SENSOR_FRAME_ORACLE_RESULTS.json").write_text(
    output, encoding="utf-8"
)
