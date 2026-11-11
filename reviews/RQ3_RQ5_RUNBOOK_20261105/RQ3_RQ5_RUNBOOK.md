# RQ3 / RQ5 experiment runbook (task 15, RQ3-RQ5-EVIDENCE-006) — DESIGN ONLY

**Status:** `IMPLEMENTED_LOCAL` (documents only). No CARLA, capture or training was run, and nothing
here is a result. RQ3 and RQ5 remain **NOT_MEASURED**. The author is Claude; this runbook needs an
independent review (a different model family) and operator sign-off before any step runs.

Code baseline: `integration/post-pr16-final-20261102` @ `1a36b560a69286841d4c42973cf00258a38f56c1`
(read-only).

## 0. Facts this runbook is built on (verified at `1a36b560`)
| Fact | Source |
|---|---|
| RQ5 training is frozen: fcn_resnet50 with random init (`weights=None`), 29 classes, Adam, lr 1e-4, constant schedule, **3 epochs**, **batch 4**, native resolution, no augmentation, median-frequency class weights from the generated-train split, **seeds [7, 17, 42]**, final-epoch checkpoint, primary metric = **generated→manual mIoU degradation**, no manual leak | `configs/rq5_protocol_freeze_v1.json` (sha256 `db7155fe…`) |
| `configs/rq3_protocol_freeze_v1.json` (sha256 `5aa8ae24…`, schema `paired_capture_manifest_v2`) freezes **the same training/evaluation decisions only**. It freezes **no capture conditions** (route, anchors, sensors, weather, sync). | file read |
| **Both freezes set the CI as a "nonparametric bootstrap over test frames, 1000 resamples, seed 7".** Frames are correlated; see §5. | both freezes, `confidence_interval_method` |
| Both arms must share sensor-rig / calibration / route / weather / sync / fixed-delta / CARLA-version / map-identity hashes (`REQUIRED_ARM_IDENTITY_KEYS`: `sensor_rig_sha256`, `weather_sha256`, `route_manifest_sha256`, `runtime_sensor_rig_sha256`, …) | `ultimate_pipeline/perception/rq3_capture_contract.py:8-78` |
| Admission (`DATASET_ADMITTED`) needs digests that resolve to real bytes under approved roots, plus an Ed25519-signed review receipt from a key in `review_trust_root`. **No trust root exists.** | `ultimate_pipeline/perception/rq3_evidence_gate.py` |
| Capture defaults: 20 fps; "thesis" rig = 6 calibrated cameras + LiDAR (npz); calibration `ultimate_pipeline/sensors/calib_data.json`; synchronous mode with `fixed_delta_seconds = 0.05` | `perception/capture_config.py:34-73`; `carla_tools/carla_sim_consolidated.py:258-259` |
| Maps: manual `Grid0828.xodr` sha256 `5eaece23…`; auto crop `auto_crop_grid0828_footprint.xodr` sha256 `b2bc2712…` (local, not committed; derived from the map-of-record `370abbbb…`) | registry; crop manifest |
| Map quality: the auto map contains U-turn lane-level discontinuities (proposed GAP-080: median 0.7467 m / 26.565°); GAP-070 residuals; GAP-079 stubs. Status open. | `docs/reviews/` on `e8218cf9` |
| Runtime: 4 headless CARLA 0.9.16 attempts timed out at the RPC handshake (GAP-077). Disk free 2026-11-05: C 1.1 G, E 0.6 G, F 2.3 G, G 5.1 G | GAP register; `df` |

