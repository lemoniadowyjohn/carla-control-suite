# WP-I sensor calibration reconciliation

## Candidate identity and scope

- Production base: `225ed15d0da6444cc257835ca777aba281553f3c`.
- WP-A source commit: `fa6cc89628a79116d2be78bc3c842f5e8f739e30`, parent
  `502dda260abb871b2333191bb33e1e7eecd1ece7`; that parent is not an ancestor
  of the production base. The original WP-A worktree remains untouched.
- PR #62 source: `c517e4859cda9b082b148950882379b5612704d2`.
- PR #51 source: `f544379f9cec2fc3404e82d88c9db89d8c5ebee9`.
- PR #53 source: `ab3e60c53247a2acc15b67fac46bd95655238452`.
- No live CARLA execution or reprojection is claimed by this report.

## Transform ruling

Calibration source transforms retain their original v1 meanings:

- `cTv` maps vehicle FLU points into OpenCV camera optical coordinates.
- `vTl` maps LiDAR FLU points into vehicle FLU coordinates.
- Existing v1 receipt booleans `ctv_inverted=false` and `vtl_inverted=true`
  remain projection/backprojection metadata. They are not reinterpreted as
  CARLA attachment instructions.

CARLA mounting is a separate v2 operation. Let `S = diag(1,-1,1,1)` convert
the right-handed FLU vehicle basis to CARLA forward/right/up, and let `C` map
CARLA camera axes into OpenCV optical axes. The candidate uses
`S @ inverse(cTv) @ C` for cameras and `S @ vTl @ S` for LiDAR. Each output is
checked for a homogeneous last row, orthogonality and determinant `+1`, with
source/mounting round-trip checks. Diagnostic-only legacy flip arguments do
not apply another handedness change.

WP-A's initial test convention treated the standalone OpenCV-to-CARLA basis
relabeling matrix (determinant `-1`) as a sensor rotation and changed v1
receipt flags to mounting semantics. A reflection is not a proper CARLA rigid
rotation, and changing v1 meanings would silently reinterpret old receipts.
Those assertions and flags were not carried forward. PR #62's two-basis
mounting implementation and proper-rotation checks are the selected source
for the v2 conversion.

## Preserved and recovered implementation

- WP-A changes to the two primary rig paths, safe attachment path, and paired
  capture runner were reconciled against production rather than replayed as a
  blind branch merge. WP-A's source commit and original tree remain intact.
- PR #62's canonical mounting matrices and explicit v2 mounting metadata are
  retained in the primary source paths.
- PR #51's exact explicit `--calib-json` selection and missing-file refusal
  are retained with its three regression tests.
- PR #53's invalid/zero completeness refusal and paired frame-set empty-set
  checks are retained with its regression tests.
- Source `calib_data.json` is unchanged. SHA-256:
  `d3ff2660b11ca56d16c6185e82d1b4c7fa94c5db27bb3469558442d79f4e97d9`.
- `validate_carla_mounting_v2` emits `CARLA_SENSOR_MOUNTING/v2`, binds the
  calibration file SHA, and explicitly records
  `live_reprojection_verified=false`.

## File-by-file reconciliation

