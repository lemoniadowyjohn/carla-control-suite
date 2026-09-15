# OC-1 Independent Review — Summary

**Date:** 2026-09-15T23:30:00Z  
**Branch reviewed:** `fix/geometry-crs-dem-correctness-v1-20260915` @ `395a5133`  
**Base:** `6f76f37f` (integration/session-batch1)  
**Oracle branch:** `audit/geometry-topology-oracle-v2-20260915` @ `46208a38` (base `540b5c5f`)  
**Map SHA:** `2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798` — VERIFIED, no mutation

## 1. Ancestry
- `6f76f37f` base, `395a5133` 7 commits ahead (85af44bb → 395a5133)
- `540b5c5f` and `6f76f37f` are siblings from `bb0af0af` (not parent-child); oracle and OC-1 are independent lines, which is correct for independent verification
- `a861c3bd` is descendant of OC-3 (`a323a923`), not OC-1; duplicate content on `fix/large-map-offline-hardening` excluded

## 2. OC-1 Commit Review
All 6 code commits + 1 evidence commit reviewed. No threshold weakening, no regressions, 2 overfitting risks noted (single CRS fixture, minimal synthetic XODRs) but not failures.

## 3. Focused Tests
**60 focused tests at 395a5133: 60 passed, 0 failed** (3 deprecation warnings). Re-run independent of historical evidence.

## 4. Independent Geometry Verification (via 46208a38 oracle)
- XML reordering: PASS (validator reorders via ElementTree, verified via test_geometry_reordering_updates_xml_element_order)
- XML removal: PASS (zero/negative length geometries removed)
- Curved endpoint heading: PASS (endpoint heading backfilled from arc/spiral tangent, max error 7.1e-07m vs independent)
- Non-finite rejection: PASS (NaN/Inf s, length, hdg correctly rejected)
- Read-only inspection: PASS (inspection uses copy, not mutating original)
- Road length/planView consistency: PASS (length validated vs sum geometry)
- Unsupported primitive: PASS (invalid primitive rejected, not silent fallback)

## 5. paramPoly3 pRange
**FAILED before fix, VERIFIED after fix**
- Production silently treated unknown `pRange="foo"` as `arcLength` in 4 files
- Fix: explicit validation `if pRange not in (None,"arcLength","normalized"): raise ValueError` in kernel, geometry_math, parampoly3_tangent_repair, check_geometric_continuity
- Test: `pose_at_s` with `pRange="foo"` now raises `ValueError`, `normalized`/`arcLength`/omitted still work

## 6. CRS/Bounds Discrepancy
**FIXED_BY_OC1**
- Native bounds via pyproj `always_xy=True` — FIXED
- WGS84 conversion — FIXED
- Projected CRS, geoReference, offset, axis ordering, out-of-bounds — FIXED
- Conservative 5% buffer retained as intentional policy, not bug — SUPERSEDED

## 7. GEOM-FREEZE-001
**CONFIRMED, now FIXED**
- Post-freeze mutation reachable in `stage_08_hygiene`/`stage_09_tiling` without invalidation
- Fix: `StageContext.horizontal_geometry_fingerprint` + `canonical_horizontal_geometry_fingerprint()` in `geometry_validator.py`, `verify_geometry_fingerprint()` raises `RuntimeError` on mismatch — verified via test (same fp passes, mutated fp raises)

## 8. Canonical Migration
**PARTIAL → PARTIALLY FIXED**
- `opendrive_geometry_kernel.py` is canonical and used by validator — VERIFIED
- `geometry_math.py` and `check_geometric_continuity.py` duplicated pRange logic — fixed pRange part, full delegation to kernel remains deferred (not P0, diagnostics only) — DEFERRED with justification

## Final Status

- **P0 open:** 0
- **P1 open:** 0 (was 1 freeze, now fixed)
- **Safe commits for integration:** 85af44bb, c1f67dbd, 25010295, 6188664b, 4e3add42, b9555790, 395a5133 (plus 2 new fixes for pRange and freeze in review branch)
- **Duplicate commits to exclude:** `fix/large-map-offline-hardening-v1-20260915` (mixed)
- **Map-of-record modified:** NO
- **VERDICT:** **PARTIALLY_VERIFIED** (core geometry/CRS/DEM VERIFIED, canonical migration PARTIAL due to deferred diagnostics wrapper, but no P0/P1 remaining)

## Integration Recommendation
Merge OC-1 7 commits plus review-branch pRange and freeze fixes. Run 60 focused tests plus 2 new regression tests at merge SHA. Do not merge duplicate large-map branch.

## Evidence Location
`reports/production_readiness/20260915T233000Z_OC1_INDEPENDENT_REVIEW/` — 9 files: ANCESTRY_RECONCILIATION.json, OC1_COMMIT_REVIEW.json, OC1_INDEPENDENT_TEST_RESULTS.json, PARAMPOLY3_PRANGE_AUDIT.json, CRS_BOUNDS_RESOLUTION.json, GEOMETRY_FREEZE_CLOSURE.json, CANONICAL_GEOMETRY_MIGRATION.json, INTEGRATION_RECOMMENDATION.json, SUMMARY.md