## 1. Gate sequence (each gate must PASS before the next starts; any failure → STOP, with a receipt)
| Gate | Requirement | Current state |
|---|---|---|
| G0 Runtime | CARLA RPC answers (`client.get_server_version()` returns a value; port listening is not enough), and **both** maps load in `OpenDriveMap` / map-generation mode | **BLOCKED (GAP-077)**: operator visible-window run or driver check |
| G1 Map admission | Both XODRs pinned by sha256. The auto map's junction defects are handled by policy (§2.3). The operator signs off which map version is the "auto" arm. | **OPEN:** decision needed (§2.3) |
| G2 Anchors | ≥ 3 surveyed fit anchors + ≥ 2 untouched holdout anchors, with tolerances fixed **before capture** (§2.2) | **MISSING:** operator data |
| G3 Pairing contract | `PAIRING_AND_SENSOR_CONTRACT.json` filled, hashed and frozen as a **new** versioned contract (v1 is not edited) | draft template provided |
| G4 Resources | Pilot ≤ 1 GB on one volume; full run sized from the pilot's measured bytes/frame (§6) | the pilot fits on G:; the full run is **BLOCKED** |
| G5 Pilot | 1 camera, low resolution, short route; every check in §3 passes | not run |
| G6 Full RQ3 capture | route sampling per §4 | not run |
| G7 RQ5(a) training | frozen v1 protocol (+ the v2 CI amendment, if adopted before training) | not run |
| G8 Admission | an Ed25519-signed external review receipt | **BLOCKED:** no trust root |

## 2. Pre-capture decisions (freeze before G5)
### 2.1 Map identity
- Record for each arm: the XODR sha256; the generator code SHA (auto); the CARLA build (0.9.16 + the
  `carla` client wheel version); the `OpenDriveMap` generation parameters (vertex distance, wall
  height, extra width, smooth junctions, mesh visibility); and the runtime map name returned by
  `world.get_map().name`.
- Dry run: load each XODR, dump `world.get_map().get_topology()`, and hash the waypoint list at fixed
  spacing (e.g. 2 m). The hash must be reproducible across two loads. That proves the runtime map
  identity.

### 2.2 Spatial registration (auto ↔ manual)
- Fit the SE(2) transform (or the existing deterministic alignment) **only** on the fit anchors.
- Report RMS and max residual on the **holdout** anchors. Accept only if both are within the
  pre-registered tolerances (`[OPERATOR: tolerance_rms_m, tolerance_max_m]`, fixed before seeing the
  holdout residuals).
- Holdout anchors are never used for fitting, for route selection, or for adjusting tolerances.

### 2.3 Map-defect policy (decide before routes are chosen)
Choose one, as pre-registered: `[OPERATOR]`
- **A. Exclude junction areas:** routes avoid every junction containing a GAP-070-residual or GAP-080
  connector (identified by the O13 validator per laneLink). This measures the gap on "clean"
  road-network segments.
- **B. Stratify:** capture both junction and non-junction segments, label each frame with its stratum
  (from the O13 list), and report RQ3/RQ5 per stratum.
- **C. Wait** for a corrected auto map (X8, plus a source-stage fix for GAP-080).
A, B and C need the O13 validator's per-laneLink output; **O13 is not finished.**

## 3. Pilot (G5) — 1 camera, low resolution, short route
1. **Rig:** one front RGB camera from the calibrated rig (the same intrinsics/extrinsics as the full
   rig, at reduced resolution `[OPERATOR: e.g. 640×360]`), plus a semantic-segmentation camera at the
   identical transform and resolution. No LiDAR in the pilot.
2. **Sync:** synchronous mode, `fixed_delta_seconds = 0.05`, the same `sensor_tick` on every sensor,
   `[OPERATOR: N]` warm-up ticks discarded, and the Traffic Manager in synchronous mode with a fixed
   seed. **No other actors** in the pilot (an empty world removes actor-state confounds).
3. **Route:** one route of `[OPERATOR: length, e.g. 300-500 m]`, defined in the **manual** frame by
   waypoints and mapped to the auto frame through the §2.2 transform. The ego follows the route with
   the same controller, target speed and seed in both arms.
4. **Environment:** identical weather preset and sun position (`weather_sha256` must match);
   identical time of day.
5. **Per-frame records:** frame id, simulation time, ego pose, the semantic and RGB file sha256s, and
   a UTC timestamp. Missing frames are **counted and reported, never interpolated**. A pilot with more
   than `[OPERATOR]`% missing frames fails.
6. **Labels:** the CARLA 29-class ontology (`carla_classes.py`). Check that both arms produce the
   same class-id set on overlapping views. Classes present in only one arm are reported.
7. **Pairing check:**
   - per-frame ego-pose difference between the arms, after the transform, must be ≤
     `[OPERATOR: m, deg]`;
   - route-length difference ≤ `[OPERATOR]`%.
   If either fails, the result is **not** a paired RQ3 measurement.
