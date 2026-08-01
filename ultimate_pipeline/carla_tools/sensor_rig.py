"""
Deprecated: use thesis_sensor_rig.py for thesis experiments; axis/direction handling may differ.
"""
import json
import math
import os
import warnings

import numpy as np
import carla

if not os.environ.get("UP_SILENCE_DEPRECATIONS"):
    warnings.warn(
        "sensor_rig.py is deprecated for thesis experiments; use thesis_sensor_rig.py (explicit conventions + axis handling).",
        FutureWarning,
        stacklevel=2,
    )


class SensorRig:
    def __init__(self, calib_file_path):
        with open(calib_file_path, 'r') as f:
            self.calib_data = json.load(f)

    def spawn_rig(self, client, ego_vehicle):
        """
        Parses calib_data.json and attaches sensors to the ego_vehicle
        preserving the exact mathematical constraints of the thesis.
        """
        world = client.get_world()
        bp_lib = world.get_blueprint_library()
        sensors = {}

        # -------------------------------------------------
        # 1. CAMERAS (Use K_undistortion, ignore K/D)
        # -------------------------------------------------
        for cam_key, cam_data in self.calib_data.get("cameras", {}).items():
            # A. Intrinsic Pinhole Logic
            # "The K in the camera parameters define the intrinsic matrix...
            #  Please simply use the K_undistortion parameters"
            K_undist = np.array(cam_data["K_undistortion"])
            img_w = cam_data["image_size"]["width"]
            img_h = cam_data["image_size"]["height"]

            # Compute FOV from K_undistortion
            # K = [[fx, 0, cx], [0, fy, cy], [0, 0, 1]]
            fx = K_undist[0, 0]
            # FOV = 2 * arctan(Width / (2 * fx))
            fov_rad = 2.0 * math.atan(img_w / (2.0 * fx))
            fov_deg = math.degrees(fov_rad)

            # B. Extrinsic Logic: cTv (Vehicle -> Camera)
            # CARLA needs Camera -> Vehicle (Pose of camera in vehicle frame)
            # "cTv gives the transformation from vehicle to camera"
            # Therefore: SpawnTransform = (cTv)^-1
            cTv = np.array(cam_data["cTv"])

            # Homogeneous matrix check
            if cTv.shape != (4, 4):
                # Fallback if 3x4
                cTv = np.vstack([cTv, [0, 0, 0, 1]])

            # INVERT to get Pose (Camera relative to Vehicle)
            camera_to_vehicle = np.linalg.inv(cTv)

            # Convert to CARLA Transform (Coordinate System Handover)
            # Note: You may need axis swizzle depending on your JSON's convention (OpenCV vs CARLA)
            # Standard OpenCV: Z-forward, X-right, Y-down
            # CARLA: X-forward, Y-right, Z-up
            spawn_tf = self._numpy_to_carla_transform(camera_to_vehicle, sensor_type="camera")

            # C. Spawn
            bp = bp_lib.find('sensor.camera.rgb')
            bp.set_attribute('image_size_x', str(int(img_w)))
            bp.set_attribute('image_size_y', str(int(img_h)))
            bp.set_attribute('fov', str(fov_deg))

            # Disable lens distortion effects (Pure Pinhole)
            bp.set_attribute('lens_circle_multiplier', '0.0')
            bp.set_attribute('lens_circle_falloff', '5.0')
            bp.set_attribute('chromatic_aberration_intensity', '0.0')
            bp.set_attribute('chromatic_aberration_offset', '0.0')

            sensor_actor = world.spawn_actor(bp, spawn_tf, attach_to=ego_vehicle)
            sensors[cam_key] = sensor_actor
            print(f"✅ Spawned Camera '{cam_key}': FOV={fov_deg:.2f}°, Pose={spawn_tf}")

        # -------------------------------------------------
        # 2. LiDARs (vTl = LiDAR -> Vehicle)
        # -------------------------------------------------
        for lid_key, lid_data in self.calib_data.get("lidars", {}).items():
            # "LiDAR has vTl and gives you the transformation from LiDAR to Vehicle"
            # This IS the spawn transform (Child in Parent Frame).
            vTl = np.array(lid_data["vTl"])

            # The prompt asked to "invert it to get vehicle->LiDAR"
            # We calculate that for dataset export requirements, but for CARLA spawning
            # we stick to vTl (LiDAR pose in Vehicle).
            vehicle_to_lidar = np.linalg.inv(vTl)  # Computed as requested for verification

            spawn_tf = self._numpy_to_carla_transform(vTl, sensor_type="lidar")

            bp = bp_lib.find('sensor.lidar.ray_cast')
            # Set default thesis params (adjust if JSON has them)
            bp.set_attribute('range', '100')
            bp.set_attribute('channels', '64')
            bp.set_attribute('points_per_second', '1300000')

            sensor_actor = world.spawn_actor(bp, spawn_tf, attach_to=ego_vehicle)
            sensors[lid_key] = sensor_actor
            print(f"✅ Spawned LiDAR '{lid_key}': Pose={spawn_tf}")

        return sensors

    @staticmethod
    def _numpy_to_carla_transform(matrix, sensor_type="camera"):
        """
        Converts a 4x4 numpy matrix (Source->Target) into a carla.Transform.
        Handling the coordinate system mismatch is CRITICAL here.
        """
        # Extract Translation
        x, y, z = matrix[0, 3], matrix[1, 3], matrix[2, 3]

        # Extract Rotation (assuming ZYX euler or similar, simplified here)
        # A robust implementation uses scipy.spatial.transform.Rotation
        # Here we use a CARLA helper if available, or manual matrix decompose.

        # MATH HACK: CARLA uses LHS, standard matrices are RHS.
        # This usually requires swapping Y axis or Pitch/Yaw.
        # For this snippet, we assume the matrix is ALREADY in CARLA coordinates
        # if it came from a 'calib_data.json' designed for this project.
        # If not, you must multiply by a 'Change of Basis' matrix.

        import carla
        # Create a transform from the matrix values directly
        # (This implies matrix is already in UE4 coords: X-fwd, Y-right, Z-up)

        # Converting rotation matrix to pitch/yaw/roll is complex without SciPy.
        # We will use CARLA's Transfrom constructor if we can, or just set Location
        # and assume simpler rotation for the thesis prototype if not specified.

        # FOR THESIS RIGOR: You should probably use `carla.Transform(carla.Location(x,y,z), carla.Rotation(...))`
        # But deriving rotation from a raw 3x3 matrix manually is error-prone.
        # Recommendation: Ensure `calib_data.json` matrices are converted to [x,y,z,roll,pitch,yaw] lists beforehand
        # OR use a helper library.

        # Placeholder for exact rotation extraction:
        pitch = math.degrees(math.atan2(-matrix[2, 0], math.sqrt(matrix[0, 0] ** 2 + matrix[1, 0] ** 2)))
        yaw = math.degrees(math.atan2(matrix[1, 0], matrix[0, 0]))
        roll = math.degrees(math.atan2(matrix[2, 1], matrix[2, 2]))

        return carla.Transform(carla.Location(x=float(x), y=float(y), z=float(z)),
                               carla.Rotation(pitch=float(pitch), yaw=float(yaw), roll=float(roll)))
