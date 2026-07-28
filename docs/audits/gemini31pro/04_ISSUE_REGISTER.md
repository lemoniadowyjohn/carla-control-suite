# Issue Register — Gemini 3.1 Pro Audit

## Format

Each issue has a stable ID (`G31-{NNN}`) for cross-run classification.
Classification categories: `resolved` | `partial` | `unchanged` | `regressed` | `blocked` | `new`

| ID | Title | Severity | Category | Evidence Hash | Description |
|---|---|---|---|---|---|

---

## Issues

### G31-001: Stage files missing from git tracking (0, 1, 2, 5, 7-11)

| Field | Value |
|---|---|
| **Severity** | **CRITICAL** |
| **Category** | `new` |
| **Evidence** | `git ls-files ultimate_pipeline/pipeline_stages/` shows only 5 of 13 stage files tracked |
| **Files** | `stage_01_sanitize.py`, `stage_02_topology_semantics.py`, `stage_03_topology_repair.py`, `stage_07_lanes.py`, `stage_09_tiling.py`, `stage_10_tile_qa.py`, `stage_11_simulation.py`, `stage_12_domain_gap.py` |
| **Description** | 8 of 13 pipeline stage files exist on disk but are NOT tracked in git on branch `deepseek-observability-integration-verification`. The pipeline WILL fail at runtime when `main_pipeline.py:run()` → `_run_internal()` tries to import the first missing stage file. |
| **Impact** | Pipeline cannot execute any complete run from a fresh clone. Only stages 3, 4, 6, 7 (enrichment, geometry, links, integrity) can execute. |
| **Regression** | Not a regression — these files were never tracked on this branch. This is a pre-existing structural gap. |

### G31-002: Zero unit tests for 6 of 10 claimed hardening fixes

| Field | Value |
|---|---|
| **Severity** | **HIGH** |
| **Category** | `new` |
| **Evidence** | `test_contracts.py` analysis; no test files for `gate_runner.py`, `drivable_surface_scanner.py`, `full_map_metrics.py` |
| **Files** | All Phase 9 new files |
| **Description** | Fixes 2 (geometry reorder), 5 (enrichment defaults), 6 (seam recompute guard), 8 (freeze hash), 9 (drivable surface scanner), 10 (full-map metrics) have zero dedicated tests. Fix 7 (CumulativeGateRunner) is exercised only indirectly through pipeline gates. |
| **Impact** | No regression detection for these fixes. A refactor that breaks these invariants would not be caught by CI. |

### G31-003: Geometry freeze hash verification untested

| Field | Value |
|---|---|
| **Severity** | **MEDIUM** |
| **Category** | `new` |
| **Evidence** | `main_pipeline.py:2479-2515` — `_verify_geometry_freeze_hash` method has no test coverage |
| **Files** | `main_pipeline.py`, `stage_05_geometry.py` |
| **Description** | The freeze hash is computed and stored in the XODR header, but the verification method (`_verify_geometry_freeze_hash`) is only called at runtime from the DEM/elevation stage. No unit test verifies hash mismatch detection or the full round-trip (compute → store → verify). |
| **Impact** | A broken hash computation would not be detected until a full pipeline run. |

### G31-004: CumulativeGateRunner lacks direct unit tests

| Field | Value |
|---|---|
| **Severity** | **MEDIUM** |
| **Category** | `new` |
| **Evidence** | `contracts/gate_runner.py` — no test file exists |
| **Files** | `gate_runner.py` |
| **Description** | `CumulativeGateRunner` has three key behaviors that should be tested: (1) tally-all — all gates run even when earlier ones fail, (2) fail-at-end — strict mode raises only at `finalize()`, (3) non-strict mode never raises. These are not directly tested. |
| **Impact** | Behavioral regression risk for the gate execution model. |

### G31-005: `pytest.ini` not tracked in git

| Field | Value |
|---|---|
| **Severity** | **LOW** |
| **Category** | `unchanged` |
| **Evidence** | `git ls-files pytest.ini` returns empty; file only exists in main worktree |
| **Files** | `pytest.ini` |
| **Description** | The `pytest.ini` configuration that restricts test paths and configures pytest is not tracked in git. CI or fresh clones will have different test discovery behavior. |
| **Impact** | CI test execution may differ from local runs. |

### G31-006: Submission test contract collides with main test contract

| Field | Value |
|---|---|
| **Severity** | **LOW** |
| **Category** | `new` |
| **Evidence** | Running `pytest ultimate_pipeline/tests/ submission/.../tests/` together causes collection error |
| **Files** | `ultimate_pipeline/tests/test_contracts.py` and `submission/.../tests/test_contracts.py` |
| **Description** | Both test files define classes with the same names (`TestExperimentConfigModel`, `TestAgentSyncContract`, `TestRunArtifacts`, `TestExperimentRegistry`). When both test paths are provided simultaneously, pytest's collection (via `--rootdir` resolution) encounters a conflict. The submission version does NOT include the `TestReleaseProfilePolicy` tests (17 parametrized cases). |
| **Impact** | Cannot run full test suite in a single invocation. Must run each path separately. |

### G31-007: Profiling: torch_geometric import remains pathologically slow on Windows

| Field | Value |
|---|---|
| **Severity** | **MEDIUM** |
| **Category** | `blocked` |
| **Evidence** | Test output: torch_geometric deprecation warnings; known timeout guard in `domain_gap_gnn/__init__.py` |
| **Files** | `domain_gap_gnn/__init__.py` |
| **Description** | The `torch_geometric` import hang on Windows is mitigated with a timeout guard but not fixed. GNN domain-gap capability remains blocked without a platform-level fix. |
| **Impact** | GNN-based domain gap analysis is unavailable on Windows. Affects thesis reproducibility on Windows platforms. |

### G31-008: No cross-branch regression baseline

| Field | Value |
|---|---|
| **Severity** | **LOW** |
| **Category** | `new` |
| **Evidence** | No `test_contracts.py` tests compare output metrics against a known-good baseline |
| **Files** | N/A |
| **Description** | The hardening Phase 9 files (drivable_surface_scanner, full_map_metrics) compute rich metrics but no test asserts expected values against a known-good XODR. There is no regression baseline. |
| **Impact** | Metric regressions (e.g., new holes introduced by a future change) would not be detected. |

---

## Summary

| Severity | Count | IDs |
|---|---|---|
| CRITICAL | 1 | G31-001 |
| HIGH | 1 | G31-002 |
| MEDIUM | 3 | G31-003, G31-004, G31-007 |
| LOW | 3 | G31-005, G31-006, G31-008 |

## Classification for Cross-Run Comparison

| Category | Count | IDs |
|---|---|---|
| resolved | 0 | — |
| partial | 0 | — |
| unchanged | 1 | G31-005 |
| regressed | 0 | — |
| blocked | 1 | G31-007 |
| new | 6 | G31-001, G31-002, G31-003, G31-004, G31-006, G31-008 |
