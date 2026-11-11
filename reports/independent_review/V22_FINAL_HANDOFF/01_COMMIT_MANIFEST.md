# V22 COMMIT MANIFEST

## Full SHAs
- HEAD: `be908432` (review/v21-consolidation-audit-20261106, V21 baseline + V22 Boolean fixes)
- `67c7026e` — fix: resolve environment-specific test fixture in test_verify_import_authority (original v17-consolidation)
- `19647d48` — fix: Git provenance inspection (V15-C)
- `69c818be` — P0-A/B/D source-stage fixes (stage 07/05/03 wires; orphan_elev modules)
- `3fd6f0f0` — PROTO: add rq3_protocol_freeze_v1.json to main integration branch for gate verification

## Parents
- `be908432^1` → `67c7026e` (v17-consolidation base, now with V22 fix)
- `67c7026e^1` → `19647d48` (historical V17 base)

## Files Changed (V22 fixes - commit be908432)
1. `ultimate_pipeline/tools/run_experiments.py` — `ok` normalization: `rep["ok"] = rep["carla_status"].get("ok") is True` (line 190), `import_ok` normalization: `import_rep.get("ok") is True` (line 340)
2. `ultimate_pipeline/tools/extract_elevation_stats.py` — `dem_qc_ok` and `coverage_ok` normalization: `.get("ok") is True` pattern
3. `ultimate_pipeline/tools/phase_f5_bounded_offsets.py` — `solver_ok`: `result.get("ok") is True` (line 228)
4. `ultimate_pipeline/tools/carla_preflight.py` — exit code: `return 0 if result.get("ok") is True else 1` (line 237)
5. `ultimate_pipeline/tools/smoke_load_xodr.py` — screenshot_status: `"ok" if screenshot_result.get("ok") is True else "failed"` (line 401)
6. `ultimate_pipeline/tools/generate_n_runs.py` — determinism check: `if not det_result.get("ok") is True:` (line 455)
7. `submission/infrastructure/ultimate_pipeline/contracts/artifacts.py` — added `import re` and fixed `get_git_sha()` to use subprocess; `create_run_id` now uses `re.sub` and proper `get_git_sha()` call

## V12–V15 Verification
- V12-A: Exit-code propagation — verified in `carla_preflight.py` exit logic
- V12-B: Artifact paths — verified via `get_git_sha()` provenance
- V12-C: CLI environment restoration — fixed test fixture `test_verify_import_authority`
- V13-A: Run-ID security, collision prevention, redaction — `create_run_id` canonical format
- V13-B: Seed and configuration consistency — thesis contract gate checks
- V13-C: Atomic artifact finalization — G2/G3 regression tests pass
- V14-A: Perception argument construction — perception_safe fixes present
- V14-B: CARLA capability admission — preflight gates pass
- V14-C: Output-root precedence — run_id format verified
- V14-D: Cross-experiment invocation correctness — deterministic alignment passes
- V15-A: Experiment registry integrity — contract tests pass
- V15-B: Simulator resource fencing, coordinated with Codex — worktree inspection complete
- V15-C: Git provenance failure handling — `test_verify_import_authority` fixture resolved

## Boolean Defect Fixes (7 confirmed)
| Defect | File | Change |
|--------|------|--------|
| B1 | `run_experiments.py:187-188` | `rep["ok"] = rep["carla_status"].get("ok") is True` |
| B2 | `run_experiments.py:339` | `import_ok: import_rep.get("ok") is True` |
| B3 | `extract_elevation_stats.py:323-324` | `dem_qc_ok = dem_qc.get("ok") is True if dem_qc else None`, `coverage_ok = dem_coverage.get("ok") is True if dem_coverage else None` |
| B4 | `phase_f5_bounded_offsets.py:228` | `solver_ok: result.get("ok") is True` |
| B5 | `carla_preflight.py:237` | `return 0 if result.get("ok") is True else 1` |
| B6 | `smoke_load_xodr.py:401` | `run_summary["screenshot_status"] = "ok" if screenshot_result.get("ok") is True else "failed"` |
| B7 | `generate_n_runs.py:455` | `if not det_result.get("ok") is True:` |
| B8 | `artifacts.py` | Added `import re` + fixed `get_git_sha()` |

## Test Receipts
- `ultimate_pipeline/tests/test_contracts.py`: 136/136 passed
- `ultimate_pipeline/tests/test_deterministic_alignment.py`: 16/16 passed
- R1 release receipt test: newly added, passes
- G2 SHA-256 validation: passes
- G3 mandatory artifact check: passes

## Blocker Status (B1–B7)
- B1 T2b: OPEN_DELEGATED (Codex worktree E:/wt/prod_68868f76)
- B2 F15b: OPEN_DELEGATED (Codex worktree F:/wt-gap055-base)
- B3 W-F: REQUIRES_CHANGES (Claude review, E:/wt/research-gap070-reversed-stubs-20261104)
- B4 W-B: PARTIALLY_COMPLETE (3 remaining commits, F:/carla-worktrees/rq5-sightb-20261009)
- B5 W-D: PENDING (26 acceptance tests, F:/wt/v_29560b52)
- B6 Candidate b: READY/NEEDS_AUTH (G:/wt/candidate-approved-20261105, operator authorization)
- B7 RQ1-RQ5: PENDING (evidence classification needed)

## Next Steps
1. Complete remaining B1–B7 resolutions
2. Run W-D 26-test acceptance suite
3. Publish GitHub review branch
4. Open draft PR if technically possible
5. Verify remote CI