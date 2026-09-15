# Geometry/CRS/DEM Correctness Hardening — Evidence Note

## Inventory of Relevant Modules

| File | Function | Problem Identified | Planned Fix | Tests |
|------|----------|-------------------|-------------|-------|
| `ultimate_pipeline/geometry/geometry_validator.py` | `GeometryValidator.validate()` | **XML Reordering (2.1):** Sorts `parsed` list but never reorders XML `<geometry>` elements in `<planView>` | Move XML elements in planView to match sorted order | Add test: input s=[20,0,10] → output serialized XML s=[0,10,20] |
| `ultimate_pipeline/geometry/geometry_validator.py` | `GeometryValidator._validate_road()` | **Geometry Removal (2.2):** Filters `parsed` list but doesn't remove XML elements from planView | Actually remove `<geometry>` elements from planView when length is zero/invalid | Test: Python object count vs XML serialized count must agree |
| `ultimate_pipeline/geometry/geometry_validator.py` | `GeometryValidator._validate_road()` | **Heading Backfill (2.3):** Uses `prev["hdg"]` (start heading) instead of endpoint heading for missing hdg after curved primitives | Use `geometry_endpoint(prev["elem"]).heading` for backfill after arcs/spirals | Regression fixture: arc → missing hdg next; new hdg == arc endpoint heading |
| `ultimate_pipeline/geometry/geometry_validator.py` | `GeometryValidator._validate_road()` | **Nonfinite Inputs (2.4):** No explicit handling for NaN/Inf/missing s/length; may crash or silently succeed | Add finite checks with deterministic outcomes: FAIL / REJECTED_REPAIR / VALID_REPAIR | Tests for NaN s, Inf length, missing s, missing length |
| `ultimate_pipeline/geometry/geometry_validator.py` | `GeometryValidator.validate()` | **Inspection/Repair Separation (3):** Single method mutates XML; no read-only inspection mode | Split into `inspect_geometry`, `plan_geometry_repairs`, `apply_geometry_repairs`, `validate_geometry` | Test: read-only inspection leaves serialized XML byte-equivalent |
| `ultimate_pipeline/dem/dem_identity.py` | `dem_identity_record()` | **DEM Identity CRS Bug (5):** `bounds_degrees` and `bounds_wgs84` assigned directly from rasterio bounds without CRS transformation | Use `pyproj.Transformer.from_crs(ds.crs, "EPSG:4326", always_xy=True)` to transform bounds | Geographic raster: bounds remain correct; Projected raster: metre coords transformed to lon/lat |
| `ultimate_pipeline/quality/check_dem_coverage.py` | `dem_coverage_gate()` | **Weak Coverage Metric (6):** Uses diagonal ratio (`coverage_ratio_diag`) which is not production-quality | Implement explicit metrics: `bbox_intersection_area_fraction`, `sampled_map_points_inside_dem_fraction`, `nodata_fraction_at_samples` | Report all three metrics separately; no opaque score |
| `ultimate_pipeline/dem/dem_crs_contract.py` | `claimed_crs_from_xodr()` | **CRS Parser Hardening (7):** Relies on string checks; needs actual pyproj.CRS parsing with distinct states | Expose `SYNTAX_VALID`, `TRANSFORM_VALID`, `SOURCE_FRAME_CONFIRMED` states | Test: parse failure vs valid CRS vs transformable vs source-confirmed |
| `ultimate_pipeline/quality/check_dem_coverage.py` | `check_dem_coverage()` | **Automatic Georeference Invention (8):** Falls back to raw XY sampling when geoReference missing; production should FAIL | Production profile: missing authoritative georeference → FAIL/INCOMPLETE; dev: optional inferred with provenance | Test: production mode fails without geoReference; dev mode allows with provenance |

## Consumers Duplicating Geometry Evaluation (Task 4)

| Consumer | Current Behavior | Migration Needed |
|----------|-----------------|------------------|
| `geometry_validator.py` | Uses `geometry_endpoint` from kernel (already migrated) | Already uses canonical kernel |
| `dem_crs_contract.py` | Has own `_geometry_endpoint` duplicate for bbox | Replace with `opendrive_geometry_kernel.endpoint` |
| `check_dem_coverage.py` | Uses simplified `_get_road_sample_points` with first-geometry-only approximation | Use canonical kernel for accurate geometry evaluation |

## Confirmed Defects Status (will update after verification)

| Defect | Status |
|--------|--------|
| XML reordering not persisted to XML | CONFIRMED |
| Geometry removal not persisted to XML | CONFIRMED |
| Heading backfill uses start heading not endpoint | CONFIRMED |
| Nonfinite input handling missing | CONFIRMED |
| DEM bounds_wgs84 = bounds_degrees (no transform) | CONFIRMED |
| Diagonal-only coverage metric | CONFIRMED |
| CRS parser only string checks | CONFIRMED |
| GeoReference fallback in production | CONFIRMED |

## Next Steps

1. Write regression tests for each confirmed defect
2. Fix geometry validator: XML reordering, removal, heading backfill, nonfinite handling
3. Add inspection/repair separation
4. Fix DEM identity CRS transformation
5. Replace DEM coverage metric
6. Harden CRS parser
7. Enforce production georeference policy
8. Run focused tests then full pytest