8. **Manifest:** `rq3_capture_contract` identity keys for both arms; `checksum_manifest` over every
   file; the contract audit must pass.
9. **Contamination check:** frame ids and file hashes of the manual arm must never appear in any
   training list (the RQ5 no-leak rule).
Pilot output: `MEASURED_NOT_ADMITTED` at most. **No RQ3 number is reported from the pilot.** It
validates the procedure only.

## 4. Full RQ3 capture (G6)
- **Units:** **routes** (or scene blocks of ≥ `[OPERATOR: s]`), not frames.
- **Route set:** `[OPERATOR: R]` routes covering the co-registered footprint, chosen by a
  pre-registered rule (e.g. stratified random over road segments, seed fixed), with a **spatial
  holdout**: whole districts or blocks reserved for RQ5 testing only.
- **Rig:** the full calibrated rig (6 cameras + LiDAR) only if the pilot passes, and only if the
  resources in §6 allow it. Otherwise the pilot rig at full route coverage.
- **Sensitivity:** adverse-weather arms (the same routes, weather presets `[OPERATOR]`) are a
  separate, labelled sensitivity analysis.
- **Rendering vs structure:** the two maps differ in structure *and* in rendered assets
  (materials, props, buildings). Where possible, separate them:
  - compare semantic-label distributions (structure-dominated) against RGB features (rendering);
  - the same-map repeat null (`DRAFT_ANALYSIS_PLAN.md`) bounds simulator noise.
  If they cannot be separated, the result is reported as a combined "perceptual" gap.

## 5. RQ5(a) training and evaluation (G7)
- **Frozen v1 protocol, exactly** (`rq5_protocol_freeze_v1.json`): no change to the model, init,
  optimizer, lr, epochs (3), batch (4), seeds [7, 17, 42], resolution, augmentations, class weights,
  checkpoint rule or primary metric. The no-manual-leak rule is enforced by a manifest check before
  training.
- **Confidence intervals: amendment required before training starts.** v1's "bootstrap over test
  frames" treats correlated adjacent frames as independent and understates uncertainty. The amendment
  policy permits a v2 with a rationale, provided RQ5(a) training has not started (it has not).
  Proposal for a v2 contract: a bootstrap over **routes / scene blocks** (1,000 resamples, seed 7),
  with the v1 frame-level interval reported **as well** and labelled "v1 frame-level (anti-
  conservative)". The operator decides; if v2 is not adopted, v1 is reported as frozen with this
  limitation stated next to it.
- **Reporting:** per seed and as mean ± CI across seeds; per-class IoU **with pixel support**.
  Classes absent from a test split are reported as absent, not as IoU 0 or 1. Seeds, routes and
  strata are reported as separate variance sources.
- **No test-set tuning**, no fake predictions, no synthetic success; the manual test split is never
  used for checkpoint selection.
- **RQ5b:** `EXTERNAL_DATA`. It stays NOT_MEASURED until a real Ingolstadt dataset with labels is
  provided. Unlabelled shift analysis follows `rq5b_boundary` in the freeze.

## 6. Capacity (see `RUNTIME_RESOURCE_CHECKLIST.md`)
- One volume holds the maps, the capture, the training temp files and the checkpoints.
- The pilot measures bytes/frame per sensor. The full-run estimate is
  `bytes/frame × frames/route × routes × arms × (1 + weather arms)` plus checkpoints
  (3 seeds × fcn_resnet50 checkpoint size) plus a 30% headroom.
- **Retention:** raw captures are kept until admission is decided; temp and training caches are
  deleted after each seed; checksum manifests are never deleted.

## 7. Evidence states (see `EVIDENCE_ADMISSION_MATRIX.md`)
`NOT_MEASURED` → `MEASURED_NOT_ADMITTED` (capture and metrics exist, with hashes) → `SIGNED_ADMITTED`
(an Ed25519 receipt from a trust-root key, bound to the exact dataset and capture digests).
Today: **no trust root**, so the maximum reachable state is `MEASURED_NOT_ADMITTED`.
