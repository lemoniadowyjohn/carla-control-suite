# V127 P0 Calibration Candidate Reconciliation

## Candidate identity

- Production baseline requested: `225ed15d0da6444cc257835ca777aba281553f3c`.
- New isolated branch: `integration/v127-calibration-p0-20261118`.
- New worktree: `G:/CARLA_RECOVERY/worktrees/v127-calibration-p0-20261118`.
- The candidate worktree HEAD was created at the requested baseline SHA. A fresh `git ls-remote` on 2026-11-18 confirmed the remote production branch still equals `225ed15d0da6444cc257835ca777aba281553f3c`; no remote V127 branch exists yet.
- Calibration source SHA-256: `d3ff2660b11ca56d16c6185e82d1b4c7fa94c5db27bb3469558442d79f4e97d9`. `calib_data.json` is unchanged.
- No source calibration, map pin, historical receipt, or experiment output was rewritten.

## Reconciliation decisions

| Input | Exact commit/ref | Decision |
|---|---|---|
| WP-A | `fa6cc89628a79116d2be78bc3c842f5e8f739e30` | Not integrated. Its mirrored geometry fails the independent source-frame oracle. Preserve original worktree and branch. |
| Codex rig candidate | `c517e4859cda9b082b148950882379b5612704d2` | Used only as a source of verified position work; its angle clamp and Euler signs are not retained. No cherry-pick. |
| OpenCode clamp fix | `82337c198d023d59e571f0f1754d68e497ba1e7e` | Reimplemented the valid position-only limit; no blind merge and no changes to its worktree. |
| Codex integration candidate | `f8c37f6c7883953294e631a1d20a838914df618b` | Not used as a base; it is not the requested production baseline. |
| PR #62 | head `c517e4859cda9b082b148950882379b5612704d2` | Alternative transform implementation not merged; it has incorrect CARLA pitch/roll signs. |
| PR #51 | head `f544379f9cec2fc3404e82d88c9db89d8c5ebee9` | Explicit calibration-selection refusal retained and tested. |
| PR #53 | head `ab3e60c53247a2acc15b67fac46bd95655238452` | Nonvacuous frame/modality completeness retained and tested. |
| PR #30 | head `21dce53c` | XML/DOCTYPE admission is a separate release work package; not included in this calibration candidate. |

The branch is a new implementation against the exact requested baseline. It does not rewrite or alter WP-A, PR #62, the OpenCode branch, PR #51, PR #53, or production. No source changes were cherry-picked from the candidate branches; verified behavior was independently implemented against the QA fixture and client API.

## Corrected convention

Source vehicle coordinates are right-handed FLU (forward, left, up). CARLA parent coordinates are forward, right, up. Camera source `cTv` maps vehicle FLU to OpenCV optical coordinates. LiDAR source `vTl` maps LiDAR to vehicle FLU. The child mount is explicit parent-from-child:

- Camera: `T_carla_ego_from_carla_camera = S_vehicle @ inverse(cTv) @ M_optical`, where `S_vehicle = diag(1,-1,1,1)` and `M_optical` maps OpenCV optical axes into CARLA camera axes.
- LiDAR: `T_carla_ego_from_carla_lidar = S_vehicle @ vTl @ S_lidar`, where `S_lidar = diag(1,-1,1,1)` converts the source LiDAR basis to CARLA's basis.

Rotations are proper rigid transforms with determinant +1. The 50 metre bound applies only to translation. Euler extraction follows the installed CARLA 0.9.16 `Rotation`/`Transform.get_matrix()` behavior; no Euler sign guess is used. Invalid, reflected, nonorthogonal, missing, or nonfinite source transforms fail closed.

## Source integration summary