| File or mirror | Decision and evidence |
|---|---|
| `ultimate_pipeline/sensors/transform_conventions.py` | PR #62 canonical camera/LiDAR mount matrices selected; v1 projection helpers retained. Both output rotations require determinant +1 and round-trip checks. |
| `ultimate_pipeline/sensors/calibration_contract.py` | v1 validation unchanged; separate v2 mount validation added with calibration SHA binding and no live-reprojection claim. |
| `ultimate_pipeline/carla_tools/thesis_sensor_rig.py` | Production spawning uses canonical v2 mounts; calibration is parsed and SHA-256 hashed from the same byte snapshot; v1 flags remain false/true; sensor and report payloads carry v2 matrix and convention metadata. Sensor-report ingestion rejects incompatible flags, missing raw transforms, or a serialized pose inconsistent with v2. |
| `ultimate_pipeline/sensors/dominik_sensor_setup.py` | Canonical pose wrappers retained; compatibility `flip_vehicle_y` is not applied as a second basis flip; report labels identify v2 mounting. |
| `ultimate_pipeline/sensors/attach_sensors_safe.py` | Replaced inverse/relabel sequence with canonical camera and LiDAR matrices; output contract carries v2 label and keeps v1 flags separately. |
| `ultimate_pipeline/tools/run_perception_safe.py` | Strict output validation checks the nested v2 convention, rehashes and parses the calibration source, derives each sensor's canonical mount from its named calibration entry, and requires the receipt matrix and applied pose to match; legacy receipt flags remain v1. |
| `ultimate_pipeline/experiments/thesis/run_perception_capture_pair.py` | PR #51 explicit calibration path fails closed when missing; automatic fallback remains only when no explicit path is supplied. |
| `ultimate_pipeline/perception/rq3_capture_contract.py`, `rq3_frame_set.py` | PR #53 invalid/empty completeness refusals retained; existing frame-set behavior is not relaxed. |
| `ultimate_pipeline/tests/unit/test_transform_conventions.py` | Expectations updated to validate v2 mount semantics while preserving v1 conversion behavior. |
| `agent_sync.yaml`, `ultimate_pipeline/contracts/agent_sync.py` | Restored to exact production-base versions; no calibration contract change was needed. |
| `ultimate_pipeline/perception/record_route_fixed.py` | Restored to exact production-base version; no sensor conversion belongs in the tick/frame publisher. |
| `ultimate_pipeline/tools/validate_thesis_run.py` | Restored to production-base version; no silent reinterpretation of v1 terminal evidence. |
| `ultimate_pipeline/sensors/calib_data.json` | Unmodified; baseline and candidate SHA-256 `d3ff2660b11ca56d16c6185e82d1b4c7fa94c5db27bb3469558442d79f4e97d9`. |
| `submission/infrastructure/ultimate_pipeline/sensors/transform_conventions.py` | Reconciled to canonical primary transform implementation; legacy helper names remain available. |
| `submission/infrastructure/ultimate_pipeline/carla_tools/thesis_sensor_rig.py` and mirror test | Corrected WP-A's direct LiDAR matrix use, fixed uninitialized verification state, enforced v1 flags, added v2 matrix and source-digest reporting from the same loaded byte snapshot, updated stale direction assertions, and added proper-rotation checks. Mirror suite run separately. |
| `submission/infrastructure/ultimate_pipeline/tools/run_perception_safe.py` | Validator checks v1 flags, explicit v2 semantics, selected calibration digest, derives expected mounts from the digest-bound calibration, and checks rigid matrix and applied-pose agreement. |
| Submission mirrors of `attach_sensors_safe.py`, `dominik_sensor_setup.py`, and `experiments/thesis/run_perception_capture_pair.py` | Canonical mount conversion, v2 labels and explicit-path refusal reconciled without replacing the divergent mirror modules wholesale. |
| Submission mirrors of `agent_sync.yaml`, `agent_sync.py`, `record_route_fixed.py`, and `validate_thesis_run.py` | Preserved at production-base semantics; not involved in the v2 mount conversion. |

## Expanded test status

- Focused calibration and RQ3/perception selection after source-binding and mirror-validator regression additions: **325 passed, 2 deselected**. The two deselected dataset-training cases require `torchvision`, which is unavailable in this environment. Five configuration-path warnings are from the sparse checkout.
- Primary strict receipt smoke: **PASS**, canonical calibration defaults -> v2 rig report -> `_rig_verification_contract_errors` returned zero errors. Adversarial tests prove altered raw camera/LiDAR transforms and mismatched calibration file digests are rejected.
- Dedicated RQ3 pair/map-dependent selection after materializing the exact pinned map: **94 passed**.
- Submission mirror rig, safe-runner rig, and explicit-calibration selection: **32 passed** when run with `submission/infrastructure` as the import root.
- `python -m compileall -q ultimate_pipeline submission/infrastructure/ultimate_pipeline tests`: **PASS**, exit `0` after the final mirror source edits.
- Submission mirror rig, safe-runner, and explicit-calibration selection: **35 passed**, using a temporary pytest config from `submission/infrastructure` to ensure imports resolve to the mirror.
- Direct mirror report/validator smoke: **PASS**, both camera and LiDAR v2 matrices validate and v1 booleans remain false/true.
- Full offline suite is **BLOCKED/INCOMPLETE** in the sparse worktree: the latest candidate run collected 3,586 items, then stopped at collection with 244 import errors and 1 skip because source directories outside the materialized sparse set are absent. Two RQ3 evidence suites also require missing `cryptography`. No result from that collection is classified as a candidate failure or as passing CI.
- `git diff --check` on the candidate source/test paths: **PASS**, exit `0`. Whole-tree diff was avoided after the sparse expansion exposed unrelated LFS map payloads; those frozen artifacts are not staged or intentionally changed.

## Release gates

