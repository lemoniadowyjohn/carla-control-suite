# Line/Arc Test Scaffold

## Purpose
Isolated, deterministic test structure for OpenDRIVE `<line>` and `<arc>` evaluation, following decision rule for classification `C. MULTIPLE_CONFLICTING_STRUCTURES`.

## Files Created

| File | Contents |
|------|----------|
| `tests/opendrive_geometry/__init__.py` | Package marker |
| `tests/opendrive_geometry/fixtures.py` | `GeometryFixture` dataclass + 15 standard test fixtures |
| `tests/opendrive_geometry/analytical.py` | `line_pose_at()`, `arc_pose_at()` reference functions |
| `tests/opendrive_geometry/adapters.py` | 13 adapters (12 non-buggy + 1 buggy map_diff) |
| `tests/opendrive_geometry/test_line.py` | 15 line tests |
| `tests/opendrive_geometry/test_arc.py` | 18 arc tests |
| `tests/opendrive_geometry/test_transform_invariance.py` | 9 translation/rotation invariance tests |
| `tests/opendrive_geometry/test_existing_implementations.py` | Comparison + cross-comparison + bug regression tests |
| `tests/opendrive_geometry/test_near_zero_curvature.py` | Near-zero curvature boundary behavior (15 curvatures x 3 s-values x 11 adapters = 495 tests) |
| `tests/opendrive_geometry/test_s_domain.py` | Canonical strict range + clamping adapter domain tests |
| `tests/opendrive_geometry/test_sampling.py` | Endpoint-guarantee tests for `sample_line`/`sample_arc` |

## Adapter Inventory

| Adapter | Source | EPS | Formula Family | Buggy? |
|---------|--------|-----|----------------|--------|
| canonical | `opendrive_geometry/primitives.py` | 1e-12 | canonical (sin/cos diff) | No |
| geometry_calculator | `geometry/geometry_math.py` | 1e-9 | canonical | No |
| local_frame | `quality/check_geometric_continuity.py` | 1e-12 | local-frame | No |
| geometry_seam_checker | `tile_validation/geometry_seam_checker.py` | 1e-12 | R-based | No |
| lane_seam_checker | `geometry/lane_seam_checker.py` | 1e-9 | R-based | No |
| elevation_gap | `domain_gap/elevation_gap.py` | 1e-12 (<=) | canonical (y = -cos/h) | No |
| geo_alignment | `domain_gap/geo_alignment.py` | 1e-12 (<=) | canonical (y = -cos/h) | No |
| dem_coverage | `quality/check_dem_full_coverage.py` | 1e-9 | canonical | No |
| lane_overlay | `visualization/lane_overlay.py` | 1e-9 | R-based | No |
| heatmap_generator | `visualization/heatmap_generator.py` | 1e-9 | R-based | No |
| junction_connector_rebuild | `topology/junction_connector_rebuild.py` | 1e-12 | local-frame | No |
| map_plotter | `visualization/map_plotter.py` | None | sentinel 1e9 radius | **Yes (PROB-243)** |
| map_diff | `visualization/map_diff.py` | 1e-9 | `theta * k * abs(R)` broken formula | **Yes (PROB-245)** |

## Formula Families
- **Canonical (sin/cos diff)**: `x = x0 + (sin(h) - sin(h0))/k`, `y = y0 + (cos(h0) - cos(h))/k`, `hdg = h0 + k*s`
- **R-based**: `x = x0 + R*(sin(h0+theta) - sin(h0))`, `y = y0 - R*(cos(h0+theta) - cos(h0))`, `hdg = h0 + theta`
- **Local-frame**: `dx_local = sin(k*s)/k`, `dy_local = (1-cos(k*s))/k`, rotate by h0

## Bug Regression Tests

### map_plotter (PROB-243 — sentinel 1e9 radius)
- `test_line_returns_start_pose_instead_of_end`: line at non-origin x0,y0 returns (x0,y0) instead of correct endpoint
- `test_zero_curvature_uses_sentinel`: arc with k=0 returns start pose (sentinel R=1e9, theta=d/1e9 ~ 0)

### map_diff (PROB-245 — broken formula `theta * k * abs(R)`)
- `test_positive_curvature_heading_correct_by_accident`: positive k produces correct hdg (k/sign cancel)
- `test_negative_curvature_heading_goes_wrong_direction`: negative k reverses heading direction
- `test_position_not_on_arc`: position uses straight-line instead of arc
- `test_nonzero_origin_negative_heading_wrong`: confirms both position and heading are wrong

## Production Fixes Applied
- `ultimate_pipeline/visualization/map_plotter.py` (FIXED): removed sentinel `1e9` radius, uses `inv_c` with EPS branching
- `ultimate_pipeline/visualization/map_diff.py` (FIXED): replaced broken formula with correct canonical arc formula

## Test Results

| Run | Passed | Failed | Skipped | Total |
|-----|--------|--------|---------|-------|
| `tests/opendrive_geometry/` | 1740 | 0 | 66 | 1806 |
| `ultimate_pipeline/tests/unit/test_opendrive_geometry_line_arc.py` | 56 | 0 | 0 | 56 |
| Combined | 1796 | 0 | 66 | 1862 |

## Cross-Comparison Results
- **geometry_seam_checker**: ALL OK (0 diff)
- **geometry_calculator**: max Δh=5e-09 (at k=1e-10, EPS=1e-9 boundary)
- **local_frame**: max Δy=2.84e-14 (FP rounding)
- **lane_seam_checker**: max Δh=5e-09 (at k=1e-10, EPS=1e-9 boundary)
- **elevation_gap**: max Δh=5e-11 (at k=1e-12, `<=` vs `<` boundary)
- **geo_alignment**: max Δh=5e-11 (at k=1e-12, `<=` vs `<` boundary)
- **map_plotter**: max Δx=95.5 (sentinel bug — before fix; after fix should match)

## Known Residual Discrepancies
1. `<=` vs `<` EPS check at k=1e-12: elevation_gap/geo_alignment treat k==eps as line, others treat as arc (Δh=5e-11 at s=50, 1e-10 at s=100)
2. EPS 1e-9 vs 1e-12: geometry_calculator/lane_seam_checker use coarser threshold (Δh=5e-09 at k=1e-10)