- Centralized named frame conversion in `ultimate_pipeline/sensors/transform_conventions.py`; retained legacy helper signatures only as versioned, fail-closed compatibility wrappers.
- Reconciled `ThesisSensorRig`, `DominikSensorSetup`, and `attach_sensors_safe` to the same v2 matrix conversion.
- Removed angle clamping from thesis/Dominik sanitizers. Only position components are range checked.
- Switched Dominik LiDAR spec selection to `resolve_active_lidars`; no fixed `middle_lidar` assumption remains in the active adapter.
- Added `APPLIED_SENSOR_RIG/v2` with requested and observed matrices, source/code identity, blueprint/effective camera metadata, actor identities, runtime frame/timestamp, dataset digest, fixed residual caps, and sealed digests. Live validation now derives the expected mounts from exact trusted calibration bytes and rejects internally consistent, re-sealed wrong matrices.
- Recorder artifacts now bind callback/file frame IDs, simulation timestamps, byte hashes, actor IDs, and type IDs. Receipt binding rejects a same-name replacement actor.
- Live consistency validation requires the repository-owned calibration bytes and rejects v1 receipts. Status-declared paths are compared against the canonical repo path, not used as a trust source. V2 self-hashes are explicitly unattested; the existing signed RQ3 review receipt remains mandatory for scientific admission.
- Kept native camera intrinsics explicitly nominal/unverified. Rendered frame dimensions and reprojection are not qualified here.
- Synchronized all changed submission mirrors byte-for-byte to their canonical source paths and verified SHA-256 parity.
- Preserved PR #51/#53 fail-closed calibration selection and modality completeness behavior.
- Disabled legacy `SensorRig.spawn_rig` and anonymous matrix conversion; old receipts remain historical and cannot pass v2 live admission.

## Independent oracle

`SENSOR_FRAME_ORACLE_RESULTS.json` was produced by the independent formula in `oracle_metrics.py` and the installed CARLA 0.9.16 client package. The reported per-sensor CARLA matrix maximum absolute error is at most `1.18e-7`; maximum translation residual is at most `6.11e-8 m`. CARLA 0.9.16 Euler reconstruction was separately sampled over 200 rotations; details are in `CARLA_ROTATION_COMPATIBILITY.json`.

The original QA `harness.py` ran all three adapters against its fake CARLA world for all six cameras and the active middle LiDAR. The stored output is `QA_FAKE_CARLA_HARNESS.log`. That harness is offline mock evidence, not a server run.

Independent review of `1f6ac6bbaa3c54be10508b451497f11595c7e113` requested changes for receipt attestation scope and a missing submission mirror. Commits `df9f48305a8c9dcc7ed5145109901bbe01d31377` and `d1c35b6ca3daa4b3e3da26515ef521dc581019de` addressed those findings; the reviewer conditionally accepted `d1c35b6ca3daa4b3e3da26515ef521dc581019de`. Follow-up adversarial inspection found the v2 validator did not compare self-reported matrices with matrices derived from trusted calibration bytes. Commit `f317d2445f8fe9752e75fbe52a8f361990ee6a85` closes that gap. Independent review of `f317d2445f8fe9752e75fbe52a8f361990ee6a85` is pending.

## Gate status

- Source transform math, client-side CARLA matrix conversion, three-adapter pose parity, position-only sanitization, receipt negative controls: **PASS offline**.
- Focused calibration/RQ3/sensor-adapter suite: **PASS**, 474 passed, 6 warnings on source commit `f317d2445f8fe9752e75fbe52a8f361990ee6a85`, with `PYTHONPATH` pinned to the candidate. The wider RQ3 regression set passed 162 tests; four additional modules were not collectable (two require absent `cryptography`, two import absent repository-level `tools`).
- Affected broader offline suites: **PASS** for executed cases (161 RQ3 cases); four modules are explicitly NOT_RUN due absent dependencies/source paths.
- Full repository offline pytest: **INCOMPLETE**. The sparse checkout collected 3,261 items but hit 292 collection errors due absent source modules/files and missing installed optional dependencies; one item was skipped. Source-level comparison against the exact production tree found all 292 failing test files already existed at baseline: 137 import modules are tracked but absent from the sparse checkout; 116 import modules are absent from the production tree; 33 errors are environment dependency/import failures; and 6 unchanged test/source pairs have unrelated import API errors. The whole baseline suite was not re-executed, so this is source-path attribution rather than a baseline test receipt. No successful full-suite claim is made.
- Compilation and CRLF-aware `git -c core.whitespace=cr-at-eol diff --check`: **PASS**; plain `git diff --check` flags CRLF in the canonical Windows route recorder.
- Live CARLA actor spawn, six-camera rendering, sensor timestamps, applied-transform runtime receipt, and reprojection: **BLOCKED_EXTERNAL / NOT_RUN**.
- Exact native `K_undistortion` compliance and final rendered frame geometry: **NOT_VERIFIED**; handled by WP-C and requires actual final-frame qualification.
- RQ3 paired Ingolstadt capture and all RQ5 training/evaluation claims: **NOT_RUN**.

Production remains **NO-GO**. No merge was performed.
