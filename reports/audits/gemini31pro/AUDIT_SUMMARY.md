# Audit Summary — Gemini 3.1 Pro

**Branch**: `deepseek-observability-integration-verification`
**SHA**: `db0d983a34209e0a47628d3c2b48efc3f9327ec4`
**Date**: 2026-07-28

## Overview

| Metric | Value |
|---|---|
| Tracked files audited | 14 |
| Claimed fixes verified | 10 |
| Fixes confirmed active | 10 |
| Fixes inactive | 0 |
| Tests discovered | 178 passed, 1 skipped |
| Issues found | 8 (1 CRITICAL, 1 HIGH, 3 MEDIUM, 3 LOW) |
| Performance regressions | 0 |
| Pipeline stages ready | 2 of 17 |
| Dimensions ready | 2 of 5 |

## Key Findings

### CRITICAL: Stage files not tracked (G31-001)
8 of 13 pipeline stage files exist on disk but are **not committed to git**. The pipeline will **fail at runtime** on any execution path that reaches an untracked stage. This affects stages 0, 1, 2, 5, 7, 8, 9, 10, 11.

### HIGH: No tests for 6 of 10 claimed fixes (G31-002)
The newly introduced Phase 9 code (`CumulativeGateRunner`, `DrivableSurfaceScanner`, `FullMapMetricsScanner`, freeze hash verification) has **zero unit test coverage**. Regression detection is absent.

### What Works
- ✅ All 10 claimed hardening fixes are **active and reachable** at runtime
- ✅ All default toggle states are **safe** (disabled/False unless `debug` profile)
- ✅ **AND policy**: both feature request AND profile permission required for unsafe operations
- ✅ **Unknown profile fails closed**: returns `experimental_unsafe=False`
- ✅ **Env var cannot bypass safe profile**: env only affects feature request, profile check is unconditional
- ✅ **CARLA integration**: map loads, spawns work, sensors attach (verified in Phases 7-8)
- ✅ **Cumulative gate runner**: tally-all, fail-at-end implemented and wired

## Issue Register

| ID | Title | Severity | Category |
|---|---|---|---|
| G31-001 | Stage files missing from git tracking (8 files) | CRITICAL | new |
| G31-002 | Zero tests for 6 of 10 claimed fixes | HIGH | new |
| G31-003 | Freeze hash verification untested | MEDIUM | new |
| G31-004 | CumulativeGateRunner lacks direct tests | MEDIUM | new |
| G31-007 | torch_geometric import slow on Windows (blocked) | MEDIUM | blocked |
| G31-005 | pytest.ini not tracked in git | LOW | unchanged |
| G31-006 | Submission/main test contract collision | LOW | new |
| G31-008 | No cross-branch regression baseline | LOW | new |

## Phase-by-Phase Hardening Audit

| Phase | Claim | Verified | Tested | Notes |
|---|---|---|---|---|
| 2 | Disable unsafe planView mutations | ✅ | ✅ | All 4 mutation types gated |
| 3 | PlanView before elevation (freeze XY) | ✅ | ❌ | Structure correct, untested |
| 4 | Disable LaneLink regen + autofix | ✅ | ✅ | Defaults = "0" confirmed |
| 5 | Release profile policies (fail-closed) | ✅ | ✅ | AND policy, unknown fails closed |
| 6 | Ground enrichment defaults | ✅ | ❌ | Both defaults = False confirmed |
| 7 | Guard recompute_geometry_starts (seam fix) | ✅ | ❌ | Guarded behind unsafe flag |
| 9a | CumulativeGateRunner | ✅ | ~ | Indirect coverage only |
| 9b | Freeze hash + invalidation | ✅ | ❌ | Hash computed, verification untested |
| 9c | Drivable-surface scanner | ✅ | ❌ | Scanner implemented, no tests |
| 9d | Full-map metrics | ✅ | ❌ | Scanner implemented, no tests |

## Files Added in This Audit

All under `docs/audits/gemini31pro/`:
- `00_REPOSITORY_IDENTITY.md`
- `01_TEST_COLLECTION.md`
- `02_ACTIVE_EXECUTION_PATH.md`
- `03_FIX_VERIFICATION.md`
- `04_ISSUE_REGISTER.md`
- `05_READINESS_ASSESSMENT.md`
- `06_READINESS_DIMENSIONS.md`

And `reports/audits/gemini31pro/AUDIT_SUMMARY.md`.
