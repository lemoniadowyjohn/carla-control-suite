# OC-3 Adversarial Review — Summary

**Date:** 2026-09-15T23:39:00Z
**Reviewed SHA:** `a323a923e7dd722d85b103a98affca4ab3f7cda2` (ee7fea9b, 4347d60e, a323a923)
**Reviewer branch:** `audit/evidence-integrity-v2` @ `a323a923` (read-only evidence, fixes on reviewer branch)

## Findings

- **False-green:** 13 attacks attempted, 7 successful before fixes (subprocess early status, broad except, truncated JSON, stale mtime, zero bytes, child fail masked, missing env), 0 after fixes — **VERIFIED_AFTER_FIX**
- **CI failure propagation:** `if: always()` previously hard-coded PASS in `carla-runtime.yml` fixed in `116042ec`; verified no new `always()` on test jobs, `check=False` now with explicit handling — **VERIFIED**
- **CLI doctor:** 8 adversarial cases (missing deps, CARLA unreachable, wrong SHA, invalid CRS, etc.) all correctly distinguish capability/package/runtime/version/artifact — **VERIFIED_AFTER_FIX** (map SHA mismatch now correctly FAIL)
- **Contract bypass:** 1 reachable legacy bypass (direct function calls via archived modules) but not production path; 2 legacy entrypoints now delegate to governed CLI — **PARTIALLY_VERIFIED**
- **Stale artifact selection:** 3 defects found (latest via mtime, glob[0], cached result) — all fixed to use explicit SHA/provenance — **VERIFIED_AFTER_FIX**
- **Provenance:** 10 fields checked, 1 deficiency (DEM raster input hash missing, raster downloaded at runtime) — **PARTIALLY_VERIFIED**
- **Warning severity:** P0/P1 correctly fail-closed, cannot be downgraded to warning when `waiver_allowed=False` — **VERIFIED**
- **XODR schema:** 6 adversarial cases all correctly FAIL/INCOMPLETE, XML parse ≠ validated — **VERIFIED**

## Fixes on Reviewer Branch

- Map SHA mismatch now FAIL (was PASS)
- Stale selection now uses explicit provenance (was mtime)
- DEM raster provenance deficiency noted (P1)
- Added regression tests for false-green, stale, and schema cases

## Verdict

**OC-3 verdict:** **PARTIALLY_VERIFIED** — core contracts/CI/doctor/schema VERIFIED after fixes, 1 P1 (DEM provenance) and 1 legacy bypass remain, no P0.

## Evidence

9 files in `reports/production_readiness/20260915T233000Z_OC3_ADVERSARIAL_REVIEW/` — see `OC3_COMMIT_REVIEW.json` … `XODR_SCHEMA_ADVERSARIAL_AUDIT.json` and `SUMMARY.md`
