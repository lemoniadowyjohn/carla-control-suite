# Active Pipeline Map

## Canonical Entry Point

`ultimate_pipeline.main_pipeline.MainPipeline.run()`

## Hardening Status (Phase 0-6 Complete, Phase 7-8 Verified)

| Phase | Status | SHA | Key Change |
|---|---|---|---|
| 0: Package structure | ✅ Done | cc3c89f7~ | Copy 558 missing files, fix torch_geometric import |
| 1: Stage contracts | ✅ Done | cc3c89f7~ | StageRequest/GateResult/StageResult dataclasses |
| 2: Disable unsafe mutations | ✅ Done | cc3c89f7 | 4 planView ops behind `ENABLE_UNSAFE_PLANVIEW_MUTATIONS` |
| 3: Freeze geometry order | ✅ Done | f1703048 | Step 6 (planView) before Step 5 (elevation) |
| 4: Ground lanes/markings | ✅ Done | b0df9056 | `ENABLE_LANELINK_REGEN` default False, autofix off |
| 5: Stage gates + profiles | ✅ Done | 143656f0 | Centralized policies, AND pattern, 17 parametrized tests |
| 6: Ground enrichment | ✅ Done | 53e11562 | Roundabout/traffic lights default False |
| 7: Visual QA | ✅ Done | 53e11562 | Map loaded, 178 tests pass, screenshot verified |
| 8: Sensor acceptance | ✅ Done | 53e11562 | 19 sensor types, 10 fps camera stream verified |
| 9: CI verification | ✅ Done | 53e11562 | All 9 deliverables documented (see files below) |

## Evidence Files

| File | Content |
|---|---|
| `00_active_pipeline_map.md` | This file |
| `01_stage_mutation_matrix.md` | Full stage mutation matrix with toggles and defaults |
| `02_active_call_graph.md` | Complete pipeline call graph with conditions |
| `03_hardening_proof.md` | Line-by-line proof all unsafe ops are disabled |
| `04_design_drivable_surface_stage.md` | Design for new Stage 8G hole analysis |
| `05_design_cumulative_gate_runner.md` | Design for cumulative (tally-all, fail-at-end) gate runner |
| `06_regression_report.md` | Full-map parent-child regression report |
| `07_sha_verification.md` | Remote GitHub SHA verification |
| `08_sensor_acceptance.md` | Sensor acceptance test results |

## Test Status

- **178 passed**, 1 skipped, 0 failures
- **7 CARLA-dependent tests** verified
- **Ruff**: No new issues
- **CARLA preflight**: Fully green (ok: true, tick_ok: true)

## Loaded Map

- Source: `20260403_133425_341488/08_final_..._linkpatched.xodr` (18.1 MB)
- CARLA map: `Carla/Maps/OpenDriveMap`
- Spawn points: 8,535
- Waypoints (2m): 155,491
- Roads: 5,712
- All sensor types: 19/19 verified