| Gate | Status | Evidence / limitation |
|---|---|---|
| Exact production base | PASS | Candidate HEAD starts at `225ed15d0da6444cc257835ca777aba281553f3c`; this is not WP-A's `502dda26` parent. |
| WP-A preservation | PASS | Original branch/worktree and commit `fa6cc89628a79116d2be78bc3c842f5e8f739e30` were not modified. Candidate cherry-pick was applied without committing and reconciled manually. |
| PR #62 conversion | PASS_OFFLINE_SOURCE | Corrected two-basis v2 mounts and positive determinant checks retained; no standalone reflection is treated as a rotation. |
| PR #51 explicit calibration | PASS_OFFLINE_TESTS | Missing explicit selected file fails rather than falling back; selected-source test passes. |
| PR #53 completeness | PASS_OFFLINE_TESTS | Empty/invalid completeness remains rejected; dedicated tests pass. |
| Focused calibration/RQ3 tests | PASS | 325 passed, 2 deselected because required `torchvision` is unavailable. |
| Full offline production CI | INCOMPLETE | Sparse checkout yielded 245 collection errors from unmaterialized source directories; independent of changed paths. Required `cryptography` is also absent for two evidence suites. |
| `git diff --check` | PASS_SCOPED | Source/test paths only, exit 0; unrelated LFS payloads were excluded. |
| CARLA spawn and reprojection | PENDING_RUNTIME | No CARLA runtime was started and no physical sensor reprojection was measured. |
| Independent review | REQUEST_CHANGES; FIXED_PENDING_REREVIEW | Review reproduced a self-consistent forged mount and identified producer-side digest TOCTOU. Validators now derive expected matrices from verified source bytes; both rig producers hash the same byte snapshot used to parse calibration. Camera, LiDAR, and changed-source regressions pass. Final re-review remains required. |
| Production integration | NOT_INTEGRATED | No merge or production ref change. A reviewable PR remains conditional on finishing the candidate gates. |

## Offline verification recorded so far

### Follow-up after independent adversarial review

- Reviewed commit `6b757c47467af442fece0544c233120773b31282` was rejected because a forged rigid mount plus matching applied pose could pass while claiming the genuine calibration path and digest.
- Primary and submission validators now load the calibration only after digest verification, resolve each sensor name to its calibration entry, derive the canonical CARLA mount, and reject any receipt matrix mismatch. The same check is covered for cameras and LiDAR in both code trees.
- The reviewer then identified producer-side digest TOCTOU: the rig parsed calibration from one read and hashed a later path read. Both rig producers now parse and hash the same byte snapshot, so any later file change produces a receipt for the bytes actually used and strict validation rejects the changed file.
- Exact focused primary command (strict receipt validator, conversion, selection, completeness and failure classification suites): **134 passed**, exit `0`, five existing configuration-path warnings.
- Mirror rig, forged-mount regressions, and calibration-path selection attempt: **16 passed, 1 failed**, exit `1`. The remaining failure is `test_default_calib_exists`, which expects relative `calib_data.json` at the runner working directory. The failure is unchanged in the production-base source and is not claimed as a pass.
- Mirror rig suite plus forged-mount/source-snapshot regressions, excluding the working-directory-dependent calibration-path test: **17 passed**, exit `0`, four existing configuration-path warnings.
- `compileall` over `ultimate_pipeline`, the submission mirror, and `tests`: **PASS**, exit `0`. `git diff --check` against the production base: **PASS**, exit `0`.
- Latest full offline command: `python -m pytest -q -p no:cacheprovider -rfEsx tests/unit ultimate_pipeline/tests/unit ultimate_pipeline/carla_tools/tests`; **INCOMPLETE**, exit `1`, 3,586 collected, 244 collection errors, 1 skipped. Missing sparse-checkout modules include `ultimate_pipeline.enrichment` and `ultimate_pipeline.lanes`.
- Regression tests in both code trees mutate the calibration file after `ThesisSensorRig` construction and verify that the receipt retains the digest of the bytes used to build mounts, while strict validation rejects the now-changed source. These latest fixes still require fresh independent review against the follow-up commit.

Command:

```text
python -m pytest -q -p no:cacheprovider --tb=short \
  tests/unit/test_thesis_mounting_frames_v2.py \
  tests/unit/test_sensor_calibration_semantics.py \
  tests/unit/test_v112_rq3_explicit_calibration.py \
  tests/unit/test_v119_rq3_completeness_nonvacuous.py \
  ultimate_pipeline/carla_tools/tests/test_thesis_sensor_rig_contract.py \
  tests/unit/test_run_perception_safe_rig_contract.py \
  ultimate_pipeline/tests/unit/test_transform_conventions.py
```

Result on Windows Python 3.12.2: **82 passed**, exit code `0`, with five
existing configuration-path warnings. This is focused source-level evidence;
it is not full offline CI or live CARLA qualification.

## Remaining acceptance boundary

`PENDING_RUNTIME`: spawn the complete six-camera plus LiDAR rig on the pinned
CARLA 0.9.16 runtime, confirm actual ego-relative poses, and measure
predeclared-target reprojection and camera/LiDAR alignment. Offline matrix
round-trips cannot establish physical sensor attachment correctness.
