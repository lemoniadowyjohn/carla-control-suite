# WP-C verification matrix

| Area | Test or evidence | Assertion | Result |
|---|---|---|---|
| Six-camera K | `test_six_camera_native_k_and_resolution_override_are_explicit` | Native/target K differ explicitly; six cameras and override matrices are enumerated | PASS |
| Runtime resolution clamp | `test_runtime_rig_derives_k_after_resolution_clamp_and_labels_native_approximation` | K follows actual dimensions; rig does not claim remap | PASS |
| Resize/crop | `test_resize_crop_intrinsics_preserve_projected_ray` | Projection follows half-pixel resize and crop transform | PASS |
| Invalid geometry | `test_resize_crop_validation_rejects_invalid_dimensions` | Invalid size, crop, FOV policy and unknown camera fail closed | PASS |
| Modality remap | `test_modality_remap_uses_explicit_mask_and_zeroes_unobserved_pixels` | RGB resamples continuously; semantic/instance IDs remain discrete; invalid pixels masked | PASS |
| Effective K/mask artifacts | `test_effective_intrinsics_bundle_exports_hash_bound_valid_mask` | K, mask SHA and coverage are linked; no exact compliance claim | PASS |
| Source/data receipt | `test_receipt_binds_clean_source_calibration_intrinsics_sensors_settings_and_dataset` | Clean commit, calibration, K, sensors, settings and dataset hashes bind; stale data rejected | PASS |
| Empty/incomplete evidence | `test_receipt_refuses_empty_dataset_or_incomplete_sensor_identity` | Empty dataset rejected | PASS |
| Projection/unprojection | `test_projection_unprojection_and_optical_axis_round_trip`; `test_known_landmark_projection_roundtrips_for_all_six_camera_frames` | Optical rays and six camera transforms round-trip numerically | PASS (offline numerical) |
| Camera/LiDAR residual scorer | `test_mock_rendered_camera_and_lidar_correspondences_are_numerical_only` | Scores fixture correspondences and labels them calculation-only | PASS (mock; not live) |
| Stale annotation | `test_camera_annotation_stale_frame_hash_is_rejected` | Wrong image digest rejected | PASS |
| Off-image annotation | `test_camera_annotations_reject_observations_outside_rendered_frame` | Out-of-frame measured pixel rejected | PASS |
| Callback frame identity | `test_mock_capture_frame_acquisition_preserves_frame_and_timestamp`; `test_stale_mock_sensor_frame_fails_closed` | World frame/timestamp captured; stale callback fails | PASS (mock) |
| RPC evidence boundary | `test_evidence_pack_rpc_probe_requires_carla_rpc_and_never_claims_rendered_pass` | CARLA RPC reachability is not rendered-frame evidence | PASS (mock RPC client) |
| Focused regression set | Command in implementation report | Existing calibration/rig hardening plus WP-C tests | 131 passed |
| RQ3 map-bound consumers | `test_rq3_paired_capture_contract.py`, `test_rq3_builder_false_pass_regression.py` | 40 pass; 4 stop because pinned XODR omitted from sparse checkout | INCOMPLETE_BLOCKED_SPARSE_INPUT |
| Compile and whitespace | `python -m compileall ...`; `git diff --check` | Syntax and patch whitespace | PASS (before final commit; rerun recorded separately) |
| Full production offline suite | Not run | Requires full source/input checkout and disk capacity | NOT_RUN |
| CARLA 0.9.16 capture/reprojection | Not run; no executable/server RPC | Live spawning/rendered evidence unavailable | BLOCKED_EXTERNAL |

The `PASS` labels above apply only to executed offline tests, including explicit
mock/numerical labels. None is a CARLA runtime or scientific data-admission pass.
