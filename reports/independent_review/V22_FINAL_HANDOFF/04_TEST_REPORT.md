# V22 TEST REPORT

## Test Suite Overview

| Test Category | Command | Collected | Passed | Failed | Skipped |
|--------------|---------|-----------|--------|--------|---------|
| Contract Tests | `pytest ultimate_pipeline/tests/test_contracts.py -q` | 136 | 136 | 0 | 0 |
| Deterministic Alignment | `pytest ultimate_pipeline/tests/test_deterministic_alignment.py -q` | 16 | 16 | 0 | 0 |
| RQ3 Manifest Verifier | `pytest tests/unit/test_o17_rq3_dataset_manifest_verifier.py -q` | 5 | 5 | 0 | 0 |
| Total | — | 157 | 157 | 0 | 0 |

## Key Test Results

### Contract Tests (136/136 PASS)
- All 136 contract tests pass including:
  - `test_create_run_id_format` — previously failed with `NameError: name 'get_git_sha' is not defined` and `name 're' is not defined`, now fixed and passing
  - `test_verify_import_authority` — fixture resolved for environment-specific test
  - R1 release receipt test — newly added and passing
  - G2 SHA-256 validation — passing
  - G3 mandatory artifact check — passing

### Deterministic Alignment (16/16 PASS)
- All 16 deterministic alignment tests pass, verifying:
  - XODR geometry translation correctness
  - Header BBox handling (stale and new)
  - Malformed geometry skipping
  - Centroid computation correctness
  - GPS bounds project validity

### RQ3 Manifest Verifier (5/5 PASS)
- `test_valid_manifest_without_paired_is_incomplete` — correctly returns INCOMPLETE without paired manifest
- `test_valid_manifest_with_paired_passes` — correctly returns PASS for matching paired manifests
- `test_duplicate_frames_fail` — correctly fails on duplicate frame IDs
- `test_missing_frames_fail` — correctly fails when missing_frames declared
- `test_paired_contract_mismatch_fails` — correctly fails on contract field mismatch

### Boolean Fix Regressions
8 boolean coercion fixes verified with direct source inspection:

| Fix | File | Change | Result |
|-----|------|--------|--------|
| B1 | `run_experiments.py:190` | `rep["ok"] = rep["carla_status"].get("ok") is True` | PASS |
| B2 | `run_experiments.py:340` | `import_ok: import_rep.get("ok") is True` | PASS |
| B3 | `extract_elevation_stats.py:323-324` | `dem_qc_ok = dem_qc.get("ok") is True if dem_qc else None` | PASS |
| B4 | `phase_f5_bounded_offsets.py:228` | `solver_ok: result.get("ok") is True` | PASS |
| B5 | `carla_preflight.py:237` | `return 0 if result.get("ok") is True else 1` | PASS |
| B6 | `smoke_load_xodr.py:401` | `"ok" if screenshot_result.get("ok") is True else "failed"` | PASS |
| B7 | `generate_n_runs.py:455` | `if not det_result.get("ok") is True:` | PASS |
| B8 | `artifacts.py` | Added `import re` + fixed `get_git_sha()` | PASS |

### Previously Fixed / Remaining
- Original 12 confirmed Boolean defects from V21 report: 8 sites have `is True` fix applied; remaining 4 (T2b, F15b) require specialist work
- V12–V15 contract compliance: 9/9 tasks verified with test matrix
- New test receipts: R1, G2, G3 all pass on current source

## Command Details

### Contract Tests
```
cd "C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main_v17"
& "C:/Users/admin/PycharmProjects/gpt4/pythonProject3/.venv/Scripts/python.exe" -m pytest ultimate_pipeline/tests/test_contracts.py -q --tb=short
```
Result: 136 passed, 6 warnings (setting path warnings only)

### Deterministic Alignment Tests
```
cd "C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main_v17"
& "C:/Users/admin/PycharmProjects/gpt4/pythonProject3/.venv/Scripts/python.exe" -m pytest ultimate_pipeline/tests/test_deterministic_alignment.py -q --tb=short
```
Result: 16 passed

### RQ3 Manifest Verifier Tests
```
cd "C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main_v17"
& "C:/Users/admin/PycharmProjects/gpt4/pythonProject3/.venv/Scripts/python.exe" -m pytest tests/unit/test_o17_rq3_dataset_manifest_verifier.py -q --tb=short
```
Result: 5 passed

### Boolean Fix Verification
Each boolean fix verified by reading source change and confirming `is True` pattern replaces `bool(...)` or truthiness checks on `.get("ok")`.

## Skipped / External Tests
- Tests requiring live CARLA runtime: NOT_RUN (not authorized)
- Expensive model training tests: NOT_RUN
- W-D 26-test acceptance suite: NOT_RUN (pending execution; test selection definition not recoverable)
- W-B RQ5 remaining 3 commits: NOT_COMMITTED
- T2b lease tests: OPEN_DELEGATED (Codex worktree)
- F15b certification tests: OPEN_DELEGATED (Codex worktree)
