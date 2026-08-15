# D2 Sensor Calibration Semantics

Date: 2026-08-15

Verdict: `CALIBRATION_SEMANTICS_LOCKED_GREEN`

## Summary

D2 resolves the `use_K_undistortion=true` plus `ignore_K=true` / `ignore_D=true` ambiguity in the CARLA simulation contract.

Locked semantics:

- CARLA cameras are ideal pinhole cameras.
- Raw real-camera `K` and `D` are ignored for simulation.
- `K_undistortion` plus `image_size` defines the effective simulator intrinsics/FOV.
- `cTv` is vehicle-to-camera and is used directly, not inverted.
- `vTl` is LiDAR-to-vehicle and is inverted to produce vehicle-to-LiDAR.

## Canonical Calibration

| Item | Value |
| --- | --- |
| Canonical path | `ultimate_pipeline/sensors/calib_data.json` |
| Source path | `submission/infrastructure/ultimate_pipeline/sensors/calib_data.json` |
| SHA-256 | `054a2d8b706ab8f6e5f7ef63c2e630a7bb7c3d0f3839afa943d2d10476679ce0` |
| Cameras | 6 |
| LiDARs | 2 |

The canonical file is a byte-identical copy of the submission mirror calibration file.

## Evidence

| Check | Result |
| --- | --- |
| Effective camera intrinsics use `K_undistortion` | PASS |
| Raw `K` ignored | PASS |
| Raw `D` ignored | PASS |
| Image size honored | PASS |
| `cTv` direct/not inverted | PASS |
| `vTl` inverted | PASS |
| Canonical file validates | PASS |

Report artifact: `reports/post_audit_hardening/D2_SENSOR_CALIBRATION_SEMANTICS.json`.

## Legacy Hazard

`ultimate_pipeline/sensors/attach_sensors_safe.py` appears to invert a matrix in its generic attachment helper and passes camera `cTv` through that helper. That path is not silently changed here. It should be reviewed before it is used as real capture evidence, because the D2 contract forbids cTv inversion.

## Tests

- Added `tests/unit/test_sensor_calibration_semantics.py`.
- Added `ultimate_pipeline/sensors/calibration_contract.py`.

## ESCALATE_TO_CLAUDE

- Confirm whether `attach_sensors_safe.py` is active in the live capture path. If yes, fix it under a separate task with runtime review because it may invert `cTv` contrary to the locked contract.
