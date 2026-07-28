# Readiness Dimensions — Gemini 3.1 Pro Audit

## 1. Structural Readiness

**Definition**: The OpenDRIVE pipeline can process an OSM input through all stages and produce a valid, complete XODR without errors.

| Criterion | Status | Evidence |
|---|---|---|
| All stage files tracked in git | ❌ | 8 of 13 files missing |
| All imports resolve at runtime | ❌ | Missing stage files will cause ImportError |
| Release profile enforcement | ✅ | All 4 profiles defined, unknown fails closed |
| Cumulative gate runner | ⚠️ | Implemented, no direct tests |
| Enrichment defaults safe | ✅ | Roundabout=False, TrafficLights=False |
| Geometry freeze active | ✅ | `geometryFrozen` header always set |
| Freeze hash computed | ✅ | SHA256 stored in header |
| Drivable-surface scanner | ⚠️ | Implemented, no tests |
| Full-map metrics | ⚠️ | Implemented, no tests |

**Verdict**: ❌ **NOT READY** — Pipeline cannot execute end-to-end due to untracked stage files. Individual structural hardening fixes (Phases 2-7, 9) are correctly implemented but the pipeline is not executable from a fresh clone.

**Action required**: Commit all missing stage files to the branch.

---

## 2. CARLA Readiness

**Definition**: CARLA can load the pipeline-generated XODR map, spawn vehicles at valid spawn points, and render the environment.

| Criterion | Status | Evidence |
|---|---|---|
| CARLA loaded pipeline map successfully | ✅ | Previous run (Visual QA, Phase 7) confirmed: `Carla/Maps/OpenDriveMap` loaded |
| Spawn points available | ✅ | 8,535 spawn points verified |
| Roads in map | ✅ | 5,712 roads verified |
| Waypoints generated | ✅ | 155,491 waypoints verified |
| Sensor attachment works | ✅ | Phase 8 confirmed 100/100 spawn points accept sensors |
| RGB camera captures frames | ✅ | 10 frames at 6.7 fps verified |
| 19 sensor blueprint types accessible | ✅ | 8 cameras, 2 LiDAR, 1 radar, 1 GNSS, 1 IMU, 6 other |
| CARLA isolation mode functional | ✅ | Windows subprocess isolation works |
| LaneLink regen disabled in CARLA | ✅ | Guarded behind AND policy |
| Unsafe planView mutations disabled | ✅ | All 8 call sites gated |

**Verdict**: ✅ **READY** — CARLA integration is fully functional. The pre-existing pipeline-generated map loads, spawns, and accepts sensors.

**Note**: This readiness applies to the last successful pipeline run (Phase 7/8 verification). A fresh run would fail due to structural issues (untracked stage files).

---

## 3. Visual-Map Readiness

**Definition**: The generated XODR map produces visually coherent road geometry, lanes, markings, and signals in CARLA's renderer.

| Criterion | Status | Evidence |
|---|---|---|
| PlanView geometry smooth | ✅ | continuity gates enabled by default |
| Elevation applied on frozen XY | ✅ | Reordered: planView first, then DEM on frozen XY |
| Lane width continuity gated | ✅ | Gate enabled by default |
| Lane geometry continuity gated | ✅ | Gate enabled by default |
| Elevation variance gated | ✅ | `05_elevation` gates active |
| Elevation seams gated | ✅ | `08_final` seam gate active |
| Drivable-surface holes detected | ⚠️ | Scanner implemented but untested on actual XODR |
| Full-map metrics computed | ⚠️ | Scanner implemented but untested on actual XODR |
| Geometry freeze hash verified | ✅ | Downstream stages verify hash |

**Verdict**: ⚠️ **PARTIAL** — The visual pipeline structure is sound. Geometry is correctly ordered, gates protect elevation quality, and the new scanners can detect issues. However, the scanners have never been run against a real XODR output in a test.

**Action required**: Add an integration test that runs DrivableSurfaceScanner and FullMapMetricsScanner against a known XODR and asserts expected metric values.

---

## 4. Sensor Readiness

**Definition**: Sensor blueprints can be attached to vehicles spawned on the map, and sensor data streams are captured correctly.

| Criterion | Status | Evidence |
|---|---|---|
| RGB camera capture | ✅ | 10 frames @ 6.7 fps |
| LiDAR available | ✅ | 2 LiDAR blueprint types (ray, ray_semantic) |
| Radar available | ✅ | 1 radar blueprint type |
| GNSS available | ✅ | 1 GNSS blueprint type |
| IMU available | ✅ | 1 IMU blueprint type |
| Sensor rig contract enforced | ✅ | Tested in submission tests (20 tests pass) |
| Sensor reload readiness | ✅ | `test_reload_ready_for_sensors` passes |
| Sensor acceptance documented | ✅ | `08_sensor_acceptance.md` exists in docs/hardening/ |

**Verdict**: ✅ **READY** — All sensor types are verified working with the pipeline-generated map. Sensor rig contracts are enforced by passing tests.

---

## 5. Perception Readiness

**Definition**: Perception tools (screenshots, road defect scanning, domain gap analysis) can run against the generated map.

| Criterion | Status | Evidence |
|---|---|---|
| Road defect scanning | ❌ | Stage file not tracked |
| Perception screenshots | ❌ | Stage file not tracked |
| Domain gap analysis (classical) | ❌ | Stage file not tracked |
| Domain gap analysis (GNN) | 🔒 | Blocked: torch_geometric slow on Windows |
| Perception test suite passes | ✅ | `test_perception_collect_tools` passes (2 tests) |
| Pipeline health summary | ✅ | `write_pipeline_health_summary` writes summary |

**Verdict**: ❌ **NOT READY** — Perception stages depend on untracked stage files and blocked GNN imports. The perception test suite is minimal.

**Action required**: Track stage files and resolve GNN Windows issue.

---

## Summary

| Dimension | Readiness | Count of Issues |
|---|---|---|
| Structural | ❌ NOT READY | 1 CRITICAL (untracked files), 3 HIGH/MED (untested code) |
| CARLA | ✅ READY | 0 issues |
| Visual-Map | ⚠️ PARTIAL | 2 untested scanners |
| Sensor | ✅ READY | 0 issues |
| Perception | ❌ NOT READY | 1 CRITICAL (untracked files), 1 BLOCKED (GNN) |
