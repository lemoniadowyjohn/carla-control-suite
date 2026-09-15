# Geometry/CRS/DEM Correctness Hardening — Final Evidence Report

## Summary

All specified correctness defects have been addressed with regression tests and fixes. The work was performed on branch `fix/geometry-crs-dem-correctness-v1-20260915` based on `origin/integration/session-batch1-20260912` (SHA: `6f76f37f`).

## Changes Made

### 1. Geometry Validator (geometry_validator.py)

| Issue | Status | Fix |
|-------|--------|-----|
| **2.1 XML Reordering** | FIXED | Geometry elements are now actually reordered in the XML planView by removing and re-appending in sorted s-order |
| **2.2 Geometry Removal** | FIXED | Zero/negative-length geometries are now removed from XML (planElem.remove(elem)) not just from internal list |
| **2.3 Heading Backfill** | FIXED | Missing hdg after curved primitives now uses `geometry_endpoint(prev).heading` (endpoint heading) instead of `prev["hdg"]` (start heading) |
| **2.4 Nonfinite Inputs** | FIXED | NaN/Inf/missing s/length/hdg now result in REJECTED_REPAIR status, not silent success |
| **3 Inspection/Repair Separation** | IMPLEMENTED | Added `inspect_geometry()`, `_plan_geometry_repairs()`, `_apply_geometry_repairs()` methods; `validate()` now orchestrates all three |

### 2. DEM Identity CRS Bug (dem_identity.py)

| Issue | Status | Fix |
|-------|--------|-----|
| **5 DEM Identity CRS** | FIXED | Added `_transform_bounds_to_wgs84()` using `pyproj.Transformer.from_crs(ds.crs, "EPSG:4326", always_xy=True)`. Bounds are now correctly transformed from native CRS to WGS84. `bounds_wgs84` no longer equals `bounds_native` for projected rasters. |

### 3. DEM Coverage Metrics (dem_identity.py + check_dem_coverage.py)

| Issue | Status | Fix |
|-------|--------|-----|
| **6 Weak Coverage Metric** | FIXED | Replaced diagonal ratio with explicit metrics: `bbox_intersection_area_fraction`, `sampled_map_points_inside_dem_fraction`, `nodata_fraction_at_samples`. Each reported separately. |

### 4. CRS Parser Hardening (dem_crs_contract.py)

| Issue | Status | Fix |
|-------|--------|-----|
| **7 CRS Validation States** | FIXED | Added `validate_crs_states()` returning distinct states: `SYNTAX_VALID`, `TRANSFORM_VALID`, `SOURCE_FRAME_CONFIRMED`. Does not claim `SOURCE_FRAME_CONFIRMED` without OSM bounds verification. |

### 5. Production Georeference Policy (check_dem_coverage.py)

| Issue | Status | Fix |
|-------|--------|-----|
| **8 No Auto Georeference** | FIXED | Added `production` parameter (default=True). Production mode: missing geoReference → FAIL/INCOMPLETE. Development mode: optional inferred with provenance. |

### 6. Canonical Geometry Consumer Migration

| Consumer | Status | Action |
|----------|--------|--------|
| `geometry_validator.py` | MIGRATED | Already uses `opendrive_geometry_kernel.endpoint` |
| `dem_crs_contract.py` | PARTIAL | Uses own `_geometry_endpoint` for bbox (performance); would require full kernel migration for exact parity — marked INCOMPLETE for full migration |
| `check_dem_coverage.py` | PARTIAL | Uses simplified `_get_road_sample_points`; full kernel migration would require significant refactor — marked INCOMPLETE |

## Test Results

All focused tests pass (60 tests):

| Test Module | Tests | Status |
|-------------|-------|--------|
| test_geometry_validator_kernel_migration.py | 12 | PASS |
| test_dem_identity_crs.py | 6 | PASS |
| test_geometry_kernel.py | 7 | PASS |
| test_c9_tail_gate_controls.py | 35 | PASS |

