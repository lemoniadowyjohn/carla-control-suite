# WP-C Windows CARLA 0.9.16 live acceptance

This procedure is intentionally separate from CARLA-free unit tests. Do not
interpret a successful mock, RPC probe, generated K matrix or image file as live
intrinsic acceptance.

## Preconditions

1. Use a clean checkout of the final reviewed WP-C commit with the thesis
   calibration file SHA recorded in the implementation report.
2. Use CARLA 0.9.16 server and Python API, the approved Ingolstadt map, a disposable
   nonprivileged Windows identity, and an empty output directory outside the repo.
3. Start CARLA using the approved server procedure. Confirm RPC and exact map
   identity; do not rely on a listening port.
4. Supply an independently reviewed annotation JSON only after the frame manifest
   and image/LiDAR hashes have been generated. Annotation schema is described by
   `score_camera_annotations` and `score_lidar_camera_annotations` in
   `ultimate_pipeline/tools/verify_camera_intrinsics_live.py`.

## Capture

From the repository root in PowerShell:

```powershell
python ultimate_pipeline/tools/verify_camera_intrinsics_live.py `
  --calibration ultimate_pipeline/sensors/calib_data.json `
  --output D:\CARLA_EVIDENCE\wp-c-<candidate-sha> `
  --expected-map "<exact-world.get_map().name>"
```

The tool fails closed if CARLA is unavailable, version/map mismatch occurs, any of
the six cameras or active LiDAR fails to spawn, attachment/readback differs, a
callback is absent/stale, or sensor frame IDs/timestamps differ. Preserve the
entire output directory and do not reuse it for another run.

## Independent residual assessment

For each of the six camera frames, annotate at least eight unique, identifiable
3D landmarks with vehicle-frame coordinates and observed image pixels. Bind each
annotation to exact `frame_id` and image SHA. For LiDAR-camera comparison, bind
each observed pixel to an actual indexed LiDAR return and exact LiDAR-data SHA.
Then run the scoring functions in the tool against those annotations and captured
bytes. Reject digest mismatch, duplicates, out-of-frame predictions, malformed
point clouds and missing per-camera support.

Thresholds are fixed by `live_calibration_assay.ACCEPTANCE_THRESHOLDS`: mean <=
2 px, p95 <= 4 px, max <= 8 px, and at least eight independent observations for
each camera. Review residual distributions and landmark quality; do not change
thresholds to obtain a pass. Generate a v2 calibration receipt from the final
clean commit, exact calibration, runtime sensor/settings identities and capture
dataset only after all bytes exist.

## Verdict rules

- Missing server or unavailable CARLA RPC: `BLOCKED_EXTERNAL`.
- Failed spawn, mismatched frame, invalid transform, missing sensor or residual
  threshold violation: `FAIL`.
- Capture and residual calculations completed but no independent review:
  `PENDING_INDEPENDENT_REVIEW`.
- Exact intrinsic compliance remains unclaimed until an independent reviewer
  verifies final rendered frames, effective K, masks/remap, calibration identity,
  and the source-bound receipt. This procedure does not itself mark RQ3 admitted
  or scientifically complete.

