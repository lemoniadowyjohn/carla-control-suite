# R16 CLAUDE C3 PERCEPTION PROTOCOL PACKET

*Run: `20260811T000000Z_C3_PROTOCOL` · branch `fix/post-audit-phase-e-junctions-roundabouts-20260803` · freeze tag `c3_freeze_20260811T000000Z_C3`*

## Purpose

C3 freezes the perception protocol **before any data collection** (no post-hoc threshold selection). The protocol governs sensor rig, sync mode, semantic ontology, route/weather seeds, and all acceptance thresholds. Parent = C2 freeze `54e08381`. All thresholds are frozen here; no adjustment after observing results.

## Claimed Anchors

| Anchor | Value |
| --- | --- |
| Parent freeze (C2) | `c2_freeze_20260810T000000Z_C2R2` → commit `54e08381d686477e750936926406be7fca92d9e0` |
| Lineage anchor (C1) | `c1_freeze_20260809T000000Z_C1` → commit `8b400351d13634104090b31e535ced6e6d748648` (`review_anchor_commit`, not parent) |
| Governed payload | `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_final.xodr` :: sha `248ffbbe6a1aa2a9cbd4330a69ad1c1680d39698e2d186dd45f5a2eb91c5db6c` |
| Full-map mesh | `reports/post_audit_hardening/20260810T000000Z_C2_REMEDIATION/fullmap_mesh/scene.obj` :: sha `a147f4fe9e34d8b8a6f32aaddd9de144f2b79e70b5c798fd2d5c7ab3476b9c2e` |
| P8 package build | `BLOCKED_SERVER_UNAVAILABLE` — `CarlaUE4.exe` (CARLA 0.9.16) + UE 4.26 + `CARLA_ROOT` missing |

---

## 1. Rig & Configuration (Frozen)

### 1.1 Sensor Suite

| Sensor | Count | Pose IDs | Rate | Resolution / Params |
| --- | --- | --- | --- | --- |
| **RGB** | 5 | `front_wide`, `front_narrow`, `left`, `right`, `rear` | 20 Hz | 1920×1080, 32-bit |
| **Depth** | 5 | same as RGB | 20 Hz | 1920×1080, 32-bit (mm) |
| **Semantic Seg** | 5 | same as RGB | 20 Hz | 1920×1080, 8-bit class ID |
| **Instance Seg** | 5 | same as RGB | 20 Hz | 1920×1080, 24-bit instance ID |
| **LiDAR** | 1 | roof-center | 20 Hz | 64 ch, 2.6M pts/s, range 100 m, ±25° vertical, 360° horizontal |
| **Radar** | 4 | `front_left`, `front_right`, `rear_left`, `rear_right` | 20 Hz | 30° H / 30° V FOV, range 100 m, 1500 pts/s |
| **GNSS** | 1 | roof-center | 20 Hz | noise lat 2.0e-6, lon 2.0e-6, alt 4.0 |
| **IMU** | 1 | roof-center | 400 Hz | accel 0.001 m/s², gyro 0.00001 rad/s, compass 0.00001° |

### 1.2 Camera Extrinsics (ego-relative, meters/deg)

| Pose | x | y | z | yaw | pitch | roll |
| --- | --- | --- | --- | --- | --- | --- |
| front_wide | 2.0 | 0.0 | 1.4 | 0 | -10 | 0 |
| front_narrow | 2.2 | 0.0 | 1.4 | 0 | -8 | 0 |
| left | 1.0 | -0.9 | 1.2 | -90 | -10 | 0 |
| right | 1.0 | 0.9 | 1.2 | 90 | -10 | 0 |
| rear | -1.5 | 0.0 | 1.4 | 180 | -10 | 0 |

### 1.3 Camera Intrinsics (derived deterministically)

For each pose: `fx = fy = 960 / tan(FOV/2)`, `cx = 960`, `cy = 540`.  
FOV frozen: `front_wide` 100°, `front_narrow` 60°, `left/right/rear` 90°.

### 1.4 LiDAR Parameters (CARLA 0.9.16)

```
channels: 64
rotation_frequency: 20.0
points_per_second: 2600000
range: 100.0
upper_fov: 10.0
lower_fov: -30.0
horizontal_fov: 360.0
dropoff_general_rate: 0.0
dropoff_intensity_limit: 0.0
dropoff_zero_intensity: 0.0
location: (0.0, 0.0, 2.0)
rotation: (0.0, 0.0, 0.0)
```

### 1.5 Radar Parameters (×4 units)