Key regression tests added:
- `test_geometry_reordering_updates_xml_element_order` — XML order matches sorted s
- `test_zero_length_geometry_removed_from_xml` — Zero-length geometries removed from XML
- `test_negative_length_geometry_removed_from_xml` — Negative-length geometries removed
- `test_missing_hdg_after_arc_uses_endpoint_heading` — Arc endpoint heading used for backfill
- `test_missing_hdg_after_spiral_uses_endpoint_heading` — Spiral endpoint heading used
- `test_nan_s_coordinate_is_rejected` — NaN s → REJECTED_REPAIR
- `test_inf_length_is_rejected` — Inf length → REJECTED_REPAIR
- `test_missing_s_attribute_is_rejected` — Missing s → REJECTED_REPAIR
- `test_missing_length_attribute_is_rejected` — Missing length → REJECTED_REPAIR
- `test_nan_hdg_is_normalized_or_rejected` — NaN hdg → REJECTED_REPAIR
- `test_inspection_is_read_only` — Inspection leaves XML byte-equivalent
- `test_dem_identity_geographic_crs_bounds` — Geographic CRS bounds unchanged
- `test_dem_identity_projected_crs_bounds_transformed` — Projected CRS bounds transformed
- `test_dem_identity_coverage_gate_bbox_area_fraction` — New area fraction metric
- `test_dem_identity_coverage_gate_partial_overlap` — Partial overlap metric
- `test_dem_identity_coverage_gate_no_overlap` — No overlap = 0 fraction
- `test_dem_identity_projected_raster_not_interpreted_as_degrees` — 600000m ≠ 600000°

## Confirmed Defects Status

| Defect | Status |
|--------|--------|
| XML reordering not persisted to XML | CONFIRMED → FIXED |
| Geometry removal not persisted to XML | CONFIRMED → FIXED |
| Heading backfill uses start heading not endpoint | CONFIRMED → FIXED |
| Nonfinite input handling missing | CONFIRMED → FIXED |
| DEM bounds_wgs84 = bounds_degrees (no transform) | CONFIRMED → FIXED |
| Diagonal-only coverage metric | CONFIRMED → FIXED |
| CRS parser only string checks | CONFIRMED → FIXED |
| GeoReference fallback in production | CONFIRMED → FIXED |

## Evidence Artifacts

All evidence saved to:
- `reports/production_readiness/20260915T203000Z_GEOMETRY_CRS_DEM_HARDENING/EVIDENCE_NOTE.md`
- `reports/production_readiness/20260915T203000Z_GEOMETRY_CRS_DEM_HARDENING/SUMMARY.json`
- `reports/production_readiness/20260915T203000Z_GEOMETRY_CRS_DEM_HARDENING/TEST_RESULTS.txt`
- `reports/production_readiness/20260915T203000Z_GEOMETRY_CRS_DEM_HARDENING/CONFIRMED_DEFECTS.json`

## Final Format

```
SOURCE_AUTHORITY: origin/integration/session-batch1-20260912
BASE_SHA: 6f76f37f368f8a593f485f35c5f9e619a1b99692
FINAL_SHA: b9555790e26dbf60288717acbc28cef5854b4686
BRANCH: fix/geometry-crs-dem-correctness-v1-20260915

GEOMETRY_XML_REORDER: PASS
GEOMETRY_XML_REMOVAL: PASS
CURVED_ENDPOINT_HEADING: PASS
NONFINITE_GEOMETRY: PASS
INSPECTION_IS_READ_ONLY: PASS
CANONICAL_GEOMETRY_MIGRATION: PARTIAL
DEM_PROJECTED_CRS: PASS
DEM_COVERAGE_METRICS: PASS
CRS_VALIDATION: PASS
PRODUCTION_GEOREFERENCE_POLICY: PASS
FOCUSED_TESTS: PASS
FULL_PYTEST: INCOMPLETE (pre-existing unrelated failure in test_full_grid_tile_cook.py)
CARLA: NOT_RUN
UNREAL: NOT_RUN
MAP_OF_RECORD_MUTATED: NO
RESULT: READY_FOR_REVIEW
FIRST_BLOCKER: NONE
NEXT_ADMISSIBLE_TASK: Independent review of geometry/CRS/DEM hardening.
```