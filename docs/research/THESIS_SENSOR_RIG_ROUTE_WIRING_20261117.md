# Thesis sensor rig / route wiring: guarded integration boundary (2026-11-17)

## Authority and history preservation
Base: `integration/production-large-map-20260918` at `225ed15d0da6444cc257835ca777aba281553f3c`.
This branch does **not** alter historical source calibration, frozen RQ3/RQ5 protocols,
research results, branch authority, the 37 previously open PRs, or any release acceptance thresholds.
No live CARLA or independent scientific reviewer has verified this branch.

## Geometry: two distinct operations

The calibration's `cTv` is the vehicle-FLU -> OpenCV-camera transform.
The calibration's `vTl` is the source-LiDAR-FLU -> vehicle-FLU transform.
CARLA `spawn_actor(transform, attach_to=ego)` expects the sensor -> vehicle pose
in CARLA's (x-forward, y-right, z-up) basis.

Source frame assumption: sensor calibration uses vehicle and LiDAR right-handed FLU
(x-forward, y-left, z-up). THIS ASSUMPTION REQUIRES LIVE VALIDATION before promoting
scientific evidence.

Let `S = diag(1,-1,1,1)`. Let `C` map CARLA camera coordinates
(x-forward,y-right,z-up) into OpenCV optical (x-right,y-down,z-forward):

```text
C = [ [0, 1,  0, 0],
      [0, 0, -1, 0],
      [1, 0,  0, 0],
      [0, 0,  0, 1] ]
T_mount_camera = S @ inv(cTv) @ C
T_mount_lidar  = S @ vTl @ S
```

Both mounting rotations are proper (det=+1) and preserve source projection
after two basis conversions. Direct cTv is still correct for vehicle->camera
PROJECTION, and inverse(vTl) is still correct for vehicle->LiDAR BACKPROJECTION.
Do not confuse these operations with attachment.

## Backward-compatible evidence fields

Historical v1 rig_verification's `ctv_inverted=false` and `vtl_inverted=true`
are retained as LEGACY PROJECTION/BACKPROJECTION FLAGS only. They no longer
describe the actual CARLA attachment. New v2 runtime sensor rows include
`mounting_ctv_inverted=true` / `mounting_vtl_inverted=false` and
`mounting_matrix_sensor_to_vehicle_carla`; the sensor_contract includes
`carla_attachment_semantics=v2`. All v1 historical receipts retain their bytes.

Important: a downstream validator which tests only historical v1 flags can
approve a logically compatible source report but MUST NOT infer the new sensor
mounting, image calibration, or live reprojection was accepted. Update the
strict evidence admission rule to require a measured v2 mounting receipt.

## Runtime entrypoints and outstanding route work

- `ultimate_pipeline/carla_tools/thesis_sensor_rig.py` -- thesis rig attachment
- `ultimate_pipeline/sensors/dominik_sensor_setup.py` -- LocalPerceptionRunner
  through the same camera/lidar attachment conversion; legacy `flip_vehicle_y`
  is a logged no-op to prevent a second reflection
- `ultimate_pipeline/sensors/attach_sensors_safe.py` -- diagnostic pair runner
  now shares canonical mounting calculations
- `ultimate_pipeline/perception/record_route_fixed.py` -- normal CARLA
  recording exists, but `--strict-rq3` dispatches to a validation call with
  `world=None`, empty stages and empty sensor-frame members. This is NOT
  end-to-end RQ3 route execution
- `ultimate_pipeline/perception/route_execution.py` -- `ego.set_transform`
  is POSE_REPLAY, not physically continuous driving
- `ultimate_pipeline/experiments/thesis/run_perception_capture_pair.py` --
  uses LocalPerceptionRunner; `route_manifest_sha256` remains empty; an
  identical geographic route is NOT proven merely by paired output labels
- `ultimate_pipeline/tools/capture_perception_pair_safe.py` -- diagnostic,
  not scientific authority; historical conditional `apply_transform` path
  requires replacement with verified `set_transform` or a real controller
- `ultimate_pipeline/perception/environment/NEW...` -- native CARLA
  pinhole frames cannot reproduce arbitrary fy/cx/cy; verify remap/crop masks

## Next release blockers (MANDATORY; do not silently pass)

1. Integrate live strict route driving/replay into the actual recording path:
   load and digest-check the same manifest for both maps, validate CRS and
   map-of-record identity, validate every pose on both lane networks, issue
   explicit motion commands, compare observed pose and route coverage.
2. Decide `POSE_REPLAY` vs `CONTINUOUS_DRIVING`; label data correctly.
   Autopilot with a seed does not prove geographic route equivalence.
3. Spawn ALL required sensors, validate active LiDAR and camera transforms
   via CARLA `get_transform()` and vehicle-relative inverse at runtime.
4. Run live checkerboard/AprilTag or landmark reprojection for all cameras,
   plus independently observed LiDAR-camera target correspondences.
5. Validate exact effective K_undistortion, resolution changes, crop/valid
   masks, RGB/semantic/instance nearest-neighbor policies.
6. Validate frame correspondence: CARLA frame IDs, timestamps, poses, RGB,
   segmentation and LiDAR for every required camera and every pair index;
   reject empty/vacuous or stale receipts.
7. Execute both Ingolstadt map arms with exact calibration/vehicle/weather/
   physics/TM/route identity, pinned source hashes and independent QA.
8. Run focused tests, full production CI, and Windows CARLA 0.9.16 live
   6-camera+LiDAR acceptance **on the exact integrated commit**.
9. Do not promote RQ3 or RQ5 science until independent review approves
   the actual live evidence and the RQ5 handoff is accepted.

## Evidence status

Source change is a **candidate, not release**. Never label "fully wired" or
"scientifically accepted" based on source-only tests. Failed or unavailable
live tests must be recorded as NOT_RUN/NO_GO, not PASS.
