# WP-C camera intrinsic realization report

## Candidate identity and claim boundary

- Branch: `integration/wp-c-camera-intrinsics-20261118`
- Base: production `225ed15d0da6444cc257835ca777aba281553f3c`
- Calibration: `ultimate_pipeline/sensors/calib_data.json`
- Calibration SHA-256: `d3ff2660b11ca56d16c6185e82d1b4c7fa94c5db27bb3469558442d79f4e97d9`
- Acceptance: `PENDING_INDEPENDENT_RENDERED_FRAME_VERIFICATION`; exact intrinsic compliance is not claimed.

The native CARLA camera model is square-pixel pinhole: `fx=fy=W/(2 tan(FOV_h/2))`,
`cx=W/2`, `cy=H/2`. The requested calibration matrices generally have unequal focal
lengths and off-center principal points. The rig therefore reports native K and
target K separately. A remapped image is only an exact geometric realization when
its output pixels, mask and exported effective K come from the same mapping.

## Six-camera audit at 1920x1080

FOV is selected from requested `fx`; native `fx` therefore matches by construction.
Delta is native minus target. Coverage is the fraction of target output pixels
whose inverse mapping samples valid native pixels. The existing coverage threshold
is 0.999; it was not changed for this work.

| Camera | Target fx, fy, cx, cy | Native fx=fy, cx, cy | Delta fx, fy, cx, cy | Coverage | Result |
|---|---|---|---|---:|---|
| back_left_camera | 1650.279, 1874.837, 935.757, 520.579 | 1650.279, 960, 540 | 0, -224.558, 24.243, 19.421 | 0.986979 | bounded approximation |
| back_right_camera | 1755.858, 1972.512, 984.371, 557.452 | 1755.858, 960, 540 | 0, -216.654, -24.371, -17.452 | 0.986979 | bounded approximation |
| front_left_camera | 1621.717, 1834.899, 944.116, 531.885 | 1621.717, 960, 540 | 0, -213.182, 15.884, 8.115 | 0.991667 | bounded approximation |
| front_right_camera | 1660.912, 1873.673, 963.019, 499.733 | 1660.912, 960, 540 | 0, -212.762, -3.019, 40.267 | 0.997917 | bounded approximation |
| left_camera | 896.252, 897.428, 1010.100, 485.498 | 896.252, 960, 540 | 0, -1.177, -50.100, 54.502 | 0.924766 | bounded approximation |
| right_camera | 903.107, 904.381, 1016.053, 453.171 | 903.107, 960, 540 | 0, -1.274, -56.053, 86.829 | 0.892148 | bounded approximation |

`K_undistortion` remains untouched. Resolution overrides (including 1280x720,
960x540 and 640x360) scale target K with the half-pixel sampling convention and
recompute native K from the actual dimensions and FOV. They remain explicitly
non-compliant native approximations unless the rendered output has been remapped,
masked and independently verified.

## Implementation and modality policy

- `camera_intrinsics.py` provides native K derivation, full-matrix projection and
  unprojection, pixel-center resize/crop transforms, realization reports, remap
  maps, and effective-K plus valid-mask artifact writing.
- RGB uses bilinear interpolation. Semantic and instance IDs use nearest-neighbor;
  depth uses nearest-neighbor to preserve measured range values; flow uses nearest.
  Invalid remap pixels are explicitly filled and excluded by the exported mask.
- The rig sets and reads back width, height, FOV and sensor tick. Pixel-budget
  resolution reductions transform K rather than retaining the old matrix.
- `intrinsic_receipt.py` emits v2 content-bound receipts for committed source,
  calibration bytes, all effective K matrices, sensor identities, runtime settings
  and every nonempty dataset file. It does not assert scientific or exact-K pass.
- `verify_camera_intrinsics_live.py` captures real CARLA frames and actual LiDAR
  bytes when a server is available. Annotation scores are residual calculations,
  not independent review or dataset admission.
- Evidence-pack RPC status now comes from CARLA version RPC, not TCP connect. RPC
  reachability alone can never become rendered-frame verification.

## Residual thresholds

The live assay consumes the repository's predeclared thresholds unchanged:
mean <= 2 px, p95 <= 4 px, maximum <= 8 px, with at least 8 independent observed
landmarks per camera. These are screening thresholds for the frozen protocol, not
newly inferred sensor accuracy. Attachment readback uses 1 mm translation and
0.01 degree rotation checks. No thresholds were relaxed. A reviewer must inspect
the annotations and source-bound receipt before any scientific acceptance.

## Verification record

Focused WP-C command and result on the current source (before commit):

```powershell
& 'C:\Users\admin\AppData\Local\Programs\Python\Python312\python.exe' -m pytest ultimate_pipeline/tests/unit/test_wp_c_camera_intrinsic_realization.py ultimate_pipeline/tests/unit/test_perception_environment_hardening_new316_333.py ultimate_pipeline/tests/unit/test_rq3_route_rig_hardening.py ultimate_pipeline/tests/unit/test_integration_runtime_rig_environment_negative_controls.py tests/unit/test_sensor_calibration_semantics.py -q -p no:cacheprovider --tb=short
```

Result: **131 passed in 16.05s**. This is a working-tree result, not a
final-commit-bound receipt.

The RQ3 consumer subset had **40 passed, 4 failed to reach their assertions**
because this sparse worktree does not contain the pinned large Ingolstadt XODR
input; each failure is a `MapRegistryDriftError` for that absent file. They are
`INCOMPLETE_BLOCKED_SPARSE_INPUT`, not product failures or passes. Full offline
production CI is **NOT_RUN**: the full checkout exhausted available disk during
materialization, and the current worktree is sparse. No test is represented as a
pass on the basis of collection or a mock.

CARLA runtime is **BLOCKED_EXTERNAL**. No `CarlaUE4.exe` process or executable was
available; the installed Python API reports 0.9.16, but the 127.0.0.1:2000 CARLA
RPC probe timed out. No simulator was launched. No rendered frame, reprojection
or LiDAR correspondence residual has been measured in this run.

## Per-camera result status

| Gate | Status |
|---|---|
| Calibration file identity and unchanged bytes | PASS (source hash recorded above) |
| Native K math and supported size transforms | Offline tests; final rerun required |
| Modality-safe remap and valid-mask math | Offline tests; final rerun required |
| Native rendered K matches target K | FAIL as an exact claim; six-camera audit shows residuals |
| Captured-frame intrinsic realization | BLOCKED_EXTERNAL |
| Camera landmark residuals | NOT_RUN |
| LiDAR-camera correspondence residuals | NOT_RUN |
| Independent calibration review | NOT_RUN |
| Full offline production CI | NOT_RUN |
