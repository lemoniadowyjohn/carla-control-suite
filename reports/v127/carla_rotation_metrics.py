"""Deterministic CARLA 0.9.16 client-only rotation reconstruction metrics."""
from __future__ import annotations

import json
from pathlib import Path

import carla
import numpy as np

from ultimate_pipeline.sensors.transform_conventions import carla_rotation_matrix_to_rpy_deg


rng = np.random.default_rng(127)
matrix_max_abs = 0.0
angle_max_deg = 0.0
for _ in range(200):
    roll = float(rng.uniform(-180.0, 180.0))
    pitch = float(rng.uniform(-89.0, 89.0))
    yaw = float(rng.uniform(-180.0, 180.0))
    source = carla.Transform(carla.Location(), carla.Rotation(roll=roll, pitch=pitch, yaw=yaw))
    source_matrix = np.asarray(source.get_matrix(), dtype=float)[:3, :3]
    out_roll, out_pitch, out_yaw = carla_rotation_matrix_to_rpy_deg(source_matrix)
    rebuilt = carla.Transform(
        carla.Location(), carla.Rotation(roll=out_roll, pitch=out_pitch, yaw=out_yaw)
    )
    rebuilt_matrix = np.asarray(rebuilt.get_matrix(), dtype=float)[:3, :3]
    matrix_max_abs = max(matrix_max_abs, float(np.max(np.abs(rebuilt_matrix - source_matrix))))
    relative = source_matrix.T @ rebuilt_matrix
    skew = np.asarray(
        [relative[2, 1] - relative[1, 2], relative[0, 2] - relative[2, 0], relative[1, 0] - relative[0, 1]]
    )
    angle = np.arctan2(np.linalg.norm(skew) / 2.0, (np.trace(relative) - 1.0) / 2.0)
    angle_max_deg = max(angle_max_deg, float(np.degrees(angle)))

pitch_forward = carla.Rotation(pitch=51.0).get_forward_vector()
roll_right = carla.Rotation(roll=51.0).get_right_vector()
report = {
    "verification_mode": "client_api_only_no_server",
    "carla_client_module": carla.__file__,
    "randomized_poses": 200,
    "seed": 127,
    "matrix_reconstruction_max_abs_error": matrix_max_abs,
    "rotation_geodesic_max_error_deg": angle_max_deg,
    "pitch_positive_forward_z": float(pitch_forward.z),
    "roll_positive_right_z": float(roll_right.z),
    "actual_carla_signs_verified": bool(pitch_forward.z > 0 and roll_right.z < 0),
}
output = json.dumps(report, indent=2, sort_keys=True) + "\n"
print(output, end="")
(Path(__file__).with_name("CARLA_ROTATION_COMPATIBILITY.json")).write_text(output, encoding="utf-8")