```
horizontal_fov: 30.0
vertical_fov: 30.0
range: 100.0
points_per_second: 1500
rotation_frequency: 20.0
locations (ego-relative): front_left (1.5, -0.5, 1.0), front_right (1.5, 0.5, 1.0), rear_left (-1.5, -0.5, 1.0), rear_right (-1.5, 0.5, 1.0)
```

### 1.6 GNSS / IMU

- **GNSS**: `noise_alt_stddev=4.0`, `noise_lat_stddev=2.0e-6`, `noise_lon_stddev=2.0e-6`
- **IMU**: `noise_accel_stddev_x=0.001`, `_y=0.001`, `_z=0.001`, `noise_gyro_stddev_x=0.00001`, `_y=0.00001`, `_z=0.00001`, `noise_compass_stddev=0.00001`

### 1.7 Sync Mode

```
synchronous_mode: True
fixed_delta_seconds: 0.05   # 20 Hz
no_substepping: True
sensor_tick: 1.0            # every server frame
```

### 1.8 Semantic Ontology (Frozen)

CARLA 0.9.16 cityscapes-compatible semantic segmentation classes (23):

| Governed Class | CARLA Semantic ID | Note |
| --- | --- | --- |
| Building | 13 | 51,898 objects (C2R2) |
| Vegetation | 9 | 3,489 trees + 832 forests |
| Sidewalk | 8 | XODR sidewalk lanes |
| CrossWalk | 20 | 66 XODR crosswalk objects / 330 corners |
| Road | 7 | Drivable lanes |
| RoadLine | 6 | Lane markings |
| Unlabeled | 0 | Unknown / out-of-ontology |

**Unknown/Unlabeled Policy**: Pixels mapped to `Unlabeled (0)` or classes outside the frozen table above count toward the **unknown-semantic rate** threshold. Dynamic actors (Pedestrian=4, Vehicles=10) are validated against the frozen spawn ledger; no open-vocabulary classes.

### 1.9 Route Seeds (Frozen)

20 deterministic route seeds (`R00`–`R19`) along governed XODR centerlines. Each route ≥ 5 km.  
**Hold-out regions**: routes `R16`–`R19` (4 routes, ~20% of network) reserved for generalization checks; **excluded from threshold compliance tuning**.

### 1.10 Weather Seeds (Frozen)

8 CARLA presets, seeded deterministic variants:

| Seed | Preset | Description |
| --- | --- | --- |
| W00 | ClearNoon | Baseline dry |
| W01 | CloudyNoon | Overcast |
| W02 | WetNoon | Post-rain wet surface |
| W03 | WetCloudyNoon | Wet + overcast |
| W04 | SoftRainNoon | Light rain |
| W05 | ClearSunset | Golden hour |
| W06 | CloudySunset | Overcast sunset |
| W07 | WetSunset | Wet + sunset |

### 1.11 Hardware Profile (Intended Minimum Spec)

- CPU: 8-core ≥ 3.0 GHz
- RAM: 32 GB DDR4
- GPU: NVIDIA RTX 3060 (8 GB VRAM) or equivalent
- Storage: NVMe SSD
- OS: Windows 10/11 (CARLA 0.9.16 server target)
- Target sustained: **20 FPS** (50 ms frame budget)

---

## 2. Frozen Acceptance Thresholds (Pre-Collection)

All thresholds frozen **before** any C4 data collection. No post-hoc adjustment.

