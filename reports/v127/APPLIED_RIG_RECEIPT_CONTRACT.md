# APPLIED_SENSOR_RIG/v2 Contract

## Purpose

`APPLIED_SENSOR_RIG/v2` binds the calibration source and v2 mounting convention to the transforms CARLA actually applied, the actors that produced frames, and the exact recorded output bytes. A source-calibration hash or v1 `rig_verification.json` is historical information only; neither proves live sensor mounting.

## Required receipt fields

The validator accepts exactly the v2 top-level field set and rejects missing or unsupported fields:

- `schema`, `calibration_contract_version` (`CARLA_SENSOR_MOUNTING/v2`), `source_calibration_sha256`, `code_commit`.
- `verification_mode`, `verification_status`, `ego_identity`, `sensor_identities`.
- `requested_parent_relative_matrices` and `applied_parent_relative_matrices`, as complete 4x4 parent-relative CARLA matrices for every requested sensor.
- `blueprint_configuration` and `effective_camera_configuration`. Each camera records requested `K_undistortion`, nominal CARLA K, image size, horizontal FOV, and a status that says rendered-frame compliance remains unverified.
- `runtime_measurements`, one per sensor, with a common callback frame ID, simulation timestamp, dataset identity, and dataset-artifact digest.
- Per-sensor residuals and immutable limits: position `0.01 m`, angle `0.1°`.
- `applied_configuration_sha256`, `identity_binding_sha256`, and `receipt_sha256`.

## Trusted mount validation

For live validation, the consumer reads the exact trusted calibration bytes (the repository canonical file by default), verifies their SHA-256 against the independently supplied expected digest, and derives every expected camera and active LiDAR mount from raw `cTv`/`vTl` using the v2 frame contract. It compares both requested and observed matrices against those derived mounts with a 2e-6 absolute matrix tolerance. Missing bytes, digest mismatch, unknown sensor names, or any matrix mismatch fail closed. Receipt self-hashes are not used as the transform oracle.

## Measurement and digest rules

1. Requested mounts are derived from the cached raw calibration bytes; the SHA is taken from those same bytes.
2. Observed mounts are reconstructed as `inverse(T_world_ego) @ T_world_sensor` from actor world transforms. The commanded transform is never copied into the observed field.
3. The applied-configuration digest binds calibration hash, code commit, convention version, complete requested/applied matrices, blueprint configuration, and effective camera configuration.
4. The identity digest binds ego and sensor actor IDs/types. The receipt digest binds every field, including runtime frame/timestamp and dataset digest.
5. Recorder manifest sensor actor ID/type must equal the receipt actor ID/type. Same-name artifacts from a replacement actor fail.
6. The binder rehashes every written file, checks callback and filename frame IDs, checks timestamps, rejects duplicate callbacks, and requires a nonempty intersection across all sensors. A dataset SHA is made from the verified sensor/frame/file-hash records.
7. Live validation requires the expected calibration SHA supplied outside the receipt by the run context, plus the exact bytes selected by the run. A caller cannot choose and self-seal its own expected digest; a custom calibration is admitted only when the caller supplies bytes whose digest matches that external expected SHA.
8. Residual limits are constants in code. A receipt cannot raise them. The validator recomputes recorded residuals and checks camera K matrices, image dimensions, common frames, common timestamps, and shared dataset identity/digest.
9. `offline_source_only` receipts remain inspectable but cannot pass `require_live=True`. V1 receipts remain readable by historical readers and are refused for v2 live admission.

## Producer status

The three source adapters can capture actor identities and observed transforms when invoked with CARLA. Only the thesis capture recorder currently supplies the frame/file manifest binding path. Dominik and `attach_sensors_safe` produce transform-only receipts that are explicitly not accepted as complete live dataset receipts until a recorder binds observed frames and bytes.

The code does not assert exact intrinsics from nominal blueprint FOV. Final rendered image dimensions, pixel remapping, effective K, valid masks, and landmark reprojection remain `NOT_VERIFIED` under WP-C. No live receipt exists for this candidate.


## Authority boundary

The v2 receipt and its SHA-256 fields establish internal consistency and detect accidental changes. They are **not an authenticity proof**: a caller can construct and reseal JSON fields, so every receipt is explicitly labeled `UNATTESTED_SELF_REPORTED`. `verification_status` describes the producer's observed-data completeness claim only. The existing signed independent RQ3 review receipt, bound to the exact capture receipt and dataset bytes, remains the scientific authority gate. The code does not add keys, signatures, or trust roots.
