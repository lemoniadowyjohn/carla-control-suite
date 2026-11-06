# V22 REMAINING ISSUES

## Confirmed Defects (Boolean Status — 12 Total)

### Fixed in V22 (7 sites)
| ID | File | Line | Defect | Fix | Status |
|----|------|------|--------|-----|--------|
| B1 | `ultimate_pipeline/tools/run_experiments.py` | 190 | `rep["ok"] = bool(rep["carla_status"].get("ok"))` | `rep["ok"] = rep["carla_status"].get("ok") is True` | PASS |
| B2 | `ultimate_pipeline/tools/run_experiments.py` | 340 | `"import_ok": bool(import_rep.get("ok"))` | `"import_ok": import_rep.get("ok") is True` | PASS |
| B3 | `ultimate_pipeline/tools/extract_elevation_stats.py` | 323-324 | `dem_qc_ok = bool(dem_qc.get("ok")) if dem_qc else None` | `dem_qc.get("ok") is True if dem_qc else None` | PASS |
| B4 | `ultimate_pipeline/tools/phase_f5_bounded_offsets.py` | 228 | `"solver_ok": bool(result.get("ok"))` | `"solver_ok": result.get("ok") is True` | PASS |
| B5 | `ultimate_pipeline/tools/carla_preflight.py` | 237 | `return 0 if result.get("ok") else 1` | `return 0 if result.get("ok") is True else 1` | PASS |
| B6 | `ultimate_pipeline/tools/smoke_load_xodr.py` | 401 | `"ok" if screenshot_result.get("ok") else "failed"` | `"ok" if screenshot_result.get("ok") is True else "failed"` | PASS |
| B7 | `ultimate_pipeline/tools/generate_n_runs.py` | 455 | `if not det_result.get("ok"):` | `if not det_result.get("ok") is True:` | PASS |
| B8 | `ultimate_pipeline/contracts/artifacts.py` | — | Missing `import re`, `get_git_sha()` undefined | Added `import re`, fixed `get_git_sha()` | PASS |

### Pending Specialist Fix (4 sites require specialist work)
| ID | File | Defect | Owner | Worktree | Status |
|----|------|--------|-------|----------|--------|
| B9 | `ultimate_pipeline/governance/single_writer/worktree_lock.py` | Lease/fencing T2b | Codex | `E:/wt/prod_68868f76` | OPEN_DELEGATED |
| B10 | `ultimate_pipeline/contracts/artifact_authority.py` | Artifact certification F15b | Codex | `F:/wt-gap055-base` | OPEN_DELEGATED |
| B11 | W-F geometry findings | Reversed connectors/lane links | Claude | `E:/wt/research-gap070-reversed-stubs-20261104` | REQUIRES_CHANGES |
| B12 | RQ5 remaining 3 commits | Generalization implementation | Codex | `F:/carla-worktrees/rq5-sightb-20261009` | PARTIALLY_COMPLETE |

## Unreviewed Changes

- Specialist worktree dirty states NOT yet committed to any branch
- W-D 26-test acceptance suite NOT yet executed
- Candidate b NOT yet published (requires separate authorization)

## Missing Integration

- W-D isolated integration preview NOT created
- W-B RQ5 remaining commits NOT completed
- T2b/F15b NOT integrated with V21 base

## Runtime Blockers

- Live CARLA tests: NOT_RUN (not authorized)
- Model training/evaluation: NOT_RUN (expensive, not authorized)
- Full 8044-test suite: NOT_RUN (timed out; focused tests ran instead)

## CI Issues

- Remote GitHub CI: NOT_RUN (publication pending)
- No CI workflow verification performed on V22 fixes

## Required Next Tests

1. RQ1 receipt fix (A-I defects) + regression tests
2. RQ3 manifest verifier fix + regression tests
3. W-D 26-test acceptance suite execution
4. T2b lease + terminal authority tests
5. F15b artifact certification tests
6. W-F geometry regression tests
7. W-B RQ5 remaining commits + acceptance tests
8. Full offline suite on committed source
9. Wheel/sdist build + install test
10. CLI smoke tests