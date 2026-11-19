"""Compare all three spawn adapters using CARLA 0.9.16 client matrices."""
from __future__ import annotations

import json
from pathlib import Path

import carla
import numpy as np

from ultimate_pipeline.carla_tools.thesis_sensor_rig import _pose_to_carla_transform
from ultimate_pipeline.sensors.dominik_sensor_setup import DominikSensorSetup
from ultimate_pipeline.sensors.transform_conventions import (
    carla_attachment_pose_from_matrix,
    carla_ego_from_camera_from_cTv,
    carla_ego_from_lidar_from_vTl,
)
from ultimate_pipeline.sensors.attach_sensors_safe import _carla_transform_from_vehicle_to_sensor


root = Path(__file__).resolve().parents[2]
calibration_path = root / "ultimate_pipeline" / "sensors" / "calib_data.json"
data = json.loads(calibration_path.read_text(encoding="utf-8"))
dominik = DominikSensorSetup(str(calibration_path))
rows = {}
for name, camera in sorted(data["cameras"].items()):
    expected = carla_ego_from_camera_from_cTv(camera["cTv"])
    pose = carla_attachment_pose_from_matrix(expected)
    thesis_transform, _ = _pose_to_carla_transform(pose)
    dominik_pose = dominik._parse_camera_transform(camera)
    dominik_transform = carla.Transform(
        carla.Location(x=dominik_pose["x"], y=dominik_pose["y"], z=dominik_pose["z"]),
        carla.Rotation(roll=dominik_pose["roll"], pitch=dominik_pose["pitch"], yaw=dominik_pose["yaw"]),
    )
    attach_transform = _carla_transform_from_vehicle_to_sensor(camera["cTv"], camera_optical_frame=True)
    matrices = {
        "thesis_sensor_rig": np.asarray(thesis_transform.get_matrix(), dtype=float),
        "dominik_sensor_setup": np.asarray(dominik_transform.get_matrix(), dtype=float),
        "attach_sensors_safe": np.asarray(attach_transform.get_matrix(), dtype=float),
    }
    rows[name] = {key: float(np.max(np.abs(value - expected))) for key, value in matrices.items()}
for name in ("middle_lidar",):
    source = data["lidars"][name]["vTl"]
    expected = carla_ego_from_lidar_from_vTl(source)
    pose = carla_attachment_pose_from_matrix(expected)
    thesis_transform, _ = _pose_to_carla_transform(pose)
    dominik_pose = dominik._parse_lidar_transform(data["lidars"][name])
    dominik_transform = carla.Transform(
        carla.Location(x=dominik_pose["x"], y=dominik_pose["y"], z=dominik_pose["z"]),
        carla.Rotation(roll=dominik_pose["roll"], pitch=dominik_pose["pitch"], yaw=dominik_pose["yaw"]),
    )
    attach_transform = _carla_transform_from_vehicle_to_sensor(source, camera_optical_frame=False)
    matrices = {
        "thesis_sensor_rig": np.asarray(thesis_transform.get_matrix(), dtype=float),
        "dominik_sensor_setup": np.asarray(dominik_transform.get_matrix(), dtype=float),
        "attach_sensors_safe": np.asarray(attach_transform.get_matrix(), dtype=float),
    }
    rows[name] = {key: float(np.max(np.abs(value - expected))) for key, value in matrices.items()}
report = {
    "verification_mode": "offline_adapter_pose_conversion_no_actor_spawn",
    "carla_client_module": carla.__file__,
    "sensors": rows,
    "maximum_matrix_abs_error": max(max(values.values()) for values in rows.values()),
}
output = json.dumps(report, indent=2, sort_keys=True) + "\n"
print(output, end="")
(root / "reports" / "v127" / "RIG_SPAWN_PATH_PARITY.json").write_text(output, encoding="utf-8")
