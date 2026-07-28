# Test Collection — Gemini 3.1 Pro Audit

## Test Discovery

| Source | Path | Count |
|---|---|---|
| Main pipeline tests | `ultimate_pipeline/tests/test_contracts.py` | 71 |
| Submission tests (excl. test_contracts collision) | `submission/infrastructure/ultimate_pipeline/tests/` | 107 |
| Submission CARLA-dependent (skipped) | various | 1 |
| **Total run** | | **178 passed, 1 skipped** |

## Per-File Breakdown

### `ultimate_pipeline/tests/test_contracts.py` (71)
- TestExperimentConfigModel (6)
- TestAgentSyncContract (5)
- TestRunArtifacts (5)
- TestReleaseProfilePolicy (17 parametrized: laneLink regen + planView mutations + strict gates + env parsing)
- TestExperimentRegistry (4)
- **New audit tests**: CumulativeGateRunner unit tests (should be added — see issue register)

### `submission/infrastructure/ultimate_pipeline/tests/test_contracts.py` (20)
- TestExperimentConfigModel (6)
- TestAgentSyncContract (5)
- TestRunArtifacts (5)
- TestExperimentRegistry (4)
- *(Does NOT include ReleaseProfilePolicy tests — these exist only in the main branch)*

### Submission other tests (87 non-CARLA)
- test_deterministic_alignment (1 skipped — pyproj not installed)
- test_perception_collect_tools (2)
- test_reload_ready_for_sensors (1)
- test_run_root_inference (2)
- test_sumo_repair (4)
- test_wait_for_first_sample (1)
- unit/ tests (76): connectivity, curvature, elevation, geo_alignment, OSM meta, domain gap, tiling CRS, tile gap evaluator, tile matcher, XODR cropper

## Key Finding

**No tests exist for:**
- `CumulativeGateRunner` (`contracts/gate_runner.py`) — 0 tests
- `DrivableSurfaceScanner` (`quality/drivable_surface_scanner.py`) — 0 tests
- `FullMapMetricsScanner` (`quality/full_map_metrics.py`) — 0 tests
- Geometry freeze hash verification (`_verify_geometry_freeze_hash`) — 0 tests
- Stage 8G/8H integration in main_pipeline — 0 tests

All 3 newly added audit-phase files (gate_runner, drivable_surface_scanner, full_map_metrics) have **zero test coverage**.
