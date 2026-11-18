# V127 Remaining Blockers

## Production and release

1. **Independent exact-source-SHA review — CONDITIONAL ACCEPT.** Review of exact candidate SHA `d1c35b6ca3daa4b3e3da26515ef521dc581019de` found no confirmed code blocker and confirmed that prior receipt-authority, canonical calibration-path trust, and submission-mirror findings are closed. Signed-review tests still need a dependency-complete run because `cryptography` is absent locally.
2. **Candidate publication — PENDING.** Remote production was refreshed and confirmed at the exact base SHA. The isolated branch and reviewable report commit must be pushed, then a PR opened; no merge is authorized.
3. **Full offline production CI — INCOMPLETE.** The prescribed whole-tree pytest command stopped at collection: 3,260 discovered items, 292 collection errors, 1 skipped (pytest exit 2). The sparse checkout lacks numerous source paths/modules; this Python install also lacks `torchvision` and `cryptography`. Failures were not exhaustively replayed against exact baseline, so baseline-versus-candidate attribution remains incomplete.

## Runtime and camera science

4. **CARLA 0.9.16 live runtime — BLOCKED_EXTERNAL.** No server/RPC, actor spawn, rendered frame, timestamped live recorder output, or runtime receipt was produced. Offline fake/client checks do not satisfy this gate.
5. **Rendered intrinsics and reprojection — NOT_VERIFIED.** The v2 receipt records nominal K from configured width/FOV and the requested calibration K, but rendered dimensions, principal-point/fy behavior, remapping, valid masks, landmark reprojection, and LiDAR-camera correspondence require WP-C runtime evidence. Exact intrinsic compliance must not be claimed.
6. **RQ3 paired Ingolstadt evidence — NOT_RUN.** No paired manual/OSM capture or independent dataset admission was performed.
7. **RQ5 training/evaluation — NOT_RUN.** No model training or evaluation claim follows from this calibration implementation.

## Executed offline test evidence

Independent reviewer exact-SHA disposition: conditional accept, no confirmed source blocker; reviewer independently ran 100 focused checks. The signed review-receipt tests remain unexecuted locally because `cryptography` is missing.

- Focused calibration/RQ3/adapter suite: 470 passed, 6 warnings, exit 0 on source commit `d1c35b6ca3daa4b3e3da26515ef521dc581019de`.
- Wider collectable RQ3 suite: 161 passed, 5 warnings, exit 0. Four modules remain NOT_RUN because `cryptography` or repository-level `tools` imports are absent.
- `compileall`: exit 0. CRLF-aware committed diff check: exit 0.

## Other independent QA findings

The full QA report's 12 findings are retained here with scope disposition:

| QA issue | V127 disposition | Evidence/status |
|---|---|---|
| 1. Incorrect transform inversion/handedness | **ADDRESSED_OFFLINE** | Source-frame oracle formulas, all-six-camera/active-LiDAR tests, mutation controls, exact expected source positions. |
| 2. Candidate acceptance missed wrong transforms | **ADDRESSED_OFFLINE** | Complete matrix and basis-vector checks with CARLA 0.9.16 client matrices; reflected/nonorthogonal candidates fail. |
| 3. RQ3 rig digest omitted applied convention/identity | **CONSISTENCY_ONLY; UNATTESTED** | V2 records the observed-data claim and hashes for accidental-change detection. It is explicitly `UNATTESTED_SELF_REPORTED`; only the existing signed independent RQ3 review gate can authorize scientific admission. No live receipt exists. |
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