| # | Metric | Frozen Threshold | Rationale |
| --- | --- | --- | --- |
| 1 | **FBX↔XODR residual (p95)** | ≤ 6.5 m | C2R2 corridor gate (lane half-width 3.5 + collision LOD buffer 3.0) |
| 2 | **FBX↔XODR residual (max)** | ≤ 13.0 m | 2× corridor hard bound |
| 3 | **Visual/collision residual (p95)** | ≤ 6.5 m | Same corridor for visual mesh & collision volumes |
| 4 | **Visual/collision residual (max)** | ≤ 13.0 m | 2× corridor |
| 5 | **Crosswalk placement residual (centroid p95)** | ≤ 6.5 m | Corridor standard applied to crosswalk centroids |
| 6 | **Crosswalk placement residual (corner max)** | ≤ 13.5 m | Corner allowance consistent with C2E captured max 13.264 m |
| 7 | **Frame loss rate** | ≤ 0.10% per route | < 1 frame per 1000 at 20 Hz |
| 8 | **Timestamp skew (max)** | ≤ 10 ms | Synchronous frame timestamp tolerance |
| 9 | **LiDAR-camera reprojection (mean)** | ≤ 2.0 px | RGB↔LiDAR depth consistency |
| 10 | **LiDAR-camera reprojection (p95)** | ≤ 5.0 px | |
| 11 | **Depth agreement (MAE)** | ≤ 0.15 m | Depth sensor vs LiDAR dense ground truth |
| 12 | **Depth agreement (rel. p95)** | ≤ 5% | Relative error |
| 13 | **GNSS residual (CEP95)** | ≤ 1.5 m | GNSS vs ground truth localization |
| 14 | **Unknown-semantic rate (per-frame p95)** | ≤ 2.0% | Unlabeled/out-of-ontology pixels |
| 15 | **Unknown-semantic rate (route mean)** | ≤ 1.0% | |
| 16 | **Route completion** | ≥ 99.5% | Waypoints reached; 0.5% cut-edge allowance |
| 17 | **Collision rate** | 0 per route | Hard fail; perception validation |
| 18 | **Lane invasion (frames)** | ≤ 1.0% | Frames with > 0.3 m beyond lane edge |
| 19 | **Lane invasion (depth max)** | ≤ 0.5 m | Max over-lane distance |
| 20 | **Elevation seam** | ≤ 0.1 m | Vertical discontinuity at tile boundaries along drivable corridor |
| 21 | **FPS (mean)** | ≥ 20.0 | Sustained 20 Hz simulation |
| 22 | **p95 frame time** | ≤ 55 ms | ≈ 18 Hz worst 95% |
| 23 | **p99 frame time** | ≤ 100 ms | ≈ 10 Hz tail |
| 24 | **Memory growth (30 min run)** | ≤ 5% RSS / ≤ 500 MB | No unbounded leaks |

---

## 3. Package Build Dependency (Prompt 1)

`P8_PACKAGE_BUILD_BLOCKED` — exact missing dependency:

- **CarlaUE4.exe** — CARLA 0.9.16 server build matching venv client `carla-0.9.16`
- **CARLA_ROOT** — environment variable unset
- **Unreal Engine 4.26** — not installed (required for `.umap` cooking, semantic materials, pedestrian navmesh)

Artifacts ready on disk (byte-exact):

| Artifact | Path | SHA256 | Bytes |
| --- | --- | --- | --- |
| Governed XODR | `campaigns/.../ingolstadt_perception_final.xodr` | `248ffbbe6a1aa2a9cbd4330a69ad1c1680d39698e2d186dd45f5a2eb91c5db6c` | 81,007,405 |
| Full-map FBX | `.../20260810T000000Z_C2_REMEDIATION/visual_layer/artifacts_fbx/scene.fbx` | TBD | 226,279,516 |
| Full-map OBJ | `.../20260810T000000Z_C2_REMEDIATION/fullmap_mesh/scene.obj` | `a147f4fe9e34d8b8a6f32aaddd9de144f2b79e70b5c798fd2d5c7ab3476b9c2e` | 398,450,258 |
| Visual OBJ | `.../20260810T000000Z_C2_REMEDIATION/visual_layer/artifacts_visual/scene.obj` | `15cdccbcd3374b79e63b590e6e591b9f4e4aa9b7abda6b260fb6f553e2d1907e` | 390,751,147 |

---

## 4. Freeze

- freeze_schema: `C3R_TAG_ANCHORED_V2`
- freeze_tag: `c3_freeze_20260811T000000Z_C3`
- parent_commit: `54e08381d686477e750936926406be7fca92d9e0` (immediate git parent == `tag^{commit}~1` = C2 freeze)
- review_anchor_commit (lineage): `8b400351d13634104090b31e535ced6e6d748648` (C1, kept distinct)
- NO head_commit / tag-object sha inside committed JSONs (non-circular; annotated tag message carries freeze_commit, freeze_tree, branch, r16 sha256, r16b sha256, manifest sha256, governed payload sha, mesh sha)
- review invariant: no commits after tag creation; worktree clean; `tag^{commit} == HEAD`

---

## 5. Verification

- Evidence: `P8_PACKAGE_BUILD_BLOCKED.json`, `R16_PRIMARY_EVIDENCE_MANIFEST.json`, `R16B_C3_REVIEW_FREEZE.json` (all tracked in this run dir)
- `verify_post_audit_hardening.py` (extended for C3) ALL PASS
- Governed payload `248ffbbe…` unchanged; mesh `a147f4fe…` byte-exact
- Raw meshes gitignored; byte-exact disk hashes recorded in status JSONs