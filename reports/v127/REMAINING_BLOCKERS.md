# V127 Remaining Blockers

## Production and release

1. **Independent exact-source-SHA review — PENDING.** Prior conditional review covered d1c35b6; the source-mount bypass was fixed in f317d244, and selected calibration bytes were propagated in dafafe3613f7ce5acd2222a7cbe18c8eb000e61c. Independent review of the final branch head bb8c18ded235250ed42e84b32f879e6fe61d56c is pending.
2. **Candidate publication — COMPLETE.** The isolated branch is pushed and draft PR #66 targets the pinned production SHA. The PR remains draft; no merge is authorized.
3. **Full offline production CI — INCOMPLETE.** The prescribed whole-tree pytest command stopped at collection: 3,261 discovered items, 292 collection errors, 1 skipped (pytest exit 2). The sparse checkout lacks numerous source paths/modules; this Python install also lacks `torchvision` and `cryptography`. Baseline source-path attribution: all 292 failing test files exist at the exact baseline; 137 imports point to baseline-tracked files omitted by sparse checkout, 116 import modules do not exist in the baseline tree, 33 are dependency/import-environment errors, and 6 are unrelated import API errors in unchanged test/source paths. The full test suite was not replayed on baseline; this is not a baseline JUnit receipt.

## Runtime and camera science

4. **CARLA 0.9.16 live runtime — BLOCKED_EXTERNAL.** No server/RPC, actor spawn, rendered frame, timestamped live recorder output, or runtime receipt was produced. Offline fake/client checks do not satisfy this gate.
5. **Rendered intrinsics and reprojection — NOT_VERIFIED.** The v2 receipt records nominal K from configured width/FOV and the requested calibration K, but rendered dimensions, principal-point/fy behavior, remapping, valid masks, landmark reprojection, and LiDAR-camera correspondence require WP-C runtime evidence. Exact intrinsic compliance must not be claimed.
6. **RQ3 paired Ingolstadt evidence — NOT_RUN.** No paired manual/OSM capture or independent dataset admission was performed.
7. **RQ5 training/evaluation — NOT_RUN.** No model training or evaluation claim follows from this calibration implementation.

## Executed offline test evidence

The independent reviewer conditionally accepted prior source SHA d1c35b6. Adversarial inspection later found that a fully resealed wrong mount could pass; f317d244 added source-derived matrix comparison and rejected the 25 cm case. Commit dafafe3613f7ce5acd2222a7cbe18c8eb000e61c propagates exact selected calibration bytes through runtime and paired capture. Exact-head review is pending. Signed reviewer-receipt tests remain unexecuted locally because cryptography is unavailable.

- Focused calibration/RQ3/adapter suite: 474 passed, 6 warnings, exit 0 on source commit dafafe3613f7ce5acd2222a7cbe18c8eb000e61c.
- Wider collectable RQ3 suite: 162 passed, 5 warnings, exit 0. Four modules remain NOT_RUN because cryptography or repository-level tools imports are absent.
- Full offline pytest: 3,261 collected/discovered, 292 collection errors, 1 skipped, exit 2. The baseline suite was not replayed.
- compileall over ultimate_pipeline, tests and submission/infrastructure: exit 0.
- CRLF-aware git diff --check: exit 0; the plain check flags pre-existing Windows CRLF lines in tracked report/source paths.

## Other independent QA findings

The full QA report's 12 findings are retained here with scope disposition:

| QA issue | V127 disposition | Evidence/status |
|---|---|---|
| 1. Incorrect transform inversion/handedness | **ADDRESSED_OFFLINE** | Source-frame oracle formulas, all-six-camera/active-LiDAR tests, mutation controls, exact expected source positions. |
| 2. Candidate acceptance missed wrong transforms | **ADDRESSED_OFFLINE** | Complete matrix and basis-vector checks with CARLA 0.9.16 client matrices; reflected/nonorthogonal candidates fail. |
| 3. RQ3 rig digest omitted applied convention/identity | **SOURCE_MATRIX_BOUND; UNATTESTED** | V2 validates requested and observed matrices against transforms independently derived from SHA-bound trusted calibration bytes; the re-sealed wrong-mount negative control fails. It remains `UNATTESTED_SELF_REPORTED`; signed independent RQ3 review is still required for scientific admission. No live receipt exists. |
| 4. Production XML admission | **SEPARATE_RELEASE_WORK_PACKAGE** | PR #30 is not merged here; XML/DOCTYPE verification and K2 review remain separate. |
| 5. Stale v1 receipt promotion | **ADDRESSED_IN_SOURCE** | V1 stays readable historically but is rejected by live v2 validators. |
| 6. Reachable legacy SensorRig | **ADDRESSED_IN_SOURCE** | Legacy `SensorRig.spawn_rig` and anonymous matrix converter fail closed; regression test added. |
| 7. Downscaled output dimensions | **WP-C / LIVE_BLOCKED** | No final rendered frame was measured; no exact resolution claim. |
| 8. Map registry CRS authority text | **SEPARATE_MAP_WORK_PACKAGE** | No map registry, CRS, or map pin changes made. |
| 9. fy/fx and principal point fidelity | **WP-C / NOT_VERIFIED** | Requested and nominal matrices are both recorded; this branch does not fabricate CARLA support for unequal focal lengths or principal points. |
| 10. OpenCode fake `sys.modules['carla']` leak | **SEPARATE_OPENCode_REMEDIATION** | No edits to OpenCode's branch or test fixtures. |
| 11. RQ1 embedded timestamp determinism | **SEPARATE_RQ1_WORK_PACKAGE** | No historical artifacts or RQ1 signatures changed. |
| 12. Scientific claim boundaries | **PRESERVED; RQ3/RQ5 NOT_RUN** | The candidate reports no RQ3/RQ5 success and leaves runtime/research NO-GO. |

## Verdict

Source-level mathematical calibration and offline adapter parity are reviewable. Release acceptance remains **NO-GO** until the full offline gate is run in a complete dependency/input environment, an independent reviewer signs the exact final SHA, and actual CARLA sensor spawn plus rendered-frame verification is complete. RQ3 and RQ5 remain open.
