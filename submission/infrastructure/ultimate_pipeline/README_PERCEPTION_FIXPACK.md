# Perception fixpack

Focus: make STEP10D Local Perception robust and debuggable.

## Fixes
1) Ego spawn robustness:
   - Previously, LocalPerceptionRunner retried the *same* spawn transform (often occupied),
     leading to RuntimeError: "Failed to spawn ego vehicle".
   - Now it tries many spawn points (rotated from spawn_point_index) and optionally shuffles,
     then falls back to waypoint-based manual spawn.

2) Always write artifacts on failure:
   - defects.json and perception_status.json are now written even when spawn fails.
   - perception_status.json includes failure_reason and saved frame counts.

3) Correct LiDAR counters + error tail:
   - _saved_lidars is incremented; failures are recorded in save_errors_tail.

## Added tests
- tests/unit/test_spawn_recovery_multi_transform.py

## Sensor transform contract (cTv, vTl) and CARLA attachment
- cTv in calib_data.json is vehicle→camera. CARLA attachment needs vehicle→sensor, so attach using cTv directly (do not invert).
- vTl in calib_data.json is lidar→vehicle. CARLA attachment needs vehicle→lidar, so attach using inverse(vTl).
- Intrinsics: use K_undistortion only (ignore K and D).

## Apply
Copy the contents of this fixpack into your repo root, overwriting files.
