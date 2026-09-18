# 03B_CANONICAL_RELEASE_TREE_DECISION.md

**Task:** SYS-001 — Canonical Release Tree
**Base commit:** e9ff5986
**Final commit:** (see git log)
**Decision date:** 2026-08-02

## Decision

**Canonical production package: `ultimate_pipeline/` (repo root).**

The donor tree `submission/infrastructure/ultimate_pipeline/` is an archived
snapshot / migration donor. It is NOT a second production tree.

## Capability comparison (computed)

| Metric | Value |
|---|---|
| Root package files on disk | 603 |
| Donor package files | 688 |
| Shared files | 555 |
| Root-only | 48 |
| Donor-only | 133 |

Full per-capability table: `03B_CAPABILITY_DIFF.json`.

## Root import failure reproduced and fixed

`python -c "import ultimate_pipeline.main_pipeline"` failed before with
`ModuleNotFoundError: ultimate_pipeline.artifacts.map_event_record`. Eight
internal module references were unresolved:

| Missing module | Used by | Resolution |
|---|---|---|
| `ultimate_pipeline.artifacts.map_event_record` | quality/carla_pruner.py, quality/check_lane_connectivity.py, quality/quarantine_bad_roads.py | restored from git history (fabcc277) |
| `ultimate_pipeline.database.db_manager` | main_pipeline.py:1622, perception/dataset_generator.py | ported from donor (3,324→ root) |
| `ultimate_pipeline.database.run_archiver` | main_pipeline.py:1543 | ported from donor |
| `ultimate_pipeline.db.sensor_logger` | tile_validation/tile_stress_tester.py | ported from donor |
| `ultimate_pipeline.augmentation.realism` | perception modules (already try/except wrapped) | import is lazy/optional; not required for import surface |
| `ultimate_pipeline.diagnostics.audit_xodr_visual_geometry` | tools/junction_connector_snap.py | restored from git history (f631b11f) |
| `ultimate_pipeline.perception.calibration` | tools/run_perception_safe.py | restored from git history (ab9edb2a) |
| `ultimate_pipeline.roadrunner.installation` | cli.py:501 | restored from git history (8329d50c) |

## Commands and results

| Command | Result |
|---|---|
| `python -m compileall ultimate_pipeline` | exit 0 |
| `python -c "import ultimate_pipeline"` | OK |
| `python -c "import ultimate_pipeline.main_pipeline"` | OK (warnings only: missing optional coordinates.json, HPC_DIR) |
| `python -c "import ultimate_pipeline.cli"` | OK |
| `python -m pytest ultimate_pipeline/tests/unit/test_sys001_import_smoke.py` | 11 passed |
| `python -m pytest --collect-only -q` | (see P03 run below) |

## Donor deprecation

- `submission/infrastructure/ultimate_pipeline/DEPRECATION_POLICY.md` already
  declares the policy; the tree remains fully tracked (688 files) but is
  classified **donor/archive — not importable as production**.
- No wholesale donor copy was performed; only 3 files were ported (database
  modules) because root code already referenced them.

## Optional deps lazy

- `carla` import is guarded (no server required at import time).
- ML/augmentation imports are inside `try/except` (perception_runner_local_aug,
  dataset_generator, tile_stress_tester).

## Unresolved

- Root package has 509 untracked files on disk (only 84 tracked). This commit
  tracks the newly restored/ported modules and tests; broader tracking of the
  root package is handled in the same promotion step as P03's acceptance
  (see git status after commit).

## Handoff

- To TEST-TRACE-001 (P04): traceability can now resolve root package paths.
